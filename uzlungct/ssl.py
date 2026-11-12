"""O'z-o'zini nazorat qiluvchi oldindan o'qitish (SimCLR, Chen 2020) — 3D variant (4.1-§).

Belgilanmagan MSKT patchlaridan har biri uchun ikki tasodifiy augmentatsiya olinadi;
kodlovchi ularning proyeksiyalarini yaqinlashtirib, boshqa patchlarnikidan uzoqlashtiradi
(NT-Xent yo'qotishi).
"""
import torch
import torch.nn.functional as F


def augment3d(x, gen=None):
    """x: (B,1,D,H,W) [0..1]. Tasodifiy aylantirish/aks ettirish, kesib kattalashtirish, intensivlik, shovqin."""
    B = x.shape[0]
    out = []
    for i in range(B):
        v = x[i]
        for ax in (1, 2, 3):
            if torch.rand(1, generator=gen) < 0.5:
                v = v.flip(ax)
        k = int(torch.randint(0, 4, (1,), generator=gen))
        v = torch.rot90(v, k, dims=(2, 3))
        # tasodifiy kesish va qayta o'lchash
        D, H, W = v.shape[1:]
        s = float(0.6 + 0.4 * torch.rand(1, generator=gen))
        d, h, w = max(4, int(D * s)), max(4, int(H * s)), max(4, int(W * s))
        z0 = int(torch.randint(0, D - d + 1, (1,), generator=gen)); y0 = int(torch.randint(0, H - h + 1, (1,), generator=gen)); x0 = int(torch.randint(0, W - w + 1, (1,), generator=gen))
        v = F.interpolate(v[None, :, z0:z0 + d, y0:y0 + h, x0:x0 + w], size=(D, H, W), mode="trilinear", align_corners=False)[0]
        # intensivlik: kontrast/yorqinlik, gamma, shovqin
        a = float(0.8 + 0.4 * torch.rand(1, generator=gen)); b = float(-0.1 + 0.2 * torch.rand(1, generator=gen))
        v = (v * a + b).clamp(0, 1)
        g = float(0.7 + 0.6 * torch.rand(1, generator=gen))
        v = v.clamp_min(1e-6) ** g
        v = v + 0.03 * torch.randn(v.shape, generator=gen, device=v.device if gen is None else "cpu").to(v.device)
        out.append(v)
    return torch.stack(out)


def nt_xent(z1, z2, tau=0.1):
    """Normallashtirilgan harorat-masshtabli kross-entropiya. Har doim fp32 da (autocast o'chiriladi):
    fp16 da -1e9 niqobi sig'maydi va o'xshashlik matritsasi aniqligi pasayadi."""
    with torch.autocast(z1.device.type, enabled=False):
        z = F.normalize(torch.cat([z1, z2]).float(), dim=1)
        n = z1.shape[0]
        sim = z @ z.t() / tau
        sim.fill_diagonal_(-1e9)
        targets = torch.cat([torch.arange(n, 2 * n), torch.arange(0, n)]).to(z.device)
        return F.cross_entropy(sim, targets)
