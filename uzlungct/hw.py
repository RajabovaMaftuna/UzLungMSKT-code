"""Apparatga moslashish: qurilma, aralash aniqlik, patch/paket hajmi va DataLoader oqimlari.

Maqsadli kompyuter: NVIDIA RTX 4060 Laptop (8 GB), 24 oqimli CPU, 16 GB RAM, Windows 10.
Boshqa kompyuterda ham avtomatik moslashadi (CPU, Kaggle T4, Colab).
"""
from __future__ import annotations

import os
import platform
import torch


def device():
    # UZLUNGCT_FORCE_CPU=1: videokarta mos emas yoki sinov yadrosi xato berdi (sysinfo.torch_state) — tahlil protsessorda
    if os.environ.get("UZLUNGCT_FORCE_CPU") != "1" and torch.cuda.is_available():
        return torch.device("cuda")
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def vram_gb():
    if device().type != "cuda":
        return 0.0
    return torch.cuda.get_device_properties(0).total_memory / 2**30


def profile(task="seg", model="r2u3d_dynamic"):
    """Videokarta xotirasiga qarab patch va paket hajmini tanlaydi."""
    g = vram_gb()
    heavy = model in ("unetr", "swin_unetr", "r2u3d_static")
    if task == "cls":
        return {"patch": [48, 48, 48], "batch": 64 if g >= 7 else (32 if g > 0 else 8)}
    if g >= 14:
        p, b = (128, 128, 128), 2
    elif g >= 7:                       # RTX 4060 8 GB
        p, b = ((96, 96, 96), 1) if heavy else ((96, 96, 96), 2)
    elif g > 0:
        p, b = (64, 64, 64), 2
    else:                              # faqat CPU — tekshiruv uchun
        p, b = (48, 48, 48), 1
    return {"patch": list(p), "batch": b}


def num_workers():
    n = os.cpu_count() or 2
    if platform.system() == "Windows":
        return min(6, max(0, n // 4))   # Windows'da spawn qimmat — kam, ammo doimiy oqimlar
    return min(8, max(0, n - 1))


def amp_dtype():
    """bf16 faqat apparat qo'llasa (Ampere+, compute capability >= 8): is_bf16_supported() T4 (sm75) da
    emulyatsiya bilan ham True qaytaradi va o'qitish ~bir necha baravar sekinlashadi. Aks holda fp16 (+ GradScaler)."""
    if device().type == "cuda":
        return torch.bfloat16 if torch.cuda.get_device_capability(0)[0] >= 8 else torch.float16
    return None


def setup_torch(seed=42, deterministic=False):
    import random
    import numpy as np
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.benchmark = not deterministic
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
    torch.set_num_threads(max(1, (os.cpu_count() or 2) // 2))


def summary():
    s = {"torch": torch.__version__, "device": str(device()), "cuda": torch.cuda.is_available(),
         "cpu_threads": os.cpu_count(), "os": platform.platform()}
    if torch.cuda.is_available():
        s["gpu"] = torch.cuda.get_device_name(0); s["vram_gb"] = round(vram_gb(), 1)
    return s


if __name__ == "__main__":
    import json
    print(json.dumps({**summary(), "seg_profile": profile(), "workers": num_workers()}, indent=1))
