"""4.4-§: sinov to'plamida segmentatsiya modellarini baholash.

python -m uzlungct.evaluate --ckpt runs/a/best.pt runs/b/best.pt --cache cache/local_tumor --split test --out results/test
Chiqish: per_case.csv (har bir holat × model), summary.json (o'rtacha, bootstrap 95% IO),
o'choq darajasida sezgirlik va FP/tekshiruv, modellar juftligi uchun Wilcoxon testi.

Model NOMI chekpoint joylashgan PAPKA nomidan olinadi: runs/abl/dicece_s42/best.pt → "dicece_s42".
Shuning uchun papka nomlari noyob bo'lishi shart; ikki chekpoint bir xil nomga ega bo'lsa, natijalar
jim aralashib ketmasligi uchun XATO beriladi (NAMING_v3.md dagi noyob nomlardan foydalaning).
summary.json da har model uchun "detail": holatlar bo'yicha Dice/HD95, o'rtacha, min, maks va
ci95 (n < 5 bo'lsa null — kichik n da bootstrap ma'nosiz).
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np
from scipy import stats

from .data.dataset import IGNORE, VolumeDataset, load_index, select
from .infer import load_model, sliding_window
from .metrics import bootstrap_ci, lesion_detection, seg_report


def model_names(ckpts):
    """Chekpoint yo'li → model nomi (papka nomi). Takroriy nom bo'lsa ValueError."""
    names = [Path(c).parent.name for c in ckpts]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        bad = [str(c) for c in ckpts if Path(c).parent.name in dup]
        raise ValueError(f"Takroriy model nomi(lar) {dup}: {bad}. Model nomi papka nomidan olinadi — papkalarni noyob nomlang.")
    return names


def _clean(v):
    v = float(v)
    return None if not np.isfinite(v) else v


def detail(d, h, n_boot=2000, min_n_ci=5):
    """Holatlar bo'yicha Dice va HD95 tafsiloti. ci95 faqat n >= min_n_ci da (aks holda null)."""
    d = np.asarray(d, float); h = np.asarray(h, float); hh = h[np.isfinite(h)]
    out = {"n": int(len(d)), "dice_per_case": [_clean(x) for x in d], "hd95_per_case": [_clean(x) for x in h],
           "dice_mean": _clean(d.mean()) if len(d) else None, "dice_min": _clean(d.min()) if len(d) else None,
           "dice_max": _clean(d.max()) if len(d) else None,
           "hd95_mean": _clean(hh.mean()) if len(hh) else None, "hd95_min": _clean(hh.min()) if len(hh) else None,
           "hd95_max": _clean(hh.max()) if len(hh) else None, "ci95": None}
    if len(d) >= min_n_ci:
        _, dl, dh = bootstrap_ci(np.mean, d, n_boot=n_boot)
        ci = {"dice": [dl, dh]}
        if len(hh) >= min_n_ci:
            _, hl, hhi = bootstrap_ci(np.mean, hh, n_boot=n_boot); ci["hd95"] = [hl, hhi]
        out["ci95"] = ci
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", nargs="+", required=True); ap.add_argument("--cache", required=True)
    ap.add_argument("--split", default="test"); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    names = model_names(a.ckpt)          # modellar yuklanishidan OLDIN tekshiriladi
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    cases = select(load_index(a.cache)["cases"], a.split)
    rows, summ, per_model = [], {}, {}
    for ck, name in zip(a.ckpt, names):
        model, cfg = load_model(ck)
        det = []
        for c in cases:
            x, y, _ = VolumeDataset(a.cache, [c])[0]
            prob = sliding_window(model, x[None], cfg["patch"], cfg["n_classes"], overlap=0.5, sw_batch=2)
            p1 = prob[1].numpy(); y = y.numpy(); ign = y == IGNORE
            r = seg_report(p1 >= 0.5, y == 1, (1, 1, 1), ign)
            tp, fp, ng, nh = lesion_detection(p1, y == 1, 0.5, ign)
            det.append((tp, fp, ng, nh))
            rows.append({"model": name, "case": c["id"], **r, "lesions_gt": ng, "lesions_hit": nh, "fp_components": len(fp)})
            print(name, c["id"], {k: round(v, 3) if isinstance(v, float) else v for k, v in r.items()})
        mr = [r for r in rows if r["model"] == name and r["vol_gt_ml"] > 0]
        d = np.array([r["dice"] for r in mr]); h = np.array([r["hd95_mm"] for r in mr])
        s = {"n_cases": len(mr)}
        if len(d):
            s["dice"] = bootstrap_ci(np.mean, d, n_boot=2000) if len(d) > 2 else (float(d.mean()), float("nan"), float("nan"))
            hh = h[np.isfinite(h)]
            s["hd95_mm"] = bootstrap_ci(np.mean, hh) if len(hh) > 2 else (float(hh.mean()) if len(hh) else float("nan"),)
        ng = sum(t[2] for t in det); nh = sum(t[3] for t in det)
        s["lesion_sensitivity"] = nh / max(ng, 1); s["fp_per_scan"] = float(np.mean([len(t[1]) for t in det])) if det else 0
        s["detail"] = detail(d, h)
        summ[name] = s; per_model[name] = {r["case"]: r["dice"] for r in mr}
    names = list(per_model)
    tests = {}
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            common = sorted(set(per_model[names[i]]) & set(per_model[names[j]]))
            if len(common) >= 5:
                st = stats.wilcoxon([per_model[names[i]][c] for c in common], [per_model[names[j]][c] for c in common])
                tests[f"{names[i]} vs {names[j]}"] = {"n": len(common), "p_wilcoxon": float(st.pvalue)}
            else:
                tests[f"{names[i]} vs {names[j]}"] = {"n": len(common), "note": "n<5 — statistik test ma'nosiz"}
    with open(out / "per_case.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    json.dump({"split": a.split, "models": summ, "pairwise": tests}, open(out / "summary.json", "w"), indent=1)
    print(json.dumps({"models": summ, "pairwise": tests}, indent=1, default=str))


if __name__ == "__main__":
    main()
