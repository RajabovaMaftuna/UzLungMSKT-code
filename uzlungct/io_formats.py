"""Turli formatdagi MSKT tasvirlarini yagona 3D hajmga o'qish.

Qo'llab-quvvatlanadi:
  * DICOM — alohida .dcm fayllar, kengaytmasiz DICOM fayllar yoki ZIP arxiv (eng ko'p kesimli seriya tanlanadi);
  * NIfTI (.nii, .nii.gz), MetaImage (.mha), NRRD (.nrrd);
  * rasmlar — JPEG, PNG, BMP, TIFF (bir nechta fayl → nomi bo'yicha tartiblangan kesimlar);
  * PDF — har bir sahifa bitta kesim;
  * video — MP4, AVI, MOV, MKV (har bir kadr bitta kesim; takroriy kadrlar olib tashlanadi).

Kalibrlanmagan manbalar (rasm, PDF, video) uchun kulrang daraja o'pka oynasi (L −600, W 1500) deb
faraz qilinib HU ga taxminan qaytariladi, piksel o'lchami 0,7 mm, kesim oralig'i 1,25 mm deb olinadi.
Bunday hollarda natija `calibrated=False` va ogohlantirishlar bilan qaytariladi.
"""
from __future__ import annotations

import io
import os
import shutil
import zipfile
from pathlib import Path

import numpy as np
import SimpleITK as sitk

VOLUME_EXT = (".nii.gz", ".nii", ".mha", ".nrrd")
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff")
VIDEO_EXT = (".mp4", ".avi", ".mov", ".mkv", ".wmv")
PDF_EXT = (".pdf",)
DICOM_EXT = (".dcm", ".dicom", ".ima", "")
ALL_EXT = VOLUME_EXT + IMAGE_EXT + VIDEO_EXT + PDF_EXT + (".dcm", ".dicom", ".ima", ".zip")

ASSUMED_LEVEL, ASSUMED_WIDTH = -600.0, 1500.0
ASSUMED_PIXEL_MM, ASSUMED_SLICE_MM = 0.7, 1.25
MAX_FRAMES = 600


def _ext(p: Path):
    n = p.name.lower()
    for e in (".nii.gz",) + VOLUME_EXT + IMAGE_EXT + VIDEO_EXT + PDF_EXT + (".zip", ".dcm", ".dicom", ".ima"):
        if n.endswith(e):
            return e
    return ""


def _is_dicom(p: Path):
    try:
        with open(p, "rb") as f:
            f.seek(128)
            return f.read(4) == b"DICM"
    except OSError:
        return False


def _gray_to_hu(stack):
    """0..255 kulrang → taxminiy HU (o'pka oynasi faraz qilinadi)."""
    g = stack.astype(np.float32) / 255.0
    return (ASSUMED_LEVEL - ASSUMED_WIDTH / 2 + g * ASSUMED_WIDTH).astype(np.int16)


def _to_gray(arr):
    a = np.asarray(arr)
    if a.ndim == 3:
        a = a[..., :3].astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)
    return np.clip(a, 0, 255).astype(np.uint8)


def _crop_common(frames):
    """Kadrlardagi qora chegaralar va interfeys elementlarini kesish (umumiy bbox)."""
    m = np.mean(np.stack(frames[: min(len(frames), 50)]), 0)
    ys, xs = np.where(m > 8)
    if len(ys) == 0:
        return frames
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    return [f[y0:y1, x0:x1] for f in frames]


def _resize_same(frames):
    from PIL import Image
    h = int(np.median([f.shape[0] for f in frames])); w = int(np.median([f.shape[1] for f in frames]))
    out = []
    for f in frames:
        out.append(f if f.shape == (h, w) else np.asarray(Image.fromarray(f).resize((w, h), Image.BILINEAR)))
    return out


def _stack_to_image(frames, source):
    frames = _resize_same(_crop_common(frames))
    vol = _gray_to_hu(np.stack(frames))                    # (z, y, x)
    img = sitk.GetImageFromArray(vol)
    img.SetSpacing((ASSUMED_PIXEL_MM, ASSUMED_PIXEL_MM, ASSUMED_SLICE_MM))
    warn = ["uncalibrated_intensity", "assumed_spacing"]
    if len(frames) < 16:
        warn.append("too_few_slices")
    return img, {"source": source, "calibrated": False, "n_slices": len(frames), "warnings": warn}


