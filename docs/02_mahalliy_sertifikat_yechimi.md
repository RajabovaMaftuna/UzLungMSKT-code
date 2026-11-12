# UzLungCT — mahalliy domenda kafolat muammosining yechim yo'llari (2026-10-26, 10:55)

## Muammo
Mahalliy baza: 21 bemor kodi, o'smali bemor ~9 (manba: lokal_baza_tahlili; xom arxivda yangi KT holat topilmadi). 95% ishonch bilan "sezgirlik >=95%" uchun nol xatoda >=59 bemor kerak. Mahalliyda bu mumkin emas.

## Hisob (nol o'tkazib yuborishda minimal bemor soni, aniq binomial)
| alpha (kutilgan o'tkazib yuborish) | delta=0.05 | delta=0.10 |
| 0.05 (sezgirlik>=95%) | 59 | 45 |
| 0.10 (>=90%) | 29 | 22 |
| 0.15 | 19 | 15 |
| 0.20 | 14 | 11 |
Mahalliy 9 bemor va 9/9 topilsa isbotlanadigan: sezgirlik >=71.7% (95% ishonch). 7 bemor: >=65.2%. Ya'ni mahalliy ma'lumotning o'zi bilan 95% da'vo qilib bo'lmaydi — bu matematika, kod bilan hal bo'lmaydi.

## Yechim yo'llari (ishonchlilik tartibida)
1. PROKSI-DOMEN SERTIFIKATI (ochiq ma'lumot). Mahalliyga eng yaqin ochiq to'plamlar:
   - Lung-PET-CT-Dx (TCIA): 355 sub'ekt, diagnostik PET/KT, o'pka saratoni, bounding box (PASCAL VOC), CC BY 4.0, rasmlar ~127 GB (kerakli ~100–150 bemor tanlab olinadi). Mahalliy baza PET/KT ekani lokal_baza_tahlili hujjatidan olingan, bu yerda qayta tekshirilmadi — yaqinlik taxminiy.
   - NSCLC-Radiomics (TCIA): 422 bemor, 33 GB, radioterapevt GTV konturi, CC BY-NC 3.0 (tijoriy emas).
   - NSCLC Radiogenomics (TCIA): 211 sub'ekt, 98 GB (CT, PET, SEG), CC BY 3.0; nechta SEG borligi sahifada aniq emas — tekshirish kerak.
   - MSD Task06 (63) allaqachon trening/OOF.
   Aniqlash darajasidagi sertifikat uchun faqat "o'choq topildimi" kerak, ya'ni bounding box yetarli (to'liq maska shart emas). Lung-PET-CT-Dx buning uchun yetarli: >=59 (aniqrog'i 100+) bemor.
   Natija: "diagnostik PET/KT o'pka-saratoni domenida kafolat" — mahalliyga emas, shu proksi domenga.
2. MAHALLIY AUDIT (kafolatsiz, shaffof). Proksida kalibrlangan t ni mahalliy 9 bemorga qo'llab, haqiqiy o'tkazib yuborishni yozish. Binomial: 9/9 bo'lsa ham mahalliy uchun isbot emas, "proksi bilan mos" deb hisobot. Siljishda buzilish sun'iy sinovda 22.8% bo'lgani uchun bu audit majburiy.
3. MAHALLIY MA'LUMOTNI KO'PAYTIRISH (foydalanuvchi qarori). Kerakli yangi holatlar: faqat o'choq joylashuvi (nuqta yoki quti) kifoya — radiolog bir nechta daqiqada belgilaydi; maska chizish shart emas. Mavjud quvur (p6_tumor.py -> radiolog tasdig'i p8a/p8b) yangi PET/KT'dan avtomatik nomzod beradi, radiolog faqat tasdiqlaydi. Maqsad: >=50 yangi o'smali bemor (9 bilan jami >=59). Bu men hal qilolmaydigan, kasalxona ruxsati va radiolog vaqti talab qiladigan qadam.
4. QO'SHIMCHA YO'L (tajriba, da'vo yo'q): og'irlangan konformal (Tibshirani 2019) mahalliy belgilanmagan rasmlar bilan ehtimollik nisbatini baholab, proksidagi kalibrlashni mahalliyga o'tkazadi; ehtimollik nisbati noto'g'ri baholansa kafolat buziladi — sun'iy va real sinovda tasdiqlanmaguncha qo'llanmaydi.
5. KAFOLATNI YUMSHATISH (halol muqobil): alpha=0.10 (>=90%) uchun 29 (delta=.05) yoki 22 (delta=.10) mahalliy bemor kerak — 3-yo'l bilan erishish osonroq. Maqsad o'zgartirilsa, buni oldindan hujjatlash shart (natijadan keyin emas).

## Tavsiya etilgan tartib (v7.1 S6 ga qo'shiladi)
a) Lung-PET-CT-Dx: annotatsiya XML + 150 bemor tanlab yuklash (bemor-darajali, tasodifiy seed bilan), lesion-box ↔ model komponent moslashuvi (markaz qutida yoki IoU>0).
b) Kalibrlash/test bo'linishi bemor bo'yicha (60/40), mahalliy bemorlar sertifikatga kirmaydi.
c) Mahalliy audit natijasi alohida jadval.
d) Foydalanuvchiga hisobot: mahalliy sertifikat uchun kerakli bemor soni va kerakli annotatsiya turi.

## Chegaralar
- Lung-PET-CT-Dx va mahalliy bir xil taqsimot ekani isbotlanmagan (boshqa mamlakat/apparat); shuning uchun proksi sertifikat mahalliyga o'tmaydi.
- Lung-PET-CT-Dx qutilari modelning komponentidan farq qilishi mumkin (quti kattaroq); moslashuv qoidasi oldindan belgilanadi (markaz-ichida).
- NSCLC-Radiomics CC BY-NC: tijoriy foydalanishga yaramaydi.

## YANGILANISH (2026-10-26 11:05): tayyor mos dataset topildi va yuklanmoqda
FDG-PET-CT-Lesions (TCIA, DOI 10.7937/gkr0-xv29; Gatidis va boshq., Sci Data 2022, 10.1038/s41597-022-01718-3):
- 900 bemor/1014 tekshiruv; shundan LUNG_CANCER = 168 tekshiruv (168 noyob bemor, klinik jadvaldan tasdiqlandi) — 59 talabidan ancha ko'p.
- Diagnostik butun-tana PET/KT (ko'pincha kontrastli, 2–3 mm), 3D qo'lda segmentatsiya (DICOM-SEG), CC BY 4.0 (defaced rasmlar).
- Yuklash: faqat KT + SEG (PET tashlanadi), skript C:\ZG\fdg2.py -> C:\ZG\ext\fdg\{CT,SEG}; 336 seriya.
- Mahalliy domenga eng yaqin: PET/KT, diagnostik KT, 3D maska (Lung-PET-CT-Dx da faqat quti bor).
Cheklovlar (tekshirish kerak): (1) SEG barcha FDG-faol o'choqlarni (limfa tugun, metastaza ham) belgilaydi — faqat o'pka birlamchi/o'pka ichidagi o'choqlar olinadi (o'pka maskasi bilan kesishuv); (2) bir bemor — bir tekshiruv; (3) bu Germaniya (Tyubingen) domeni — mahalliyga kafolat emas; (4) PET asosida belgilangan etalon KT-faqat model uchun biroz farq qilishi mumkin.
Boshqa AI modellaridan so'rash: bu sessiyada boshqa modellarga murojaat qilish vositasi yo'q; qidiruv Zenodo/TCIA/Nature manbalari orqali o'zim bajarildi.
