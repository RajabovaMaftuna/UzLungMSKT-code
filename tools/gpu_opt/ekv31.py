"""31-promt: V namunasida GPU va CPU rejimlarini qaror darajasida solishtirish. Uzilsa qayta ishga tushiring – tayyorlari o'tkaziladi."""
import json, os, random, subprocess, sys, time, shutil
import numpy as np, nibabel as nib
from scipy import ndimage as nd
PY = r"C:\ZG\build_exe\stage\python\python.exe"; RUN = r"C:\ZG\build_exe\stage\n8_runner.py"
NII = r"D:\UzLungCT_DATASET_v2\data\NLSTseg\nii"; W = r"C:\ZG\build_exe\gpu_opt\ekv31"; os.makedirs(W, exist_ok=True)
NAM = r"C:\ZG\docs\31_namuna.json"
ST = np.ones((3, 3, 3))
if not os.path.exists(NAM):
    V = json.load(open(r"D:\UzLungCT_DATASET_v2\data\NLSTseg\splits_v9_nlst.json", encoding='utf-8'))['splits']['V']
    rnd = random.Random(42); s = sorted(rnd.sample(sorted(V), 10))
    json.dump({'qism': 'V', 'seed': 42, 'n': 10, 'bemorlar': s, 'yaratildi': time.strftime('%Y-%m-%d %H:%M')}, open(NAM, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
ids = json.load(open(NAM, encoding='utf-8'))['bemorlar']


def run(pid, mode):
    out = os.path.join(W, f'{pid}_{mode}')
    if os.path.exists(os.path.join(out, 'n8_boxes.json')):
        return out
    if shutil.disk_usage('C:\\').free / 2**30 < 40:
        sys.exit('C: diskida joy kam (<40 GB) – to‘xtatildi')
    env = {k: v for k, v in os.environ.items() if not k.startswith('PYTHON')}
    if mode == 'cpu': env['UZLUNGCT_FORCE_CPU'] = '1'
    t = time.time()
    r = subprocess.run([PY, '-E', '-s', RUN, os.path.join(NII, pid, f'{pid}_CT.nii.gz'), out], env=env, capture_output=True, text=True)
    if r.returncode:
        open(out + '_xato.txt', 'w', encoding='utf-8').write(r.stderr[-3000:]); raise RuntimeError(f'{pid} {mode}: xato')
    json.dump({'s': round(time.time() - t, 1)}, open(os.path.join(out, 'vaqt.json'), 'w'))
    return out


def found_list(pred, lab, vals):          # s7a_def_T.found_list bilan bir xil mezon
    cc, n = nd.label(pred, structure=ST)
    cents = [tuple(int(round(c)) for c in x) for x in nd.center_of_mass(pred, cc, range(1, n + 1))] if n else []
    return [bool((pred & (lab == v)).sum() / (lab == v).sum() >= 0.10 or any(lab[c] == v for c in cents)) for v in vals]


def lesions(out):
    m = np.asarray(nib.load(os.path.join(out, 'n8_mask.nii.gz')).dataobj) > 0
    src = np.asarray(nib.load(os.path.join(out, 'n8_src.nii.gz')).dataobj)
    p = np.asarray(nib.load(os.path.join(out, 'n8_prob.nii.gz')).dataobj)
    cc, n = nd.label(m, structure=ST); asosiy = 0
    for i, sl in enumerate(nd.find_objects(cc), 1):
        c = cc[sl] == i; bits = int(np.bitwise_or.reduce(src[sl][c])); nsrc = bin(bits & 7).count('1')
        if nsrc >= 2 or float(p[sl][c].max()) >= 0.5: asosiy += 1
    return m, p, n, asosiy


res = []
for pid in ids:
    g, c = run(pid, 'gpu'), run(pid, 'cpu')
    lab, nl = nd.label(np.asarray(nib.load(os.path.join(NII, pid, f'{pid}_tumor.nii.gz')).dataobj) > 0, structure=ST)
    vals = list(range(1, nl + 1))
    mg, pg, ng, ag = lesions(g); mc, pc, nc, ac = lesions(c)
    fg, fc = found_list(mg, lab, vals), found_list(mc, lab, vals)
    bg, bc = json.load(open(os.path.join(g, 'n8_boxes.json'))), json.load(open(os.path.join(c, 'n8_boxes.json')))
    dice = 2 * (mg & mc).sum() / max(mg.sum() + mc.sum(), 1)
    r = {'bemor': pid, 'etalon_ochoq': nl, 'L_gpu': int(not all(fg)), 'L_cpu': int(not all(fc)), 'ochoq_qarorlari_bir_xil': fg == fc,
         'model_ochoq_gpu': ng, 'model_ochoq_cpu': nc, 'asosiy_gpu': ag, 'asosiy_cpu': ac, 'qutilar': [len(bg), len(bc)],
         'dice': round(float(dice), 5), 'voksel_farq': int((mg != mc).sum()), 'prob_max_farq': round(float(np.abs(pg - pc).max()), 5),
         'vaqt_gpu_s': json.load(open(os.path.join(g, 'vaqt.json')))['s'], 'vaqt_cpu_s': json.load(open(os.path.join(c, 'vaqt.json')))['s']}
    res.append(r); print(json.dumps(r, ensure_ascii=False), flush=True)
    json.dump(res, open(r"C:\ZG\docs\31_natija.json", 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
M1 = all(r['L_gpu'] == r['L_cpu'] for r in res); M2 = all(r['ochoq_qarorlari_bir_xil'] for r in res)
M3 = all(r['model_ochoq_gpu'] == r['model_ochoq_cpu'] and r['asosiy_gpu'] == r['asosiy_cpu'] for r in res); M4 = all(r['dice'] >= 0.999 for r in res)
json.dump({'bemorlar': res, 'mezonlar': {'M1_Li': M1, 'M2_ochoq': M2, 'M3_soni_triaj': M3, 'M4_dice': M4}}, open(r"C:\ZG\docs\31_natija.json", 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('MEZONLAR', M1, M2, M3, M4)
