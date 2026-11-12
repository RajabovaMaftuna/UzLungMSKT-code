# Yangilashdan keyin: eski admin bilan kirish, avtotest bemori va tahlillar saqlanganmi.
import json, requests, sys
B = sys.argv[1]; c = json.load(open(sys.argv[2])); s = requests.Session(); s.headers["x-uzlungct"] = "1"
r = s.post(B + "/api/auth/login", json=c); print("login", r.status_code)
p = s.post(B + "/api/patients/search", json={"q": "Avtotest"}).json(); j = s.get(B + "/api/jobs").json()
print("bemor", len(p), "tahlillar", len(j), "audit", s.get(B + "/api/audit/verify").json().get("ok"))
sys.exit(0 if r.status_code == 200 and len(p) >= 1 and len(j) >= 1 else 1)
