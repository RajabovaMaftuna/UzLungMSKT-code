"""Diagnostika paketi (PM-9): boshqa kompyuterdagi xatoni aniqlash uchun jurnallar va apparat hisoboti — bitta ZIP.

Faqat RUXSAT RO'YXATIDAGI fayllar kiradi; parollar, kalitlar, bazalar, bemor tasvirlari hech qachon kirmaydi.
Matnlardagi bemor ID va F.I.Sh. lari (bemor reyestridan olinadi) «[bemor]» bilan almashtiriladi.
  UI:  GET /api/admin/diagnostics (faqat administrator)
  CLI: UzLungCT.exe --diagnose --bundle   (python -m uzlungct.autostart diagnose --bundle) → ish stolida ZIP
"""
from __future__ import annotations

import io
import json
import re
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAIL = 2 << 20                                    # har bir jurnalning oxirgi 2 MB i
FORBIDDEN_NAMES = {".patient_key", ".service_token", "boshlangich_admin_paroli.txt", "auth.db", "patients.db", "consults.db",
                   "settings.json", "patients.csv", "klinik.xlsx"}
FORBIDDEN_EXT = (".db", ".nii", ".nii.gz", ".dcm", ".npz", ".npy", ".png", ".jpg", ".jpeg", ".pdf", ".zip", ".pt", ".xlsx", ".csv",
                 ".key", ".pem", ".mp4", ".avi")
SAFE_SETTINGS = ("dataset_root", "institution")
ID_RE = re.compile(r"(?<![\w-])\d{6}(?![\w-])")   # bemor ID: 6 xonali raqam (vaqt belgilari 20261010-074801 tegilmaydi)


def _maskers(home: Path):
    """Bemor reyestridagi ID va F.I.Sh. lar (bo'lmasa — faqat 6 xonali raqamlar umumiy niqobi)."""
    words, ids = set(), set()
    try:
        from .web.patients import PatientDB
        if (home / "patients.db").exists() and (home / ".patient_key").exists():
            for pid, p in PatientDB(home / "patients.db", home / ".patient_key")._all().items():
                ids.add(str(pid))
                for k in ("last", "first", "middle"):
                    v = (p.get(k) or "").strip()
                    if len(v) >= 3:
                        words.add(v)
    except Exception:          # reyestr ochilmasa ham paket tuziladi (umumiy niqob bilan)
        pass
    wre = re.compile("|".join(re.escape(w) for w in sorted(words, key=len, reverse=True)), re.I) if words else None

    def mask(text: str) -> str:
        if wre:
            text = wre.sub("[bemor]", text)
        for i in ids:
            text = text.replace(i, "[bemor]")
        return ID_RE.sub("[bemor]", text)
    return mask


def _tail(p: Path) -> str:
    with open(p, "rb") as f:
        f.seek(0, 2); n = f.tell(); f.seek(max(0, n - TAIL))
        return f.read().decode("utf-8", "replace")


def _vc_redist() -> dict:
    if sys.platform != "win32":
        return {}
    import winreg
    out = {}
    for key in (r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64", r"SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
                out = {"installed": bool(winreg.QueryValueEx(k, "Installed")[0]), "version": winreg.QueryValueEx(k, "Version")[0]}
                break
        except OSError:
            continue
    return out or {"installed": False}


def _allowed(name: str) -> bool:
    low = name.lower()
    return Path(low).name not in FORBIDDEN_NAMES and not low.endswith(FORBIDDEN_EXT)


def build(home: Path, root: Path = ROOT) -> bytes:
    from . import sysinfo
    home, root = Path(home), Path(root)
    mask = _maskers(home)
    files: dict[str, str] = {}
    logs = home / "logs"
    if logs.exists():
        for p in sorted(logs.iterdir()):
            if p.is_file() and p.suffix.lower() in (".log", ".txt") and _allowed(p.name):
                files[f"logs/{p.name}"] = mask(_tail(p))
    for n in ("install.log", "VERSION.txt", "README_UzLungCT.txt"):
        if (root / n).is_file():
            files[n] = mask(_tail(root / n))
    jobs = home / "jobs"
    if jobs.exists():
        recent = sorted((d for d in jobs.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime, reverse=True)[:5]
        for d in recent:
            for n in ("job.json", "stdout.log"):
                if (d / n).is_file():
                    files[f"jobs/{d.name}/{n}"] = mask(_tail(d / n))
    rep = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "python": sys.version, "executable": sys.executable, "root": str(root),
           "home": str(home), "vc_redist": _vc_redist()}
    try:
        rep["system"] = sysinfo.summary(home)
        rep["torch_state"] = sysinfo.torch_state()
    except Exception as e:
        rep["system_error"] = f"{type(e).__name__}: {e}"
    if (root / "python").is_dir():                      # o'rnatilgan nusxa: DLL bog'liqliklari tahlili
        try:
            from .dlldeps import analyze
            res = analyze(root / "python")
            rep["dll"] = {k: v for k, v in res.items() if k in ("MISSING", "SYSTEM")} | {"counts": {k: len(v) for k, v in res.items()}}
        except Exception as e:
            rep["dll_error"] = f"{type(e).__name__}: {e}"
    try:
        s = json.loads((home / "settings.json").read_text(encoding="utf-8")) if (home / "settings.json").exists() else {}
        rep["settings"] = {k: s.get(k) for k in SAFE_SETTINGS if k in s}
        dr = rep["settings"].get("dataset_root")
        if dr:
            rep["settings"]["dataset_json_exists"] = (Path(dr) / "dataset.json").is_file()
    except Exception as e:
        rep["settings_error"] = f"{type(e).__name__}: {e}"
    files["hisobot.json"] = mask(json.dumps(rep, ensure_ascii=False, indent=1, default=str))
    bad = [n for n in files if not _allowed(n)]
    assert not bad, f"diagnostika paketiga taqiqlangan fayl tushdi: {bad}"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, text in files.items():
            z.writestr(n, text)
    return buf.getvalue()


def write_desktop(home: Path, root: Path = ROOT) -> Path:
    desk = Path.home() / "Desktop"
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0:   # CSIDL_DESKTOPDIRECTORY
                desk = Path(buf.value)
        except OSError:
            pass
    if not desk.is_dir():
        desk = Path(home)
    out = desk / f"UzLungMSKT_diagnostika_{time.strftime('%Y%m%d_%H%M')}.zip"
    out.write_bytes(build(home, root))
    return out
