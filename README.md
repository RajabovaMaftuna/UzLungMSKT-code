# UzLungMSKT v1.0.1 — lung-lesion detection platform for chest CT (SenGuard-3D 1.0.1)

> **The platform detects lung lesions; whether they are malignant is assessed by the physician.**
> Research software. It is **not** a medical device and is **not** cleared for clinical use.

This repository contains the source code, frozen parameters and evaluation results that accompany the PhD
dissertation of M.R. Rajabova (Tashkent University of Information Technologies named after Muhammad al-Khwarizmi)
and the related journal manuscripts on SenGuard-3D and the «UzLungMSKT» software.

## Contents

| Folder / file | Content |
|---|---|
| `uzlungct/` | Platform source: web server (FastAPI), authentication (scrypt, sessions, CSRF), patient registry (AES-256-GCM), reports (uz/ru/en, PDF), training and evaluation code (`train_seg.py`, `train_cls.py`, `ssl.py`, `metrics.py`, `losses.py`, `models/`) |
| `n8_runner.py`, `n8fusion.py`, `tsfusion.py` | SenGuard-3D inference: union of two nnU-Net v2 models, TotalSegmentator `lung_nodules` and a MONAI 3D RetinaNet (internal identifier N8) |
| `research/ltt/` | Learn-then-Test certification (`s10_eval.py`, `s7a_def_T.py`) and the reproducible certificate-violation simulation (`sim_ltt_v2.py`, seed 20261112, with its output `sim_ltt_v2.json`) |
| `results/` | Frozen parameters, NLSTseg patient-level split (`splits_v9_nlst.json`), per-patient evaluations on NLSTseg V/C/X and FDG-PET-CT-Lesions C, certificate result (`S10_natija.json`), CPU–GPU equivalence (`31_natija.json`), component hash registry (`senguard3d_registry.json`) |
| `results/local_anonymised/` | Anonymised aggregate tables of the local clinical dataset: volumes and quality control, radiologist-confirmed reference lesions, SenGuard-3D local audit |
| `docs/` | Model card (`22_SenGuard3D_model_kartasi.md`), final scientific report, certification method notes, CPU–GPU and clean-install test reports (in Uzbek) |
| `packaging/` | Windows build, installer and release-test scripts |
| `tools/gpu_opt/` | GPU/CPU adaptation and equivalence scripts |

Model weights, Python runtime and datasets are **not** included. The SHA-256 hashes of all frozen components are listed
in `results/senguard3d_registry.json`; the Windows installer (build 6) is distributed separately.

## Main results (patient level)

| Set | n | Patients with ≥ 1 missed lung lesion | Statement |
|---|---|---|---|
| NLSTseg C ∪ X (screening low-dose CT) | 236 | 3 (1.3 %), 95 % upper bound 3.25 % | sensitivity ≥ 90 % with 95 % confidence (Learn then Test, p = 5.3·10⁻⁸) |
| NLSTseg, S2 subgroup, ≥ 95 % claim | 135 | 3 | not certified (p = 0.090) |
| FDG-PET-CT-Lesions, CT part (C) | 81 | 27 (33.3 %), upper bound 42.9 % | no certificate |
| Local clinical CT | 6 + 3 | 0 | descriptive only (n < 59) |

The certificate holds only for the screening-CT domain (NLSTseg). There is no certificate for PET/CT or for local data.

## Data

* NLSTseg — Chen et al., 2025, *Scientific Data* 12, 1475, https://doi.org/10.1038/s41597-025-05742-x; data: https://doi.org/10.5281/zenodo.14838349 (CC BY 4.0).
* FDG-PET-CT-Lesions — Gatidis et al., 2022, *Scientific Data* 9, 601.
* Local clinical images (Republican Specialised Scientific and Practical Medical Centre of Oncology and Radiology; ethics committee protocol No. 58 of 26 May 2025) are confidential; the images are not part of this repository. Anonymised aggregate results (no images, names, dates or UIDs) are in `results/local_anonymised/`.

## Requirements

Windows 10/11, Python 3.11–3.13, PyTorch (CUDA recommended; CPU mode is supported but slow), 16 GB RAM, ≥ 30 GB free disk.
Main Python packages: torch, numpy, scipy, SimpleITK, fastapi, cryptography, fpdf2, pyyaml, nnunetv2, TotalSegmentator, monai.

## Citation

See `CITATION.cff`. Please cite the dissertation and the corresponding article when using this code.

## Licence

Apache License 2.0 (`LICENSE`). Third-party components and their licences are listed in `NOTICE`.

---

### Qisqacha (o‘zbekcha)

Ushbu omborda «UzLungMSKT» platformasi va SenGuard-3D ansamblining manba kodi, muzlatilgan parametrlari va ochiq
ma’lumotlar to‘plamlaridagi baholash natijalari joylashgan. Platforma o‘pka o‘choqlarini aniqlaydi; ularning malign
ekanini shifokor baholaydi. Statistik kafolat faqat skrining KT domenida (NLSTseg) o‘rinli; mahalliy bemor
ma’lumotlari omborga kiritilmagan.
