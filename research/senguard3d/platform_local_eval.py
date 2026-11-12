# «UzLungMSKT» platformasida (analyze_dataset) bajarilgan mahalliy tahlillarni radiologlar tasdiqlagan etalon bilan solishtirish (2026-11-13).
# Kirish: platforma ish papkasidagi jobs/<id>/ (job.json, report.json, mask_1mm.nii.gz) va mahalliy to'plam (tumor_gt, lung_LR).
# Mezon sertifikat baholashi bilan bir xil: o'pka o'simtasi - o'simta komponentining >= 50 % i to'ldirilgan o'pkada; topilgan -
# platforma niqobi o'choqning >= 10 % ini qoplaydi yoki niqob komponenti markazi o'choq ichida.
# Har bir platforma o'chog'i (report.json) uchun: o'simta (1), boshqa belgilangan hudud (2 limfa tuguni / 3 noaniq) yoki
# hech qaysi belgiga tegmaydi (radiolog tasdiqlamagan topilma). Malignlikni shifokor baholaydi; tasniflagich ehtimoli faqat tavsifiy.
# Chiqish (sanasiz): <out>_exams.csv, <out>_lesions.csv. Ishlatish: python -E -s platform_local_eval.py <jobs papkasi> <Mahalliy_2024-2025> <out prefiks>
import csv, json, sys
from pathlib import Path
import numpy as np, SimpleITK as sitk
from scipy import ndimage as nd
sys.path.insert(0, r'C:\ZG\build_exe\stage')
from uzlungct.data.prepare import to_ras_1mm
from uzlungct.sio import read_image

JOBS, ROOT, OUT = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
ST = np.ones((3, 3, 3))
arr = lambda img: sitk.GetArrayFromImage(img)


def filled_lung(lung, zooms):
    f = np.zeros_like(lung)
    for z in range(lung.shape[0]):
        f[z] = nd.binary_fill_holes(lung[z])
    r = [max(1, int(round(2.5 / s))) for s in zooms]
    return nd.binary_closing(f, structure=np.ones([2 * x + 1 for x in r]))


vols = list(csv.DictReader(open(ROOT / 'metadata' / 'volumes.csv', encoding='utf-8-sig'), delimiter=';'))
vmap = {f"{v['patient']}_{v['study']}": v for v in vols}
order = {}
for p in sorted({v['patient'] for v in vols}):
    for i, s in enumerate(sorted(v['study'] for v in vols if v['patient'] == p), 1):
        order[f'{p}_{s}'] = f'E{i}'
ds = json.load(open(ROOT / 'dataset.json', encoding='utf-8'))
items = {f"{it['patient']}_{it['study']}": it for sp, its in ds['splits'].items() for it in its}
latest = {}
for jf in JOBS.glob('*/job.json'):
    j = json.load(open(jf, encoding='utf-8'))
    c = (j.get('params') or {}).get('case')
    if j.get('kind') == 'analyze' and c and j.get('status') == 'done' and (jf.parent / 'report.json').exists():
        if c not in latest or j['created'] > latest[c][0]['created']:
            latest[c] = (j, jf.parent)
ex_rows, les_rows = [], []
for c in sorted(latest, key=lambda k: (k.split('_')[0], order[k])):
    j, d = latest[c]; it = items[c]; v = vmap[c]
    rep = json.load(open(d / 'report.json', encoding='utf-8'))
    mimg = read_image(d / 'mask_1mm.nii.gz'); m = arr(mimg) > 0
    zooms = mimg.GetSpacing()[::-1]
    lung = arr(to_ras_1mm(read_image(ROOT / it['lung']), True)) > 0 if it.get('lung') else np.ones(m.shape, bool)
    gt = arr(to_ras_1mm(read_image(ROOT / it['lesion']), True)).astype(np.int16) if it.get('lesion') else np.zeros(m.shape, np.int16)
    assert lung.shape == m.shape == gt.shape, (c, lung.shape, m.shape, gt.shape)
    fl = filled_lung(lung, zooms)
    lab, nl = nd.label(gt == 1, structure=ST)
    vals = [k for k in range(1, nl + 1) if fl[lab == k].mean() >= 0.5]
    cc, n = nd.label(m, structure=ST)
    cents = [tuple(int(round(x)) for x in q) for q in nd.center_of_mass(m, cc, range(1, n + 1))] if n else []
    found = [bool((m & (lab == k)).sum() / (lab == k).sum() >= 0.10 or any(lab[q] == k for q in cents)) for k in vals]
    tp = oth = unc = 0
    for l in rep['lesions']:
        z, y, x = [int(round(t)) for t in l['centroid_zyx_vox']]
        comp = cc[z, y, x] if 0 <= z < m.shape[0] and 0 <= y < m.shape[1] and 0 <= x < m.shape[2] else 0
        reg = gt[cc == comp] if comp else gt[max(z - 2, 0):z + 3, max(y - 2, 0):y + 3, max(x - 2, 0):x + 3].ravel()
        cls = 'tumour' if (reg == 1).any() else ('lymph_node' if (reg == 2).any() else ('uncertain' if (reg == 3).any() else 'not_confirmed'))
        tp += cls == 'tumour'; oth += cls in ('lymph_node', 'uncertain'); unc += cls == 'not_confirmed'
        les_rows.append({'patient_code': c.split('_')[0], 'exam': order[c], 'reference_annotated': bool(it.get('lesion')), 'lesion': l['id'], 'tier': l.get('tier'),
                         'match': cls, 'volume_ml': l.get('volume_ml'), 'eq_diameter_mm': round(l.get('eq_diameter_mm') or 0, 1), 'mean_hu': round(l.get('mean_hu') or 0),
                         'lung_rads': l.get('lung_rads'), 'nodule_type': l.get('nodule_type'), 'detector_only': l.get('approx'),
                         'classifier_prob_pct': l.get('model_prob_pct')})
    pt = rep.get('patient', {})
    ex_rows.append({'patient_code': c.split('_')[0], 'exam': order[c], 'split': it.get('split', ''), 'modality': 'PET/CT (CT part)' if c.endswith('PETCT') else 'CT',
                    'manufacturer': v['scanner'].split(' ')[0], 'slice_spacing_mm': v['spacing_xyz_mm'].split('x')[-1], 'reference_annotated': bool(it.get('lesion')),
                    'reference_lung_tumours': len(vals), 'detected': sum(found), 'patient_loss_L': (0 if all(found) else 1) if vals else '',
                    'platform_lesions': len(rep['lesions']), 'primary': pt.get('n_asosiy'), 'secondary': pt.get('n_qoshimcha'),
                    'lesions_on_tumour': tp, 'lesions_on_node_or_uncertain': oth, 'lesions_not_confirmed': unc,
                    'patient_lung_rads': pt.get('lung_rads'), 'ai_conclusion': pt.get('ai_conclusion'), 'reliability': pt.get('reliability'),
                    'dice_vs_reference': round(rep['vs_ground_truth']['dice'], 3) if rep.get('vs_ground_truth') else '',
                    'analysis_s': rep.get('seconds')})
    print(ex_rows[-1], flush=True)
for suf, rows in (('_exams.csv', ex_rows), ('_lesions.csv', les_rows)):
    with open(OUT + suf, 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
print('tekshiruvlar', len(ex_rows), 'o‘choqlar', len(les_rows))
