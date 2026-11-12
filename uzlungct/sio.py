"""SimpleITK uchun xavfsiz o'qish/yozish.

Windows'da SimpleITK (ITK) yo'lda lotin bo'lmagan belgilar bo'lsa (masalan, "2024-2025 год")
faylni ocha olmaydi. Bunday hollarda fayl vaqtinchalik ASCII papkaga nusxalanadi (yoki u yerga
yoziladi va keyin ko'chiriladi).
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import SimpleITK as sitk


def _ascii(p: str) -> bool:
    try:
        p.encode("ascii"); return True
    except UnicodeEncodeError:
        return False


def _tmpdir():
    base = Path(tempfile.gettempdir())
    if not _ascii(str(base)):
        base = Path(os.environ.get("SystemDrive", "C:") + "\\") / "Temp"
        base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="uzlct_", dir=str(base)))


def read_image(path, pixel_type=None) -> sitk.Image:
    path = str(path)
    if _ascii(path):
        return sitk.ReadImage(path) if pixel_type is None else sitk.ReadImage(path, pixel_type)
    d = _tmpdir()
    try:
        src = Path(path)
        dst = d / ("in" + "".join(src.suffixes[-2:]) if src.name.lower().endswith(".nii.gz") else "in" + src.suffix)
        shutil.copyfile(src, dst)
        if src.suffix.lower() == ".mhd":           # MetaImage: yonidagi .raw/.zraw ham kerak
            for ext in (".raw", ".zraw"):
                r = src.with_suffix(ext)
                if r.exists():
                    shutil.copyfile(r, d / r.name)
        img = sitk.ReadImage(str(dst)) if pixel_type is None else sitk.ReadImage(str(dst), pixel_type)
        return img
    finally:
        shutil.rmtree(d, ignore_errors=True)


def write_image(img: sitk.Image, path, compress=True):
    path = str(path)
    if _ascii(path):
        return sitk.WriteImage(img, path, compress)
    d = _tmpdir()
    try:
        src = Path(path)
        tmp = d / ("out.nii.gz" if src.name.lower().endswith(".nii.gz") else "out" + src.suffix)
        sitk.WriteImage(img, str(tmp), compress)
        shutil.move(str(tmp), path)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def series_files(directory):
    """DICOM seriyalari: {series_id: [fayllar]} (lotin bo'lmagan yo'llar uchun ham)."""
    directory = str(directory)
    out = {}
    for sid in sitk.ImageSeriesReader.GetGDCMSeriesIDs(directory) or []:
        out[sid] = list(sitk.ImageSeriesReader.GetGDCMSeriesFileNames(directory, sid))
    return out
