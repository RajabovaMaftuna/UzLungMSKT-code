# SenGuard-3D (ichki N8) ko'chma quvuri. Barcha modellar ./models/senguard3d ichida; internet ishlatilmaydi; platformaning o'z python'i bilan ishlaydi.
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


def nnunet(model_dir, inp, out, probs):
    from nnunetv2.inference.predict_from_raw_data import nnUNetPredictor
    p = nnUNetPredictor(tile_step_size=0.5, use_gaussian=True, use_mirroring=False, perform_everything_on_device=True,
                        device=torch.device("cuda" if torch.cuda.is_available() else "cpu"), verbose=False, verbose_preprocessing=False, allow_tqdm=False)
    p.initialize_from_trained_model_folder(str(model_dir), use_folds=(0, 1, 2, 3, 4), checkpoint_name="checkpoint_final.pth")
    p.predict_from_files(str(inp), str(out), save_probabilities=probs, overwrite=True, num_processes_preprocessing=2, num_processes_segmentation_export=2)


def detector():
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
    return det.to("cuda" if torch.cuda.is_available() else "cpu").eval()


def main():
    ct, out = sys.argv[1], Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
    from totalsegmentator.python_api import totalsegmentator
    tsl = np.asarray(totalsegmentator(ct, None, task="lung_nodules", quiet=True).dataobj)
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
    x = ((x.clamp(-1024, 300) + 1024) / 1324).to(dev); det = detector()
    with torch.no_grad(), torch.autocast(dev, enabled=dev == "cuda"):
        o = det([x], use_inferer=True)[0]
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
