"""Segmentatsiya va tasniflash uchun yo'qotish funksiyalari (4.2-§).

Barcha segmentatsiya yo'qotishlari quyidagi kirishlarni qabul qiladi:
  logits : (B, C, D, H, W) — tarmoq chiqishi (softmax oldidan)
  target : (B, D, H, W)    — butun sonli sinf belgilari
  ignore_index : bu belgili voksellar (masalan, "noaniq" = 3) hisobga olinmaydi.

Tasniflash yo'qotishlari:
  logits : (B, K), target : (B,)
"""
from __future__ import annotations

import math
import torch
import torch.nn as nn
import torch.nn.functional as F


def _prep(logits, target, ignore_index):
    C = logits.shape[1]
    valid = torch.ones_like(target, dtype=torch.bool)
    if ignore_index is not None:
        valid = target != ignore_index
    t = torch.where(valid, target, torch.zeros_like(target)).long()
    t = t.clamp(0, C - 1)
    oh = F.one_hot(t, C).movedim(-1, 1).float()            # (B,C,...)
    v = valid.unsqueeze(1).float()
    p = torch.softmax(logits.float(), dim=1)
    return p * v, oh * v, v, t, valid


class SoftDiceLoss(nn.Module):
    """Soft-DSC (Milletari 2016): 1 - 2Σpg / (Σp² + Σg² + ε). Fon sinfi hisobdan chiqariladi."""

    def __init__(self, include_background=False, squared=True, eps=1e-5, ignore_index=None):
        super().__init__()
        self.ib, self.sq, self.eps, self.ii = include_background, squared, eps, ignore_index

    def per_class_dice(self, logits, target):
        p, g, _, _, _ = _prep(logits, target, self.ii)
        dims = (0,) + tuple(range(2, p.ndim))
        inter = (p * g).sum(dims)
        den = (p * p).sum(dims) + (g * g).sum(dims) if self.sq else p.sum(dims) + g.sum(dims)
        d = (2 * inter + self.eps) / (den + self.eps)
        return d if self.ib else d[1:]

    def forward(self, logits, target):
        return 1 - self.per_class_dice(logits, target).mean()


class FocalLoss(nn.Module):
    """Fokal yo'qotish (Lin 2017): -α(1-p_t)^γ log p_t. Segmentatsiya va tasniflash uchun."""

    def __init__(self, gamma=2.0, alpha=None, ignore_index=None):
        super().__init__()
        self.gamma, self.ii = gamma, ignore_index
        self.register_buffer("alpha", None if alpha is None else torch.as_tensor(alpha, dtype=torch.float32))

    def forward(self, logits, target):
        logp = F.log_softmax(logits.float(), dim=1)
        valid = torch.ones_like(target, dtype=torch.bool) if self.ii is None else target != self.ii
        t = torch.where(valid, target, torch.zeros_like(target)).long()
        logpt = logp.gather(1, t.unsqueeze(1)).squeeze(1)
        pt = logpt.exp()
        loss = -((1 - pt) ** self.gamma) * logpt
        if self.alpha is not None:
            loss = loss * self.alpha.to(loss.device)[t]
        loss = loss[valid]
        return loss.mean() if loss.numel() else logits.sum() * 0


class TverskyLoss(nn.Module):
    """Tversky (Salehi 2017): TP/(TP+αFN+βFP); α>β — yolg'on manfiylar (o'tkazib yuborilgan o'sma) qattiqroq jazolanadi.
    gamma<1 bo'lsa Focal-Tversky (Abraham 2019)."""

    def __init__(self, alpha=0.7, beta=0.3, gamma=1.0, eps=1e-5, ignore_index=None):
        super().__init__()
        self.a, self.b, self.g, self.eps, self.ii = alpha, beta, gamma, eps, ignore_index

    def forward(self, logits, target):
        p, g, _, _, _ = _prep(logits, target, self.ii)
        dims = (0,) + tuple(range(2, p.ndim))
        tp = (p * g).sum(dims)
        fn = ((1 - p) * g).sum(dims)
        fp = (p * (1 - g)).sum(dims)
        ti = (tp + self.eps) / (tp + self.a * fn + self.b * fp + self.eps)
        return ((1 - ti[1:]).clamp_min(0) ** self.g).mean()


