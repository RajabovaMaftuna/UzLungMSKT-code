"""UzLungMSKT serverini Windows yoqilganda (foydalanuvchi tizimga kirganda) avtomatik va konsol oynasisiz ishga tushirish.

Avtostart yozuvi HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run da saqlanadi (administrator huquqi kerak emas)
va UzLungCT_server.pyw ni pythonw.exe bilan ishga tushiradi. Server chiqishi <ish papkasi>/logs/web_server.log ga yoziladi.

  python -m uzlungct.autostart enable  [--port 8000] [--name NOM]   avtostartni yoqish
  python -m uzlungct.autostart disable [--name NOM]                 avtostartni o'chirish
  python -m uzlungct.autostart status  [--name NOM] [--port 8000]   holat
  python -m uzlungct.autostart start   [--port 8000]                serverni hozir fon rejimida ishga tushirish
  python -m uzlungct.autostart stop                                 fon rejimidagi serverni to'xtatish
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]           # loyiha yoki o'rnatilgan papka (uzlungct/ ning otasi)
PYW = ROOT / "UzLungCT_server.pyw"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
PORTABLE = (ROOT / "python" / "python.exe").exists()  # UzLungCT.exe o'rnatgan portativ nusxa
DEFAULT_NAME = "UzLungCT" if PORTABLE else "UzLungCT_loyiha"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DETACHED = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | \
    getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)


def home() -> Path:
    return Path(os.environ.get("UZLUNGCT_HOME", ROOT / "workspace")).resolve()


def pid_file() -> Path:
    return home() / "logs" / "web_server.pid"


def pythonw() -> Path:
    exe = ROOT / "python" / "pythonw.exe" if PORTABLE else Path(sys.executable).with_name("pythonw.exe")
    if not exe.exists():
        raise SystemExit(f"pythonw.exe topilmadi: {exe}")
    return exe


def command(port: int) -> list[str]:
    """Konsolsiz server buyrug'i. Portativ nusxada -E -s: tizimdagi boshqa Python sozlamalari ta'sir qilmaydi."""
    flags = ["-E", "-s"] if PORTABLE else []
    return [str(pythonw()), *flags, "-X", "utf8", str(PYW), "--port", str(port)]


def cmdline(args: list[str]) -> str:
    return subprocess.list2cmdline(args)


_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # tizim proksi-serveri chetlab o'tiladi


def running(port: int) -> bool:
    try:
        with _DIRECT.open(f"http://127.0.0.1:{port}/", timeout=3) as r:
            b_ = r.read(4096); return b"UzLungCT" in b_ or b"UzLungMSKT" in b_
    except Exception:
        return False


# ---------------------------------------------------------------- reyestr
def _key(write=False):
    import winreg
    return winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE if write else winreg.KEY_QUERY_VALUE)


def get(name: str) -> str | None:
    import winreg
    try:
        with _key() as k:
            return winreg.QueryValueEx(k, name)[0]
    except FileNotFoundError:
        return None


def enable(name: str, port: int) -> str:
    import winreg
    if not PYW.exists():
        raise SystemExit(f"ishga tushiruvchi topilmadi: {PYW}")
    value = cmdline(command(port))
    with _key(True) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
    return value


def disable(name: str) -> bool:
    import winreg
    try:
        with _key(True) as k:
            winreg.DeleteValue(k, name)
        return True
    except FileNotFoundError:
        return False


# ---------------------------------------------------------------- fon rejimi
def start(port: int, wait: float = 240) -> bool:
    """Serverni konsolsiz, ota jarayondan mustaqil ishga tushiradi va javob berguncha kutadi."""
    if running(port):
        return True
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    kw = dict(cwd=ROOT, env=env, close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        subprocess.Popen(command(port), creationflags=DETACHED | NO_WINDOW, **kw)
    except OSError:   # ota jarayon ishi (job) ajralishga ruxsat bermasa
        subprocess.Popen(command(port), creationflags=(DETACHED & ~getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)) | NO_WINDOW, **kw)
    t = time.time()
    while time.time() - t < wait:
        if running(port):
            return True
        time.sleep(1)
    return False


def stop() -> bool:
    pf = pid_file()
    if not pf.exists():
        return False
    try:
        pid = int(pf.read_text().split()[0])
    except (ValueError, IndexError):
        pf.unlink(missing_ok=True); return False
    img = _image(pid)
    # PID qayta ishlatilgan bo'lishi mumkin: faqat Python jarayoni bo'lsa to'xtatiladi
    if img is None or not Path(img).name.lower().startswith("python"):
        pf.unlink(missing_ok=True); return False
    r = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)
    for _ in range(30):                     # jarayon to'liq chiqib, fayllarni bo'shatguncha
        if _image(pid) is None:
            break
        time.sleep(0.5)
    pf.unlink(missing_ok=True)
    return r.returncode == 0


def _image(pid: int) -> str | None:
    """Jarayonning bajariladigan fayli (jarayon yo'q bo'lsa — None)."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        code = wintypes.DWORD()
        if k32.GetExitCodeProcess(h, ctypes.byref(code)) and code.value != 259:      # STILL_ACTIVE
            return None
        buf = ctypes.create_unicode_buffer(1024); n = wintypes.DWORD(1024)
        return buf.value if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) else ""
    finally:
        k32.CloseHandle(h)


