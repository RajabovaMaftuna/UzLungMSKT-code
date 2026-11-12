"""Platforma statistikasi va monitoringi: vazifalar, hisobotlar, tashxislar va konsultatsiyalar bo'yicha agregat sonlar.

Faqat o'qiydi (workspace/jobs/*/job.json, report.json, review.json). Bemor identifikatori, xulosa matni va
fayl yo'llari natijaga kiritilmaydi — faqat sanalar, toifalar va sonlar.
Vaqt zonasi: Asia/Tashkent (UTC+5, yozgi vaqt yo'q).
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

TZ = dt.timezone(dt.timedelta(hours=5), "Asia/Tashkent")
GRAN = ("day", "month", "year")
MAX_DAYS = 366
DX = ("lung_cancer_suspected", "benign_lesion", "follow_up", "no_pathology", "other")
AIC = ("no_lesion", "probably_benign", "suspicious", "high_suspicion", "faqat_qoshimcha")
RADS = ("1", "2", "3", "4A", "4B", "4X")
SOURCES = ("dicom", "volume", "image", "pdf", "video")


def _load(p: Path):
    return json.load(open(p, encoding="utf-8"))


def _saved_ts(s):
    """review.json 'saved' ("YYYY-MM-DD HH:MM", mahalliy vaqt) → unix vaqt."""
    try:
        return dt.datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=TZ).timestamp()
    except (TypeError, ValueError):
        return None


def collect(home: Path):
    """Har bir vazifa uchun normallashtirilgan yozuv. Qaytaradi: (rows, skipped)."""
    rows, skipped = [], 0
    root = Path(home) / "jobs"
    if not root.exists():
        return rows, skipped
    for d in sorted(root.iterdir()):
        jf = d / "job.json"
        if not d.is_dir() or not jf.exists():
            continue
        try:
            m = _load(jf)
            r = {"id": m["id"], "t": float(m["created"]), "kind": m.get("kind"), "status": m.get("status"),
                 "owner": m.get("owner"), "split": (m.get("params") or {}).get("split"),
                 "seconds": (m.get("result") or {}).get("seconds"), "n_lesions": (m.get("result") or {}).get("n_lesions"),
                 "ai_conclusion": (m.get("result") or {}).get("ai_conclusion"), "finished": m.get("finished"),
                 "source": None, "lung_rads": None, "review_status": None, "final_diagnosis": None, "final_lung_rads": None,
                 "reviewer": None, "t_final": None, "n_confirmed_tumor": 0, "review_delay_h": None}
            if r["kind"] == "analyze":
                if (d / "report.json").exists():
                    rep = _load(d / "report.json")
                    pt = rep.get("patient") or {}
                    r["source"] = (rep.get("input") or {}).get("source", "volume")
                    r["lung_rads"] = pt.get("lung_rads")
                    r["ai_conclusion"] = r["ai_conclusion"] or pt.get("ai_conclusion")
                    r["review_status"] = rep.get("status", "pending_review")
                    r["n_lesions"] = r["n_lesions"] if r["n_lesions"] is not None else rep.get("n_lesions")
                if (d / "review.json").exists():
                    rv = _load(d / "review.json")
                    r["reviewer"] = rv.get("radiologist_login")
                    r["n_confirmed_tumor"] = sum(1 for l in rv.get("lesions") or [] if l.get("decision") == "tumor")
                    if r["review_status"] == "final":
                        r["final_diagnosis"] = rv.get("final_diagnosis")
                        r["final_lung_rads"] = rv.get("final_lung_rads")
                        r["t_final"] = _saved_ts(rv.get("saved"))
                        if r["t_final"] and r["finished"]:
                            r["review_delay_h"] = max(0.0, (r["t_final"] - float(r["finished"])) / 3600)
            rows.append(r)
        except Exception:
            skipped += 1                                  # buzilgan yoki chala fayl — hisobga olinmaydi
    return rows, skipped


def _key(ts, gran):
    d = dt.datetime.fromtimestamp(ts, TZ)
    return d.strftime({"day": "%Y-%m-%d", "month": "%Y-%m", "year": "%Y"}[gran])


def _labels(d0: dt.date, d1: dt.date, gran):
    out = []
    if gran == "day":
        n = (d1 - d0).days + 1
        if n > MAX_DAYS:
            raise ValueError("bad_params")
        out = [(d0 + dt.timedelta(days=i)).isoformat() for i in range(n)]
    elif gran == "month":
        y, m = d0.year, d0.month
        while (y, m) <= (d1.year, d1.month):
            out.append(f"{y:04d}-{m:02d}"); m += 1
            if m > 12:
                y, m = y + 1, 1
    else:
        out = [f"{y:04d}" for y in range(d0.year, d1.year + 1)]
    return out


def _date(ts):
    return dt.datetime.fromtimestamp(ts, TZ).date()


def aggregate(rows, granularity="month", date_from=None, date_to=None, consults=None, by_user=False):
    """rows — collect() natijasi (ruxsat bo'yicha oldindan filtrlangan); consults — [{t, sender}] ro'yxati.
    date_from/date_to — datetime.date (ikkalasi ham kiritiladi). ValueError("bad_params") — noto'g'ri parametrlar."""
    if granularity not in GRAN:
        raise ValueError("bad_params")
    consults = consults or []
    today = dt.datetime.now(TZ).date()
    all_t = [r["t"] for r in rows] + [c["t"] for c in consults]
    d0 = date_from or (_date(min(all_t)) if all_t else today)
    d1 = date_to or today
    if d1 < d0:
        raise ValueError("bad_params")
    labels = _labels(d0, d1, granularity)
    idx = {k: i for i, k in enumerate(labels)}
    inr = lambda ts: ts is not None and d0 <= _date(ts) <= d1
    zero = lambda: [0] * len(labels)
    series = {k: zero() for k in ("analyses", "finalized", "pending", "errors", "train", "evaluate", "consults_sent")}
    dx_series = {k: zero() for k in DX}

    def add(name, ts):
        i = idx.get(_key(ts, granularity))
        if i is not None:
            series[name][i] += 1

    an = [r for r in rows if r["kind"] == "analyze" and inr(r["t"])]
    fin = [r for r in rows if r["kind"] == "analyze" and r["review_status"] == "final" and inr(r["t_final"] or r["t"])]
    for r in rows:
        if not inr(r["t"]):
            continue
        if r["kind"] == "analyze":
            add("analyses", r["t"])
            if r["status"] == "done" and r["review_status"] != "final":
                add("pending", r["t"])
        if r["status"] == "error":
            add("errors", r["t"])
        if r["kind"] in ("train", "evaluate"):
            add(r["kind"], r["t"])
    for r in fin:
        ts = r["t_final"] or r["t"]
        add("finalized", ts)
        if r["final_diagnosis"] in dx_series:
            i = idx.get(_key(ts, granularity))
            if i is not None:
                dx_series[r["final_diagnosis"]][i] += 1
    cons = [c for c in consults if inr(c["t"])]
    for c in cons:
        add("consults_sent", c["t"])

    done = [r for r in an if r["status"] == "done"]
    secs = [r["seconds"] for r in done if isinstance(r["seconds"], (int, float))]
    delays = [r["review_delay_h"] for r in fin if r["review_delay_h"] is not None]
    users = {r["owner"] for r in rows if inr(r["t"]) and r["owner"]} | {r["reviewer"] for r in fin if r["reviewer"]} \
        | {c["sender"] for c in cons}
    users.discard("_service")
    pair = [r for r in fin if r["lung_rads"] and r["final_lung_rads"]]
    match = sum(1 for r in pair if str(r["lung_rads"]) == str(r["final_lung_rads"]))
    count = lambda items, keys: {k: sum(1 for x in items if x == k) for k in keys}
    out = {
        "granularity": granularity, "from": d0.isoformat(), "to": d1.isoformat(), "labels": labels,
        "summary": {
            "analyses": len(an), "finalized": len(fin), "pending": sum(1 for r in done if r["review_status"] != "final"),
            "train": sum(series["train"]), "evaluate": sum(series["evaluate"]), "errors": sum(series["errors"]),
            "avg_analysis_sec": round(sum(secs) / len(secs), 1) if secs else None,
            "avg_review_delay_h": round(sum(delays) / len(delays), 1) if delays else None,
            "active_users": len(users), "consults_sent": len(cons),
            "consults_received": sum(c.get("n_recipients", 1) for c in cons),
        },
        "series": series,
        "diagnoses": {"total": count([r["final_diagnosis"] for r in fin], DX), "series": dx_series},
        "ai_conclusions": count([r["ai_conclusion"] for r in done], AIC),
        "lung_rads": {"ai": count([str(r["lung_rads"]) for r in done if r["lung_rads"]], RADS),
                      "final": count([str(r["final_lung_rads"]) for r in fin if r["final_lung_rads"]], RADS)},
        "agreement": {"n": len(pair), "agree": match, "rate": round(match / len(pair), 3) if pair else None,
                      "descriptive": len(pair) < 10},
        "sources": count([r["source"] for r in done], SOURCES),
        "tz": "Asia/Tashkent",
        "generated_at": dt.datetime.now(TZ).isoformat(timespec="seconds"),
    }
    if by_user:
        bu = {}
        for r in an:
            if r["owner"]:
                bu.setdefault(r["owner"], {"analyses": 0, "finalized": 0, "consults_sent": 0})["analyses"] += 1
        for r in fin:
            if r["reviewer"]:
                bu.setdefault(r["reviewer"], {"analyses": 0, "finalized": 0, "consults_sent": 0})["finalized"] += 1
        for c in cons:
            bu.setdefault(c["sender"], {"analyses": 0, "finalized": 0, "consults_sent": 0})["consults_sent"] += 1
        bu.pop("_service", None)
        out["by_user"] = bu
    return out


def to_csv_rows(agg):
    """Agregat → CSV qatorlari (faqat sonlar): davr; har bir qator nomi."""
    names = list(agg["series"]) + [f"dx_{k}" for k in DX]
    yield ["period", *names]
    for i, lab in enumerate(agg["labels"]):
        yield [lab, *[agg["series"][n][i] for n in agg["series"]], *[agg["diagnoses"]["series"][k][i] for k in DX]]
