# UzLungCT yakuniy ilmiy hisobot (2026-11-02)
Tizim SenGuard-3D (ichki identifikator N8; model kartasi docs\22): M2-500 (5 fold, p>=0.05) ∪ K1 ∪ TS lung_nodules ∪ MONAI RetinaNet (ball>=0.9).
| To'plam | Bemor | O'tkazish | Holat |
|---|---|---|---|
| NLSTseg C∪X, o'pka o'choqlari | 236 | 3 (1.3%), 95% yuqori 3.3% | H1 >=90% SERTIFIKAT |
| S2 toifa | 135 | 3 (2.2%), p=0.090 | H2 o'tmadi |
| O'pka o'choqlari >=95% | 236 | - | H3 sinalmadi; tavsifiy |
| NLSTseg barcha label | 241 | 5 (2.1%) | tavsifiy |
| FP/bemor C/X | - | ~4.3 | tavsifiy |
| FDG-C | 81 | 27 (33.3%), yuqori 42.9% | sertifikat yo'q |
| Mahalliy audit | 6 | 0; o'choq 7/7 | tavsifiy, n juda kichik |
| Yopiq test | 3 | 0; 3/3 | tavsifiy; 3/3 da 95% quyi chegara ~37% |
Ochiq yoziladi: ta'rif (o'pka>=50%) va S2 T natijasini ko'rib tanlangan; H2/H3 tartibi; T/V/C∪X farqi sababi noma'lum; detektor mezoni R7 ga o'xshash, aynan emas; T da TTA, V/C/X da TTA yo'q; M3 rad etilgan; l10 da tumor_gt xatosi natija ko'rilmasdan tuzatilgan; mahalliy 8 tadqiqotdan 2 tasi o'choq mezonidan o'tmagan. Kontur uchun C mezoni (Dice) sertifikatlanmagan.
Klinik ishlatish uchun ruxsat emas; shifokor nazorati majburiy.
