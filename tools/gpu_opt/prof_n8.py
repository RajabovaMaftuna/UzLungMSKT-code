"""SenGuard-3D quvurini bosqichlar bo'yicha o'lchash: vaqt, torch VRAM cho'qqisi, nvidia-smi umumiy cho'qqi, RAM cho'qqisi.
Ishlatish: python prof_n8.py <runner.py> <ct.nii.gz> <out_dir> <log.json>"""
def _run():
    import sys, time, json, threading, subprocess, importlib.util, os
    runner, ct, out, logf = sys.argv[1:5]
    SMI = r"C:\Windows\System32\DriverStore\FileRepository\nvaci.inf_amd64_8eeb4ccec4045818\nvidia-smi.exe"
    peak = {'smi_mb': 0}; stop = False
    def sampler():
        while not stop:
            try:
                v = int(subprocess.run([SMI, '--query-gpu=memory.used', '--format=csv,noheader,nounits'], capture_output=True, text=True, creationflags=0x08000000).stdout.strip().split()[0])
                peak['smi_mb'] = max(peak['smi_mb'], v)
            except Exception:
                pass
            time.sleep(0.5)
    threading.Thread(target=sampler, daemon=True).start()
    spec = importlib.util.spec_from_file_location('n8r', runner); R = importlib.util.module_from_spec(spec)
    sys.argv = [runner, ct, out]; spec.loader.exec_module(R)
    import torch
    phases = []
    def timed(name, fn):
        def w(*a, **k):
            if torch.cuda.is_available(): torch.cuda.synchronize(); torch.cuda.reset_peak_memory_stats()
            t = time.time(); r = fn(*a, **k)
            if torch.cuda.is_available(): torch.cuda.synchronize()
            phases.append({'bosqich': name, 's': round(time.time() - t, 1), 'vram_torch_mb': round(torch.cuda.max_memory_allocated() / 2**20) if torch.cuda.is_available() else 0})
            return r
        return w
    import totalsegmentator.python_api as tsa
    tsa.totalsegmentator = timed('TotalSegmentator', tsa.totalsegmentator)
    _nn = R.nnunet; cnt = {'k': 0}
    def nn(*a, **k):
        cnt['k'] += 1; return timed('M2' if cnt['k'] == 1 else 'K1', _nn)(*a, **k)
    R.nnunet = nn
    _det = R.detector
    R.detector = timed('RetinaNet_yuklash', _det)
    t0 = time.time()
    try:
        import psutil; proc = psutil.Process()
    except Exception:
        proc = None
    R.main()
    stop = True
    res = {'jami_s': round(time.time() - t0, 1), 'smi_cho‘qqi_mb': peak['smi_mb'], 'ram_mb': round(proc.memory_info().peak_wset / 2**20) if proc and hasattr(proc.memory_info(), 'peak_wset') else None, 'bosqichlar': phases}
    json.dump(res, open(logf, 'w', encoding='utf-8'), ensure_ascii=False, indent=1); print(json.dumps(res, ensure_ascii=False))
    

if __name__ == '__main__':
    _run()