def serve(argv: list[str]) -> None:
    """UzLungCT_server.pyw kirish nuqtasi: port band bo'lib unda UzLungCT ishlayotgan bo'lsa — chiqadi, aks holda serverni
    jurnal fayli bilan ishga tushiradi va PID faylini yozadi."""
    os.chdir(ROOT)
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--port", type=int, default=8000)
    a, rest = ap.parse_known_args(argv)
    if running(a.port):
        return
    pf = pid_file(); pf.parent.mkdir(parents=True, exist_ok=True)
    pf.write_text(f"{os.getpid()} {a.port}", encoding="utf-8")
    # stdout/stderr jurnalga UzLungCT_server.pyw da yo'naltirilgan (konsoldan ishga tushirilganda — konsolga)
    sys.argv = ["uzlungct.web", "--port", str(a.port), "--no-browser", *rest]
    print("[bosqich] kutubxonalar yuklanmoqda...", flush=True)
    try:
        from .web.server import main
        main()
    finally:
        try:
            if pf.read_text().split()[0] == str(os.getpid()):
                pf.unlink()
        except OSError:
            pass


def diagnose(port: int = 8000) -> int:
    """Kompyuter va o'rnatma diagnostikasi (UzLungCT.exe --diagnose). Hisobot: <ish papkasi>/logs/diagnostika.txt"""
    import ctypes
    import importlib
    import platform
    import shutil
    import socket
    lines, bad = [], 0

    def add(name, value, good=True):
        nonlocal bad
        bad += 0 if good else 1
        lines.append(f"[{'OK ' if good else 'XATO'}] {name}: {value}")
        print(lines[-1], flush=True)

    add("Windows", f"{platform.platform()} ({platform.machine()})")
    add("Python", f"{sys.version.split()[0]} — {sys.executable}")
    add("O‘rnatish papkasi", f"{ROOT}{' (lotin bo‘lmagan belgilar bor)' if any(ord(c) > 127 for c in str(ROOT)) else ''}")
    if (ROOT / "python").exists():          # faqat o'rnatilgan nusxada (UzLungCT.exe): yarim o'rnatma va eski qoldiqlar
        ver = ROOT / "VERSION.txt"
        add("O‘rnatma versiyasi", ver.read_text(encoding="utf-8").strip() if ver.exists() else "VERSION.txt yo‘q — o‘rnatish yakunlanmagan",
            ver.exists())
        if (ROOT / "INSTALLING.txt").exists():
            add("O‘rnatish holati", "yakunlanmagan (INSTALLING.txt) — UzLungCT.exe ni qayta ishga tushiring", False)
        old = sorted(p.name for p in ROOT.glob("*.old_*"))
        if old:
            add("Eski versiya qoldiqlari", ", ".join(old) + " — keyingi ishga tushirishda o‘chiriladi")
    k32 = ctypes.windll.kernel32
    avx, avx2 = bool(k32.IsProcessorFeaturePresent(39)), bool(k32.IsProcessorFeaturePresent(40))
    add("Protsessor", f"{platform.processor()}; yadrolar {os.cpu_count()}; AVX={avx}, AVX2={avx2}", avx)

    class MEM(ctypes.Structure):
        _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                    ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong), ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong),
                    ("ae", ctypes.c_ulonglong)]
    m = MEM(); m.len = ctypes.sizeof(MEM); k32.GlobalMemoryStatusEx(ctypes.byref(m))
    add("Operativ xotira", f"{m.total / 2**30:.1f} GB (bo‘sh {m.avail / 2**30:.1f} GB)", m.total >= 7.5 * 2**30)
    du = shutil.disk_usage(home().anchor if home().exists() else ROOT)
    add("Disk", f"bo‘sh {du.free / 2**30:.1f} GB", du.free > 5 * 2**30)
    try:
        q = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"], capture_output=True,
                           text=True, timeout=15, creationflags=NO_WINDOW)
        add("Videokarta (NVIDIA)", q.stdout.strip() or "topilmadi — tahlil protsessorda (sekinroq) bajariladi")
    except (OSError, subprocess.TimeoutExpired):
        add("Videokarta (NVIDIA)", "nvidia-smi yo‘q — tahlil protsessorda (sekinroq) bajariladi")
    for p in (port, *range(8000, 8021)):
        if p != port and p > 8003:
            break
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", p)); state = "bo‘sh"
        except OSError:
            state = "UzLungMSKT ishlayapti" if running(p) else "BOSHQA DASTUR band qilgan"
        finally:
            s.close()
        add(f"Port {p}", state, state != "BOSHQA DASTUR band qilgan" or p != port)
    for mod in ("numpy", "scipy", "SimpleITK", "cv2", "cryptography", "fastapi", "uvicorn", "fpdf", "torch", "monai", "uzlungct.web.server"):
        t = time.time()
        try:
            mm = importlib.import_module(mod)
            extra = ""
            if mod == "torch":
                extra = f"; CUDA={mm.cuda.is_available()}" + (f" ({mm.cuda.get_device_name(0)})" if mm.cuda.is_available() else "")
            add(f"import {mod}", f"{time.time() - t:.1f} s{extra}")
        except BaseException as e:
            add(f"import {mod}", f"{type(e).__name__}: {e}", False)
    # PM-9: torch holati (GPU mosligi), DLL bog'liqliklari, Visual C++ runtime
    try:
        from . import sysinfo
        ts = sysinfo.torch_state()
        if ts.get("ok"):
            add("Tahlil qurilmasi", f"{ts['device']}" + (f"; {ts.get('gpu')} ({ts.get('arch')})" if ts.get("gpu") else "")
                + (f"; videokarta ishlatilmaydi: {ts['gpu_note']} {ts.get('gpu_error', '')[:200]}" if ts.get("gpu_note") else ""))
        else:
            add("PyTorch", f"{ts.get('error', '')[:300]}" + (f"; yetishmayotgan DLL: {', '.join(ts['missing'])}" if ts.get("missing") else ""), False)
    except Exception as e:
        add("PyTorch holati", f"{type(e).__name__}: {e}", False)
    if (ROOT / "python").exists():
        try:
            from .dlldeps import analyze
            res = analyze(ROOT / "python")
            miss = res.get("MISSING", []) + res.get("SYSTEM", [])
            add("DLL bog‘liqliklari", "hammasi o‘rnatma ichida yoki Windows tarkibida" if not miss
                else "o‘rnatmada yo‘q: " + "; ".join(miss[:8]), not res.get("MISSING"))
        except Exception as e:
            add("DLL bog‘liqliklari", f"{type(e).__name__}: {e}", False)
    try:
        from .diagbundle import _vc_redist
        vc = _vc_redist()
        add("Visual C++ Redistributable (x64)", vc.get("version") if vc.get("installed") else "o‘rnatilmagan (UzLungMSKT o‘z nusxasidan foydalanadi)")
    except Exception:
        pass
    for f in (home() / "logs" / "startup_error.txt", home() / "logs" / "web_server.log"):
        if f.exists():
            tail = f.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-12:]
            lines.append(f"--- {f.name} (oxiri) ---"); lines.extend(tail)
    lines.append(f"XULOSA: {'muammo topilmadi' if not bad else str(bad) + ' ta muammo'}")
    print(lines[-1])
    out = home() / "logs" / "diagnostika.txt"; out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"UzLungMSKT diagnostikasi — {time.strftime('%Y-%m-%d %H:%M:%S')}\n" + "\n".join(lines) + "\n", encoding="utf-8")
    print(f"Hisobot: {out}")
    return 1 if bad else 0


