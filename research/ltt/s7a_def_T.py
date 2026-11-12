# v15 2-bo'lim + 3-bo'lim (faqat T, R23): to'ldirilgan o'pka maskasi bilan o'choq ta'rifi; N2/N5 bemor-o'tkazish ikkala ta'rifda; M3 qiyin bemorlar ro'yxati.
import json, os, glob
import numpy as np, nibabel as nib
from scipy import ndimage as nd
from multiprocessing import Pool

R = r"D:\nnUNet_m2\results\Dataset107_LungMix\nnUNetTrainer_500epochs__nnUNetPlans__3d_fullres"
S6A = r"C:\ZG\s6a_local"; NII = r"D:\ext\nlstseg\nii"; T_DET = 0.05
ST = np.ones((3, 3, 3))


def found_list(pred, lab, vals):
    cc, n = nd.label(pred, structure=ST)
    cents = [tuple(int(round(c)) for c in x) for x in nd.center_of_mass(pred, cc, range(1, n + 1))] if n else []
    return [bool((pred & (lab == v)).sum() / (lab == v).sum() >= 0.10 or any(lab[c] == v for c in cents)) for v in vals]


def filled_lung(lung, zooms):
    f = np.zeros_like(lung)
    for z in range(lung.shape[2]):
        f[:, :, z] = nd.binary_fill_holes(lung[:, :, z])
    r = [max(1, int(round(2.5 / s))) for s in zooms]  # 5 mm diametrli yopish
    return nd.binary_closing(f, structure=np.ones([2 * x + 1 for x in r]))


def one(a):
    f, p = a
    pid = os.path.basename(p)[5:-4]
    li = nib.load(os.path.join(NII, pid, f"{pid}_tumor.nii.gz")); lab = np.asarray(li.dataobj).astype(np.int16)
    p1 = np.load(p)["probabilities"][1].transpose(2, 1, 0); assert p1.shape == lab.shape
    meta = json.load(open(os.path.join(S6A, pid, "done.json"))); sl = tuple(slice(a_, b) for a_, b in zip(meta["crop_lo"], meta["crop_hi"]))
    tsl = np.asarray(nib.load(os.path.join(S6A, pid, "ts_lungnod.nii.gz")).dataobj)
    ts = np.zeros(lab.shape, bool); k1 = np.zeros(lab.shape, bool); lung = np.zeros(lab.shape, bool)
    ts[sl] = tsl == 2; lung[sl] = tsl > 0
    k1[sl] = np.asarray(nib.load(os.path.join(S6A, pid, "k1_seg.nii.gz")).dataobj) > 0
    fl = filled_lung(lung | ts, li.header.get_zooms()[:3])
    vals = [v for v in np.unique(lab) if v]
    m2 = p1 >= T_DET
    fm2 = found_list(m2, lab, vals)
    return {"pid": pid, "fold": f,
            "lung_frac": [round(float(fl[lab == v].mean()), 3) for v in vals],
            "M2": fm2, "N2": found_list(m2 | ts, lab, vals), "N5": found_list(m2 | ts | k1, lab, vals)}


def main():
    jobs = [(f, p) for f in range(5) for p in sorted(glob.glob(fr"{R}\fold_{f}\validation\nlst_*.npz"))]
    T = set(json.load(open(r"C:\ZG\splits_v9_nlst.json"))["splits"]["T"])
    assert len(jobs) == 296 and all(os.path.basename(p)[5:-4] in T for _, p in jobs)
    with Pool(4) as pool:
        rows = pool.map(one, jobs, chunksize=4)
    json.dump(rows, open(r"C:\ZG\s7a_def_T.json", "w"))
    from scipy.stats import beta
    for name in ("N2", "N5"):
        for dname, keep in (("BARCHA label", lambda fr: True), ("o'pka >=50% (v15)", lambda fr: fr >= 0.5)):
            pts = [[h for h, fr in zip(r[name], r["lung_frac"]) if keep(fr)] for r in rows]
            pts = [x for x in pts if x]; n = len(pts); k = sum(not all(x) for x in pts)
            lo = beta.ppf(.025, k, n - k + 1) if k else 0; hi = beta.ppf(.975, k + 1, n - k)
            print(f"{name} | {dname:18s} | bemor {n} | o'tkazish {k} ({100*k/n:.1f}%, CI {100*lo:.1f}-{100*hi:.1f})")
    excl = sum(fr < 0.5 for r in rows for fr in r["lung_frac"]); tot = sum(len(r["lung_frac"]) for r in rows)
    print(f"v15 ta'rifi bilan chiqarilgan o'choqlar: {excl}/{tot}")
    hard = sorted({r["pid"] for r in rows if not all(r["M2"])})
    json.dump(hard, open(r"C:\ZG\m3_hard_T.json", "w"))
    print("M3 qiyin bemorlar (M2 t=0.05 o'tkazgan):", len(hard))


if __name__ == "__main__":
    main()
