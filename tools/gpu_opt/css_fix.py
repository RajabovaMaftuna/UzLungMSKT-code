"""Mobil/planshet moslik tuzatishi: style.css oxiriga qo'shiladi (stage, o'rnatma, test nusxa). Takroriy qo'shilmaydi."""
FIX = """
/* moslashuv 1.1 (2026-11-04): telefon va planshet brauzerlari */
@media(max-width:900px){
  .side{scrollbar-width:none;-webkit-overflow-scrolling:touch}.side::-webkit-scrollbar{display:none}
  main{min-width:0}.shell>*{min-width:0}
  #train table,#eval table,#stats table,#users table,#consult table{display:block;max-width:100%;overflow-x:auto}
  img{max-width:100%;height:auto}
}
@media(max-width:600px){
  .badge{white-space:normal;max-width:100%}
  .side nav button{padding:8px 8px}
}
"""
for p in (r"C:\ZG\build_exe\stage\uzlungct\web\static\style.css", r"C:\Users\User\AppData\Local\UzLungCT\uzlungct\web\static\style.css",
          r"C:\ZG\platform_test\uzlungct\web\static\style.css"):
    t = open(p, encoding='utf-8').read()
    if 'moslashuv 1.1' not in t:
        open(p, 'w', encoding='utf-8', newline='').write(t.rstrip('\n') + '\n' + FIX)
    print('ok', p)
