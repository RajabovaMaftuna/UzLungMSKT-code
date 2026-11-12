"""N8 tashqi quvurini platforma tahliliga ulaydi: tashqi jarayon, natija 1 mm RAS to'riga."""
import json, os, subprocess, sys, tempfile
from pathlib import Path
import numpy as np

PY = sys.executable.replace("pythonw.exe", "python.exe")   # platformaning o'z (ko'chma) python'i


def run_n8(img0, img):
    """img0 — asl tasvir, img — 1 mm to'r. (bool massiv zyx, ma'lumot) qaytaradi."""
    import SimpleITK as sitk
    cache = Path(__file__).parent.parent / "workspace" / "cache"; cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(cache)) as d:
        ct = Path(d) / "ct.nii.gz"; out = Path(d) / "o"
        sitk.WriteImage(img0, str(ct))
        for _ in range(2):
            r = subprocess.run([PY, str(Path(__file__).parent.parent / "n8_runner.py"), str(ct), str(out)], capture_output=True, text=True,
                               env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"}, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | 0x08000000)
            if not r.returncode:
                break
        if r.returncode:
            raise RuntimeError("n8_failed: " + r.stderr[-300:])
        m = sitk.ReadImage(str(out / "n8_mask.nii.gz"))
        boxes = json.load(open(out / "n8_boxes.json"))
        src = sitk.GetArrayFromImage(sitk.Resample(sitk.ReadImage(str(out / "n8_src.nii.gz")), img, sitk.Transform(), sitk.sitkNearestNeighbor, 0)).astype(np.uint8)
        prob = sitk.GetArrayFromImage(sitk.Resample(sitk.ReadImage(str(out / "n8_prob.nii.gz")), img, sitk.Transform(), sitk.sitkLinear, 0.0)).astype(np.float32)
    mask = sitk.GetArrayFromImage(sitk.Resample(m, img, sitk.Transform(), sitk.sitkNearestNeighbor, 0)) > 0
    m2p = prob.copy(); dsc = np.zeros_like(prob); shape = np.array(mask.shape[::-1])
    for b in boxes:
        a = np.array(img.TransformPhysicalPointToContinuousIndex((-b["lo"][0], -b["lo"][1], b["lo"][2])))
        e = np.array(img.TransformPhysicalPointToContinuousIndex((-b["hi"][0], -b["hi"][1], b["hi"][2])))
        lo = np.floor(np.minimum(a, e)).astype(int).clip(0, shape - 1); hi = np.ceil(np.maximum(a, e)).astype(int).clip(1, shape)
        c = (lo + hi - 1) / 2; r = np.maximum((hi - lo) / 2, 1)
        z, y, x = np.ogrid[lo[2]:hi[2], lo[1]:hi[1], lo[0]:hi[0]]
        e = ((x - c[0]) / r[0]) ** 2 + ((y - c[1]) / r[1]) ** 2 + ((z - c[2]) / r[2]) ** 2 <= 1
        v = (slice(lo[2], hi[2]), slice(lo[1], hi[1]), slice(lo[0], hi[0]))
        mask[v] |= e; src[v] |= (e * 8).astype(np.uint8); prob[v] = np.where(e, np.maximum(prob[v], b["score"]), prob[v]); dsc[v] = np.where(e, np.maximum(dsc[v], b["score"]), dsc[v])
    return mask, {"status": "ok", "model": "N8", "boxes": len(boxes), "_src": src, "_prob": prob, "_m2p": m2p, "_dsc": dsc}
