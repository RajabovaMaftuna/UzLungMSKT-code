"""Apparat ma'lumoti va PyTorch holati — torch'ga BOG'LIQ BO'LMAGAN qism (PM-9).

Boshqa kompyuterda torch yuklanmasa (masalan, «WinError 126 ... shm.dll» — VC++ runtime yo'q) ham CPU, operativ xotira,
videokarta va disk ma'lumoti ko'rsatiladi; torch xatosi alohida maydonda tushuntiriladi, tahlil esa aniq xabar bilan rad etiladi.
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ---------------------------------------------------------------- apparat (torch'siz)
def cpu() -> dict:
    d = {"cpu_threads": os.cpu_count()}
    name = ""
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                name = str(winreg.QueryValueEx(k, "ProcessorNameString")[0]).strip()
        except OSError:
            pass
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            d["avx"] = bool(k32.IsProcessorFeaturePresent(39)); d["avx2"] = bool(k32.IsProcessorFeaturePresent(40))
        except (OSError, AttributeError):
            pass
    d["cpu"] = re.sub(r"\s+", " ", name or platform.processor() or platform.machine())
    return d


def ram() -> dict:
    if sys.platform == "win32":
        import ctypes

        class MEM(ctypes.Structure):
            _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                        ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong), ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong),
                        ("ae", ctypes.c_ulonglong)]
        m = MEM(); m.len = ctypes.sizeof(MEM)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return {"ram_gb": round(m.total / 2**30, 1), "ram_free_gb": round(m.avail / 2**30, 1)}
        return {}
    try:
        pages, size = os.sysconf("SC_PHYS_PAGES"), os.sysconf("SC_PAGE_SIZE")
        return {"ram_gb": round(pages * size / 2**30, 1)}
    except (ValueError, OSError, AttributeError):
        return {}


_GPU_CACHE: dict = {}


def gpus() -> list[dict]:
    """nvidia-smi (10 s chegarasi), bo'lmasa WMI (Win32_VideoController). Natija 60 s keshlanadi."""
    if _GPU_CACHE and time.time() - _GPU_CACHE["t"] < 60:
        return _GPU_CACHE["v"]
    out = []
    smi = shutil.which("nvidia-smi") or (r"C:\Windows\System32\nvidia-smi.exe" if Path(r"C:\Windows\System32\nvidia-smi.exe").exists() else None)
    if smi:
        try:
            q = subprocess.run([smi, "--query-gpu=name,driver_version,memory.total,compute_cap", "--format=csv,noheader,nounits"],
                               capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW)
            for line in q.stdout.strip().splitlines():
                p = [x.strip() for x in line.split(",")]
                if len(p) >= 3:
                    g = {"name": p[0], "driver": p[1], "vram_gb": round(float(p[2]) / 1024, 1) if p[2].replace(".", "").isdigit() else None,
                         "vendor": "NVIDIA"}
                    if len(p) >= 4 and re.match(r"^\d+\.\d+$", p[3]):
                        g["compute_cap"] = p[3]
                    out.append(g)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass
    if not out and sys.platform == "win32":
        try:
            q = subprocess.run(["powershell", "-NoProfile", "-Command",
                                "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-CimInstance Win32_VideoController | "
                                "ForEach-Object { \"$($_.Name)|$($_.DriverVersion)|$($_.AdapterRAM)\" }"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20, creationflags=NO_WINDOW)
            for line in q.stdout.strip().splitlines():
                p = line.split("|")
                if len(p) == 3 and p[0].strip():
                    ram_b = int(p[2]) if p[2].strip().isdigit() else 0
                    out.append({"name": p[0].strip(), "driver": p[1].strip(), "vram_gb": round(ram_b / 2**30, 1) if ram_b else None,
                                "vendor": "NVIDIA" if "nvidia" in p[0].lower() else ""})
        except (OSError, subprocess.TimeoutExpired):
            pass
    _GPU_CACHE.update(t=time.time(), v=out)
    return out


def disk(path) -> dict:
    try:
        return {"disk_free_gb": round(shutil.disk_usage(path).free / 2**30, 1)}
    except OSError:
        return {}


# ---------------------------------------------------------------- PyTorch holati (bir marta, keshlanadi)
_LOCK = threading.Lock()
_STATE: dict = {}


def _hint(err: str) -> str:
    e = err.lower()
    if "winerror 126" in e or "winerror 127" in e or "dll load failed" in e or "error loading" in e:
        return "dll_missing"
    if "no kernel image" in e or "not compatible with the current pytorch" in e or "sm_" in e and "not compatible" in e:
        return "gpu_arch"
    if "driver" in e and ("insufficient" in e or "too old" in e or "version" in e):
        return "gpu_driver"
    if "out of memory" in e:
        return "gpu_oom"
    return "other"


def missing_dlls(err: str) -> list[str]:
    """WinError 126 xatosida nomi aytilgan DLL ning o'rnatma ichida topilmagan bog'liqliklari (PE import jadvali bo'yicha)."""
    m = re.search(r'Error loading "([^"]+\.dll)"', err)
    if not m or not Path(m.group(1)).exists():
        return []
    try:
        from .dlldeps import unresolved
        return unresolved(Path(m.group(1)), Path(sys.base_prefix))
    except Exception:          # tahlil — faqat yordamchi ma'lumot
        return []


def arch_compatible(cap: tuple[int, int], archs: list[str]) -> bool:
    """CUDA mosligi: sm_XY kodi bir xil major va minor ≤ bo'lgan GPU'da ishlaydi (sm_86 → sm_89);
    compute_XY (PTX) esa XY ≤ GPU qobiliyati bo'lsa JIT bilan ishlaydi."""
    major, minor = cap
    for a in archs:
        kind, _, num = a.partition("_")
        if not num.isdigit() or len(num) < 2:
            continue
        am, an = int(num[:-1]), int(num[-1])
        if kind == "sm" and am == major and an <= minor:
            return True
        if kind == "compute" and (am, an) <= (major, minor):
            return True
    return False


def torch_state(gpu_test: bool = True) -> dict:
    """{"ok", "version", "cuda", "device", "gpu_ok", "gpu_note", "error", "hint", "missing"} — birinchi chaqiriqda hisoblanadi."""
    with _LOCK:
        if _STATE:
            return dict(_STATE)
        t0 = time.time()
        if os.environ.get("UZLUNGCT_TEST_NO_TORCH") == "1":          # faqat sinov uchun: torch yuklanmagan holat
            err = 'OSError: [WinError 126] Error loading "shm.dll" or one of its dependencies. (sinov rejimi)'
            _STATE.update(ok=False, error=err, hint="dll_missing", missing=[], seconds=0.0)
            return dict(_STATE)
        try:
            import torch
        except BaseException as e:          # OSError (DLL), ImportError va h.k.
            err = f"{type(e).__name__}: {e}"
            _STATE.update(ok=False, error=err, hint=_hint(err), missing=missing_dlls(err), trace=traceback.format_exc()[-3000:],
                          seconds=round(time.time() - t0, 1))
            return dict(_STATE)
        st = {"ok": True, "version": torch.__version__, "cuda": False, "device": "cpu", "gpu_ok": False, "gpu_note": ""}
        try:
            if os.environ.get("UZLUNGCT_FORCE_CPU") == "1":
                st["gpu_note"] = "force_cpu"
            elif torch.cuda.is_available():
                st["cuda"] = True
                cap = torch.cuda.get_device_capability(0)
                arch = f"sm_{cap[0]}{cap[1]}"
                archs = torch.cuda.get_arch_list()
                st["gpu"] = torch.cuda.get_device_name(0); st["arch"] = arch
                if archs and not arch_compatible(cap, archs):
                    st["gpu_note"] = "gpu_arch"
                elif gpu_test:
                    if os.environ.get("UZLUNGCT_TEST_FAIL_CUDA") == "1":
                        raise RuntimeError("CUDA error: no kernel image is available for execution on the device (sinov rejimi)")
                    x = torch.randn(1, 1, 8, 8, 8, device="cuda")
                    w = torch.randn(2, 1, 3, 3, 3, device="cuda")
                    y = torch.softmax(torch.nn.functional.conv3d(x, w, padding=1), 1)
                    float((y @ y.transpose(-1, -2)).sum().item())
                    torch.cuda.synchronize()
                    st["gpu_ok"] = True; st["device"] = "cuda"
                else:
                    st["gpu_ok"] = True; st["device"] = "cuda"
        except BaseException as e:
            st["gpu_note"] = _hint(str(e)) if _hint(str(e)) != "other" else "gpu_error"
            st["gpu_error"] = f"{type(e).__name__}: {e}"[:500]
            st["gpu_ok"] = False; st["device"] = "cpu"
        if not st["gpu_ok"] and st.get("cuda"):
            os.environ["UZLUNGCT_FORCE_CPU"] = "1"       # hw.device() va bola jarayonlar CPU'ni tanlaydi
        st["seconds"] = round(time.time() - t0, 1)
        _STATE.update(st)
        return dict(_STATE)


def reset():
    """Faqat testlar uchun."""
    with _LOCK:
        _STATE.clear()
    _GPU_CACHE.clear()


def summary(home) -> dict:
    """/api/system uchun: har bir qism mustaqil — biri xato bersa, qolganlari ko'rsatiladi."""
    s, errors = {"os": platform.platform()}, {}
    for name, fn in (("cpu", cpu), ("ram", ram), ("disk", lambda: disk(home))):
        try:
            s.update(fn())
        except Exception as e:
            errors[name] = f"{type(e).__name__}: {e}"
    try:
        g = gpus()
        if g:
            s["gpus"] = g; s["gpu"] = g[0]["name"]
            if g[0].get("vram_gb"):
                s["vram_gb"] = g[0]["vram_gb"]
            if g[0].get("driver"):
                s["gpu_driver"] = g[0]["driver"]
    except Exception as e:
        errors["gpu"] = f"{type(e).__name__}: {e}"
    ts = torch_state()
    if ts.get("ok"):
        s.update(torch=ts["version"], cuda=ts["cuda"], device=ts["device"])
        if ts.get("gpu"):
            s["gpu"] = ts["gpu"]
        if ts.get("gpu_note"):
            s["gpu_note"] = ts["gpu_note"]
        try:
            from . import hw
            import torch
            s["seg_profile"] = hw.profile(); s["workers"] = hw.num_workers()
            if ts["device"] == "cuda":
                s["vram_gb"] = round(hw.vram_gb(), 1)
                free, _ = torch.cuda.mem_get_info(); s["vram_free_gb"] = round(free / 2**30, 2)
        except Exception as e:
            errors["torch_info"] = f"{type(e).__name__}: {e}"[:300]
    else:
        s.update(torch=None, device=None)
        errors["torch"] = ts.get("error", "")[:500]
        s["torch_hint"] = ts.get("hint"); s["torch_missing"] = ts.get("missing", [])
    if errors:
        s["errors"] = errors
    return s
