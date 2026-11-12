# SenGuard-3D (ichki N8) ko'chma quvuri, 1.0.1 (apparatga moslashuv; hisob-kitob 1.0 bilan bir xil). Barcha modellar ./models/senguard3d ichida; internet ishlatilmaydi; platformaning o'z python'i bilan ishlaydi.
# Muzlatilgan qoida (frozen_nomzod_v18.json): M2 (nnU-Net, 5 fold, TTA yo'q, p>=0.05) ∪ K1 (nnU-Net, 5 fold) ∪ TotalSegmentator lung_nodules; RetinaNet qutilari ball>=0.9.
# Ishlatish: n8_runner.py <ct.nii.gz> <out_dir>  ->  n8_mask.nii.gz, n8_src.nii.gz, n8_prob.nii.gz, n8_boxes.json
import json, os, sys, shutil
# Ikkinchi himoya: o'rnatma tashqarisidagi site-packages (masalan %APPDATA%\Python\Python313) yo'ldan olib tashlanadi
sys.path = [p for p in sys.path if "site-packages" not in p.lower() or os.path.abspath(p).lower().startswith(os.path.abspath(sys.prefix).lower())]
from pathlib import Path
ROOT = Path(__file__).resolve().parent; MD = ROOT / "models" / "senguard3d"
os.environ["TOTALSEG_HOME_DIR"] = str(MD / "totalseg")          # TotalSegmentator vaznlari va sozlamasi paket ichida (statistika yuborilmaydi)
for k in ("nnUNet_raw", "nnUNet_preprocessed", "nnUNet_results"):
    os.environ.setdefault(k, str(ROOT / "workspace" / "cache"))
import numpy as np, nibabel as nib, torch
import torch.nn.functional as F
TH_DET, TH_P = 0.9, 0.05
SP = (0.703125, 0.703125, 1.25)


# ---- 1.0.1: apparatga moslashuv (natijani o'zgartirmaydi; faqat qurilma, oqimlar va xotira boshqaruvi) ----
import gc, platform


def _free_gb():
    try:
        f, t = torch.cuda.mem_get_info(); return f / 2**30, t / 2**30
    except Exception:
        return 0.0, 0.0


def _ram_gb():
    try:
        import ctypes
        class MS(ctypes.Structure):
            _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                        ("a", ctypes.c_ulonglong), ("b", ctypes.c_ulonglong), ("c", ctypes.c_ulonglong), ("d", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong)]
        m = MS(); m.l = ctypes.sizeof(MS); ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)); return m.total / 2**30
    except Exception:
        return 8.0


def hw_plan():
    """Har qanday kompyuter: NVIDIA (CUDA) bo'lsa va bo'sh videoxotira yetarli bo'lsa — GPU; AMD/Intel/GPU yo'q yoki
    UZLUNGCT_FORCE_CPU=1 bo'lsa — protsessor. Oqimlar soni yadrolar va operativ xotiraga qarab."""
    cpu = os.cpu_count() or 2; ram = _ram_gb()
    use_gpu = os.environ.get("UZLUNGCT_FORCE_CPU") != "1" and torch.cuda.is_available()
    free, total = _free_gb() if use_gpu else (0.0, 0.0)
    if use_gpu and free < 2.0:                       # juda kam bo'sh videoxotira (boshqa dastur band qilgan) — protsessor
        use_gpu = False
    procs = 1 if ram < 12 or cpu <= 4 else 2
    plan = {"gpu": use_gpu, "name": torch.cuda.get_device_name(0) if use_gpu else platform.processor() or "CPU",
            "vram_free_gb": round(free, 1), "vram_total_gb": round(total, 1), "ram_gb": round(ram, 1), "cpu": cpu,
            "on_device": use_gpu and free >= 6.0,       # nnU-Net natijalarni videoxotirada yig'adimi (aks holda RAM da)
            "procs": procs}
    if not use_gpu:
        torch.set_num_threads(max(1, cpu - 1))
    return plan


PLAN = None


def _cleanup():
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def _oom(e):
    return isinstance(e, torch.cuda.OutOfMemoryError) or "out of memory" in str(e).lower()


def nnunet(model_dir, inp, out, probs):
    from nnunetv2.inference.predict_from_raw_data import nnUNetPredictor
    tries = [(PLAN["gpu"], PLAN["on_device"])] + ([(True, False)] if PLAN["gpu"] and PLAN["on_device"] else []) + ([(False, False)] if PLAN["gpu"] else [])
    for k, (g, od) in enumerate(tries):
        try:
            p = nnUNetPredictor(tile_step_size=0.5, use_gaussian=True, use_mirroring=False, perform_everything_on_device=od,
                                device=torch.device("cuda" if g else "cpu"), verbose=False, verbose_preprocessing=False, allow_tqdm=False)
            p.initialize_from_trained_model_folder(str(model_dir), use_folds=(0, 1, 2, 3, 4), checkpoint_name="checkpoint_final.pth")
            p.predict_from_files(str(inp), str(out), save_probabilities=probs, overwrite=True, num_processes_preprocessing=PLAN["procs"], num_processes_segmentation_export=PLAN["procs"])
            del p; _cleanup(); return
        except Exception as e:
            p = None; _cleanup()
            if not _oom(e) or k == len(tries) - 1:
                raise
            print(f"[hw] videoxotira yetmadi ({Path(model_dir).name}), keyingi rejim: {tries[k + 1]}", flush=True)


