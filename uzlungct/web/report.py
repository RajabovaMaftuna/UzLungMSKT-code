"""Radiolog uchun HTML hisobot (brauzerda "Chop etish → PDF sifatida saqlash")."""
import base64
import html
import io
import json
import time
from pathlib import Path

import numpy as np

ASSET_V = 24   # static/*.js versiyasi (index.html dagi ?v= bilan bir xil)

TXT = {
 "uz": {"pid": "Bemor ID", "pt": "Bemor", "born": "Tug‘ilgan sanasi", "age": "{n} yosh", "title": "MSKT tahlili bo‘yicha hisobot (UzLungMSKT)", "print": "Chop etish", "save_pdf": "Hisobotni yuklab olish (PDF)", "inst": "Muassasa", "exam": "Tekshiruv", "job": "Vazifa", "date": "Sana",
        "model": "Model", "n": "aniqlangan o‘choqlar soni", "time": "tahlil vaqti", "sec": "s", "mm": "mm", "gt": "Etalon bilan solishtirish",
        "cols": ["#", "Hajm, ml", "Ekv. diametr, mm", "Sferiklik", "O‘rtacha HU", "Lung-RADS", "Xavf, %", "Radiolog qarori"],
        "les": "O‘choq", "rad": "Radiolog", "concl": "Xulosa",
        "disc": "Ushbu hisobot sun’iy intellekt yordamida tayyorlangan va radiolog tomonidan tasdiqlanishi shart. Tizim tashxis qo‘ymaydi; yakuniy klinik qaror shifokor zimmasida.",
        "dec": {"tumor": "O‘sma (tasdiqlandi)", "node": "Limfa tuguni", "uncertain": "Noaniq", "reject": "Rad etildi (yolg‘on musbat)", None: "Ko‘rib chiqilmagan"}},
 "en": {"pid": "Patient ID", "pt": "Patient", "born": "Date of birth", "age": "age {n}", "title": "CT analysis report (UzLungMSKT)", "print": "Print", "save_pdf": "Download report (PDF)", "inst": "Institution", "exam": "Examination", "job": "Job", "date": "Date",
        "model": "Model", "n": "number of detected lesions", "time": "analysis time", "sec": "s", "mm": "mm", "gt": "Comparison with reference",
        "cols": ["#", "Volume, ml", "Eq. diameter, mm", "Sphericity", "Mean HU", "Lung-RADS", "Risk, %", "Radiologist decision"],
        "les": "Lesion", "rad": "Radiologist", "concl": "Conclusion",
        "disc": "This report was prepared with the help of artificial intelligence and must be confirmed by a radiologist. The system does not make a diagnosis; the final clinical decision rests with the physician.",
        "dec": {"tumor": "Tumor (confirmed)", "node": "Lymph node", "uncertain": "Uncertain", "reject": "Rejected (false positive)", None: "Not reviewed"}},
 "ru": {"pid": "ID пациента", "pt": "Пациент", "born": "Дата рождения", "age": "возраст {n}", "title": "Отчёт по анализу МСКТ (UzLungMSKT)", "print": "Печать", "save_pdf": "Скачать отчёт (PDF)", "inst": "Учреждение", "exam": "Исследование", "job": "Задача", "date": "Дата",
        "model": "Модель", "n": "число обнаруженных очагов", "time": "время анализа", "sec": "с", "mm": "мм", "gt": "Сравнение с эталоном",
        "cols": ["№", "Объём, мл", "Экв. диаметр, мм", "Сферичность", "Средняя HU", "Lung-RADS", "Риск, %", "Решение рентгенолога"],
        "les": "Очаг", "rad": "Рентгенолог", "concl": "Заключение",
        "disc": "Отчёт подготовлен с помощью искусственного интеллекта и должен быть подтверждён рентгенологом. Система не ставит диагноз; окончательное клиническое решение принимает врач.",
        "dec": {"tumor": "Опухоль (подтверждено)", "node": "Лимфоузел", "uncertain": "Неопределённо", "reject": "Отклонено (ложноположительный)", None: "Не просмотрено"}},
}
EXT = {'uz': {'tsused': 'Diqqat: natijaga TotalSegmentator (lung_nodules, ochiq model, tibbiy qurilma emas) topilmalari qo‘shilgan. Har bir o‘choqning manbasi ko‘rsatilgan; yolg‘on topilmalar bo‘lishi mumkin. Tasvirni radiolog ko‘zdan kechirishi shart.', 'tsfail': 'Diqqat: qo‘shimcha model (TotalSegmentator) ishlamadi — tahlil faqat asosiy model bilan bajarildi.', 'weakmodel': 'Diqqat: segmentatsiya modeli kam ma‘lumotda o‘qitilgan (tekshiruv Dice = {d}, o‘qitish holatlari: {n}). “O‘choq aniqlanmadi” natijasi saraton yo‘qligini bildirmaydi; hosila topilmasligi mumkin. Tasvirni radiolog ko‘zdan kechirishi shart.', 'ai': 'Intellektual yordamchi bahosi', 'prob': 'Xavfli o‘simta ehtimoli', 'rads': 'Lung-RADS toifasi', 'aic': 'AI dastlabki xulosasi', 'srcR': 'manba: ACR Lung-RADS v2022 bo‘yicha taxminiy xavf oralig‘i', 'srcM': 'manba: kalibrlangan tasniflash modeli', 'low': 'Diqqat: tasvir kalibrlanmagan (rasm, PDF yoki video) — natija ishonchliligi past.', 'nomodel': 'Diqqat: tasniflash modeli ishlamadi yoki topilmadi — foiz faqat Lung-RADS jadvalidan olingan (modelning kalibrlangan bahosi yo‘q).', 'filt': 'Diqqat: o‘pka qobig‘idan tashqarida bo‘lgani uchun {a} ta komponent olib tashlandi, o‘choq chegarasi (30) dan oshgani uchun {b} ta ko‘rsatilmadi. Tasvirni radiolog ko‘zdan kechirishi shart.', 'mass': 'Lung-RADS skrining tugunlari uchun mo‘ljallangan; ≥ 30 mm hosilada toifa faqat yo‘naltiruvchi, klinik baholash zarur.', 'psolid': 'Yarim qattiq tugun: toifa umumiy diametr bo‘yicha taxminan hisoblandi (ACR qattiq komponent o‘lchamiga qaraydi).', 'xcand': 'Shakli notekis (past sferiklik): radiolog 4X toifasini ko‘rib chiqsin. Toifa avtomatik o‘zgartirilmagan.', 'fin': 'Mutaxassisning yakuniy qarori', 'fdx': 'Yakuniy tashxis', 'frads': 'Yakuniy Lung-RADS', 'rec': 'Tavsiya', 'draft': 'TASDIQLANMAGAN — radiolog qarori kutilmoqda', 'final': 'Yakuniy hisobot — radiolog tomonidan tasdiqlangan', 'input': 'Kirish fayli', 'conc': {'no_lesion': 'O‘choq aniqlanmadi', 'probably_benign': 'Ehtimoliy xavfsiz o‘zgarish', 'suspicious': 'Shubhali o‘choq', 'faqat_qoshimcha': 'Faqat qo‘shimcha nomzodlar — shifokor ko‘rigi shart', 'high_suspicion': 'O‘pka saratoniga yuqori shubha'}, 'dx': {'lung_cancer_suspected': 'O‘pka saratoniga shubha', 'benign_lesion': 'Xavfsiz o‘zgarish', 'follow_up': 'Dinamik kuzatuv talab etiladi', 'no_pathology': 'Patologiya aniqlanmadi', 'other': 'Boshqa patologiya'}, 'src': {'dicom': 'DICOM', 'volume': '3D hajm fayli', 'image': 'rasm(lar)', 'pdf': 'PDF', 'video': 'video'}}, 'en': {'tsused': 'Warning: findings from TotalSegmentator (lung_nodules, open model, not a medical device) were merged into the result. Each lesion shows its source; false positives are possible. A radiologist must review the images.', 'tsfail': 'Warning: the additional model (TotalSegmentator) did not run — the analysis used the primary model only.', 'weakmodel': 'Warning: the segmentation model was trained on limited data (validation Dice = {d}, training cases: {n}). “No lesion detected” does not exclude cancer; a lesion may be missed. A radiologist must review the images.', 'ai': 'Intelligent assistant assessment', 'prob': 'Malignancy probability', 'rads': 'Lung-RADS category', 'aic': 'AI preliminary conclusion', 'srcR': 'source: estimated risk range according to ACR Lung-RADS v2022', 'srcM': 'source: calibrated classification model', 'low': 'Warning: the image is not calibrated (picture, PDF or video) — the result has low reliability.', 'nomodel': 'Warning: the classification model did not run or was not found — the percentage comes from the Lung-RADS table only (no calibrated model estimate).', 'filt': 'Warning: {a} component(s) were removed as lying outside the lung envelope and {b} were not shown because of the 30-lesion limit. A radiologist must review the images.', 'mass': 'Lung-RADS is intended for screening nodules; for a lesion ≥ 30 mm the category is indicative only and clinical assessment is required.', 'psolid': 'Part-solid nodule: the category was approximated from the total diameter (ACR uses the solid component size).', 'xcand': 'Irregular shape (low sphericity): the radiologist should consider category 4X. The category was not changed automatically.', 'fin': 'Specialist’s final decision', 'fdx': 'Final diagnosis', 'frads': 'Final Lung-RADS', 'rec': 'Recommendation', 'draft': 'NOT CONFIRMED — awaiting the radiologist’s decision', 'final': 'Final report — confirmed by the radiologist', 'input': 'Input file', 'conc': {'no_lesion': 'No lesion detected', 'probably_benign': 'Probably benign finding', 'suspicious': 'Suspicious lesion', 'faqat_qoshimcha': 'Only secondary candidates — physician review required', 'high_suspicion': 'High suspicion of lung cancer'}, 'dx': {'lung_cancer_suspected': 'Suspected lung cancer', 'benign_lesion': 'Benign finding', 'follow_up': 'Follow-up required', 'no_pathology': 'No pathology detected', 'other': 'Other pathology'}, 'src': {'dicom': 'DICOM', 'volume': '3D volume file', 'image': 'image(s)', 'pdf': 'PDF', 'video': 'video'}}, 'ru': {'tsused': 'Внимание: в результат добавлены находки TotalSegmentator (lung_nodules, открытая модель, не медицинское изделие). У каждого очага указан источник; возможны ложные находки. Снимки обязательно должен просмотреть рентгенолог.', 'tsfail': 'Внимание: дополнительная модель (TotalSegmentator) не сработала — анализ выполнен только основной моделью.', 'weakmodel': 'Внимание: модель сегментации обучена на ограниченных данных (Dice на валидации = {d}, случаев обучения: {n}). Результат «Очагов не обнаружено» не исключает рак; очаг может быть пропущен. Снимки обязательно должен просмотреть рентгенолог.', 'ai': 'Оценка интеллектуального помощника', 'prob': 'Вероятность злокачественности', 'rads': 'Категория Lung-RADS', 'aic': 'Предварительное заключение ИИ', 'srcR': 'источник: ориентировочный диапазон риска по ACR Lung-RADS v2022', 'srcM': 'источник: откалиброванная модель классификации', 'low': 'Внимание: изображение не откалибровано (картинка, PDF или видео) — надёжность результата низкая.', 'nomodel': 'Внимание: модель классификации не сработала или не найдена — процент взят только из таблицы Lung-RADS (калиброванной оценки модели нет).', 'filt': 'Внимание: {a} компонент(ов) удалено как лежащие вне контура лёгких, {b} не показано из-за предела в 30 очагов. Снимки обязательно должен просмотреть рентгенолог.', 'mass': 'Lung-RADS предназначена для скрининговых узлов; для образования ≥ 30 мм категория лишь ориентировочная, необходима клиническая оценка.', 'psolid': 'Частично солидный узел: категория оценена приближённо по общему диаметру (ACR учитывает размер солидного компонента).', 'xcand': 'Неправильная форма (низкая сферичность): рентгенологу стоит рассмотреть категорию 4X. Категория автоматически не изменялась.', 'fin': 'Окончательное решение специалиста', 'fdx': 'Окончательный диагноз', 'frads': 'Окончательная категория Lung-RADS', 'rec': 'Рекомендация', 'draft': 'НЕ ПОДТВЕРЖДЕНО — ожидается решение рентгенолога', 'final': 'Окончательный отчёт — подтверждён рентгенологом', 'input': 'Входной файл', 'conc': {'no_lesion': 'Очагов не обнаружено', 'probably_benign': 'Вероятно доброкачественное изменение', 'suspicious': 'Подозрительный очаг', 'faqat_qoshimcha': 'Только дополнительные кандидаты — нужен осмотр врача', 'high_suspicion': 'Высокое подозрение на рак лёгкого'}, 'dx': {'lung_cancer_suspected': 'Подозрение на рак лёгкого', 'benign_lesion': 'Доброкачественное изменение', 'follow_up': 'Требуется динамическое наблюдение', 'no_pathology': 'Патологии не выявлено', 'other': 'Другая патология'}, 'src': {'dicom': 'DICOM', 'volume': 'файл 3D-объёма', 'image': 'изображение(я)', 'pdf': 'PDF', 'video': 'видео'}}}
for _l in TXT:
    TXT[_l].update(EXT[_l])