def _read_images(paths):
    from PIL import Image, ImageSequence
    frames = []
    for p in sorted(paths, key=lambda q: q.name):
        im = Image.open(p)
        for fr in ImageSequence.Iterator(im):             # ko'p sahifali TIFF
            frames.append(_to_gray(fr.convert("RGB")))
    return _stack_to_image(frames, "image")


def _read_pdf(p):
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(p))
    frames = []
    for i in range(min(len(doc), MAX_FRAMES)):
        frames.append(_to_gray(np.asarray(doc[i].render(scale=2).to_pil().convert("RGB"))))
    return _stack_to_image(frames, "pdf")


def _ascii_file(p: Path):
    """OpenCV/GDCM Windows'da lotin bo'lmagan yo'lni ocha olmaydi — fayl vaqtinchalik ASCII papkaga nusxalanadi.
    Qaytaradi: (ishlatiladigan yo'l, o'chiriladigan vaqtinchalik papka | None)."""
    from .sio import _ascii, _tmpdir
    if _ascii(str(p)):
        return p, None
    t = _tmpdir(); q = t / ("in" + (p.suffix if _ascii(p.suffix) else ""))
    shutil.copyfile(p, q)
    return q, t


def _ascii_tree(d: Path):
    """DICOM papkasi: yo'llarning birortasi ASCII bo'lmasa, barcha fayllar vaqtinchalik ASCII papkaga noyob nomlar bilan
    nusxalanadi (GDCM seriyalarni fayl ichidagi SeriesInstanceUID bo'yicha guruhlaydi, papka tuzilishi kerak emas)."""
    from .sio import _ascii, _tmpdir
    files = [q for q in d.rglob("*") if q.is_file()]
    if _ascii(str(d)) and all(_ascii(str(q)) for q in files):
        return d, None
    t = _tmpdir()
    for i, q in enumerate(files):
        shutil.copyfile(q, t / f"f{i:06d}{q.suffix if _ascii(q.suffix) else ''}")
    return t, t


def _read_video(p):
    p, tmp = _ascii_file(Path(p))
    try:
        return _read_video_ascii(p)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def _read_video_ascii(p):
    import cv2
    cap = cv2.VideoCapture(str(p))
    frames, prev = [], None
    while len(frames) < MAX_FRAMES:
        ok, fr = cap.read()
        if not ok:
            break
        g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        if prev is not None and np.mean(np.abs(g.astype(np.int16) - prev.astype(np.int16))) < 1.0:
            continue                                        # bir xil kadr (pauza) — tashlanadi
        frames.append(g); prev = g
    cap.release()
    if not frames:
        raise ValueError("video_unreadable")
    return _stack_to_image(frames, "video")


def _read_dicom_dir(d: Path):
    d, tmp = _ascii_tree(Path(d))
    try:
        return _read_dicom_dir_ascii(d)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def _read_dicom_dir_ascii(d: Path):
    best, n = None, 0
    dirs = [d] + [p for p in d.rglob("*") if p.is_dir()]
    for sub in dirs:
        for sid in sitk.ImageSeriesReader.GetGDCMSeriesIDs(str(sub)) or []:
            files = sitk.ImageSeriesReader.GetGDCMSeriesFileNames(str(sub), sid)
            if len(files) > n:
                best, n = files, len(files)
    if not best:
        raise ValueError("no_dicom_series")
    r = sitk.ImageSeriesReader(); r.SetFileNames(best)
    img = r.Execute()
    meta = {"source": "dicom", "calibrated": True, "n_slices": img.GetSize()[2], "warnings": []}
    if n < 16:
        meta["warnings"].append("too_few_slices")
    return img, meta


MAX_UNZIP_BYTES, MAX_UNZIP_FILES = 12 * 2**30, 50_000     # «zip bombasi» va diskni to'ldirishdan himoya