class ExpLogLoss(nn.Module):
    """Eksponensial-logarifmik yo'qotish (Wong 2018, R²U3D da qo'llangan):
    L = w_dice·E[(-ln Dice_i)^γ] + w_ce·E[w_l (-ln p_l)^γ]."""

    def __init__(self, w_dice=0.8, w_ce=0.2, gamma=0.3, ignore_index=None, eps=1e-6):
        super().__init__()
        self.wd, self.wc, self.g, self.ii, self.eps = w_dice, w_ce, gamma, ignore_index, eps
        self.dice = SoftDiceLoss(include_background=True, squared=False, ignore_index=ignore_index)

    def forward(self, logits, target):
        d = self.dice.per_class_dice(logits, target).clamp(self.eps, 1.0)
        l_dice = ((-torch.log(d)) ** self.g).mean()
        logp = F.log_softmax(logits.float(), 1)
        valid = torch.ones_like(target, dtype=torch.bool) if self.ii is None else target != self.ii
        t = torch.where(valid, target, torch.zeros_like(target)).long()
        lp = -logp.gather(1, t.unsqueeze(1)).squeeze(1)
        # sinf chastotasiga teskari vazn (Wong 2018: w_l = (Σf_k / f_l)^0.5)
        C = logits.shape[1]
        counts = torch.bincount(t[valid].flatten(), minlength=C).float().clamp_min(1)
        wl = (counts.sum() / counts) ** 0.5
        wl = wl / wl.mean()
        l_ce = (wl[t] * lp.clamp_min(self.eps) ** self.g)[valid].mean()
        return self.wd * l_dice + self.wc * l_ce


class UnifiedFocalLoss(nn.Module):
    """Unifikatsiyalangan fokal yo'qotish (Yeung 2022), ikkilik/ko'p sinfli soddalashtirilgan:
    L = λ·L_mF(asimmetrik fokal) + (1-λ)·L_mFT(asimmetrik fokal-Tversky)."""

    def __init__(self, lam=0.5, delta=0.6, gamma=0.5, ignore_index=None):
        super().__init__()
        self.lam, self.delta, self.gamma, self.ii = lam, delta, gamma, ignore_index
        self.ft = TverskyLoss(alpha=delta, beta=1 - delta, gamma=gamma, ignore_index=ignore_index)

    def forward(self, logits, target):
        logp = F.log_softmax(logits.float(), 1)
        valid = torch.ones_like(target, dtype=torch.bool) if self.ii is None else target != self.ii
        t = torch.where(valid, target, torch.zeros_like(target)).long()
        logpt = logp.gather(1, t.unsqueeze(1)).squeeze(1)
        pt = logpt.exp()
        # asimmetrik: fon voksellari fokal bilan susaytiriladi, oldingi plan (o'sma) — susaytirilmaydi
        bg = (t == 0).float()
        # γ < 1 da (1-p)^γ ning hosilasi p=1 da cheksiz → NaN; asos 1e-6 dan pastga tushirilmaydi (faqat shu holatga ta'sir qiladi)
        mf = -(bg * (1 - self.delta) * (1 - pt).clamp_min(1e-6) ** self.gamma * logpt + (1 - bg) * self.delta * logpt)
        mf = mf[valid].mean() if valid.any() else logits.sum() * 0
        return self.lam * mf + (1 - self.lam) * self.ft(logits, target)


class DiceCELoss(nn.Module):
    """Amaliyotdagi standart: Dice + kross-entropiya (nnU-Net)."""

    def __init__(self, w_dice=1.0, w_ce=1.0, ignore_index=None):
        super().__init__()
        self.d = SoftDiceLoss(ignore_index=ignore_index, squared=False)
        self.wd, self.wc, self.ii = w_dice, w_ce, ignore_index

    def forward(self, logits, target):
        ce = F.cross_entropy(logits.float(), target.long(), ignore_index=-100 if self.ii is None else self.ii)
        return self.wd * self.d(logits, target) + self.wc * ce


# ---------------------------------------------------------------- adaptiv yo'qotishlar (4.2-§)

