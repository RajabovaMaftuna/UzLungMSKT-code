"""Sirpanuvchi oyna bilan 3D xulosa chiqarish va bitta MSKT hajmini tahlil qilish.

CLI:  python -m uzlungct.infer --ckpt runs/tumor_r2u3d/best.pt --image ct.nii.gz --out natija/
Chiqish: <out>/mask.nii.gz (asl geometriyada), <out>/prob.nii.gz, <out>/report.json (o'choqlar ro'yxati,
hajm, diametr, sferiklik va h.k.).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from . import hw
from .data.dataset import norm_hu
from .models import build_seg_model
from .sio import read_image, write_image


def _gauss(patch, sigma=0.125):
    g = [np.exp(-0.5 * ((np.arange(p) - (p - 1) / 2) / (sigma * p)) ** 2) for p in patch]
    w = g[0][:, None, None] * g[1][None, :, None] * g[2][None, None, :]
    return torch.from_numpy((w / w.max()).astype(np.float32)).clamp_min(1e-3)


@torch.no_grad()
def sliding_window(model, x, patch, n_classes, overlap=0.5, sw_batch=2, amp=True):
    """x: (1,1,D,H,W) CPU tensor. Qaytaradi: (C,D,H,W) ehtimollar (CPU, float32).
    Natija CPU da yig'iladi — 8 GB videokartada katta hajmlar uchun xotira tejaladi."""
    dev = next(model.parameters()).device
    _, _, D, H, W = x.shape
    pd = [max(0, p - s) for p, s in zip(patch, (D, H, W))]
    if any(pd):
        x = F.pad(x, (0, pd[2], 0, pd[1], 0, pd[0]))
    _, _, D2, H2, W2 = x.shape
    steps = [max(1, int(p * (1 - overlap))) for p in patch]
    starts = [sorted(set(list(range(0, max(s - p, 0) + 1, st)) + [max(s - p, 0)])) for s, p, st in zip((D2, H2, W2), patch, steps)]
    out = torch.zeros((n_classes, D2, H2, W2)); cnt = torch.zeros((D2, H2, W2))
    w = _gauss(patch)
    coords = [(a, b, c) for a in starts[0] for b in starts[1] for c in starts[2]]
    dt = hw.amp_dtype() if (amp and dev.type == "cuda") else None
    for i in range(0, len(coords), sw_batch):
        cb = coords[i:i + sw_batch]
        xb = torch.cat([x[:, :, a:a + patch[0], b:b + patch[1], c:c + patch[2]] for a, b, c in cb]).to(dev)
        with torch.autocast(dev.type, dtype=dt, enabled=dt is not None):
            pr = torch.softmax(model(xb).float(), 1).cpu()
        for k, (a, b, c) in enumerate(cb):
            out[:, a:a + patch[0], b:b + patch[1], c:c + patch[2]] += pr[k] * w
            cnt[a:a + patch[0], b:b + patch[1], c:c + patch[2]] += w
    out = out / cnt.clamp_min(1e-6)
    return out[:, :D, :H, :W]


def load_model(ckpt, dev=None):
    dev = dev or hw.device()
    ck = torch.load(ckpt, map_location="cpu", weights_only=False)
    cfg = ck["cfg"]
    m = build_seg_model(cfg["model"], 1, cfg["n_classes"], patch=cfg["patch"], **cfg.get("model_kw", {}))
    m.load_state_dict(ck["model"]); m.to(dev).eval()
    return m, cfg


MAX_LESIONS = 30


def lung_envelope(ct, margin_mm=10):
    """Tez o'pka qobig'i (1 mm hajm uchun): tana ichidagi havo zichligidagi (−950…−400 HU) eng katta
    ikki komponent, kesimlar bo'yicha teshiklari to'ldirilgan va margin_mm ga kengaytirilgan.
    Maqsad — o'pkadan tashqaridagi (yurak, ko'krak devori) yolg'on o'choqlarni chiqarib tashlash."""
    from scipy import ndimage as nd
    body = nd.binary_fill_holes(nd.binary_opening(ct > -500, iterations=2), structure=np.ones((1, 3, 3)))
    air = (ct < -400) & (ct > -1024) & body
    air = nd.binary_opening(air, iterations=1)
    lab, n = nd.label(air)
    if n == 0:
        return np.ones(ct.shape, bool)
    sizes = np.bincount(lab.ravel()); sizes[0] = 0
    keep = [i for i in np.argsort(-sizes)[:2] if sizes[i] > 50000]      # > 50 ml
    if not keep:
        return np.ones(ct.shape, bool)
    lung = np.isin(lab, keep)
    lung = np.stack([nd.binary_fill_holes(z) for z in lung])          # kesim bo'yicha (o'sma, tomirlar)
    # o'pkalar orasidagi chuqur joylashgan (markaziy) o'smalar uchun qavariq qobiqqa yaqin kengaytirish
    return nd.binary_dilation(lung, iterations=int(margin_mm))