def _rng(r):
    if not r:
        return "—"
    lo, hi = r
    return f"> {lo:g}" if hi >= 100 else (f"< {hi:g}" if lo <= 0 else f"{lo:g}–{hi:g}")


def _thumb_png(case_dir: Path, z: int) -> bytes:
    """O'choq markazidagi aksial kesim (o'pka oynasi, maska qizil) — PNG baytlari (HTML va PDF hisobot uchun)."""
    import SimpleITK as sitk
    from ..sio import read_image
    from PIL import Image
    ct = sitk.GetArrayFromImage(read_image(case_dir / "ct_1mm.nii.gz"))
    m = sitk.GetArrayFromImage(read_image(case_dir / "mask_1mm.nii.gz"))
    z = int(np.clip(z, 0, ct.shape[0] - 1))
    s = np.clip((ct[z].astype(np.float32) + 1350) / 1500, 0, 1)
    rgb = np.stack([s, s, s], -1); mm = m[z] > 0
    rgb[mm] = rgb[mm] * 0.45 + np.array([1, .25, .2]) * .55
    buf = io.BytesIO(); Image.fromarray((rgb[::-1] * 255).astype(np.uint8)).save(buf, "PNG")
    return buf.getvalue()


def _thumb(case_dir: Path, z: int):
    return base64.b64encode(_thumb_png(case_dir, z)).decode()


