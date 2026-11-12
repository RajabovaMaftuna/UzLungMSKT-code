"""Gibrid usul: TotalSegmentator `lung_nodules` natijasini o'z modelimiz niqobi bilan birlashtirish.

Qoida (oldindan qat'iy, 8 ta bemorda sozlanmagan): yakuniy niqob = o'z modeli (p>=0.5)  YOKI  TotalSegmentator nodul niqobi.
So'ng o'pka qobig'i filtri (infer.select_components) ikkalasiga ham birdek qo'llanadi.
Har bir o'choqda manba belgisi saqlanadi: own / ts / both — radiolog qaysi model topganini ko'radi.
TotalSegmentator mavjud bo'lmasa yoki xato bersa, tahlil faqat o'z modeli bilan davom etadi (holat hisobotda)."""
from __future__ import annotations
import os, subprocess, sys, tempfile, time
from pathlib import Path
import numpy as np

DEFAULT_PY = sys.executable.replace("pythonw.exe", "python.exe")
DEFAULT_WEIGHTS = str(Path(__file__).resolve().parents[1] / "models" / "senguard3d" / "totalseg")
TIMEOUT_S = 2400


def config() -> dict:
    return {"python": os.environ.get("UZLUNGCT_TS_PYTHON", DEFAULT_PY),
            "weights": os.environ.get("UZLUNGCT_TS_WEIGHTS", DEFAULT_WEIGHTS),
            "mode": os.environ.get("UZLUNGCT_TS", "auto").lower()}      # auto | off


def available() -> bool:
    c = config()
    return c["mode"] != "off" and Path(c["python"]).is_file()


def fuse(own: np.ndarray, ts: np.ndarray | None) -> np.ndarray:
    own = own.astype(bool)
    return own if ts is None else (own | ts.astype(bool))


def source_of(own: np.ndarray, ts: np.ndarray | None, comp_slice, comp: np.ndarray) -> str:
    """Komponent qaysi modeldan: o'z modeli niqobi bilan kesishsa 'own', TS bilan kesishsa 'ts', ikkalasi bilan 'both'."""
    in_own = bool(own[comp_slice][comp].any())
    in_ts = bool(ts is not None and ts[comp_slice][comp].any())
    return "both" if in_own and in_ts else ("ts" if in_ts else "own")


def run_nodules(img, workdir: Path | None = None, runner: str | None = None):
    """img — 1 mm RAS SimpleITK tasviri (analyze_image ichidagi `img`). Qaytaradi: (bool massiv | None, info dict)."""
    import SimpleITK as sitk
    c = config()
    info = {"status": "off", "model": "TotalSegmentator lung_nodules"}
    if c["mode"] == "off":
        return None, info
    if not Path(c["python"]).is_file():
        info["status"] = "unavailable"
        return None, info
    t0 = time.time()
    tmp = tempfile.mkdtemp(prefix="uzlungct_ts_", dir=str(workdir) if workdir else None)
    try:
        src = os.path.join(tmp, "ct.nii.gz")
        sitk.WriteImage(img, src)
        out = os.path.join(tmp, "out")
        env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
        env["TOTALSEG_HOME_DIR"] = c["weights"]
        runner = runner or str(Path(__file__).with_name("ts_runner.py"))
        r = subprocess.run([c["python"], "-E", "-s", runner, src, out], env=env, capture_output=True, text=True, timeout=TIMEOUT_S)
        f = os.path.join(out, "lung_nodules.nii.gz")
        if r.returncode != 0 or not os.path.isfile(f):
            info.update(status="error", detail=(r.stderr or r.stdout or "")[-300:])
            return None, info
        arr = sitk.GetArrayFromImage(sitk.ReadImage(f)) > 0
        if arr.shape != tuple(sitk.GetArrayFromImage(img).shape):
            info.update(status="error", detail=f"shape {arr.shape}")
            return None, info
        info.update(status="ok", seconds=round(time.time() - t0, 1), voxels=int(arr.sum()))
        return arr, info
    except subprocess.TimeoutExpired:
        info.update(status="timeout", seconds=round(time.time() - t0, 1))
        return None, info
    except Exception as e:                       # TS hech qachon asosiy tahlilni buzmasligi kerak
        info.update(status="error", detail=f"{type(e).__name__}: {str(e)[:200]}")
        return None, info
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def make_ts_fn():
    """analyze_image(ts_fn=...) uchun: TS mavjud bo'lsa funksiya, aks holda None."""
    return (lambda img, ct: run_nodules(img)) if available() else None