def _safe_extract(zpath: Path, dest: Path, budget: list):
    """ZIP ni xavfsiz ochish: yo'l dest ichida qoladi, umumiy ochilgan hajm va fayllar soni cheklangan,
    ichki ZIP lar ochilmaydi (rekursiya yo'q). budget = [qolgan_bayt, qolgan_fayl]."""
    root = dest.resolve()
    with zipfile.ZipFile(zpath) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            budget[0] -= info.file_size; budget[1] -= 1
            if budget[0] < 0 or budget[1] < 0:
                raise ValueError("archive_too_large")
            out = (dest / info.filename).resolve()
            if root not in out.parents:
                continue                                    # «../» yoki mutlaq yo'l — o'tkazib yuboriladi
            out.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(out, "wb") as dst:
                n = 0
                while True:
                    chunk = src.read(1 << 20)
                    if not chunk:
                        break
                    n += len(chunk)
                    if n > info.file_size:                  # sarlavhadagi hajm yolg'on bo'lsa
                        raise ValueError("archive_too_large")
                    dst.write(chunk)


def _tar_extract(zpath: Path, dest: Path, budget: list):
    """Zaxira: Windows 10+ dagi tar.exe (libarchive) — zip (Deflate64/LZMA), rar, 7z ni ochadi.
    libarchive mutlaq yo'l va «../» ni o'zi rad etadi; hajm/fayl soni chegarasi ochilgandan keyin tekshiriladi."""
    import subprocess
    tar = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tar.exe"
    if not tar.exists():
        raise ValueError("unsupported_format")
    dest.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([str(tar), "-xf", str(zpath), "-C", str(dest)], capture_output=True, timeout=1800,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    files = [q for q in dest.rglob("*") if q.is_file()]
    if r.returncode != 0 and not files:
        raise ValueError("unsupported_format")
    budget[0] -= sum(q.stat().st_size for q in files); budget[1] -= len(files)
    if budget[0] < 0 or budget[1] < 0:
        shutil.rmtree(dest, ignore_errors=True)
        raise ValueError("archive_too_large")


def load_any(paths, workdir: Path, _depth=0):
    """paths — yuklangan fayllar ro'yxati (Path). Qaytaradi: (SimpleITK rasm, meta)."""
    paths = [Path(p) for p in paths]
    workdir.mkdir(parents=True, exist_ok=True)
    exts = {_ext(p) for p in paths}
    if ".zip" in exts:
        if _depth > 0:
            raise ValueError("unsupported_format")          # ZIP ichidagi ZIP ochilmaydi
        d = workdir / "unzipped"
        budget = [MAX_UNZIP_BYTES, MAX_UNZIP_FILES]
        for p in paths:
            if _ext(p) == ".zip":
                try:
                    _safe_extract(p, d, budget)
                except (zipfile.BadZipFile, NotImplementedError):
                    _tar_extract(p, d, budget)              # RAR/7z «.zip» nomi bilan yoki Deflate64/LZMA usuli
        inner = [q for q in d.rglob("*") if q.is_file()] if d.exists() else []
        iexts = {_ext(q) for q in inner}
        if any(_is_dicom(q) for q in inner[:200]) or iexts & {".dcm", ".dicom", ".ima"}:
            return _read_dicom_dir(d)
        return load_any(inner, workdir / "inner", _depth + 1)
    if len(paths) == 1 and _ext(paths[0]) in VOLUME_EXT:
        from .sio import read_image
        img = read_image(paths[0])
        if img.GetDimension() != 3:
            raise ValueError("not_3d")
        return img, {"source": "volume", "calibrated": True, "n_slices": img.GetSize()[2], "warnings": []}
    if exts <= set(VIDEO_EXT) and len(paths) == 1:
        return _read_video(paths[0])
    if exts <= set(PDF_EXT) and len(paths) == 1:
        return _read_pdf(paths[0])
    if exts <= set(IMAGE_EXT):
        return _read_images(paths)
    dcm = [p for p in paths if _ext(p) in (".dcm", ".dicom", ".ima") or _is_dicom(p)]
    if dcm and len(dcm) * 2 >= len(paths):                   # papkadagi begona fayllar (LOCKFILE, VERSION, txt …) e'tiborga olinmaydi
        d = workdir / "dicom"; d.mkdir(exist_ok=True)
        for p in dcm:
            if p.parent != d:
                p.replace(d / p.name)
        return _read_dicom_dir(d)
    raise ValueError("unsupported_format")