class AdaptiveCompoundLoss(nn.Module):
    """Adaptiv kompozit yo'qotish: bir nechta yo'qotish komponentining vaznlari o'qitish
    davomida gomoskedastik noaniqlik orqali o'rganiladi (Kendall va boshq., 2018):
        L = Σ_k [ exp(-s_k)·L_k + s_k ],   s_k = log σ_k² — o'rganiluvchi parametr.
    Shu bilan qo'lda tanlanadigan w_dice / w_ce vaznlariga ehtiyoj qolmaydi."""

    def __init__(self, components: dict[str, nn.Module]):
        super().__init__()
        self.components = nn.ModuleDict(components)
        self.log_vars = nn.Parameter(torch.zeros(len(components)))

    def forward(self, logits, target):
        total = 0.0
        self.last = {}
        for i, (name, fn) in enumerate(self.components.items()):
            li = fn(logits, target)
            self.last[name] = float(li.detach())
            total = total + torch.exp(-self.log_vars[i]) * li + self.log_vars[i]
        return total

    def weights(self):
        return {n: float(torch.exp(-v)) for n, v in zip(self.components.keys(), self.log_vars.detach())}


def class_balanced_weights(counts, beta=0.999):
    """Cui va boshq. (2019) samarali namunalar soni bo'yicha sinf vaznlari: w_c ∝ (1-β)/(1-β^{n_c})."""
    counts = torch.as_tensor(counts, dtype=torch.float32).clamp_min(1)
    eff = (1 - torch.pow(beta, counts)) / (1 - beta)
    w = 1.0 / eff
    return w / w.sum() * len(counts)


class AdaptiveFocalCB(nn.Module):
    """Tasniflash uchun adaptiv yo'qotish: sinf-muvozanatli (CB) vaznli fokal yo'qotish.
    Vaznlar har epoxada joriy o'qitish to'plamidagi sinf chastotalari bo'yicha yangilanadi
    (update_counts), γ esa validatsiya F1 ga qarab moslashadi (adapt_gamma)."""

    def __init__(self, n_classes=2, gamma=2.0, beta=0.999):
        super().__init__()
        self.beta, self.gamma = beta, gamma
        self.register_buffer("w", torch.ones(n_classes))

    def update_counts(self, counts):
        self.w = class_balanced_weights(counts, self.beta).to(self.w.device)

    def adapt_gamma(self, minority_recall, target=0.8, lo=0.5, hi=4.0):
        # ozchilik sinf sezgirligi past bo'lsa, qiyin misollarga e'tibor oshiriladi
        self.gamma = float(min(hi, max(lo, self.gamma * (1.1 if minority_recall < target else 0.95))))

    def forward(self, logits, target):
        logp = F.log_softmax(logits.float(), 1)
        logpt = logp.gather(1, target.long().unsqueeze(1)).squeeze(1)
        pt = logpt.exp()
        return (-(self.w[target.long()]) * (1 - pt).clamp_min(1e-6) ** self.gamma * logpt).mean()   # γ<1 da p=1 → cheksiz hosila


def build_seg_loss(name: str, ignore_index=None, **kw) -> nn.Module:
    name = name.lower()
    if name == "dice":
        return SoftDiceLoss(ignore_index=ignore_index)
    if name == "dicece":
        return DiceCELoss(ignore_index=ignore_index)
    if name == "focal":
        return FocalLoss(ignore_index=ignore_index, **kw)
    if name == "tversky":
        return TverskyLoss(ignore_index=ignore_index, **kw)
    if name == "focal_tversky":
        return TverskyLoss(gamma=0.75, ignore_index=ignore_index, **kw)
    if name == "ell":
        return ExpLogLoss(ignore_index=ignore_index, **kw)
    if name == "unified_focal":
        return UnifiedFocalLoss(ignore_index=ignore_index, **kw)
    if name == "adaptive":
        return AdaptiveCompoundLoss({
            "dice": SoftDiceLoss(ignore_index=ignore_index, squared=False),
            "focal": FocalLoss(gamma=2.0, ignore_index=ignore_index),
            "tversky": TverskyLoss(ignore_index=ignore_index),
        })
    raise ValueError(f"Noma'lum yo'qotish: {name}")
