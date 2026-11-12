# UzLungCT — "Kafolatli sezgirlik" (ishonch >95%) usuli (2026-10-26, 10:35)

## Muammo
"Sezgirlik >95%" va "bu da'voga ishonch >95%" ikki xil narsa. 10 o'choqda 10/10 bo'lsa ham 95% CI quyi chegarasi ~69%. Ishonchni ma'lumot sonidan tashqari USUL bilan ham oshirish mumkin: chegarani statistik kafolat bilan tanlash.

## Topilgan asos (manbalar)
- Conformal Lesion Segmentation (arXiv 2510.17897): 3D lesion segmentatsiyada kalibrlash to'plamidan chegara tanlab, FNR ni belgilangan darajadan past ushlash; oltita 3D dataset, besh backbone. (Faqat annotatsiya o'qildi, aniq ehtimollik shakli tekshirilmagan.)
- Conformal risk control (arXiv 2504.04482): chegara kalibrlash to'plamida tanlanadi; kafolat FAQAT KUTILGAN yo'qotish bo'yicha (marginal, almashinuvchanlik farazi), bitta MRI dataset; maqolada nomuvofiqliklar bor -> g'oya, natijalarga ishonmaymiz.
- Learn then Test (arXiv 2110.01052): xavf nazoratini ko'p gipoteza testi sifatida; istalgan model va noma'lum taqsimotda chekli-tanlanma kafolat; modelni qayta o'qitish shart emas.
- LUNA16 (arXiv 1612.08012): 888 CT, nomzodlarni birlashtirgan tizimlar <1 FP/skanda sezgirlik >95% (tugunlar uchun) -> detektorlarni birlashtirish yordam beradi.

## Usul (S6 ga qo'shiladi)
1. Birlik: o'choq; resempling: bemor bo'yicha (bir bemor o'choqlari bog'liq).
2. Har haqiqiy o'choq uchun ball s_i = ansamblning bu o'choqni qoplovchi komponentidagi maksimal ehtimollik (yoki filtr bahosi). Chegara t da o'choq "topilgan" = s_i >= t.
3. Kalibrlash to'plamida (o'qitish va testdan alohida!) t ni shunday tanlash: o'tkazib yuborilgan soni k bo'lganda Clopper-Pearson bir tomonli yuqori chegara (delta=0.05) <= 0.05. Natija: "haqiqiy sezgirlik >=95% (ishonch 95%)".
4. Narx: shu t dagi FP/bemor ham CI bilan e'lon qilinadi; FP filtri va nomzod birlashmasi t tanlashdan OLDIN muzlatiladi, FP ni kamaytiradi.
5. Kichik va katta o'choq uchun ALOHIDA chegara (hajm tabaqasi bo'yicha) — "ikkalasida ham >95%".
6. Kafolatni tekshirish: har manba (NLSTseg, LIDC, mahalliy) alohida; realizatsiya qilingan FNR eps dan yuqori bo'lsa — domen siljishi, qayta kalibrlash kerak.

## Kerakli o'choq soni (95% ishonch, maqsad: sezgirlik >=95%)
| Kalibrlash o'choqlari n | ruxsat etilgan o'tkazib yuborish | isbotlanadigan sezgirlik |
| 30 | — (isbotlab bo'lmaydi) | — |
| 59 | 0 | >=95% |
| 100 | 1 | >=95% (kuzatilgan 99%) |
| 200 | 4 | >=95% (kuzatilgan 98%) |
| 400 | 12 | >=95% (kuzatilgan 97%) |
| 715 (NLSTseg) | 25 | >=95% (kuzatilgan 96.5%) |
Har tabaqa (kichik/katta) uchun alohida n kerak: ~60–100 dan.

## Cheklovlar (halol)
- Kafolat marginal va almashinuvchanlikka bog'liq; domen siljishida (MSD, LDCT, mahalliy) buziladi -> har domenga o'z kalibrlash to'plami; mahalliyda o'choq soni 59 dan kam bo'lsa kafolat berib bo'lmaydi (qo'shimcha bemor yoki aniq "tavsifiy" deb belgilash).
- 95% sezgirlikning narxi — FP/bemor ortishi; qabul mezoni FP byudjeti bilan birga (masalan <=2/bemor).
- 2510.17897 va 2504.04482 faqat annotatsiya/qisman o'qildi; to'liq maqolalardagi aniq teorema tekshirilishi shart.
- Kalibrlash to'plami o'qitishda va chegara/filtr tanlashda ishtirok etmagan bo'lishi shart; testga tegilmaydi (S9).

## TUZATMALAR (v7.1, to'liq maqolalar o'qilgach)
1. CLS (2510.17897) kafolati voksel-darajali FNR uchun (har rasm uchun 1 - |Mask∩GT|/|GT|), o'choq-darajali emas; ehtimol kalibrlash+test tanlanmasi bo'yicha; almashinuvchanlik; siljish faqat "kelajak ish". LIDC-IDRI ishlatilgan. Matn bilan jadval o'rtasida nomuvofiqlik bor.
2. LTT (2110.01052): P(R(T_lambda)<=alpha)>=1-delta; ikkilik yo'qotishda aniq binomial dum; fixed-sequence testing; i.i.d. kalibrlash; kafolat marginal (kichik guruhlar uchun emas).
3. Bizning ta'rif: birlik = bemor, yo'qotish = "kamida bitta o'choq topilmadi" (ikkilik). Tabaqalash — kuzatiladigan nomzod hajmi bo'yicha (haqiqiy GT hajmi test paytida noma'lum).
4. Siljishda kafolat buziladi (2608.18193: 7/12 a'zo; sun'iy sinovimizda 22.8%). Shuning uchun har manbada audit, mahalliyda >=59 bemor bo'lmasa kafolat berilmaydi.
5. Og'irlangan konformal (Tibshirani 2019) kovariat siljishini faqat ehtimollik nisbati ma'lum yoki ishonchli baholanganda hal qiladi — bizda tekshirilmagan, tajriba sifatida, da'vo qilinmaydi.
6. Sun'iy sinov (sim_ltt.py): n=59..600 bemorda kafolat buzilishi 2.2–3.9% (<=5%); 25%->40% qiyin o'choq siljishida 22.8%.