def select_components(lab, n, env, max_lesions=MAX_LESIONS, min_voxels=30):
    """Komponentlarni tanlash: o'pka qobig'idan tashqaridagilar (>50 % tashqarida) va shovqin (<min_voxels) olib tashlanadi,
    eng kattalaridan max_lesions tasi qoldiriladi. Qaytaradi: (niqob uint8, saqlangan id lar, hisob, filtrlangan lab).
    Hisob hisobotga yoziladi — filtr bilan olib tashlangan o'choqlar foydalanuvchidan yashirilmaydi."""
    lab = lab.copy()
    n_drop = 0
    if env is not None and n:
        inside = np.bincount(lab.ravel(), weights=env.ravel().astype(np.float32), minlength=n + 1)
        total = np.bincount(lab.ravel(), minlength=n + 1).astype(np.float32)
        drop = np.where((inside / np.maximum(total, 1) < 0.5) & (total > 0))[0]
        drop = drop[drop > 0]
        n_drop = int(len(drop))
        if n_drop:
            lab[np.isin(lab, drop)] = 0
    sizes = np.bincount(lab.ravel(), minlength=n + 1)
    sizes[0] = 0
    big = [i for i in np.argsort(-sizes) if sizes[i] >= min_voxels]
    keep = big[:max_lesions]
    keep_set = np.zeros(len(sizes), bool)
    keep_set[keep] = True
    present = int((sizes > 0).sum())
    stats = {"raw": int(n), "outside_lung": n_drop, "too_small": present - len(big), "over_limit": max(0, len(big) - max_lesions)}
    return keep_set[lab].astype(np.uint8), keep, stats, lab


def analyze_image(model, cfg, image_path, out_dir, lung_crop=True, ts_fn=None, external=None):
    import SimpleITK as sitk
    from scipy import ndimage as nd
    from .data.prepare import to_ras_1mm
    from .metrics import morphology
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    img0 = image_path if isinstance(image_path, sitk.Image) else read_image(image_path)
    img = to_ras_1mm(img0)
    ct = sitk.GetArrayFromImage(img).astype(np.int16)
    # tana chegarasida kesish (tashqi havo hisoblanmaydi) — tezlik uchun
    body = ct > -500
    zz, yy, xx = [np.where(body.any(axis=a))[0] for a in ((1, 2), (0, 2), (0, 1))]
    if len(zz) and len(yy) and len(xx):
        bb = (slice(max(zz[0] - 4, 0), zz[-1] + 5), slice(max(yy[0] - 4, 0), yy[-1] + 5), slice(max(xx[0] - 4, 0), xx[-1] + 5))
    else:
        bb = tuple(slice(0, n) for n in ct.shape)
    if external is not None:                # N8: muzlatilgan birlashma, o'lcham filtrlarisiz (sertifikatlangan quvur bilan bir xil)
        ext_mask, ext_info = external(img0, img)
        p1 = ext_info.pop("_prob"); src = ext_info.pop("_src"); m2p = ext_info.pop("_m2p"); dsc = ext_info.pop("_dsc"); mask = ext_mask.astype(np.uint8)
        lab, n = nd.label(mask)
        mask, keep, filt, lab = select_components(lab, n, None, max_lesions=10 ** 6, min_voxels=1)
        return _finish(cfg, image_path, img0, img, ct, mask, keep, filt, lab, p1, mask > 0, None, ext_info, out_dir, src, m2p, dsc)
    x = torch.from_numpy(norm_hu(ct[bb]))[None, None]
    prob_c = sliding_window(model, x, cfg["patch"], cfg["n_classes"], overlap=0.5)[1].numpy()
    p1 = np.zeros(ct.shape, np.float32); p1[bb] = prob_c
    mask = (p1 >= 0.5).astype(np.uint8)
    lab, n = nd.label(mask)
    env = lung_envelope(ct) if (lung_crop and n) else None
    mask, keep, filt, lab = select_components(lab, n, env)          # o'pka qobig'i filtri FAQAT o'z modeli niqobiga
    own = mask > 0
    ts_mask, ts_info = (ts_fn(img, ct) if ts_fn else (None, {"status": "off"}))
    if ts_mask is not None:
        # gibrid: o'z modeli (filtrlangan) YOKI TotalSegmentator. TS niqobi qobiq filtridan o'tkazilmaydi: filtr yirik markaziy
        # o'smalarni ham o'chirib yuborardi (8 bemorda: LC021 Dice 0.57 -> 0.00). Faqat shovqin (<30 voksel) va 30 o'choq chegarasi qo'llanadi.
        lab, n = nd.label(own | ts_mask)
        mask, keep, f2, lab = select_components(lab, n, None)
        filt["too_small"] += f2["too_small"]; filt["over_limit"] = f2["over_limit"]
    return _finish(cfg, image_path, img0, img, ct, mask, keep, filt, lab, p1, own, ts_mask, ts_info, out_dir)


