# Mahalliy to'plamdan (D:\UzLungCT_DATASET_v2\data\Mahalliy_2024-2025) ochiq e'lon uchun anonim agregat jadvallar (2026-11-12).
# Chiqmaydi: tasvirlar, ism, sana, UID, yosh/jins, apparat modeli, o'choq koordinatalari, erkin matnli izohlar.
# Tekshiruv sanasi o'rniga bemor ichidagi tartib raqami (E1, E2, ...) beriladi.
import csv, json, os, sys
SRC = r'D:\UzLungCT_DATASET_v2\data\Mahalliy_2024-2025\metadata'
RES = r'C:\ZG\docs\natijalar_DATASET'
OUT = sys.argv[1]; os.makedirs(OUT, exist_ok=True)

def rd(name):
    with open(os.path.join(SRC, name), encoding='utf-8-sig') as f:
        return list(csv.DictReader(f, delimiter=';'))

vols = rd('volumes.csv')
order = {}
for p in sorted({v['patient'] for v in vols}):
    st = sorted(v['study'] for v in vols if v['patient'] == p)
    for i, s in enumerate(st, 1):
        order[(p, s)] = f'E{i}'
mod = lambda s: 'PET/CT (CT part)' if s.endswith('PETCT') else 'CT'

def wr(name, head, rows):
    with open(os.path.join(OUT, name), 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f); w.writerow(head); w.writerows(rows)
    print(name, len(rows))

qc = {(r['patient'], r['study']): r for r in rd('qc_v2.csv')}
mk = {(r['patient'], r['study']): r for r in rd('mask_kelishuv.csv')}
gf = {(r['patient'], r['study']): r for r in rd('geom_fix.csv')}
rows = []
for v in sorted(vols, key=lambda v: (v['patient'], order[(v['patient'], v['study'])])):
    k = (v['patient'], v['study']); q = qc.get(k, {}); m = mk.get(k, {})
    phase = q.get('phase', '').split(' ')[0]
    rows.append([v['patient'], order[k], mod(v['study']), v['scanner'].split(' ')[0], v['spacing_xyz_mm'].split('x')[-1],
                 v['lung_volume_L'], {'OGOHLANTIRISH': 'WARNING'}.get(q.get('status', ''), q.get('status', '')), q.get('issues', ''), {'nativ': 'non-contrast', 'kontrastli': 'contrast', 'arterial': 'contrast (arterial)'}.get(phase, phase),
                 m.get('dice_lungmask_vs_TS', ''), 'yes' if gf.get(k, {}).get('CT_z_teskari_edi') == 'ha' else 'no', v['split']])
wr('local_volumes.csv', ['patient_code', 'exam', 'modality', 'manufacturer', 'slice_spacing_mm', 'lung_volume_L', 'qc_status', 'qc_issues',
                         'contrast_phase', 'lung_mask_dice_lungmask_vs_TotalSegmentator', 'z_direction_corrected', 'split'], rows)

tr = {'o\'sma': 'tumour', 'limfa tuguni': 'lymph node', 'noaniq': 'uncertain', "noaniq (e'tiborsiz)": 'uncertain (masked in evaluation)', 'olib tashlandi': 'removed'}
rows = [[r['patient'], order.get((r['patient'], r['study']), ''), mod(r['study']), r['lesion'], tr.get(r['yakuniy_toifa'], r['yakuniy_toifa']),
         r['volume_ml'], r['max_diameter_mm'], r['SUVmax'], 'PET/CT, two radiologists' if r['manba'].startswith('PET') else 'CT only, one radiologist'] for r in rd('lesions_gt.csv')]
wr('local_reference_lesions.csv', ['patient_code', 'exam', 'modality', 'lesion', 'final_category', 'volume_ml', 'max_diameter_mm', 'SUVmax', 'reference_source'], rows)

rows = []
for nm, f in (('audit', 'eval_local_audit.json'), ('closed test', 'eval_local_yopiq.json')):
    for r in json.load(open(os.path.join(RES, f), encoding='utf-8')):
        p, s = r['c'].split('__'); fnd = r.get('found', [])
        rows.append([nm, p, order[(p, s)], mod(s), r['n'], sum(fnd), (0 if all(fnd) else 1) if r['n'] else ''])
wr('local_senguard3d_audit.csv', ['set', 'patient_code', 'exam', 'modality', 'reference_lung_lesions', 'detected', 'patient_loss_L'], rows)
