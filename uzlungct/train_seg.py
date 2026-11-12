"""Segmentatsiya modellarini o'qitish (III bob: 3.1–3.4-§; IV bob 4.2-§ yo'qotishlari bilan).

Misollar:
  python -m uzlungct.train_seg --config configs/tumor_local_r2u3d.yaml
  python -m uzlungct.train_seg --cache cache/local_tumor --model r2u3d_dynamic --loss adaptive --epochs 100

Xususiyatlar: aralash aniqlik (fp16/bf16), gradient to'plash, AdamW + cosine, eng yaxshi model
validatsiya Dice bo'yicha saqlanadi, erta to'xtatish, log.csv, oldindan o'qitilgan vaznlardan
(fine-tune) boshlash, bemor darajasidagi k-fold.

Davom ettirish (--resume true): last.pt (model, optimizator, scheduler, scaler, yo'qotish parametrlari,
epoxa, best, bad) har validatsiyada atomik yoziladi; uzilgan o'qitish shu holatdan davom etadi,
log.csv va loss_params.csv ga qo'shib yoziladi. Adaptiv yo'qotishda o'rganilgan vaznlar
har epoxada loss_params.csv ga yoziladi (4.2-§ vazn dinamikasi).
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import subprocess
import time
from pathlib import Path

import numpy as np
import torch
import yaml
from torch.utils.data import DataLoader

from . import hw
from .data.dataset import IGNORE, PatchDataset, VolumeDataset, load_index, patient_folds, select
from .infer import sliding_window
from .losses import build_seg_loss
from .metrics import dice, hd95
from .models import build_seg_model, count_params

DEFAULTS = dict(cache=None, out="runs/exp", model="r2u3d_dynamic", model_kw={}, n_classes=2, loss="dicece",
                epochs=100, samples_per_epoch=200, patch=None, batch=None, accum=1, lr=3e-4, wd=1e-5,
                pos_ratio=0.66, val_every=2, patience=15, fold=None, k=5, seed=42, task="tumor",
                init=None, max_val_cases=8, workers=None, amp=True, val_split="val", train_split="train", resume=False)

LOG_COLS = ["epoch", "loss", "val_dice", "val_hd95", "lr", "sec", "gpu_mem_gb"]


def atomic_save(obj, path):
    """Avval vaqtinchalik faylga, keyin os.replace — uzilishda yarim yozilgan chekpoint qolmaydi."""
    path = Path(path); tmp = path.with_name(path.name + ".tmp")
    torch.save(obj, tmp); os.replace(tmp, path)


def git_commit():
    """COMMIT.txt (kod paketida) bo'lsa undan, aks holda git rev-parse. Qaytaradi: (hash, dirty) yoki (None, None)."""
    root = Path(__file__).resolve().parents[1]
    f = root / "COMMIT.txt"
    if f.exists():
        kv = dict(l.split(":", 1) for l in f.read_text(encoding="utf-8").splitlines() if ":" in l)
        dirty = kv.get("dirty", "").strip().lower()
        return kv.get("commit", "").strip() or None, (dirty == "true") if dirty else None
    for exe in ("git", r"C:\Program Files\Git\cmd\git.exe"):
        try:
            h = subprocess.run([exe, "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=10)
            if h.returncode == 0:
                st = subprocess.run([exe, "status", "--porcelain", "--untracked-files=no"], cwd=root, capture_output=True, text=True, timeout=10)
                return h.stdout.strip(), bool(st.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            continue
    return None, None


def _keep_rows(path, upto, header):
    """CSV dan epoch <= upto qatorlarni qoldiradi (resume dan keyin log monoton bo'lishi uchun)."""
    if not path.exists():
        return
    rows = list(csv.reader(open(path, encoding="utf-8", newline="")))
    keep = [r for r in rows[1:] if r and int(r[0]) <= upto]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(rows[0] if rows else header); w.writerows(keep)


def loss_param_cols(loss_fn):
    if not hasattr(loss_fn, "log_vars"):
        return None
    names = list(loss_fn.components.keys())
    return ["epoch"] + [f"s_{n}" for n in names] + [f"w_{n}" for n in names]


def loss_param_row(ep, loss_fn):
    s = loss_fn.log_vars.detach().float().cpu().tolist()
    return [ep] + [round(v, 6) for v in s] + [round(math.exp(-v), 6) for v in s]


def parse():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    for k, v in DEFAULTS.items():
        if k == "model_kw":
            continue
        t = {"batch": int, "workers": int, "fold": int}.get(k, type(v) if v is not None else str)
        if t is bool:
            ap.add_argument(f"--{k}", type=lambda s: s.lower() in ("1", "true", "ha", "yes"))
        elif k == "patch":
            ap.add_argument("--patch", type=int, nargs=3)
        else:
            ap.add_argument(f"--{k}", type=t if t in (int, float) else str)
    a = vars(ap.parse_args())
    cfg = dict(DEFAULTS)
    if a.get("config"):
        cfg.update(yaml.safe_load(open(a["config"], encoding="utf-8")) or {})
    cfg.update({k: v for k, v in a.items() if v is not None and k != "config"})
    prof = hw.profile("seg", cfg["model"])
    cfg["patch"] = list(cfg["patch"] or prof["patch"]); cfg["batch"] = cfg["batch"] or prof["batch"]
    if cfg["workers"] is None:
        cfg["workers"] = hw.num_workers()
    return cfg


def evaluate(model, cache, cases, cfg, dev):
    model.eval(); res = []
    for c in cases:
        x, y, _ = VolumeDataset(cache, [c])[0]
        prob = sliding_window(model, x[None], cfg["patch"], cfg["n_classes"], overlap=0.25, sw_batch=cfg["batch"], amp=cfg["amp"])
        pred = prob.argmax(0).numpy(); y = y.numpy()
        ign = y == IGNORE
        d = dice(pred == 1, y == 1, ign)
        h = hd95((pred == 1) & ~ign, (y == 1) & ~ign) if (y == 1).any() else float("nan")
        res.append({"id": c["id"], "dice": d, "hd95": h, "has_fg": bool((y == 1).any())})
    model.train()
    fg = [r for r in res if r["has_fg"]] or res
    return float(np.mean([r["dice"] for r in fg])), float(np.nanmean([r["hd95"] for r in fg])) if fg else float("nan"), res


def main():
    cfg = parse()
    hw.setup_torch(cfg["seed"])
    dev = hw.device()
    out = Path(cfg["out"]); out.mkdir(parents=True, exist_ok=True)
    idx = load_index(cfg["cache"]); cases = idx["cases"]
    if cfg["fold"] is not None:
        folds = patient_folds([c for c in cases if c["split"] != "test"], cfg["k"], cfg["seed"])
        pool = [c for c in cases if c["split"] != "test"]
        tr = [c for c in pool if folds[c["patient"]] != cfg["fold"]]
        va = [c for c in pool if folds[c["patient"]] == cfg["fold"]]
    else:
        tr, va = select(cases, cfg["train_split"]), select(cases, cfg["val_split"])
    assert not ({c["patient"] for c in tr} & {c["patient"] for c in va}), "Bemor o'qitish va validatsiyada takrorlanmoqda!"
    va = [c for c in va if c.get("has_label", True)][: cfg["max_val_cases"]] or va[: cfg["max_val_cases"]]
    print(json.dumps({**hw.summary(), "train_cases": len(tr), "val_cases": len(va), "patch": cfg["patch"], "batch": cfg["batch"]}, ensure_ascii=False))

    model = build_seg_model(cfg["model"], 1, cfg["n_classes"], patch=cfg["patch"], **cfg["model_kw"]).to(dev)
    if cfg["init"]:
        sd = torch.load(cfg["init"], map_location="cpu", weights_only=False)["model"]
        own = model.state_dict()
        sd = {k: v for k, v in sd.items() if k in own and own[k].shape == v.shape}
        model.load_state_dict(sd, strict=False); print(f"init_loaded={len(sd)}/{len(own)}")
    loss_fn = build_seg_loss(cfg["loss"], ignore_index=IGNORE).to(dev)
    params = list(model.parameters()) + list(loss_fn.parameters())
    opt = torch.optim.AdamW(params, lr=cfg["lr"], weight_decay=cfg["wd"])
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda e: 0.5 * (1 + math.cos(math.pi * min(e, cfg["epochs"]) / cfg["epochs"])))
    dt = hw.amp_dtype() if (cfg["amp"] and dev.type == "cuda") else None
    scaler = torch.amp.GradScaler("cuda", enabled=(dt == torch.float16))
    ds = PatchDataset(cfg["cache"], tr, cfg["patch"], cfg["samples_per_epoch"], cfg["pos_ratio"], True, cfg["seed"])
    dl = DataLoader(ds, batch_size=cfg["batch"], shuffle=True, num_workers=cfg["workers"], pin_memory=dev.type == "cuda",
                    persistent_workers=cfg["workers"] > 0, drop_last=True)
    yaml.safe_dump({**cfg, "params": count_params(model)}, open(out / "config.yaml", "w", encoding="utf-8"), allow_unicode=True)
    best, bad, start, sec_prev = -1.0, 0, 1, 0.0
    lp_cols = loss_param_cols(loss_fn)
    if cfg["resume"] and (out / "last.pt").exists():
        ck = torch.load(out / "last.pt", map_location="cpu", weights_only=False)
        if "opt" not in ck:
            raise RuntimeError(f"{out / 'last.pt'} eski formatda (optimizator holati yo'q) — davom ettirib bo'lmaydi")
        model.load_state_dict(ck["model"]); opt.load_state_dict(ck["opt"]); sched.load_state_dict(ck["sched"])
        scaler.load_state_dict(ck["scaler"]); loss_fn.load_state_dict(ck["loss_fn"])
        best, bad, start, sec_prev = ck["best"], ck["bad"], ck["epoch"] + 1, ck.get("seconds_total", 0.0)
        _keep_rows(out / "log.csv", ck["epoch"], LOG_COLS)
        if lp_cols:
            _keep_rows(out / "loss_params.csv", ck["epoch"], lp_cols)
        print(f"resume epoch={ck['epoch']} best={best:.4f} bad={bad}")
    else:
        for f in ("log.csv", "loss_params.csv"):
            (out / f).unlink(missing_ok=True)
    new_log = not (out / "log.csv").exists()
    log = open(out / "log.csv", "a", newline="", encoding="utf-8"); wr = csv.writer(log)
    if new_log:
        wr.writerow(LOG_COLS)
    lpw = None
    if lp_cols:
        new_lp = not (out / "loss_params.csv").exists()
        lpf = open(out / "loss_params.csv", "a", newline="", encoding="utf-8"); lpw = csv.writer(lpf)
        if new_lp:
            lpw.writerow(lp_cols)
    t_run = time.time()
    ep = start - 1
    for ep in range(start, cfg["epochs"] + 1):
        t0 = time.time(); model.train(); tot = 0.0; opt.zero_grad(set_to_none=True)
        if dev.type == "cuda":
            torch.cuda.reset_peak_memory_stats()
        for it, (x, y) in enumerate(dl):
            x, y = x.to(dev, non_blocking=True), y.to(dev, non_blocking=True)
            with torch.autocast(dev.type, dtype=dt, enabled=dt is not None):
                logits = model(x)
            loss = loss_fn(logits.float(), y) / cfg["accum"]
            scaler.scale(loss).backward()
            if (it + 1) % cfg["accum"] == 0:
                scaler.unscale_(opt); torch.nn.utils.clip_grad_norm_(params, 12.0)
                scaler.step(opt); scaler.update(); opt.zero_grad(set_to_none=True)
            tot += loss.item() * cfg["accum"]
        if not math.isfinite(tot):      # NaN holat chekpointga yozilmaydi; navbat skripti xatoni ushlaydi
            raise FloatingPointError(f"epoch {ep}: loss NaN/cheksiz")
        sched.step()
        if lpw:
            lpw.writerow(loss_param_row(ep, loss_fn)); lpf.flush()
        vd, vh, ck = float("nan"), float("nan"), None
        if ep % cfg["val_every"] == 0 or ep == cfg["epochs"]:
            vd, vh, _ = evaluate(model, cfg["cache"], va, cfg, dev)
            ck = {"model": model.state_dict(), "cfg": cfg, "epoch": ep, "val_dice": vd}
            if vd > best:
                best, bad = vd, 0; atomic_save(ck, out / "best.pt")
            else:
                bad += cfg["val_every"]
        mem = torch.cuda.max_memory_allocated() / 2**30 if dev.type == "cuda" else 0
        wr.writerow([ep, round(tot / max(1, len(dl)), 5), vd, vh, opt.param_groups[0]["lr"], round(time.time() - t0, 1), round(mem, 2)]); log.flush()
        if ck is not None:     # log qatoridan KEYIN: uzilsa, resume ortiqcha qatorlarni kesib tashlaydi
            atomic_save({**ck, "opt": opt.state_dict(), "sched": sched.state_dict(), "scaler": scaler.state_dict(),
                         "loss_fn": loss_fn.state_dict(), "best": best, "bad": bad,
                         "seconds_total": sec_prev + time.time() - t_run}, out / "last.pt")
        print(f"ep {ep:3d} loss {tot / max(1, len(dl)):.4f} val_dice {vd:.4f} hd95 {vh:.2f} {time.time() - t0:.0f}s mem {mem:.1f}GB")
        if bad >= cfg["patience"]:
            print(f"early_stop epoch={ep}"); break
    log.close()
    if lpw:
        lpf.close()
    rows = list(csv.DictReader(open(out / "log.csv", encoding="utf-8")))
    commit, dirty = git_commit()
    json.dump({"best_val_dice": best, "epochs_run": ep, "params": count_params(model),
               "seconds_total": round(sec_prev + time.time() - t_run, 1),
               "peak_vram_gb": max((float(r["gpu_mem_gb"]) for r in rows), default=0.0),
               "git_commit": commit, "git_dirty": dirty, "seed": cfg["seed"],
               "n_train_cases": len(tr), "n_val_cases": len(va), "patch": cfg["patch"], "batch": cfg["batch"],
               "accum": cfg["accum"], "init": cfg["init"], "loss": cfg["loss"]},
              open(out / "summary.json", "w"), indent=1)
    print(f"done best_val_dice={best:.4f}")


if __name__ == "__main__":
    main()