def detector(dev=None):
    from monai.networks.nets.resnet import resnet50
    from monai.apps.detection.networks.retinanet_network import resnet_fpn_feature_extractor, RetinaNet
    from monai.apps.detection.networks.retinanet_detector import RetinaNetDetector
    from monai.apps.detection.utils.anchor_utils import AnchorGeneratorWithAnchorShape
    anc = AnchorGeneratorWithAnchorShape(feature_map_scales=[1, 2, 4], base_anchor_shapes=[[6, 8, 4], [8, 6, 5], [10, 10, 6]])
    bb = resnet50(spatial_dims=3, n_input_channels=1, conv1_t_stride=[2, 2, 1], conv1_t_size=[7, 7, 7])
    net = RetinaNet(spatial_dims=3, num_classes=1, num_anchors=3, feature_extractor=resnet_fpn_feature_extractor(bb, 3, False, [1, 2], None), size_divisible=[16, 16, 8], use_list_output=False)
    sd = torch.load(MD / "retinanet" / "models" / "model.pt", map_location="cpu", weights_only=False); net.load_state_dict(sd if "model" not in sd else sd["model"])
    det = RetinaNetDetector(network=net, anchor_generator=anc, debug=False, spatial_dims=3, num_classes=1, size_divisible=[16, 16, 8])
    det.set_target_keys(box_key="box", label_key="label")
    det.set_box_selector_parameters(score_thresh=0.02, topk_candidates_per_level=1000, nms_thresh=0.22, detections_per_img=300)
    det.set_sliding_window_inferer(roi_size=[192, 192, 80], overlap=0.25, sw_batch_size=1, mode="constant", device="cpu")
    return det.to(dev or ("cuda" if torch.cuda.is_available() else "cpu")).eval()


def main():
    ct, out = sys.argv[1], Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
    from totalsegmentator.python_api import totalsegmentator
    global PLAN
    PLAN = hw_plan(); print("[hw]", json.dumps(PLAN, ensure_ascii=False), flush=True)
    try:
        tsl = np.asarray(totalsegmentator(ct, None, task="lung_nodules", quiet=True, device="gpu" if PLAN["gpu"] else "cpu").dataobj)
    except Exception as e:
        if not (PLAN["gpu"] and _oom(e)):
            raise
        _cleanup(); print("[hw] TotalSegmentator protsessorda", flush=True)
        tsl = np.asarray(totalsegmentator(ct, None, task="lung_nodules", quiet=True, device="cpu").dataobj)
    _cleanup()
    im = nib.load(ct); z = im.header.get_zooms()[:3]; assert tsl.shape == im.shape[:3]
    lung = tsl > 0; pred = tsl == 2; src = (tsl == 2).astype(np.uint8) * 4; prob = np.zeros(lung.shape, np.float32)
    if lung.any():
        w = np.where(lung); sl = tuple(slice(max(0, int(x.min() - 20 / s)), min(n, int(x.max() + 20 / s) + 1)) for x, s, n in zip(w, z, lung.shape))
    else:
        sl = tuple(slice(0, n) for n in lung.shape)
    i1 = out / "in"; o1 = out / "m2"; o2 = out / "k1"; i1.mkdir(exist_ok=True)
    nib.save(im.slicer[sl], str(i1 / "c_0000.nii.gz"))
    nnunet(MD / "M2", i1, o1, True); nnunet(MD / "K1", i1, o2, False)
    pm = np.load(o1 / "c.npz")["probabilities"][1].transpose(2, 1, 0); mm = pm >= TH_P; kk = np.asarray(nib.load(str(o2 / "c.nii.gz")).dataobj) > 0
    pred[sl] |= mm; pred[sl] |= kk; src[sl] |= mm.astype(np.uint8) | (kk.astype(np.uint8) * 2); prob[sl] = pm
    for n, a in (("n8_mask", pred.astype(np.uint8)), ("n8_src", src), ("n8_prob", prob)):
        nib.save(nib.Nifti1Image(a, im.affine), str(out / f"{n}.nii.gz"))
    c = nib.as_closest_canonical(im); zz = c.header.get_zooms()[:3]; a = np.asarray(c.dataobj).astype(np.float32)
    size = [max(8, int(round(n * q / s))) for n, q, s in zip(a.shape, zz, SP)]
    x = F.interpolate(torch.from_numpy(a)[None, None], size=size, mode="trilinear", align_corners=False)[0]
    fac = [n / m for n, m in zip(c.shape[:3], x.shape[1:])]; dev = "cuda" if torch.cuda.is_available() else "cpu"
    dev = "cuda" if PLAN["gpu"] else "cpu"
    x = ((x.clamp(-1024, 300) + 1024) / 1324)
    for dv in ([dev, "cpu"] if dev == "cuda" else ["cpu"]):
        try:
            det = detector(dv); xx = x.to(dv)
            with torch.no_grad(), torch.autocast(dv, enabled=dv == "cuda"):
                o = det([xx], use_inferer=True)[0]
            break
        except Exception as e:
            det = xx = None; _cleanup()
            if dv == "cpu" or not _oom(e):
                raise
            print("[hw] detektor protsessorda", flush=True)
    del det, xx; _cleanup()
    B = []
    for b, s in zip(o["box"].float().cpu().numpy(), o["label_scores"].float().cpu().numpy()):
        if s >= TH_DET:
            lo = nib.affines.apply_affine(c.affine, [b[i] * fac[i] for i in range(3)]); hi = nib.affines.apply_affine(c.affine, [b[i + 3] * fac[i] for i in range(3)])
            B.append({"lo": lo.tolist(), "hi": hi.tolist(), "score": float(s)})
    json.dump(B, open(out / "n8_boxes.json", "w"))
    for d in (i1, o1, o2):
        shutil.rmtree(d, ignore_errors=True)
    print("N8 TUGADI", int(pred.sum()), len(B))


if __name__ == "__main__":
    main()
