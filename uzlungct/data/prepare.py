"""Ma'lumotlarni yagona keshga tayyorlash (2.1–2.2-§ algoritmining o'qitishga moslangan qismi).

Har bir holat uchun:
  1) KT ni 1×1×1 mm izotrop o'lchamga keltirish (agar kerak bo'lsa),
  2) o'pka maskasi chegarasida (+margin mm) kesish — RAM va disk tejaladi,
  3) int16 HU va uint8 belgilarni bitta .npz ga yozish (np.savez, siqilmagan → tez o'qiladi),
  4) indeks.json: holatlar ro'yxati, bo'linish, voksel o'lchami, kesish koordinatalari.

Manbalar:
  local  — UzLungMSKT-local (dataset.json; image_1mm, lung, lesion)
  msd    — Medical Segmentation Decathlon Task06_Lung (imagesTr/labelsTr, nnU-Net formati)
  pairs  — istalgan CSV: case_id,image,label[,lung][,split]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path

import numpy as np
import SimpleITK as sitk


def read(path):
    from ..sio import read_image
    img = read_image(path)
    return img


def to_ras_1mm(img, is_label=False, spacing=(1.0, 1.0, 1.0)):
    img = sitk.DICOMOrient(img, "RAS")
    sp, sz = img.GetSpacing(), img.GetSize()
    if all(abs(a - b) < 1e-3 for a, b in zip(sp, spacing)):
        return img
    nsz = [max(1, int(round(sz[i] * sp[i] / spacing[i]))) for i in range(3)]
    return sitk.Resample(img, nsz, sitk.Transform(), sitk.sitkNearestNeighbor if is_label else sitk.sitkLinear,
                         img.GetOrigin(), spacing, img.GetDirection(), 0 if is_label else -1024, img.GetPixelID())


def arr(img):  # SimpleITK (x,y,z) → numpy (z,y,x)
    return sitk.GetArrayFromImage(img)


def bbox(mask, margin):
    idx = np.argwhere(mask)
    if len(idx) == 0:
        return tuple(slice(0, s) for s in mask.shape)
    lo = np.maximum(idx.min(0) - margin, 0); hi = np.minimum(idx.max(0) + margin + 1, mask.shape)
    return tuple(slice(int(a), int(b)) for a, b in zip(lo, hi))


def save_case(out_dir, cid, ct, label, lung, spacing, meta):
    out_dir.mkdir(parents=True, exist_ok=True)
    sl = bbox(lung > 0, 10) if lung is not None and lung.any() else tuple(slice(0, s) for s in ct.shape)
    d = {"ct": np.clip(ct[sl], -1024, 3071).astype(np.int16)}
    if label is not None:
        d["label"] = label[sl].astype(np.uint8)
    if lung is not None:
        d["lung"] = (lung[sl] > 0).astype(np.uint8)
    np.savez(out_dir / f"{cid}.npz", **d)
    return {**meta, "id": cid, "file": f"{cid}.npz", "shape": list(d["ct"].shape),
            "spacing_zyx": list(spacing[::-1]), "crop": [[s.start, s.stop] for s in sl],
            "has_label": label is not None and bool((label > 0).any())}


def prepare_local(root, out, task):
    root = Path(root)
    ds = json.load(open(root / "dataset.json", encoding="utf-8"))
    cases = []
    for split, items in ds["splits"].items():
        for it in items:
            if not it.get("image_1mm"):
                continue
            ct_img = to_ras_1mm(read(root / it["image_1mm"]))
            ct = arr(ct_img)
            lung = arr(to_ras_1mm(read(root / it["lung"]), True)) if it.get("lung") else None
            if task == "lung":
                label = (lung > 0).astype(np.uint8) if lung is not None else None
            else:
                if not it.get("lesion"):
                    label = np.zeros_like(ct, np.uint8)       # o'smasiz hajm (manfiy misol)
                else:
                    lab = arr(to_ras_1mm(read(root / it["lesion"]), True))
                    # 1 = o'sma; 2 = limfa tuguni → bu vazifada fon emas, e'tiborsiz (255); 3 = noaniq → 255
                    label = np.where(lab == 1, 1, np.where(lab >= 2, 255, 0)).astype(np.uint8)
            cid = f"{it['patient']}_{it['study']}"
            cases.append(save_case(Path(out), cid, ct, label, lung, ct_img.GetSpacing(),
                                   {"patient": it["patient"], "split": split, "source": "local"}))
            print("ok", cid, cases[-1]["shape"])
    return cases


def prepare_pairs(rows, out, source):
    cases = []
    for r in rows:
        ct_img = to_ras_1mm(read(r["image"]))
        ct = arr(ct_img)
        label = arr(to_ras_1mm(read(r["label"]), True)) if r.get("label") else None
        lung = arr(to_ras_1mm(read(r["lung"]), True)) if r.get("lung") else None
        if label is not None and lung is not None and label.shape != lung.shape:
            lung = None
        cases.append(save_case(Path(out), r["case_id"], ct, label, lung, ct_img.GetSpacing(),
                               {"patient": r.get("patient", r["case_id"]), "split": r.get("split", "train"), "source": source}))
        print("ok", r["case_id"], cases[-1]["shape"])
    return cases


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["local", "msd", "pairs"], required=True)
    ap.add_argument("--root", required=True, help="DATASET papkasi / Task06_Lung papkasi / CSV fayl")
    ap.add_argument("--out", required=True)
    ap.add_argument("--task", choices=["lung", "tumor"], default="tumor")
    ap.add_argument("--val_frac", type=float, default=0.2)
    a = ap.parse_args()
    if a.source == "local":
        cases = prepare_local(a.root, a.out, a.task)
    elif a.source == "msd":
        root = Path(a.root)
        imgs = sorted((root / "imagesTr").glob("*.nii.gz"))
        imgs = [p for p in imgs if not p.name.startswith("._")]
        rng = np.random.default_rng(42)
        perm = rng.permutation(len(imgs))
        nval = int(len(imgs) * a.val_frac)
        rows = []
        for k, i in enumerate(perm):
            p = imgs[i]
            rows.append({"case_id": p.name.replace(".nii.gz", "").replace("_0000", ""), "image": str(p),
                         "label": str(root / "labelsTr" / p.name.replace("_0000", "")),
                         "split": "val" if k < nval else "train"})
        cases = prepare_pairs(rows, a.out, "msd")
    else:
        rows = list(csv.DictReader(open(a.root, encoding="utf-8")))
        cases = prepare_pairs(rows, a.out, "pairs")
    json.dump({"task": a.task, "source": a.source, "cases": cases}, open(Path(a.out) / "index.json", "w"), indent=1)
    print(f"done cases={len(cases)} out={a.out}")


if __name__ == "__main__":
    main()
