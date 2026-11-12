"""Matematik-statistik baholash ko'rsatkichlari (4.4-§). Faqat numpy/scipy/sklearn.

Segmentatsiya: Dice, HD95, ASSD (mm, voksel o'lchami hisobga olinadi).
Aniqlash: o'choq darajasida sezgirlik, FP/tekshiruv, FROC va CPM (LUNA16).
Tasniflash: AUC, sezgirlik, o'ziga xoslik, bootstrap 95% IO, DeLong testi.
Kelishuv: Cohen κ.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage as nd
from scipy import stats


# ------------------------------------------------------------------ segmentatsiya

def dice(pred, gt, ignore=None):
    pred, gt = pred.astype(bool), gt.astype(bool)
    if ignore is not None:
        keep = ~ignore.astype(bool)
        pred, gt = pred & keep, gt & keep
    s = pred.sum() + gt.sum()
    return 1.0 if s == 0 else 2.0 * (pred & gt).sum() / s


def _surface(mask):
    return mask & ~nd.binary_erosion(mask, structure=nd.generate_binary_structure(3, 1))


def surface_distances(pred, gt, spacing=(1.0, 1.0, 1.0)):
    """pred sirtidan gt gacha va gt sirtidan pred gacha bo'lgan masofalar (mm)."""
    pred, gt = pred.astype(bool), gt.astype(bool)
    if not pred.any() or not gt.any():
        return None, None
    sp, sg = _surface(pred), _surface(gt)
    dt_g = nd.distance_transform_edt(~sg, sampling=spacing)
    dt_p = nd.distance_transform_edt(~sp, sampling=spacing)
    return dt_g[sp], dt_p[sg]


def hd95(pred, gt, spacing=(1.0, 1.0, 1.0)):
    a, b = surface_distances(pred, gt, spacing)
    if a is None:
        return float("nan")
    return float(max(np.percentile(a, 95), np.percentile(b, 95)))


def assd(pred, gt, spacing=(1.0, 1.0, 1.0)):
    a, b = surface_distances(pred, gt, spacing)
    if a is None:
        return float("nan")
    return float((a.sum() + b.sum()) / (len(a) + len(b)))


def seg_report(pred, gt, spacing=(1.0, 1.0, 1.0), ignore=None):
    if ignore is not None:
        keep = ~ignore.astype(bool)
        pred, gt = pred.astype(bool) & keep, gt.astype(bool) & keep
    vox = float(np.prod(spacing)) / 1000.0
    return {
        "dice": dice(pred, gt),
        "hd95_mm": hd95(pred, gt, spacing),
        "assd_mm": assd(pred, gt, spacing),
        "vol_pred_ml": float(pred.sum() * vox),
        "vol_gt_ml": float(gt.sum() * vox),
    }


# ------------------------------------------------------------------ morfologiya (3.2-§ formulalari)

def morphology(mask, spacing=(1.0, 1.0, 1.0), hu=None):
    """Hajm (ml), ekvivalent diametr, sferiklik S=π^{1/3}(6V)^{2/3}/A, cho'ziqlik, yassilik, massa."""
    from skimage import measure
    m = mask.astype(bool)
    if not m.any():
        return {}
    vox = float(np.prod(spacing))
    V = m.sum() * vox
    verts, faces, _, _ = measure.marching_cubes(np.pad(m, 1).astype(np.uint8), 0.5, spacing=tuple(spacing))
    A = measure.mesh_surface_area(verts, faces)
    pts = np.argwhere(m) * np.asarray(spacing)
    ev = np.sort(np.linalg.eigvalsh(np.cov(pts.T)))[::-1] if len(pts) > 3 else np.ones(3)
    ev = np.clip(ev, 1e-9, None)
    out = {
        "volume_ml": V / 1000.0,
        "eq_diameter_mm": (6 * V / np.pi) ** (1 / 3),
        "major_axis_mm": 4 * np.sqrt(ev[0]),
        "sphericity": float(np.pi ** (1 / 3) * (6 * V) ** (2 / 3) / A) if A > 0 else float("nan"),
        "elongation": float(np.sqrt(ev[1] / ev[0])),
        "flatness": float(np.sqrt(ev[2] / ev[0])),
    }
    if hu is not None:
        A_mean = float(hu[m].mean())
        out["mean_hu"] = A_mean
        out["mass_mg"] = out["volume_ml"] * (A_mean + 1000.0)  # M = V·(A+1000)/1000 g → mg
    return out