CONS = {"uz": {"title": "Konsultatsiyalar", "consult": "Ikkinchi fikr", "handover": "Topshirish", "from": "Kimdan", "to": "Kimga"},
        "en": {"title": "Consultations", "consult": "Second opinion", "handover": "Handover", "from": "From", "to": "To"},
        "ru": {"title": "Консультации", "consult": "Второе мнение", "handover": "Передача", "from": "От", "to": "Кому"}}


def _cons_html(consults, lang):
    """Konsultatsiyalar bo'limi (faqat hisobotni ko'rishga huquqi bor foydalanuvchiga tegishli yozuvlar)."""
    if not consults:
        return ""
    C = CONS[lang]
    ts = lambda t: time.strftime("%d.%m.%Y %H:%M", time.localtime(t))
    items = []
    for c in consults:
        msgs = "".join(f"<li><b>{html.escape(m['author'])}</b> ({ts(m['created'])}): {html.escape(m['text'])}</li>" for m in c["messages"])
        items.append(f"<p><b>{C[c['kind']]}</b> — {ts(c['created'])}; {C['from']}: {html.escape(c['from'])}; "
                     f"{C['to']}: {html.escape(', '.join(c['to']))}</p>" + (f"<ul>{msgs}</ul>" if msgs else ""))
    return f"<div class=box><h2>{C['title']}</h2>{''.join(items)}</div>"


