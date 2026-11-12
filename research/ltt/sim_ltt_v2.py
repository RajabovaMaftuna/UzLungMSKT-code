# 2-maqola, 3.3/4.1-bo'lim: LTT kafolati buzilishining qayta tiklanadigan simulyatsiyasi (2026-11-12).
# Model: bemor "qiyin" (ehtimol pi) yoki "oson"; o'tkazib yuborish ehtimoli r_h yoki r_e.
# Kafolat: kalibrlash tanlanmasida k <= k*(n, eps, delta) bo'lsa beriladi (aniq binomial, H0: R > eps).
# Buzilish: kafolat berilgan VA maqsad domenidagi haqiqiy xavf R_T > eps.
import json, numpy as np
from scipy.stats import binom
SEED, REPS, EPS, DELTA = 20261112, 20000, 0.10, 0.05
NS = [59, 81, 135, 236, 400, 600]
SC = {  # nom: (r_e, r_h, pi_kalibrlash, pi_qollash)
    "almashinuvchan": (0.04, 0.30, 0.25, 0.25),   # R_S = R_T = 0,105 > eps: LTT uchun eng noqulay holat
    "siljish":        (0.04, 0.24, 0.25, 0.40),   # R_S = 0,090 <= eps < R_T = 0,120
}
R = lambda re, rh, pi: (1 - pi) * re + pi * rh
def kstar(n):
    k = -1
    while binom.cdf(k + 1, n, EPS) <= DELTA: k += 1
    return k
rng = np.random.default_rng(SEED); out = {"seed": SEED, "reps": REPS, "eps": EPS, "delta": DELTA, "natija": []}
for nom, (re, rh, pc, pq) in SC.items():
    RS, RT = R(re, rh, pc), R(re, rh, pq)
    for n in NS:
        k = kstar(n)
        hard = rng.random((REPS, n)) < pc
        miss = rng.random((REPS, n)) < np.where(hard, rh, re)
        cert = miss.sum(1) <= k
        v_mc = float(cert.mean()) * (RT > EPS)
        v_ex = float(binom.cdf(k, n, RS)) * (RT > EPS)
        se = (v_mc * (1 - v_mc) / REPS) ** 0.5
        out["natija"].append({"sharoit": nom, "r_e": re, "r_h": rh, "pi_S": pc, "pi_T": pq, "R_S": round(RS, 4), "R_T": round(RT, 4),
                              "n": n, "k_star": k, "V_mc": round(v_mc, 4), "V_mc_se": round(se, 4), "V_aniq": round(v_ex, 4)})
        print(nom, n, k, round(RS, 3), round(RT, 3), f"MC {100*v_mc:.1f}% (SE {100*se:.2f})", f"aniq {100*v_ex:.1f}%")
json.dump(out, open("sim_ltt_v2.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
