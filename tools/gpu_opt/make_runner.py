"""n8_runner.py dan moslashuvchan (1.0.1) variantini yasaydi: hisob-kitob o'zgarmaydi, faqat qurilma/xotira boshqaruvi."""
src = open(r"C:\ZG\build_exe\stage\n8_runner.py", encoding='utf-8').read()
HW = '''

# ---- 1.0.1: apparatga moslashuv (natijani o'zgartirmaydi; faqat qurilma, oqimlar va xotira boshqaruvi) ----
import gc, platform


def _free_gb():
    try:
        f, t = torch.cuda.mem_get_info(); return f / 2**30, t / 2**30
    except Exception:
        return 0.0, 0.0


def _ram_gb():
    try:
        import ctypes
        class MS(ctypes.Structure):
            _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                        ("a", ctypes.c_ulonglong), ("b", ctypes.c_ulonglong), ("c", ctypes.c_ulonglong), ("d", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong)]
        m = MS(); m.l = ctypes.sizeof(MS); ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)); return m.total / 2**30
    except Exception:
        return 8.0


def hw_plan():
    """Har qanday kompyuter: NVIDIA (CUDA) bo'lsa va bo'sh videoxotira yetarli bo'lsa — GPU; AMD/Intel/GPU yo'q yoki
    UZLUNGCT_FORCE_CPU=1 bo'lsa — protsessor. Oqimlar soni yadrolar va operativ xotiraga qarab."""
    cpu = os.cpu_count() or 2; ram = _ram_gb()
    use_gpu = os.environ.get("UZLUNGCT_FORCE_CPU") != "1" and torch.cuda.is_available()
    free, total = _free_gb() if use_gpu else (0.0, 0.0)
    if use_gpu and free < 2.0:                       # juda kam bo'sh videoxotira (boshqa dastur band qilgan) — protsessor
        use_gpu = False
    procs = 1 if ram < 12 or cpu <= 4 else 2
    plan = {"gpu": use_gpu, "name": torch.cuda.get_device_name(0) if use_gpu else platform.processor() or "CPU",
            "vram_free_gb": round(free, 1), "vram_total_gb": round(total, 1), "ram_gb": round(ram, 1), "cpu": cpu,
            "on_device": use_gpu and free >= 6.0,       # nnU-Net natijalarni videoxotirada yig'adimi (aks holda RAM da)
            "procs": procs}
    if not use_gpu:
        torch.set_num_threads(max(1, cpu - 1))
    return plan


PLAN = None


def _cleanup():
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def _oom(e):
    return isinstance(e, torch.cuda.OutOfMemoryError) or "out of memory" in str(e).lower()
'''
new_nn = '''def nnunet(model_dir, inp, out, probs):
    from nnunetv2.inference.predict_from_raw_data import nnUNetPredictor
    tries = [(PLAN["gpu"], PLAN["on_device"])] + ([(True, False)] if PLAN["gpu"] and PLAN["on_device"] else []) + ([(False, False)] if PLAN["gpu"] else [])
    for k, (g, od) in enumerate(tries):
        try:
            p = nnUNetPredictor(tile_step_size=0.5, use_gaussian=True, use_mirroring=False, perform_everything_on_device=od,
                                device=torch.device("cuda" if g else "cpu"), verbose=False, verbose_preprocessing=False, allow_tqdm=False)
            p.initialize_from_trained_model_folder(str(model_dir), use_folds=(0, 1, 2, 3, 4), checkpoint_name="checkpoint_final.pth")
            p.predict_from_files(str(inp), str(out), save_probabilities=probs, overwrite=True, num_processes_preprocessing=PLAN["procs"], num_processes_segmentation_export=PLAN["procs"])
            del p; _cleanup(); return
        except Exception as e:
            p = None; _cleanup()
            if not _oom(e) or k == len(tries) - 1:
                raise
            print(f"[hw] videoxotira yetmadi ({Path(model_dir).name}), keyingi rejim: {tries[k + 1]}", flush=True)
'''
i = src.index('def nnunet('); j = src.index('def detector(')
src = src[:i] + new_nn + '\n\n' + src[j:]
src = src.replace('SP = (0.703125, 0.703125, 1.25)\n', 'SP = (0.703125, 0.703125, 1.25)\n' + HW, 1)
# TotalSegmentator: qurilma rejaga ko'ra, OOM da protsessor
src = src.replace('    tsl = np.asarray(totalsegmentator(ct, None, task="lung_nodules", quiet=True).dataobj)',
'''    global PLAN
    PLAN = hw_plan(); print("[hw]", json.dumps(PLAN, ensure_ascii=False), flush=True)
    try:
        tsl = np.asarray(totalsegmentator(ct, None, task="lung_nodules", quiet=True, device="gpu" if PLAN["gpu"] else "cpu").dataobj)
    except Exception as e:
        if not (PLAN["gpu"] and _oom(e)):
            raise
        _cleanup(); print("[hw] TotalSegmentator protsessorda", flush=True)
        tsl = np.asarray(totalsegmentator(ct, None, task="lung_nodules", quiet=True, device="cpu").dataobj)
    _cleanup()''')
# detektor: qurilma rejaga ko'ra; OOM -> protsessor
src = src.replace('''    x = ((x.clamp(-1024, 300) + 1024) / 1324).to(dev); det = detector()
    with torch.no_grad(), torch.autocast(dev, enabled=dev == "cuda"):
        o = det([x], use_inferer=True)[0]''',
'''    dev = "cuda" if PLAN["gpu"] else "cpu"
    x = ((x.clamp(-1024, 300) + 1024) / 1324)
    for dv in ([dev, "cpu"] if dev == "cuda" else ["cpu"]):
        try:
            det = detector(dv); xx = x.to(dv)
            with torch.no_grad(), torch.autocast(dv, enabled=dv == "cuda"):
                o = det([xx], use_inferer=True)[0]
            break
        except Exception as e:
            det = xx = None; _cleanup()
            if dv == "cpu" or not _oom(e):
                raise
            print("[hw] detektor protsessorda", flush=True)
    del det, xx; _cleanup()''')
src = src.replace('def detector():', 'def detector(dev=None):').replace('    return det.to("cuda" if torch.cuda.is_available() else "cpu").eval()', '    return det.to(dev or ("cuda" if torch.cuda.is_available() else "cpu")).eval()')
assert src.count('[hw]') >= 4 and 'def detector(dev=None)' in src and 'det.to(dev or' in src
src = src.replace('# SenGuard-3D (ichki N8) ko\'chma quvuri.', '# SenGuard-3D (ichki N8) ko\'chma quvuri, 1.0.1 (apparatga moslashuv; hisob-kitob 1.0 bilan bir xil).', 1)
open(r"C:\ZG\build_exe\stage\n8_runner_101.py", 'w', encoding='utf-8', newline='\n').write(src)
print('ok')