def caveats(L, pt, rep):
    """AI natijasi cheklovlari (model holati, filtr, Lung-RADS izohlari) — HTML va PDF hisobot uchun bir xil matn."""
    w, f = [], rep.get("filters") or {}
    if pt.get("model_status") in ("unavailable", "error"):
        w.append(L["nomodel"])
    if f.get("outside_lung", 0) > 0 or f.get("over_limit", 0) > 0:
        w.append(L["filt"].replace("{a}", str(f.get("outside_lung", 0))).replace("{b}", str(f.get("over_limit", 0))))
    mi = rep.get("model_info") or {}
    if mi and (mi.get("val_dice", 1) < 0.5 or mi.get("n_train", 1e9) < 100):
        w.append(L["weakmodel"].replace("{d}", f"{mi.get('val_dice', 0):.2f}").replace("{n}", str(mi.get("n_train", "?"))))
    _ts = (rep.get("ts") or {}).get("status")
    if _ts == "ok":
        w.append(L["tsused"])
    elif _ts in ("error", "timeout"):
        w.append(L["tsfail"])
    if rep.get("model") in ("N8", "SenGuard-3D"):
        if any(l.get("approx") for l in rep.get("lesions", [])):
            w.append("Faqat detektor topgan o'choqlar (belgilangan) taxminiy shaklda: hajm, tur va Lung-RADS hisoblanmagan.")
        if (rep.get("patient") or {}).get("ai_conclusion") == "faqat_qoshimcha":
            w.append("DIQQAT: ishonchli (asosiy) topilma yo'q, lekin qo'shimcha nomzodlar bor. Bu 'o'choq yo'q' degani EMAS — barcha nomzodlarni shifokor ko'rib chiqishi shart.")
        if any(l.get("tier") == "qoshimcha" for l in rep.get("lesions", [])):
            w.append("Qo'shimcha nomzodlar (bitta model, past ishonch) bemor xulosasiga kirmagan. Ular orasida haqiqiy o'choq ham bo'lishi mumkin (sinovda ~2.5% hollarda): ro'yxatni ham ko'rib chiqing.")
        w.append("SenGuard-3D da o'rtacha ~4 ta soxta (FP) o'choq kutiladi: har bir o'choqni shifokor tasdiqlashi shart. Bemor ehtimolligi (%) sertifikatlanmagan klassifikatordan.")
        w.append("SenGuard-3D: sertifikat (sezgirlik >=90%, 95% ishonch) faqat NLSTseg past dozali skrining KT va o'pka o'choqlari uchun. Boshqa KT (diagnostik, PET/KT, mahalliy) uchun sertifikat yo'q; o'choqlar o'tkazib yuborilishi mumkin. Yakuniy qarorni shifokor qabul qiladi.")
    else:
        w.append("Bu model sertifikatlanmagan. Yakuniy qarorni shifokor qabul qiladi.")
    notes = pt.get("rads_notes") or []
    if "mass_ge_30mm" in notes:
        w.append(L["mass"])
    if "part_solid_total_diameter" in notes:
        w.append(L["psolid"])
    if pt.get("rads_x_candidate"):
        w.append(L["xcand"])
    return w


