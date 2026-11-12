# 31-promt hisoboti: SenGuard-3D 1.0.1 — CPU va GPU rejimlarining qaror darajasidagi ekvivalentligi (2026-11-04)

Namuna: NLSTseg V qismidan seed = 42 bilan oldindan tanlangan 10 bemor (`31_namuna.json`), 17 ta etalon o‘choq. C/X qismlariga tegilmadi. Natija fayli: `31_natija.json`.

| Mezon | Natija |
|---|---|
| M1: bemor darajasidagi yo‘qotish Lᵢ bir xil | **bajarildi** — 10/10 (GPU da ham, CPU da ham 3 bemorda Lᵢ = 1) |
| M2: har bir etalon o‘choq qarori bir xil | **bajarildi** — 17/17 |
| M3: model o‘choqlari soni va «asosiy» soni bir xil | **bajarilmadi** — «asosiy» soni 10/10 bir xil; o‘choqlar soni 9/10 (218368: GPU 5, CPU 6 — qo‘shimcha «qo‘shimcha» toifadagi kichik komponent) |
| M4: niqob Dice ≥ 0,999 | **bajarilmadi** — 5/10; Dice 0,975–0,9997 (mediana 0,9990); farq 1–770 voksel |

Tezlik: GPU 127–217 s (o‘rtacha 161 s), CPU 1309–2891 s (o‘rtacha 1864 s) — CPU taxminan 11,6 baravar sekin.

Talqin:
- Sertifikat qaror funksiyasiga (o‘choq topildi/topilmadi) taalluqli; bu namunada CPU rejimi barcha bemor va o‘choq qarorlarini GPU bilan bir xil takrorladi (M1, M2). Bu ekvivalentlik dalili, yangi sertifikat emas; n = 10 cheklangan namuna (17 o‘choq).
- Voksel darajasidagi farqlar (M4) va bitta qo‘shimcha kichik komponent (M3) protsessor va GPU suzuvchi nuqtali hisobining farqidan kelib chiqadi; Dice past qiymatlari kichik niqoblarda bir necha voksel farqdan (203861: 9 voksel → 0,975). 123944 da ehtimollik xaritasida bitta joyda 0,81 gacha farq kuzatildi, niqob farqi 28 voksel, qarorlar bir xil — sababi tekshirilmagan.
- Platformada CPU rejimi natijalari «GPU bilan qaror darajasida mos (V, n = 10); sertifikat GPU quvuri uchun» deb talqin qilinadi.
- Cheklov: topish mezoni bu yerda niqob bo‘yicha (detektor ellipsoidlarisiz); detektor qutilari soni barcha bemorda bir xil (10/10).

## Qo‘shimcha: 123944 dagi ehtimollik farqi sababi (tahlil 2026-11-04)
- Farq > 0,1 bo‘lgan 94 vokselning **barchasi (94/94)** niqob chegarasida (±2 voksel) joylashgan; eng katta farq (GPU 0,134, CPU 0,944) o‘simta chegarasidagi bitta vokselda.
- Sabab: kesish sohasi Ω_L TotalSegmentator o‘pka niqobidan olinadi; CPU va GPU dagi o‘pka niqobi biroz farq qilgani uchun Ω_L chegarasi 3 vokselga siljigan (y bo‘yicha 498 va 495). Natijada nnU-Net sirpanuvchi oynalari boshqa joyda boshlanadi va chegara vokselidagi ehtimollik Gauss vaznli yig‘ishda boshqacha chiqadi. τ₁ = 0,05 dan o‘tish 21 vokselda farq qildi, o‘choq qarorlariga ta’sir qilmadi.
- Bartaraf etish: farqni to‘liq yo‘qotish uchun Ω_L chegaralarini qat’iy to‘rga (masalan, 16 voksel) yaxlitlash kerak. Bu GPU natijalarini ham o‘zgartiradi, ya’ni sertifikatlangan quvurni o‘zgartirish bo‘ladi; C ∪ X qismlari bir marta ishlatilgani uchun qayta sertifikatlash yangi mustaqil ma’lumot talab qiladi. Shu sababli 1.0.1 ga kiritilmadi; 1.1 versiya uchun tavsiya sifatida qayd etildi. Joriy holatda qarorlar darajasidagi ekvivalentlik (M1, M2) saqlanadi.