def _body_only(img, ct):
    """Tana tashqarisidagi havo shovqinini -1024 ga tenglaydi (gzip yaxshi siqadi). Tana ichidagi HU o'zgarmaydi."""
    import SimpleITK as sitk
    from scipy import ndimage as nd
    try:
        b = nd.binary_opening(ct > -500, iterations=2)
        l, n = nd.label(b)
        if not n:
            return img
        b = l == (np.argmax(np.bincount(l.ravel())[1:]) + 1)
        b = nd.binary_dilation(np.stack([nd.binary_fill_holes(x) for x in b]), iterations=5)
        o = sitk.GetImageFromArray(np.where(b, ct, -1024).astype(np.int16)); o.CopyInformation(img)
        return o
    except Exception:                       # har qanday xatoda asl tasvir saqlanadi
        return img


def _finish(cfg, image_path, img0, img, ct, mask, keep, filt, lab, p1, own, ts_mask, ts_info, out_dir, src=None, m2p=None, dsc=None):
    import SimpleITK as sitk
    from scipy import ndimage as nd
    from .metrics import morphology
    objs = nd.find_objects(lab)
    lesions = []
    for i in keep:
        sl = objs[i - 1]
        comp = lab[sl] == i
        mo = morphology(comp, (1, 1, 1), ct[sl])
        cz, cy, cx = np.argwhere(comp).mean(0) + np.array([s_.start for s_ in sl])
        les = {"id": 0, "score": float(p1[sl][comp].max()), "centroid_zyx_vox": [float(cz), float(cy), float(cx)], **mo}
        if ts_mask is not None:
            from .tsfusion import source_of
            les["source"] = source_of(own, ts_mask, sl, comp)
        if src is not None:                 # N8: qaysi modellar topgan; faqat detektor -> o'lcham taxminiy
            bits = int(np.bitwise_or.reduce(src[sl][comp]))
            les["source"] = [n for b, n in ((1, "M2"), (2, "K1"), (4, "TS"), (8, "detektor")) if bits & b]
            les["approx"] = les["source"] == ["detektor"]
            les["m2_prob"] = float(m2p[sl][comp].max())
            les["det_score"] = float(dsc[sl][comp].max())
            les["tier"] = "asosiy" if (len(les["source"]) >= 2 or les["m2_prob"] >= 0.5 or les["det_score"] >= 0.99) else "qoshimcha"
        lesions.append(les)
    lesions.sort(key=lambda d: -d["volume_ml"])
    for k, l in enumerate(lesions, 1):
        l["id"] = k
    m_img = sitk.GetImageFromArray(mask); m_img.CopyInformation(img)
    m_orig = sitk.Resample(m_img, img0, sitk.Transform(), sitk.sitkNearestNeighbor, 0)
    write_image(m_orig, out_dir / "mask.nii.gz")
    p_img = sitk.GetImageFromArray((p1 * 255).astype(np.uint8)); p_img.CopyInformation(img)
    write_image(p_img, out_dir / "prob_1mm.nii.gz")
    write_image(_body_only(img, ct), out_dir / "ct_1mm.nii.gz")
    rep = {"image": "uploaded" if isinstance(image_path, sitk.Image) else str(image_path), "model": "SenGuard-3D" if (ts_info or {}).get("model") == "N8" else cfg["model"], "task": cfg.get("task"), "n_lesions": len(lesions), "filters": filt, "ts": ts_info, "lesions": lesions}
    json.dump(rep, open(out_dir / "report.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return rep, ct, mask, p1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True); ap.add_argument("--image", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    m, cfg = load_model(a.ckpt)
    rep, *_ = analyze_image(m, cfg, a.image, a.out)
    print(json.dumps({k: v for k, v in rep.items() if k != "lesions"}, ensure_ascii=False))
    for l in rep["lesions"][:10]:
        print(f"  #{l['id']}: {l['volume_ml']:.2f} ml, d={l['eq_diameter_mm']:.1f} mm, S={l['sphericity']:.2f}, p={l['score']:.2f}")


if __name__ == "__main__":
    main()