def render_report(case_dir: Path, job: dict, settings: dict, lang: str = "uz", consults=None, patient=None) -> str:
    """patient — reyestrdagi bemor (patients.public), bo'lsa hisobotda oldindan ko'rsatiladi va chop etish oynasi to'ldiriladi."""
    L = TXT[lang]
    rep = json.load(open(case_dir / "report.json", encoding="utf-8"))
    rv = json.load(open(case_dir / "review.json", encoding="utf-8")) if (case_dir / "review.json").exists() else {}
    dmap = {l["id"]: l for l in rv.get("lesions", [])}
    rows = []
    for l in rep["lesions"]:
        r = dmap.get(l["id"], {})
        risk = f"{l['model_prob_pct']:.1f}" if l.get("model_prob_pct") is not None else _rng(l.get("rads_risk_pct"))
        rows.append(f"<tr><td>{l['id']}</td><td>{l['volume_ml']:.2f}</td><td>{l['eq_diameter_mm']:.1f}</td>"
                    f"<td>{l.get('sphericity', float('nan')):.2f}</td><td>{l.get('mean_hu', float('nan')):.0f}</td><td>{html.escape(str(l.get('lung_rads', '—')))}</td>"
                    f"<td>{html.escape(risk)}</td><td>{html.escape(L['dec'].get(r.get('decision')))}</td></tr>")
    imgs = "".join(f"<figure><img src='data:image/png;base64,{_thumb(case_dir, l['centroid_zyx_vox'][0])}'><figcaption>{L['les']} #{l['id']}</figcaption></figure>"
                   for l in rep["lesions"][:4])
    gt = rep.get("vs_ground_truth")
    gt_html = f"<p><b>{L['gt']}:</b> Dice = {gt['dice']:.3f}, HD95 = {gt['hd95_mm']:.1f} {L['mm']}</p>" if gt else ""
    src = job["params"].get("case") or job["params"].get("file") or ""
    pt = rep.get("patient", {}); inp = rep.get("input", {})
    final = rep.get("status") == "final"
    prob = f"{pt['model_prob_pct']:.1f} %" if pt.get("model_prob_pct") is not None else (_rng(pt.get("rads_risk_pct")) + " %" if pt.get("rads_risk_pct") else "—")
    ai_html = (f"<div class=box><h2>{L['ai']}</h2><p><b>{L['aic']}:</b> {html.escape(L['conc'].get(pt.get('ai_conclusion'), '—'))}</p>"
               f"<p><b>{L['prob']}:</b> {prob} ({L['srcM'] if pt.get('model_prob_pct') is not None else L['srcR']}); <b>{L['rads']}:</b> {html.escape(str(pt.get('lung_rads', '—')))}</p>"
               + (f"<p class=warn>{L['low']}</p>" if pt.get("reliability") == "low" else "")
               + "".join(f"<p class=warn>{html.escape(x)}</p>" for x in caveats(L, pt, rep)) + "</div>") if pt else ""
    fin_html = (f"<div class=box><h2>{L['fin']}</h2><p><b>{L['fdx']}:</b> {html.escape(L['dx'].get(rv.get('final_diagnosis'), '—'))}</p>"
                f"<p><b>{L['frads']}:</b> {html.escape(str(rv.get('final_lung_rads') or '—'))}; <b>{L['rec']}:</b> {html.escape(rv.get('recommendation', '') or '—')}</p></div>")
    banner = f"<div class='banner {'ok' if final else 'draft'}'>{L['final'] if final else L['draft']}</div>"
    src_txt = L["src"].get(inp.get("source", "volume"), "")
    head = "".join(f"<th>{html.escape(c)}</th>" for c in L["cols"])
    if patient:
        from .patient import age
        import datetime as _dt
        _b = _dt.date.fromisoformat(patient['birth'])
        pt_name, pt_birth = patient['fio'], f"{_b:%d.%m.%Y} ({L['age'].format(n=age(_b))})"
        preset = {k: patient[k] for k in ('id', 'last', 'first', 'middle', 'birth')}
    else:
        pt_name = pt_birth = ''; preset = None
    return f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="/static/favicon.svg" type="image/svg+xml"><title>UzLungMSKT — {job['id']}</title>
