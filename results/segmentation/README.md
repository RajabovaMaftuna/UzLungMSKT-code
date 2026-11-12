# Segmentation models (manuscript 5) — reproducible measurements

| File | How it was produced |
|---|---|
| `complexity.json` | `research/segmentation/profile_models.py` on the saved checkpoints (NVIDIA GeForce RTX 5060 Laptop, 8 GB; torch 2.14): parameters, forward FLOPs at 1×1×96³ (torch FlopCounterMode), inference time (bfloat16, median of 30), training-step time and peak GPU memory (bfloat16, AdamW, batch from the run configuration) |
| `local_test_summary.json`, `local_test_per_case.csv` | `python -m uzlungct.evaluate --split test` on the local test set (4 examinations, 3 tumour volumes; label 3 "uncertain" and lymph nodes masked); Dice, HD95, lesion-level sensitivity ("at least one common voxel"), FP components per examination. Case names: patient code + examination order (no dates) |
| `../seg_training/*/summary.json, config.yaml` | Training summaries and configurations of the saved checkpoints (MSD pre-training, local fine-tuning) |

n = 3 tumour volumes: all local results are descriptive; pairwise tests are not meaningful (n < 5).

| `loss_ablation.json`, `loss_ablation_eval_summary.json` | Loss ablation retrained on 2026-11-12/13: dynamic R²U3D initialised from the MSD checkpoint, five losses × seeds 42, 7, 2026 (`python -m uzlungct.train_seg`), each run evaluated on the local validation set (`uzlungct.evaluate --split val`) and aggregated with `research/segmentation/aggregate_ablation.py` (mean ± SD over seeds) |
| `../seg_training/abl_retrained/*` | Training summaries and configurations of the 15 retrained ablation runs |
