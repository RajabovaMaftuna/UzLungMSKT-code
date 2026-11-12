"""Intellektual yordamchi: o'choqlar va bemor darajasida xavfli o‘simta ehtimoli (%) hamda AI dastlabki xulosasi.

Ikki manba:
1) Lung-RADS v2022 (ACR) — tugun turi va o'lchami bo'yicha toifa va rasmiy taxminiy xavflilik oralig'i:
     2: < 1 %,  3: 1–2 %,  4A: 5–15 %,  4B/4X: > 15 %  (ACR Lung-RADS v2022 jadvali).
   Bu modeldan mustaqil, har doim mavjud bo'lgan, adabiyotga asoslangan baho.
2) O'qitilgan tasniflagich (4.1-§, LIDC-IDRI) — agar workspace/runs/cls*/ da model va calibration.json
   (harorat bo'yicha kalibrlash) bo'lsa, har bir o'choq uchun P(xavfli) foizda.

Bemor darajasidagi ehtimollik — o'choqlar ehtimolligining eng kattasi (eng shubhali o'choq bo'yicha qaror).
Bu tashxis emas: yakuniy qaror radiolog tomonidan kiritiladi.
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

import numpy as np

RADS_RISK = {"2": (0.0, 1.0), "3": (1.0, 2.0), "4A": (5.0, 15.0), "4B": (15.0, 100.0), "4X": (15.0, 100.0)}


def nodule_type(mean_hu):
    if mean_hu is None or not np.isfinite(mean_hu):
        return "unknown"
    if mean_hu < -500:
        return "ground_glass"
    if mean_hu < -150:
        return "part_solid"
    return "solid"


def lung_rads(lesion):
    """Boshlang'ich skrining toifasi (soddalashtirilgan; o'lcham = ekvivalent diametr, mm)."""
    d = lesion.get("eq_diameter_mm", 0.0)
    t = nodule_type(lesion.get("mean_hu"))
    if t == "ground_glass":
        cat = "2" if d < 30 else "3"
    elif t == "part_solid":
        cat = "2" if d < 6 else ("3" if d < 8 else ("4A" if d < 15 else "4B"))
    else:
        cat = "2" if d < 6 else ("3" if d < 8 else ("4A" if d < 15 else "4B"))
    return cat, t


def x_candidate(lesion, cat):
    """4X ni faqat radiolog belgilaydi (ACR: qo'shimcha shubhali belgilar). Past sferiklik — faqat ESLATMA, toifa o'zgarmaydi."""
    return cat in ("3", "4A", "4B") and lesion.get("sphericity", 1.0) < 0.55 and lesion.get("eq_diameter_mm", 0.0) >= 8


MASS_MM = 30.0
HIGH_PROB, SUSP_PROB = 50.0, 15.0     # ai_conclusion chegaralari: validatsiya to'plamida tanlanmagan, ehtiyotkor taxminiy qiymatlar

def _load_classifier():
    import torch
    from .models import NoduleClassifier
    runs = Path(__file__).resolve().parents[1] / "workspace" / "runs"
    # yakuniy konfiguratsiya (4.1-§, K3: SimCLR + adaptiv fokal) ustuvor; bo'lmasa eski joylashuv
    cks = sorted(glob.glob(str(runs / "cls" / "cls_K3" / "cls_fold*.pt"))) or \
        sorted(glob.glob(str(runs / "cls*" / "cls_fold*.pt")))
    if not cks:
        return None
    models = []
    for c in cks:
        m = NoduleClassifier(); m.load_state_dict(torch.load(c, map_location="cpu")["model"]); m.eval(); models.append(m)
    calib = Path(cks[0]).parent / "calibration.json"
    T = json.load(open(calib))["temperature"] if calib.exists() else None
    return models, T, str(Path(cks[0]).parent.name)


def _get_classifier(calibrated):
    """(clf | None, holat, izoh). Holat: ok | skipped (tasvir kalibrlanmagan) | unavailable (vazn fayli yo'q) | error."""
    if not calibrated:
        return None, "skipped", None
    try:
        clf = _load_classifier()
    except Exception as e:                      # jimgina yutilmaydi: holat hisobotga yoziladi
        return None, "error", type(e).__name__
    if clf is None:
        return None, "unavailable", "no_checkpoint"
    return clf, "ok", clf[2]


def _model_probs(clf, lesions, ct_hu):
    import torch
    from .data.dataset import norm_hu
    models, T, _ = clf
    probs = []
    for l in lesions:
        x = torch.from_numpy(norm_hu(_patch(ct_hu, l["centroid_zyx_vox"])))[None, None]
        with torch.no_grad():
            logits = torch.stack([m(x)[0] for m in models]).mean(0)
            if T:
                logits = logits / T
            probs.append(round(100 * float(torch.softmax(logits, 0)[1]), 1))
    return probs


def _patch(ct, c, s=48):
    lo = np.round(np.asarray(c) - s / 2).astype(int)
    pad = [(max(0, -l), max(0, l + s - d)) for l, d in zip(lo, ct.shape)]
    v = np.pad(ct, pad, constant_values=-1024); lo = lo + np.array([p[0] for p in pad])
    return v[lo[0]:lo[0] + s, lo[1]:lo[1] + s, lo[2]:lo[2] + s]


def assess(lesions, ct_hu, calibrated=True):
    """lesions — infer.analyze_image natijasidagi ro'yxat. ct_hu — 1 mm hajm (z,y,x).
    Qaytaradi: (o'choqlar bahosi, bemor darajasidagi xulosa). Bemor xulosasida:
      reliability  — TASVIR ishonchliligi (normal | low: kalibrlanmagan rasm/PDF/video);
      model_status — tasniflagich holati (ok | skipped | unavailable | error); ok bo'lmasa foizlar faqat Lung-RADS jadvalidan."""
    clf, mstatus, mnote = _get_classifier(calibrated)
    probs = None
    if clf is not None:
        try:
            probs = _model_probs(clf, lesions, ct_hu)
        except Exception as e:
            probs, mstatus, mnote, clf = None, "error", type(e).__name__, None
    out = []
    for k, l in enumerate(lesions):
        cat, typ = lung_rads(l)
        lo, hi = RADS_RISK[cat]
        d = l.get("eq_diameter_mm", 0.0)
        notes = []
        if d >= MASS_MM:
            notes.append("mass_ge_30mm")           # Lung-RADS skrining tugunlari uchun; massada faqat yo'naltiruvchi
        if typ == "part_solid":
            notes.append("part_solid_total_diameter")   # ACR qattiq komponent o'lchamiga qaraydi; bu yerda umumiy diametr
        if typ in ("ground_glass", "part_solid"):
            notes.append("type_by_mean_hu")
        item = {"id": l["id"], "lung_rads": cat, "nodule_type": typ, "rads_risk_pct": [lo, hi],
                "rads_applicable": d < MASS_MM, "rads_notes": notes, "rads_x_candidate": x_candidate(l, cat)}
        if probs is not None:
            item["model_prob_pct"] = probs[k]; item["model_calibrated"] = bool(clf[1]); item["model_name"] = clf[2]
        out.append(item)
    if out:
        key = lambda it: it.get("model_prob_pct", it["rads_risk_pct"][1])     # bir chaqiruvda hammasi yoki modelli, yoki jadvalli
        worst = max(out, key=key)
        pat = {"worst_lesion": worst["id"], "lung_rads": worst["lung_rads"], "rads_risk_pct": worst["rads_risk_pct"],
               "rads_notes": worst["rads_notes"], "rads_x_candidate": worst["rads_x_candidate"]}
        if "model_prob_pct" in worst:
            pat["model_prob_pct"] = worst["model_prob_pct"]
        prob = worst.get("model_prob_pct", worst["rads_risk_pct"][1])
    else:
        pat = {"worst_lesion": None, "lung_rads": "1", "rads_risk_pct": [0.0, 1.0], "rads_notes": [], "rads_x_candidate": False}
        prob = 0.0
    # AI dastlabki xulosasi (kodlar — interfeysda uch tilga tarjima qilinadi)
    if not out:
        concl = "no_lesion"
    elif pat["lung_rads"] in ("4B", "4X") or prob >= HIGH_PROB:
        concl = "high_suspicion"
    elif pat["lung_rads"] == "4A" or prob >= SUSP_PROB:
        concl = "suspicious"
    else:
        concl = "probably_benign"
    pat["ai_conclusion"] = concl
    pat["reliability"] = "normal" if calibrated else "low"
    pat["model_status"], pat["model_note"] = mstatus, mnote
    return out, pat
