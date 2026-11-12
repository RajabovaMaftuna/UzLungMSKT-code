# 6-maqola, 3.2-bo'lim: turli kirish formatlari uchun yuklash va tahlil vaqti (2026-11-12).
# Kirish fayllari ochiq NLSTseg tekshiruvidan yasaladi (bemor ma'lumoti emas): NIfTI hajm, bitta DICOM kesim, PNG kesim,
# 40 kadrli MP4 video va bitta sahifali PDF. Har bir fayl uchun: hajm (MB); platformaning uzlungct.io_formats.load_any bilan
# yuklash vaqti; olingan hajmdagi kesimlar soni va kalibrlanganlik belgisi; SenGuard-3D tahlil zanjiri (n8_runner.py,
# alohida jarayon) vaqti. Ishlatish: python -E -s format_timing.py <NLSTseg nii papkasi> <bemor ID> <ish papkasi> <natija.json>
import json, os, shutil, subprocess, sys, time
from pathlib import Path
import numpy as np
import SimpleITK as sitk
STAGE = Path(r'C:\ZG\build_exe\stage'); sys.path.insert(0, str(STAGE))
from uzlungct.io_formats import load_any

NII, PID, W, OUT = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4])
W.mkdir(parents=True, exist_ok=True)
ct_path = NII / PID / f'{PID}_CT.nii.gz'
ct = sitk.ReadImage(str(ct_path)); a = sitk.GetArrayFromImage(ct).astype(np.int16)
z = int(np.argmax([(s < -500).sum() for s in a]))                   # o'pka maydoni eng katta kesim
win = lambda s: np.clip((s.astype(np.float32) + 1350) / 1500 * 255, 0, 255).astype(np.uint8)   # L -600, W 1500

files = {}
files['NIfTI'] = W / 'hajm.nii.gz'; shutil.copyfile(ct_path, files['NIfTI'])
d = W / 'dicom'; d.mkdir(exist_ok=True)
sl = sitk.GetImageFromArray(a[z]); sl.SetSpacing(ct.GetSpacing()[:2])      # bitta kesim, HU (rescale 1/0)
for k, v in (('0008|0060', 'CT'), ('0028|1052', '0'), ('0028|1053', '1'), ('0020|0013', '1')):
    sl.SetMetaData(k, v)
sitk.WriteImage(sl, str(d / 'IM0001.dcm'))
files['DICOM'] = d / 'IM0001.dcm'
import cv2
files['PNG'] = W / 'kesim.png'; cv2.imwrite(str(files['PNG']), win(a[z]))
files['MP4'] = W / 'video.mp4'
vw = cv2.VideoWriter(str(files['MP4']), cv2.VideoWriter_fourcc(*'mp4v'), 10, (a.shape[2], a.shape[1]), False)
for k in range(max(0, z - 20), max(0, z - 20) + 40):
    vw.write(win(a[min(k, len(a) - 1)]))
vw.release()
from fpdf import FPDF
pdf = FPDF(unit='pt', format=(a.shape[2], a.shape[1])); pdf.add_page(); pdf.image(str(files['PNG']), 0, 0, a.shape[2], a.shape[1])
files['PDF'] = W / 'sahifa.pdf'; pdf.output(str(files['PDF']))

res = {}
env = {k: v for k, v in os.environ.items() if not k.startswith('PYTHON')}
for name, f in files.items():
    t0 = time.perf_counter(); img, meta = load_any([f], W / f'dec_{name}'); t_load = time.perf_counter() - t0
    vol = W / f'in_{name}.nii.gz'; sitk.WriteImage(img, str(vol))
    out = W / f'n8_{name}'; shutil.rmtree(out, ignore_errors=True)
    t0 = time.perf_counter()
    r = subprocess.run([str(STAGE / 'python' / 'python.exe'), '-E', '-s', str(STAGE / 'n8_runner.py'), str(vol), str(out)], env=env, capture_output=True, text=True)
    t_an = time.perf_counter() - t0
    res[name] = {'file_mb': round(f.stat().st_size / 2**20, 2), 'load_s': round(t_load, 2), 'slices': img.GetSize()[2],
                 'calibrated': bool(meta.get('calibrated', True)), 'source': meta.get('source'), 'analysis_s': round(t_an, 1),
                 'analysis_ok': r.returncode == 0}
    print(name, res[name], flush=True)
import torch
json.dump({'case': f'NLSTseg {PID} (public)', 'gpu': torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'cpu',
           'platform': (STAGE / 'VERSION.txt').read_text(encoding='utf-8').strip(), 'formats': res}, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
