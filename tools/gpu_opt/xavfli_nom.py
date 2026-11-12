import ast
P = [("web\\static\\i18n.js", '"ai.prob": "Xavflilik ehtimoli"', '"ai.prob": "Xavfli o‘simta ehtimoli"'),
     ("web\\report.py", "'prob': 'Xavflilik ehtimoli'", "'prob': 'Xavfli o‘simta ehtimoli'"),
     ("diagnosis.py", "xavflilik ehtimoli (%)", "xavfli o‘simta ehtimoli (%)")]
n = 0
for r in (r"C:\ZG\build_exe\stage\uzlungct", r"C:\Users\User\AppData\Local\UzLungCT\uzlungct"):
    for f, o, w in P:
        p = r + "\\" + f; t = open(p, encoding="utf-8").read()
        if o in t:
            t = t.replace(o, w); open(p, "w", encoding="utf-8", newline="").write(t); n += 1
        if p.endswith(".py"): ast.parse(t)
print("almashtirildi", n, "sintaksis OK")