def rotate_token() -> int:
    """Xizmat tokenini (.service_token) yangilaydi; ishlab turgan server yangi token bilan qayta ishga tushiriladi."""
    import secrets
    pf = pid_file(); port = None
    if pf.exists():
        try:
            port = int(pf.read_text().split()[1])
        except (ValueError, IndexError):
            port = None
    was = stop()
    tf = home() / ".service_token"; tf.parent.mkdir(parents=True, exist_ok=True)
    tf.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    print("Xizmat tokeni yangilandi.")
    if was and port:
        ok = start(port)
        print(f"Server qayta ishga tushirildi: http://localhost:{port}" if ok else "Server qayta ishga tushmadi — UzLungCT.exe ni ishga tushiring.")
        return 0 if ok else 1
    return 0


def main():
    ap = argparse.ArgumentParser(description="UzLungMSKT serverining Windows avtostarti")
    ap.add_argument("action", choices=["enable", "disable", "status", "start", "stop", "diagnose", "rotate-token"])
    ap.add_argument("--bundle", action="store_true", help="diagnose: ish stolida diagnostika paketi (ZIP) ham yaratiladi")
    ap.add_argument("--name", default=DEFAULT_NAME, help=f"reyestrdagi yozuv nomi (standart: {DEFAULT_NAME})")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    if a.action == "enable":
        v = enable(a.name, a.port)
        print(f"Avtostart yoqildi ({a.name}): {v}")
    elif a.action == "disable":
        print("Avtostart o‘chirildi." if disable(a.name) else "Avtostart yozuvi topilmadi.")
    elif a.action == "status":
        v = get(a.name)
        print(f"Avtostart ({a.name}): {'yoqilgan — ' + v if v else 'o‘chirilgan'}")
        print(f"Server http://localhost:{a.port}: {'ishlayapti' if running(a.port) else 'ishlamayapti'}")
    elif a.action == "start":
        ok = start(a.port)
        print(f"Server http://localhost:{a.port}: {'ishlayapti' if ok else 'ishga tushmadi — jurnal: ' + str(home() / 'logs' / 'web_server.log')}")
        sys.exit(0 if ok else 1)
    elif a.action == "stop":
        print("Server to‘xtatildi." if stop() else "Fon rejimidagi server topilmadi (PID fayli yo‘q).")
    elif a.action == "diagnose":
        rc = diagnose(a.port)
        if a.bundle:
            from .diagbundle import write_desktop
            out = write_desktop(home(), ROOT)
            print(f"Diagnostika paketi: {out}")
            print("Shu faylni yuboring (unda parollar, kalitlar va bemor ma’lumotlari yo‘q).")
        sys.exit(rc)
    elif a.action == "rotate-token":
        sys.exit(rotate_token())


if __name__ == "__main__":
    main()