<style>body{{font-family:'Times New Roman',serif;margin:24px;color:#111}}h1{{font-size:20px}}table{{border-collapse:collapse;width:100%;font-size:13px}}
td,th{{border:1px solid #888;padding:4px 6px;text-align:center}}figure{{display:inline-block;margin:6px;width:23%}}img{{width:100%}}
.small{{font-size:12px;color:#444}}#ptGuard{{display:none}}.tw{{overflow-x:auto}}@media (max-width:600px){{body{{margin:12px}}figure{{width:46%}}}}
@media print{{body.needpt>*{{display:none!important}}body.needpt>#ptGuard{{display:block!important;font-size:16px;margin:40px 0}}}}
#ptBlock{{font-size:15px;margin:6px 0 4px}}#ptBlock p{{margin:2px 0}}button,a.pdf{{font:14px sans-serif;padding:6px 14px;margin:0 6px 10px 0;border:1px solid #0b6bcb;border-radius:6px;background:#fff;color:#0b6bcb;cursor:pointer;text-decoration:none;display:inline-block}}a.pdf,button.pdf{{background:#0b6bcb;color:#fff}}button:disabled{{opacity:.5;cursor:wait}}.box{{border:1px solid #888;padding:6px 10px;margin:10px 0}}h2{{font-size:16px;margin:4px 0}}
.banner{{padding:6px 10px;font-weight:bold;margin:8px 0}}.draft{{background:#fde7c8;border:2px dashed #e8710a}}.ok{{background:#d7f0d9;border:2px solid #2e7d32}}.warn{{color:#a35b00}}
@media print{{button,a.pdf{{display:none!important}}.tw{{overflow:visible}}}}</style></head><body{'' if patient else ' class=needpt'}>
<p id=ptGuard></p>
<button type=button id=btnPrint>{L['print']}</button> <button type=button class=pdf id=btnPdf>{L['save_pdf']}</button>
<h1>{L['title']}</h1>{banner}
<div id=ptBlock{'' if patient else ' hidden'}>{f"<p><b>{L['pid']}:</b> {html.escape(patient['id'])}</p>" if patient else ''}<p><b>{L['pt']}:</b> <span id=ptName>{html.escape(pt_name)}</span></p><p><b>{L['born']}:</b> <span id=ptBirth>{html.escape(pt_birth)}</span></p></div>
<p class=small>{L['inst']}: {html.escape(settings.get('institution', '') or '—')} &nbsp;|&nbsp; {L['exam']}: {html.escape(src or '—')} &nbsp;|&nbsp; {L['job']}: {job['id']} &nbsp;|&nbsp; {L['date']}: {time.strftime('%d.%m.%Y %H:%M')}</p>
<p>{L['input']}: {html.escape(src_txt)}. {L['model']}: <b>{html.escape(str(rep.get('model')))}</b>; {L['n']}: <b>{rep['n_lesions']}</b>; {L['time']}: {rep.get('seconds', '?')} {L['sec']}.</p>{gt_html}
{ai_html}<div class=tw><table><tr>{head}</tr>{''.join(rows)}</table></div>
<div>{imgs}</div>
{fin_html}<p><b>{L['rad']}:</b> {html.escape(rv.get('radiologist', '') or settings.get('radiologist', '') or '—')} &nbsp; <b>{L['concl']}:</b> {html.escape(rv.get('conclusion', '') or '—')}</p>
{_cons_html(consults, lang)}
<p class=small>{L['disc']}</p>
<script src="/static/i18n.js?v={ASSET_V}"></script><script src="/static/patient.js?v={ASSET_V}"></script>
<script>
LANG = {json.dumps(lang)};
const JID = {json.dumps(job['id'])};
const PRESET = {json.dumps(preset, ensure_ascii=False).replace('<', '\\u003c')};
document.getElementById("ptGuard").textContent = t("pt.guard");
const blk = document.getElementById("ptBlock");
function clearPt() {{ if (PRESET) return; blk.hidden = true; document.getElementById("ptName").textContent = ""; document.getElementById("ptBirth").textContent = "";
  document.body.classList.add("needpt"); }}
window.addEventListener("afterprint", clearPt);
document.getElementById("btnPrint").onclick = async () => {{
  const p = await PatientDialog.open("print", PRESET); if (!p) return;
  document.getElementById("ptName").textContent = PatientDialog.fullName(p);
  document.getElementById("ptBirth").textContent = PatientDialog.birthText(p);
  blk.hidden = false; document.body.classList.remove("needpt");
  setTimeout(() => window.print(), 50);
}};
document.getElementById("btnPdf").onclick = async e => {{
  const btn = e.currentTarget, p = await PatientDialog.open("pdf", PRESET); if (!p) return;
  try {{ await PatientDialog.downloadPdf(JID, LANG, p, btn); }} catch (err) {{ alert(err.message); }}
}};
</script>
</body></html>"""