def vdt_days(v1_ml, v2_ml, dt_days):
    """Hajmning ikki barobar ortish vaqti: VDT = ln2·Δt / ln(V2/V1)."""
    if v1_ml <= 0 or v2_ml <= 0 or v2_ml == v1_ml:
        return float("inf")
    return float(np.log(2) * dt_days / np.log(v2_ml / v1_ml))


# ------------------------------------------------------------------ aniqlash (o'choq darajasi)

def lesion_detection(pred_prob, gt, thr=0.5, ignore=None, min_vox=10, hit="overlap"):
    """Bashorat komponentlari va gt o'choqlarini moslashtiradi.
    Qaytaradi: (tp_scores, fp_scores, n_gt, n_hit)."""
    gl, ng = nd.label(gt.astype(bool))
    pb = pred_prob >= thr
    if ignore is not None:
        pb &= ~ignore.astype(bool)
    pl, npred = nd.label(pb)
    tp, fp, hit_ids = [], [], set()
    for i in range(1, npred + 1):
        comp = pl == i
        if comp.sum() < min_vox:
            continue
        score = float(pred_prob[comp].max())
        ids = set(np.unique(gl[comp])) - {0}
        if ids:
            tp.append(score); hit_ids |= ids
        else:
            fp.append(score)
    return tp, fp, ng, len(hit_ids)


def froc(cases, fp_rates=(0.125, 0.25, 0.5, 1, 2, 4, 8)):
    """cases: [(tp_scores, fp_scores, n_gt), ...]. LUNA16 CPM — 7 nuqtadagi sezgirlik o'rtachasi."""
    all_tp = np.concatenate([np.asarray(c[0], float) for c in cases]) if cases else np.array([])
    all_fp = np.concatenate([np.asarray(c[1], float) for c in cases]) if cases else np.array([])
    n_gt = sum(c[2] for c in cases)
    n_scan = len(cases)
    thr = np.unique(np.concatenate([all_tp, all_fp, [np.inf]]))[::-1]
    sens, fps = [], []
    for t in thr:
        sens.append((all_tp >= t).sum() / max(n_gt, 1))
        fps.append((all_fp >= t).sum() / max(n_scan, 1))
    sens, fps = np.array(sens), np.array(fps)
    at = [float(sens[fps <= r].max()) if (fps <= r).any() else 0.0 for r in fp_rates]
    return {"fp_per_scan": fps.tolist(), "sensitivity": sens.tolist(),
            "sens_at": dict(zip([str(r) for r in fp_rates], at)), "cpm": float(np.mean(at))}


# ------------------------------------------------------------------ tasniflash

def binary_report(y_true, y_score, thr=0.5):
    from sklearn.metrics import roc_auc_score, confusion_matrix
    y_true = np.asarray(y_true).astype(int); y_score = np.asarray(y_score, float)
    y_pred = (y_score >= thr).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    return {
        "auc": float(roc_auc_score(y_true, y_score)) if len(set(y_true)) == 2 else float("nan"),
        "sensitivity": tp / max(tp + fn, 1), "specificity": tn / max(tn + fp, 1),
        "accuracy": (tp + tn) / max(len(y_true), 1), "ppv": tp / max(tp + fp, 1), "npv": tn / max(tn + fn, 1),
        "n": int(len(y_true)), "n_pos": int(y_true.sum()),
    }


def bootstrap_ci(fn, *arrays, n_boot=2000, alpha=0.05, seed=42, stratify=None):
    """Istalgan ko'rsatkich uchun persentil bootstrap 95% IO. fn(*resampled_arrays) -> float."""
    rng = np.random.default_rng(seed)
    arrays = [np.asarray(a) for a in arrays]
    n = len(arrays[0])
    base = float(fn(*arrays))
    vals = []
    for _ in range(n_boot):
        if stratify is not None:
            s = np.asarray(stratify)
            idx = np.concatenate([rng.choice(np.where(s == c)[0], (s == c).sum()) for c in np.unique(s)])
        else:
            idx = rng.integers(0, n, n)
        try:
            v = fn(*[a[idx] for a in arrays])
            if np.isfinite(v):
                vals.append(v)
        except ValueError:
            continue
    lo, hi = np.percentile(vals, [100 * alpha / 2, 100 * (1 - alpha / 2)]) if vals else (np.nan, np.nan)
    return base, float(lo), float(hi)


