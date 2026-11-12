# v18.1 baholash: s10_eval.py <to'plam>. N5, N8; v15 / barcha / S2; FP/bemor. Natija inf_<S>\eval.json. Mezon T bilan bir xil (R7; detektor: e2_eval).
import json, os, sys, numpy as np, nibabel as nib, torch
import torch.nn.functional as F
from scipy import ndimage as nd
from scipy.stats import beta
sys.path.insert(0, r"C:\ZG")
from guard import ids
from s7a_def_T import found_list, filled_lung, ST
S = sys.argv[1]; W = rf"C:\ZG\inf_{S}"; NII = r"D:\ext\nlstseg\nii"; S6A = r"C:\ZG\s6a_local"; TH = 0.9
rows = []
for p in [str(x) for x in ids(S)]:
    li = nib.load(os.path.join(NII, p, f"{p}_tumor.nii.gz")); lab = np.asarray(li.dataobj).astype(np.int16); ct = np.asarray(nib.load(os.path.join(NII, p, f"{p}_CT.nii.gz")).dataobj)
    meta = json.load(open(os.path.join(S6A, p, "done.json"))); sl = tuple(slice(a, b) for a, b in zip(meta["crop_lo"], meta["crop_hi"]))
    tsl = np.asarray(nib.load(os.path.join(S6A, p, "ts_lungnod.nii.gz")).dataobj)
    ts = np.zeros(lab.shape, bool); k1 = ts.copy(); lung = ts.copy(); m2 = ts.copy()
    ts[sl] = tsl == 2; lung[sl] = tsl > 0; k1[sl] = np.asarray(nib.load(os.path.join(S6A, p, "k1_seg.nii.gz")).dataobj) > 0
    m2[sl] = np.load(os.path.join(W, "m2", p + ".npz"))["m"]
    fl = filled_lung(lung | ts, li.header.get_zooms()[:3]); vals = [v for v in np.unique(lab) if v]
    pred = m2 | ts | k1; n5 = found_list(pred, lab, vals)
    cc, n = nd.label(pred, structure=ST); hit = set(np.unique(cc[lab > 0])) - {0}
    fp = sum(1 for i, c in enumerate(nd.center_of_mass(pred, cc, range(1, n + 1)), 1) if i not in hit and lung[tuple(int(round(x)) for x in c)]) if n else 0
    d = json.load(open(os.path.join(W, "det", p + ".json")))
    cl = nib.as_closest_canonical(li); L = F.interpolate(torch.from_numpy(np.asarray(cl.dataobj).astype(np.float32))[None, None], size=d["shape"], mode="nearest")[0, 0].numpy().astype(np.int16)
    bh = [False] * len(vals); bfp = 0
    for b, s in zip(d["box"], d["score"]):
        if s < TH:
            continue
        x0, y0, z0, x1, y1, z1 = [int(round(v)) for v in b]; bs = (slice(max(x0, 0), x1 + 1), slice(max(y0, 0), y1 + 1), slice(max(z0, 0), z1 + 1))
        c = tuple(min(int((a + e) / 2), m - 1) for a, e, m in zip((x0, y0, z0), (x1, y1, z1), L.shape)); h = False
        for i, v in enumerate(vals):
            g = (L == v).sum()
            if g and ((L[bs] == v).sum() / g >= 0.10 or L[c] == v):
                bh[i] = True; h = True
        bfp += not h
    vox = float(np.prod(li.header.get_zooms()[:3]))
    les = [{"lung": float(fl[lab == v].mean()), "hu": float(np.median(ct[lab == v])), "vol": float((lab == v).sum() * vox), "N5": a, "N8": a or b} for v, a, b in zip(vals, n5, bh)]
    rows.append({"pid": p, "les": les, "fp5": fp, "fp8": fp + bfp})
json.dump(rows, open(W + r"\eval.json.part", "w")); os.replace(W + r"\eval.json.part", W + r"\eval.json")
D = {"v15": lambda l: l["lung"] >= .5, "barcha": lambda l: True, "S2": lambda l: l["lung"] >= .5 and l["hu"] >= -300 and l["vol"] >= 1000}
for k in ("N5", "N8"):
    print(k, "FP/bemor", round(np.mean([r["fp5" if k == "N5" else "fp8"] for r in rows]), 2))
    for nm, f in D.items():
        x = [[l[k] for l in r["les"] if f(l)] for r in rows]; x = [a for a in x if a]; n = len(x); m = sum(not all(a) for a in x)
        hi = beta.ppf(.975, m + 1, n - m); lo = beta.ppf(.025, m, n - m + 1) if m else 0
        print(f"  {nm}: {m}/{n} ({100*m/n:.1f}%, CI {100*lo:.1f}-{100*hi:.1f})")
print("BAHOLASH TUGADI", S)
