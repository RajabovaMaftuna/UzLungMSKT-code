# 5-maqola, 2-jadval: segmentatsiya modellarining hisoblash murakkabligi (2026-11-12).
# Har bir saqlangan chekpoint uchun: parametrlar soni, FLOPs (torch FlopCounterMode, oldinga o'tish, 1x1x96^3),
# xulosa vaqti (bfloat16, 1x1x96^3, 5 ta isitishdan keyin 30 ta takror mediana), o'qitish qadami vaqti va eng yuqori
# videoxotira (bfloat16 autocast, AdamW, konfiguratsiyadagi paket hajmi, 96^3, 3 isitish + 10 qadam mediana).
# Ishlatish: python -E -s profile_models.py <natija.json> <ckpt1> <ckpt2> ...
import json, statistics, sys, time
from pathlib import Path
import torch
from torch.utils.flop_counter import FlopCounterMode
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))          # ombor ildizi (uzlungct paketi)
from uzlungct.models import build_seg_model

dev = torch.device('cuda'); out = {}
gpu = torch.cuda.get_device_name(0)
for ck in sys.argv[2:]:
    name = Path(ck).parent.name
    c = torch.load(ck, map_location='cpu', weights_only=False); cfg = c['cfg']
    m = build_seg_model(cfg['model'], 1, cfg['n_classes'], patch=cfg['patch'], **cfg.get('model_kw', {}))
    m.load_state_dict(c['model']); m.to(dev)
    params = sum(p.numel() for p in m.parameters())
    x1 = torch.randn(1, 1, 96, 96, 96, device=dev)
    m.eval()
    with torch.no_grad(), FlopCounterMode(display=False) as fc:
        m(x1)
    flops = fc.get_total_flops()
    ts = []
    with torch.no_grad(), torch.autocast('cuda', dtype=torch.bfloat16):
        for i in range(35):
            torch.cuda.synchronize(); t0 = time.perf_counter(); m(x1); torch.cuda.synchronize()
            if i >= 5: ts.append(time.perf_counter() - t0)
    inf_ms = 1000 * statistics.median(ts)
    m.train(); bs = int(cfg.get('batch', 2))
    opt = torch.optim.AdamW(m.parameters(), lr=1e-4)
    xb = torch.randn(bs, 1, 96, 96, 96, device=dev); yb = torch.randint(0, cfg['n_classes'], (bs, 96, 96, 96), device=dev)
    torch.cuda.empty_cache(); torch.cuda.reset_peak_memory_stats(); st = []
    for i in range(13):
        torch.cuda.synchronize(); t0 = time.perf_counter()
        with torch.autocast('cuda', dtype=torch.bfloat16):
            lo = torch.nn.functional.cross_entropy(m(xb).float(), yb)
        opt.zero_grad(set_to_none=True); lo.backward(); opt.step(); torch.cuda.synchronize()
        if i >= 3: st.append(time.perf_counter() - t0)
    out[name] = {'model': cfg['model'], 'params': params, 'gflops_forward_96': round(flops / 1e9, 1),
                 'inference_ms_bf16': round(inf_ms, 1), 'train_step_s_bf16': round(statistics.median(st), 3),
                 'train_batch': bs, 'peak_vram_gb_train': round(torch.cuda.max_memory_allocated() / 2**30, 2)}
    print(name, out[name], flush=True)
    del m, opt, xb, yb; torch.cuda.empty_cache()
json.dump({'gpu': gpu, 'torch': torch.__version__, 'input': [1, 1, 96, 96, 96], 'models': out}, open(sys.argv[1], 'w'), indent=1)