def cluster_bootstrap_ci(fn, y, s, groups, n_boot=2000, alpha=0.05, seed=42):
    """Klaster (bemor) darajasidagi bootstrap: bemorlar qaytarib tanlanadi, ularning barcha tugunlari
    birga olinadi. Bir bemorning tugunlari bog'liq bo'lgani uchun tugun-bootstrap oralig'i tor chiqadi."""
    y, s, groups = np.asarray(y), np.asarray(s), np.asarray(groups)
    uniq = np.unique(groups)
    members = [np.where(groups == g)[0] for g in uniq]
    rng = np.random.default_rng(seed)
    base = float(fn(y, s)); vals = []
    for _ in range(n_boot):
        idx = np.concatenate([members[i] for i in rng.integers(0, len(uniq), len(uniq))])
        try:
            v = fn(y[idx], s[idx])
            if np.isfinite(v):
                vals.append(v)
        except ValueError:
            continue
    lo, hi = np.percentile(vals, [100 * alpha / 2, 100 * (1 - alpha / 2)]) if vals else (np.nan, np.nan)
    return base, float(lo), float(hi)


def ece(y_true, prob, n_bins=15):
    """Kutilgan kalibrlash xatosi (Guo 2017): teng kenglikdagi n_bins qutida |aniqlik − ishonch| ning vaznli o'rtachasi.
    Ikkilik holat: prob — ijobiy sinf ehtimoli; ishonch = max(p, 1−p)."""
    y = np.asarray(y_true).astype(int); p = np.asarray(prob, float)
    conf = np.maximum(p, 1 - p); pred = (p >= 0.5).astype(int)
    edges = np.linspace(0, 1, n_bins + 1); e = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf > lo) & (conf <= hi) if lo > 0 else (conf >= lo) & (conf <= hi)
        if m.any():
            e += m.mean() * abs((pred[m] == y[m]).mean() - conf[m].mean())
    return float(e)


def reliability_bins(y_true, prob, n_bins=15):
    """Reliability diagramma uchun: har qutida (o'rtacha bashorat, haqiqiy ijobiy ulush, soni)."""
    y = np.asarray(y_true).astype(int); p = np.asarray(prob, float)
    b = np.clip((p * n_bins).astype(int), 0, n_bins - 1)
    return [(float(p[b == k].mean()), float(y[b == k].mean()), int((b == k).sum())) for k in range(n_bins) if (b == k).any()]


def _midrank(x):
    J = np.argsort(x); Z = x[J]; N = len(x); T = np.zeros(N); i = 0
    while i < N:
        j = i
        while j < N and Z[j] == Z[i]:
            j += 1
        T[i:j] = 0.5 * (i + j - 1) + 1
        i = j
    out = np.empty(N); out[J] = T
    return out


def delong_test(y_true, score_a, score_b):
    """Ikki bog'liq ROC egri chizig'i AUC larini solishtirish (DeLong 1988, tez algoritm Sun & Xu 2014).
    Qaytaradi: auc_a, auc_b, z, p."""
    y = np.asarray(y_true).astype(int)
    order = np.argsort(-y, kind="mergesort")
    preds = np.vstack([np.asarray(score_a, float), np.asarray(score_b, float)])[:, order]
    m = int(y.sum()); n = len(y) - m
    pos, neg = preds[:, :m], preds[:, m:]
    k = preds.shape[0]
    tx = np.array([_midrank(pos[r]) for r in range(k)])
    ty = np.array([_midrank(neg[r]) for r in range(k)])
    tz = np.array([_midrank(preds[r]) for r in range(k)])
    aucs = tz[:, :m].sum(1) / m / n - (m + 1.0) / 2.0 / n
    v01 = (tz[:, :m] - tx) / n
    v10 = 1.0 - (tz[:, m:] - ty) / m
    S = np.cov(v01) / m + np.cov(v10) / n
    l = np.array([1, -1])
    var = float(l @ S @ l)
    z = float((aucs[0] - aucs[1]) / np.sqrt(var)) if var > 0 else 0.0
    p = float(2 * stats.norm.sf(abs(z)))
    return float(aucs[0]), float(aucs[1]), z, p


def cohen_kappa(a, b):
    from sklearn.metrics import cohen_kappa_score
    return float(cohen_kappa_score(a, b))
