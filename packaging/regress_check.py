# Regressiya (03.11.2026, boshqa PC xatolari): o'rnatma ichida, "zaharlangan" foydalanuvchi site-packages bilan
# 1) .zip nomli 7z arxivi (Kirill nom) ochilishi, 2) SenGuard-3D to'liq ishlashi. Ishlatish: python -E -s regress_check.py <ct.nii.gz> <ish_papka>
import os, sys, subprocess, shutil
from pathlib import Path
ct, w = Path(sys.argv[1]), Path(sys.argv[2]); shutil.rmtree(w, ignore_errors=True)
pois = w / "userbase" / "Python313" / "site-packages" / "nnunetv2"; pois.mkdir(parents=True)
(pois / "__init__.py").write_text('raise ImportError("SOXTA foydalanuvchi nnunetv2")')
os.environ["APPDATA"] = os.environ["PYTHONUSERBASE"] = str(w / "userbase")
sys.path.insert(0, os.getcwd())
src = w / "src" / "Синов_папка"; src.mkdir(parents=True); shutil.copy(ct, src / "ct.nii.gz")
arc = w / "МСКТ тест.zip"
subprocess.run([os.path.join(os.environ["SystemRoot"], "System32", "tar.exe"), "--format", "7zip", "-cf", str(arc), "-C", str(w / "src"), "."], check=True)
from uzlungct.io_formats import load_any
from uzlungct.n8fusion import run_n8
img, meta = load_any([arc], w / "dec"); print("arxiv OK", img.GetSize())
m, info = run_n8(img, img); n = int(m.sum()); print("N8 OK voksel", n, "qutilar", info["boxes"])
sys.exit(0 if n > 0 else 1)
