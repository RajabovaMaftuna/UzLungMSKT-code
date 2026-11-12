"""Kesh (.npz) dan patch namunalovchi PyTorch dataset. RAM tejash uchun holatlar
mmap bilan ochiladi (np.load(..., mmap_mode) .npz da ishlamagani uchun bir martalik
.npy ga ochiladi: <cache>/_npy/<id>_ct.npy)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import Dataset

HU_MIN, HU_MAX = -1000.0, 400.0
IGNORE = 255


def norm_hu(x):
    return ((np.clip(x.astype(np.float32), HU_MIN, HU_MAX) - HU_MIN) / (HU_MAX - HU_MIN)).astype(np.float32)


def load_index(cache):
    return json.load(open(Path(cache) / "index.json", encoding="utf-8"))


def _npy(cache: Path, c: dict, key: str):
    d = cache / "_npy"; d.mkdir(exist_ok=True)
    p = d / f"{c['id']}_{key}.npy"
    if not p.exists():
        with np.load(cache / c["file"]) as z:
            if key not in z.files:
                return None
            np.save(p, z[key])
    return np.load(p, mmap_mode="r")


def select(cases, split=None, folds=None, fold=None, role=None):
    """split: 'train'/'val'/'test' yoki None. folds+fold: k-karrali (bemor bo'yicha) bo'linish."""
    out = cases
    if split:
        out = [c for c in out if c["split"] == split]
    if folds is not None and fold is not None:
        out = [c for c in out if (folds[c["patient"]] == fold) == (role == "val")]
    return out


def patient_folds(cases, k=5, seed=42):
    pats = sorted({c["patient"] for c in cases})
    rng = np.random.default_rng(seed); rng.shuffle(pats)
    return {p: i % k for i, p in enumerate(pats)}


class PatchDataset(Dataset):
    """Tasodifiy 3D patchlar; pos_ratio ulushida patch markazi oldingi plan vokseliga tushiriladi."""

    def __init__(self, cache, cases, patch=(96, 96, 96), samples_per_epoch=200, pos_ratio=0.66,
                 augment=True, seed=0):
        self.cache = Path(cache); self.cases = [c for c in cases]
        self.patch = np.array(patch); self.n = samples_per_epoch
        self.pos_ratio, self.augment = pos_ratio, augment
        self.rng = np.random.default_rng(seed)
        self._fg = {}

    def __len__(self):
        return self.n

    def _fg_coords(self, c, lab):
        if c["id"] not in self._fg:
            idx = np.argwhere((lab > 0) & (lab != IGNORE))
            if len(idx) > 20000:
                idx = idx[np.random.default_rng(0).choice(len(idx), 20000, replace=False)]
            self._fg[c["id"]] = idx
        return self._fg[c["id"]]

    def __getitem__(self, i):
        rng = np.random.default_rng(self.rng.integers(1 << 31) + i)
        c = self.cases[rng.integers(len(self.cases))]
        ct = _npy(self.cache, c, "ct"); lab = _npy(self.cache, c, "label")
        shp = np.array(ct.shape)
        fg = self._fg_coords(c, lab) if lab is not None else np.zeros((0, 3))
        if len(fg) and rng.random() < self.pos_ratio:
            ctr = fg[rng.integers(len(fg))] + rng.integers(-self.patch // 4, self.patch // 4 + 1)
        else:
            ctr = rng.integers(0, shp)
        lo = np.clip(ctr - self.patch // 2, 0, np.maximum(shp - self.patch, 0))
        sl = tuple(slice(int(a), int(a + p)) for a, p in zip(lo, self.patch))
        x = norm_hu(np.asarray(ct[sl]))
        y = np.asarray(lab[sl]).astype(np.int64) if lab is not None else np.zeros(x.shape, np.int64)
        x, y = pad_to(x, self.patch, 0.0), pad_to(y, self.patch, 0)
        if self.augment:
            x, y = augment_pair(x, y, rng)
        return torch.from_numpy(x[None].copy()), torch.from_numpy(y.copy())


def pad_to(a, shape, val):
    pad = [(0, max(0, int(s) - d)) for d, s in zip(a.shape, shape)]
    return np.pad(a, pad, constant_values=val) if any(p[1] for p in pad) else a


def augment_pair(x, y, rng):
    for ax in (0, 1, 2):
        if rng.random() < 0.5:
            x, y = np.flip(x, ax), np.flip(y, ax)
    if rng.random() < 0.5:
        k = int(rng.integers(1, 4)); x, y = np.rot90(x, k, (1, 2)), np.rot90(y, k, (1, 2))
    if rng.random() < 0.3:
        x = np.clip(x * rng.uniform(0.9, 1.1) + rng.uniform(-0.05, 0.05), 0, 1)
    if rng.random() < 0.2:
        x = np.clip(x + rng.normal(0, 0.02, x.shape).astype(np.float32), 0, 1)
    return np.ascontiguousarray(x, dtype=np.float32), np.ascontiguousarray(y)


class VolumeDataset(Dataset):
    """Validatsiya/sinov: butun (kesilgan) hajm."""

    def __init__(self, cache, cases):
        self.cache = Path(cache); self.cases = cases

    def __len__(self):
        return len(self.cases)

    def __getitem__(self, i):
        c = self.cases[i]
        ct = _npy(self.cache, c, "ct"); lab = _npy(self.cache, c, "label")
        x = torch.from_numpy(norm_hu(np.asarray(ct))[None])
        y = torch.from_numpy(np.asarray(lab).astype(np.int64)) if lab is not None else torch.zeros(x.shape[1:], dtype=torch.long)
        return x, y, c


# ------------------------------------------------------------- tugun patchlari (tasniflash, 4.1-§)

_PATCH_CACHE = {}


def load_patches(npz):
    """patches.npz ni jarayonda BIR MARTA ochadi: X yonidagi <npz>.X.npy dan mmap bilan o'qiladi (yo'q bo'lsa bir marta
    atomik yoziladi). Ilgari har bir dataset (o'qitish/ichki/tashqi × har fold) X ni RAM ga alohida yuklardi (~1,5 GB × n).
    Qiymatlar o'zgarmaydi."""
    import os
    key = str(Path(npz).resolve())
    if key not in _PATCH_CACHE:
        side = Path(str(npz) + ".X.npy")
        with np.load(npz, allow_pickle=True) as z:
            y, pat = z["y"].astype(np.int64), z["patient"]
            if not side.exists():
                tmp = side.with_name(f"{side.name}.{os.getpid()}.tmp.npy")
                np.save(tmp, z["X"]); os.replace(tmp, side)
        _PATCH_CACHE[key] = (np.load(side, mmap_mode="r"), y, pat)
    return _PATCH_CACHE[key]


class NodulePatchDataset(Dataset):
    """patches.npz: X (N,48,48,48) int16 HU, y (N,) {0,1,-1 belgisiz}, patient (N,)."""

    def __init__(self, npz, idx=None, augment=True, labeled_only=True):
        self.X, self.y, self.pat = load_patches(npz)
        keep = np.arange(len(self.y)) if idx is None else np.asarray(idx)
        if labeled_only:
            keep = keep[self.y[keep] >= 0]
        self.idx, self.augment = keep, augment
        self.rng = np.random.default_rng(0)

    def __len__(self):
        return len(self.idx)

    def __getitem__(self, i):
        j = self.idx[i]
        x = norm_hu(self.X[j])
        if self.augment:
            for ax in (0, 1, 2):
                if self.rng.random() < 0.5:
                    x = np.flip(x, ax)
            x = np.ascontiguousarray(x)
        return torch.from_numpy(x[None].astype(np.float32)), int(self.y[j])
