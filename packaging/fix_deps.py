# Ko'chma python'da import xatolarini takrorlab aniqlaydi va yetishmagan paketni (py3.13 g'ildirak) o'rnatadi. Ko'pi bilan 30 aylanish.
import subprocess, re, sys
PP = r"C:\ZG\build_exe\stage\python\python.exe"; T = r"C:\ZG\build_exe\stage\python\Lib\site-packages"
TEST = "import nnunetv2, totalsegmentator, nibabel; from totalsegmentator.python_api import totalsegmentator as t; from nnunetv2.inference.predict_from_raw_data import nnUNetPredictor; from nnunetv2.utilities.plans_handling.plans_handler import PlansManager; import monai, torch; print('IMPORT_OK')"
MAP = {"yaml": "PyYAML", "PIL": "Pillow", "skimage": "scikit-image", "sklearn": "scikit-learn", "cv2": "opencv-python-headless", "dateutil": "python-dateutil", "gdcm": "python-gdcm", "cc3d": "connected-components-3d", "attr": "attrs", "google": "protobuf"}
for i in range(30):
    r = subprocess.run([PP, "-c", TEST], capture_output=True, text=True)
    if "IMPORT_OK" in r.stdout:
        print("TAYYOR", i); sys.exit(0)
    m = re.search(r"No module named '([^'.]+)", r.stderr)
    if not m:
        print("BOSHQA XATO:\n", r.stderr[-1500:]); sys.exit(1)
    mod = m.group(1); pkg = MAP.get(mod, mod.replace("_", "-"))
    print("o'rnatilmoqda:", mod, "->", pkg, flush=True)
    q = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--target", T, "--python-version", "3.13", "--platform", "win_amd64", "--implementation", "cp", "--only-binary=:all:", "--no-deps", pkg], capture_output=True, text=True)
    if q.returncode:
        q = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--target", T, "--no-deps", pkg], capture_output=True, text=True)
        if q.returncode:
            print("O'RNATILMADI", pkg, q.stderr[-400:]); sys.exit(1)
print("30 aylanishdan oshdi"); sys.exit(1)
