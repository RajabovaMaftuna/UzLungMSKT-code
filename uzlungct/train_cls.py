"""4.1–4.2-§: o'z-o'zini nazorat qiluvchi oldindan o'qitish (SimCLR) va tugunlarni tasniflash.

1-bosqich (SSL):  python -m uzlungct.train_cls ssl  --patches cache/lidc_patches.npz --out runs/ssl [--resume]
2-bosqich (FT):   python -m uzlungct.train_cls ft   --patches cache/lidc_patches.npz --init runs/ssl/encoder.pt --loss adaptive --out runs/cls_ssl
Taqqoslash uchun: --init siz (noldan) va --loss ce bilan.
Bo'linish bemor darajasida (5-fold yoki --fold). Har foldning o'qitish bemorlaridan --inner_frac (10 %) qismi
«ichki validatsiya»: epoxa tanlash va adapt_gamma FAQAT shunga qaraydi. Tashqi (tekshiruv) fold har epoxada
faqat bashorat qilinadi; OOF ballar ichki validatsiya tanlagan epoxadan olinadi.
Natija: oof_scores.csv (index, y, score, fold, patient), metrics.json (AUC, bemor darajasidagi klaster
bootstrap 95% IO, sezgirlik, o'ziga xoslik), calibration.json (T, NLL, ECE oldin/keyin), reliability.png.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset

from . import hw
from .data.dataset import NodulePatchDataset, norm_hu
from .losses import AdaptiveFocalCB, FocalLoss
from .metrics import binary_report, cluster_bootstrap_ci, ece, reliability_bins
from .models import NoduleClassifier, ProjectionHead, ResNet3DEncoder
from .ssl import augment3d, nt_xent


def _atomic_save(obj, path):
    path = Path(path); tmp = path.with_name(path.name + ".tmp")
    torch.save(obj, tmp); os.replace(tmp, path)


def ssl_main(a):
    hw.setup_torch(a.seed); dev = hw.device()
    z = np.load(a.patches, allow_pickle=True)
    X = z["X"]                      # belgili va belgisiz barcha patchlar SSL da ishlatiladi (belgilar emas!)
    enc = ResNet3DEncoder().to(dev); head = ProjectionHead(enc.out_dim).to(dev)
    opt = torch.optim.AdamW(list(enc.parameters()) + list(head.parameters()), lr=a.lr, weight_decay=1e-4)
    dt = hw.amp_dtype() if dev.type == "cuda" else None
    scaler = torch.amp.GradScaler("cuda", enabled=(dt == torch.float16))
    bs = a.batch or hw.profile("cls")["batch"]
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    start = 1
    if a.resume and (out / "ssl_last.pt").exists():
        ck = torch.load(out / "ssl_last.pt", map_location="cpu", weights_only=False)
        enc.load_state_dict(ck["encoder"]); head.load_state_dict(ck["head"]); opt.load_state_dict(ck["opt"])
        start = ck["epoch"] + 1
        np.random.set_state(ck["np_rng"])
        print(f"SSL resume epoch={ck['epoch']}")
    for ep in range(start, a.epochs + 1):
        t0 = time.time(); perm = np.random.permutation(len(X)); tot = n = 0
        for i in range(0, len(perm) - bs + 1, bs):
            x = torch.from_numpy(norm_hu(X[perm[i:i + bs]]))[:, None]
            v1, v2 = augment3d(x).to(dev), augment3d(x).to(dev)
            with torch.autocast(dev.type, dtype=dt, enabled=dt is not None):
                loss = nt_xent(head(enc(v1)).float(), head(enc(v2)).float(), a.tau)
            opt.zero_grad(); scaler.scale(loss).backward(); scaler.step(opt); scaler.update(); tot += float(loss); n += 1
        print(f"SSL ep {ep} loss {tot / max(n, 1):.4f} {time.time() - t0:.0f}s")
        _atomic_save({"encoder": enc.state_dict()}, out / "encoder.pt")
        _atomic_save({"encoder": enc.state_dict(), "head": head.state_dict(), "opt": opt.state_dict(), "epoch": ep,
                      "np_rng": np.random.get_state()}, out / "ssl_last.pt")


def patient_fold_map(pat, y_all, k=5, seed=42):
    """Belgili tugunlari bor bemorlar → fold raqami (bemor darajasida, seed bilan). diss_collect ham shuni ishlatadi."""
    lab = np.where(np.asarray(y_all) >= 0)[0]
    pats = sorted(set(np.asarray(pat)[lab])); rng = np.random.default_rng(seed); rng.shuffle(pats)
    return {p: i % k for i, p in enumerate(pats)}


def split_fold(y_all, pat, fold_of, f, inner_frac=0.1, seed=42):
    """f-fold uchun (o'qitish, ichki validatsiya, tashqi tekshiruv) indekslari. Ichki validatsiya —
    o'qitish bemorlarining inner_frac ulushi (kamida 1 bemor), bemor darajasida."""
    y_all, pat = np.asarray(y_all), np.asarray(pat)
    lab = np.where(y_all >= 0)[0]
    outer = np.array([i for i in lab if fold_of[pat[i]] == f], dtype=int)
    rest = [i for i in lab if fold_of[pat[i]] != f]
    tr_pats = sorted(set(pat[rest]))
    rng = np.random.default_rng(seed + 1000 * (f + 1)); rng.shuffle(tr_pats)
    n_in = max(1, int(round(inner_frac * len(tr_pats))))
    inner_p = set(tr_pats[:n_in])
    inner = np.array([i for i in rest if pat[i] in inner_p], dtype=int)
    train = np.array([i for i in rest if pat[i] not in inner_p], dtype=int)
    return train, inner, outer


def _predict(model, dl, dev):
    model.eval(); sc, ys = [], []
    with torch.no_grad():
        for x, y in dl:
            sc.append(torch.softmax(model(x.to(dev)).float(), 1)[:, 1].cpu()); ys.append(y)
    return torch.cat(sc).numpy(), torch.cat(ys).numpy()


def _select_score(ys, sc):
    """Epoxa tanlash mezoni (ichki validatsiyada): AUC; bitta sinf bo'lsa — manfiy log-yo'qotish."""
    rep = binary_report(ys, sc)
    if np.isfinite(rep["auc"]):
        return rep["auc"], rep
    p = np.clip(sc, 1e-6, 1 - 1e-6)
    return float(np.mean(ys * np.log(p) + (1 - ys) * np.log(1 - p))), rep


def ft_main(a):
    hw.setup_torch(a.seed); dev = hw.device()
    z = np.load(a.patches, allow_pickle=True)
    y_all, pat = z["y"].astype(int), z["patient"]
    fold_of = patient_fold_map(pat, y_all, a.k, a.seed)
    if len(fold_of) < a.k + 1:
        raise SystemExit(f"Belgili tugunli bemorlar {len(fold_of)} ta — {a.k}-fold va ichki validatsiya uchun kamida {a.k + 1} ta kerak")
    folds = [a.fold] if a.fold is not None else list(range(a.k))
    oof, sel = [], {}
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    for f in folds:
        tr, inner, va = split_fold(y_all, pat, fold_of, f, a.inner_frac, a.seed)
        enc = ResNet3DEncoder()
        if a.init:
            enc.load_state_dict(torch.load(a.init, map_location="cpu")["encoder"])
        model = NoduleClassifier(enc).to(dev)
        counts = np.bincount(y_all[tr], minlength=2)
        if a.loss == "adaptive":
            crit = AdaptiveFocalCB(2).to(dev); crit.update_counts(counts)
        elif a.loss == "focal":
            crit = FocalLoss(gamma=2.0)
        else:
            crit = torch.nn.CrossEntropyLoss()
        lr_enc = a.lr * (0.1 if a.init else 1.0)
        opt = torch.optim.AdamW([{"params": model.encoder.parameters(), "lr": lr_enc},
                                 {"params": model.head.parameters(), "lr": a.lr}], weight_decay=1e-4)
        bs = a.batch or hw.profile("cls")["batch"]
        dl = DataLoader(NodulePatchDataset(a.patches, tr, augment=True), batch_size=bs, shuffle=True,
                        num_workers=a.workers if a.workers is not None else min(4, hw.num_workers()), drop_last=len(tr) > bs)
        di = DataLoader(NodulePatchDataset(a.patches, inner, augment=False), batch_size=bs)
        dv = DataLoader(NodulePatchDataset(a.patches, va, augment=False), batch_size=bs)
        dt = hw.amp_dtype() if dev.type == "cuda" else None
        scaler = torch.amp.GradScaler("cuda", enabled=(dt == torch.float16))
        best, best_scores, best_ep = -np.inf, None, None
        for ep in range(1, a.epochs + 1):
            model.train()
            for x, y in dl:
                x, y = x.to(dev), y.to(dev)
                with torch.autocast(dev.type, dtype=dt, enabled=dt is not None):
                    lg = model(x)
                loss = crit(lg.float(), y)
                opt.zero_grad(); scaler.scale(loss).backward(); scaler.step(opt); scaler.update()
            si, yi = _predict(model, di, dev)
            score, rep = _select_score(yi, si)                       # tanlash FAQAT ichki validatsiyada
            if a.loss == "adaptive":
                crit.adapt_gamma(rep["sensitivity"] if counts[1] < counts[0] else rep["specificity"])
            sv, _ = _predict(model, dv, dev)                          # tashqi fold: faqat bashorat
            if score > best:
                best, best_scores, best_ep = score, sv.copy(), ep
                _atomic_save({"model": model.state_dict(), "fold": f, "epoch": ep}, out / f"cls_fold{f}.pt")
            print(f"fold {f} ep {ep} loss {float(loss.detach()):.4f} ichki AUC {rep['auc']:.3f} sens {rep['sensitivity']:.2f} spec {rep['specificity']:.2f}")
        sel[str(f)] = {"epoch": best_ep, "inner_score": float(best), "n_train": int(len(tr)), "n_inner": int(len(inner)),
                       "n_outer": int(len(va)), "n_inner_patients": int(len(set(pat[inner])))}
        oof += [(int(i), int(y_all[i]), float(s), f, str(pat[i])) for i, s in zip(va, best_scores)]
    with open(out / "oof_scores.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["index", "y", "score", "fold", "patient"]); w.writerows(oof)
    y, s = np.array([o[1] for o in oof]), np.array([o[2] for o in oof]); g = np.array([o[4] for o in oof])
    from sklearn.metrics import roc_auc_score
    auc, lo, hi = cluster_bootstrap_ci(lambda yy, ss: roc_auc_score(yy, ss), y, s, g, n_boot=2000, seed=a.seed)
    rep = binary_report(y, s); rep["auc_ci95"] = [lo, hi]; rep["auc_ci95_method"] = "bemor darajasida klaster bootstrap, 2000"
    rep["n_patients"] = int(len(set(g))); rep["selection"] = sel
    # harorat bo'yicha kalibrlash (Guo 2017): OOF ehtimolliklar asosida T tanlanadi
    from scipy.optimize import minimize_scalar
    zl = np.log(np.clip(s, 1e-6, 1 - 1e-6) / np.clip(1 - s, 1e-6, 1))
    nll = lambda T: float(np.mean(np.log1p(np.exp(-(2 * y - 1) * zl / T))))
    T = float(minimize_scalar(nll, bounds=(0.05, 20), method="bounded").x)
    s_cal = 1 / (1 + np.exp(-zl / T))
    cal = {"temperature": T, "nll_before": nll(1.0), "nll_after": nll(T),
           "ece_before": ece(y, s, 15), "ece_after": ece(y, s_cal, 15), "ece_bins": 15}
    json.dump(cal, open(out / "calibration.json", "w"), indent=1)
    _reliability_png(y, s, s_cal, out / "reliability.png")
    rep["temperature"] = T
    json.dump(rep, open(out / "metrics.json", "w"), indent=1)
    print(json.dumps(rep, indent=1))


def _reliability_png(y, s, s_cal, path, n_bins=15):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(4.5, 4.5), dpi=150)
    ax.plot([0, 1], [0, 1], color="0.6", lw=1, ls="--", label="ideal")
    for p, lab, mk in ((s, f"oldin (ECE {ece(y, s, n_bins):.3f})", "o"), (s_cal, f"keyin (ECE {ece(y, s_cal, n_bins):.3f})", "s")):
        b = reliability_bins(y, p, n_bins)
        ax.plot([t[0] for t in b], [t[1] for t in b], marker=mk, ms=4, lw=1.2, label=lab)
    ax.set_xlabel("Bashorat qilingan ehtimol"); ax.set_ylabel("Haqiqiy xavfli ulushi")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.legend(frameon=False, fontsize=8)
    fig.tight_layout(); fig.savefig(path); plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["ssl", "ft"])
    ap.add_argument("--patches", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--init"); ap.add_argument("--loss", default="adaptive", choices=["adaptive", "focal", "ce"])
    ap.add_argument("--epochs", type=int, default=50); ap.add_argument("--batch", type=int)
    ap.add_argument("--lr", type=float, default=1e-3); ap.add_argument("--tau", type=float, default=0.1)
    ap.add_argument("--k", type=int, default=5); ap.add_argument("--fold", type=int); ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--inner_frac", type=float, default=0.1); ap.add_argument("--workers", type=int)
    ap.add_argument("--resume", action="store_true", help="ssl: ssl_last.pt dan davom ettirish")
    a = ap.parse_args()
    ssl_main(a) if a.stage == "ssl" else ft_main(a)


if __name__ == "__main__":
    main()
