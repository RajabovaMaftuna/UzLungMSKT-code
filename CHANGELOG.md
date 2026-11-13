# Changelog

## v1.0.2 (2026-11-13)
- Single-slice inputs (one DICOM slice, one image or one PDF page) are rejected before inference with a clear message (`err.single_slice`, uz/en/ru) instead of an nnU-Net crash ("axes don't match array" reported as "Background workers died"). Volumes with 2 or more slices are analysed; volumes with fewer than 16 slices get the `too_few_slices` warning (now also for NIfTI/MHA/NRRD).
- Result files that back the manuscripts: classifier metrics, segmentation complexity and local re-evaluation, retrained loss ablation, per-format timing, anonymised local tables (including the platform test on all 30 local CT volumes) and the patient-code merge log.
- The SenGuard-3D decision function (n8_runner.py, n8fusion.py, frozen thresholds) is unchanged from v1.0.1.

## v1.0.1 (2026-11-04, build 6)
- SenGuard-3D 1.0.1 with GPU/CPU adaptation; release bot 9/9, 23 automated tests, clean installation 8/8.
