import sys, json, numpy as np, nibabel as nib
a, b = sys.argv[1], sys.argv[2]
r = {}
for n in ('n8_mask', 'n8_src'):
    x = np.asarray(nib.load(f'{a}/{n}.nii.gz').dataobj); y = np.asarray(nib.load(f'{b}/{n}.nii.gz').dataobj)
    r[n + '_farq_voksel'] = int((x != y).sum())
x = np.asarray(nib.load(f'{a}/n8_prob.nii.gz').dataobj); y = np.asarray(nib.load(f'{b}/n8_prob.nii.gz').dataobj)
r['prob_max_farq'] = float(np.abs(x - y).max())
ba, bb = json.load(open(f'{a}/n8_boxes.json')), json.load(open(f'{b}/n8_boxes.json'))
r['qutilar'] = [len(ba), len(bb)]
r['quti_ball_max_farq'] = max([abs(p['score'] - q['score']) for p, q in zip(ba, bb)] or [0.0])
r['OK'] = r['n8_mask_farq_voksel'] == 0 and r['n8_src_farq_voksel'] == 0 and r['prob_max_farq'] <= 1e-5 and len(ba) == len(bb) and r['quti_ball_max_farq'] <= 1e-5
print(json.dumps(r))
