# 5-maqola, 4.4-bo'lim: yo'qotish funksiyalari ablatsiyasini jamlash (2026-11-12).
# Kirish: `python -m uzlungct.evaluate --split val` chiqishi (summary.json); har bir yugurish nomi <yo'qotish>_s<seed>.
# Har bir yugurish uchun o'simtali validatsiya hajmlari bo'yicha o'rtacha Dice va HD95 olinadi, so'ng 3 seed bo'yicha
# o'rtacha va standart og'ish (ddof = 1) hisoblanadi.
# Ishlatish: python aggregate_ablation.py <evaluate summary.json> <loss_ablation.json>
import json, statistics, sys
S = json.load(open(sys.argv[1]))['models']
runs, out = {}, {}
for name, m in S.items():
    loss, seed = name.rsplit('_s', 1)
    d = m['detail']
    runs.setdefault(loss, []).append({'seed': int(seed), 'n_tumour_volumes': d['n'], 'dice_mean': d['dice_mean'], 'hd95_mean': d['hd95_mean'],
                                      'lesion_sensitivity': m['lesion_sensitivity'], 'fp_per_scan': m['fp_per_scan']})
for loss, rs in runs.items():
    dm = [r['dice_mean'] for r in rs]; hm = [r['hd95_mean'] for r in rs if r['hd95_mean'] is not None]
    out[loss] = {'n_seeds': len(rs), 'dice_mean': statistics.mean(dm), 'dice_sd': statistics.stdev(dm) if len(dm) > 1 else 0.0,
                 'hd95_mean': statistics.mean(hm) if hm else None, 'hd95_sd': statistics.stdev(hm) if len(hm) > 1 else 0.0,
                 'runs': sorted(rs, key=lambda r: r['seed'])}
json.dump({'model': 'r2u3d_dynamic', 'init': 'MSD Lung checkpoint (seg_training/seg_M3_r2u3d_dynamic_msd)', 'split': 'val',
           'seeds': sorted({r['seed'] for rs in runs.values() for r in rs}), 'losses': out}, open(sys.argv[2], 'w'), indent=1)
for k, v in out.items():
    print(k, v['n_seeds'], round(v['dice_mean'], 3), round(v['dice_sd'], 3), v['hd95_mean'] and round(v['hd95_mean'], 1))
