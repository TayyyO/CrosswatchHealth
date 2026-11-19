"""CrossWatch scoring, Risk Scoring Specification v0.1.

Reads a snapshot produced by fetch_openfda.py (or the committed
data/snapshot-2026-09.json) and prints the combined score, tier and
convergence flag for every category, plus the retrospective test.

This is the reference implementation. The prototype page runs the same
logic in JavaScript; both should give identical results.

Usage:
    python pipeline/score.py data/snapshot-2026-09.json
"""
import json
import math
import sys
from statistics import mean, pstdev


def months_back(m, n):
    y, mo = map(int, m.split("-"))
    mo -= n
    while mo <= 0:
        y, mo = y - 1, mo + 12
    return f"{y:04d}-{mo:02d}"


def months_fwd(m, n):
    y, mo = map(int, m.split("-"))
    mo += n
    while mo > 12:
        y, mo = y + 1, mo - 12
    return f"{y:04d}-{mo:02d}"


def s1(cat, M, cfg):
    """Adverse event trend: last 3 months vs the 24 months before them."""
    c = cfg["s1"]
    ae = cat["ae"]
    hist = [k for k in ae if k <= M]
    cur = [ae[months_back(M, i)] for i in range(3) if months_back(M, i) in ae]
    base = [ae[months_back(M, i)] for i in range(c["cur"], c["cur"] + c["base"]) if months_back(M, i) in ae]
    if len(hist) < c["minHist"] or len(cur) < 3 or len(base) < 12 or sum(base) < c["minBase"]:
        return {"status": "insufficient", "comp": 0.0, "elev": False, "z": None}
    mu, sd, c3 = mean(base), pstdev(base), mean(cur)
    if mu < c["poissonBelow"] or sd == 0:
        z = (c3 * 3 - 3 * mu) / math.sqrt(3 * mu)
    else:
        z = (c3 - mu) / sd
    elev = z >= c["z"] and c3 >= c["min"]
    return {"status": "ok", "z": z, "comp": min(1.0, z / (2 * c["z"])) if elev else 0.0, "elev": elev}


def s2(cat, cfg):
    """Severity mix: death and injury share, recent 6 months vs prior 24."""
    rd, rt, pd, pt = cat["s2"]
    d = (rd / rt * 100 if rt else 0.0) - (pd / pt * 100 if pt else 0.0)
    elev = d >= cfg["s2"]["pp"] and rd >= cfg["s2"]["minDI"]
    return {"delta": d, "comp": min(1.0, d / (2 * cfg["s2"]["pp"])) if elev else 0.0, "elev": elev}


def s3(cat, M, cfg):
    """Recall activity: weighted recall events in the last 12 months."""
    c = cfg["s3"]
    lo = months_back(M, 11)
    ev = [e for e in cat["rec"] if lo <= e[1][:7] <= M]
    wc = sum(c["w"][e[2]] for e in ev)
    c1 = any(e[2] == "I" for e in ev)
    comp = min(1.0, wc / c["div"])
    if c1:
        comp = max(comp, c["classIMin"])
    return {"weighted": wc, "classI": c1, "comp": comp, "elev": c1 or wc >= c["thr"]}


def s4(cat, M):
    """List status as of the end of month M."""
    L, end = cat["list"], M + "-31"
    if L.get("on") and L["on"] <= end and not L.get("offUnknown") and (not L.get("off") or L["off"] > end):
        return 1.0
    if L.get("off") and L["off"] <= end and L["off"][:7] > months_back(M, 12):
        return 0.4
    return 0.0


def s5(n):
    return 1.0 if n == 1 else 0.7 if n == 2 else 0.4 if n <= 4 else 0.1


def score(cat, M, cfg, include_s4=True):
    w = cfg["w"]
    a, b, r = s1(cat, M, cfg), s2(cat, cfg), s3(cat, M, cfg)
    safety = w["s1"] * a["comp"] + w["s2"] * b["comp"] + w["s3"] * r["comp"]
    supply = (w["s4"] * s4(cat, M) if include_s4 else 0) + w["s5"] * s5(cat["labelers"])
    total = 100 * (0.5 * safety + 0.5 * supply)
    conv = safety >= cfg["conv"] and supply >= cfg["conv"]
    t = cfg["tiers"]
    tier = "High" if total >= t["high"] or conv else "Elevated" if total >= t["elev"] else "Watch" if total >= t["watch"] else "Low"
    return {"score": total, "tier": tier, "conv": conv, "safety": safety, "supply": supply, "s1": a, "s2": b, "s3": r}


def retro(cat, start, end, cfg):
    """Point-in-time back-test with S4 excluded. S2 is not available monthly yet."""
    rows, m = [], start
    w = cfg["w"]
    while m <= end:
        a, r = s1(cat, m, cfg), s3(cat, m, cfg)
        safety = w["s1"] * a["comp"] + w["s3"] * r["comp"]
        supply = w["s5"] * s5(cat["labelers"])
        rows.append({"month": m, "s1": a["elev"], "s3": r["elev"], "score": 100 * (0.5 * safety + 0.5 * supply)})
        m = months_fwd(m, 1)
    return rows


def main(path):
    snap = json.load(open(path))
    cfg, M, cats = snap["config"], snap["scoring_month"], snap["categories"]
    results = sorted(((c, score(cats[c], M, cfg)) for c in cats), key=lambda x: -x[1]["score"])
    print(f"Scoring month {M}, config v{cfg['version']}")
    print(f"{'code':<5} {'score':>6}  {'tier':<9} conv  safety supply")
    for c, s in results:
        print(f"{c:<5} {s['score']:>6.1f}  {s['tier']:<9} {'yes ' if s['conv'] else 'no  '}  {s['safety']:.2f}   {s['supply']:.2f}")
    print()
    for code, listed, start, end in [("FJK", "2025-03", "2024-03", "2026-09"), ("MDB", "2024-07", "2022-03", "2025-06")]:
        rows = retro(cats[code], start, end, cfg)
        for sig in ("s1", "s3"):
            first = next((r["month"] for r in rows if r[sig]), None)
            print(f"Retrospective {code} (listed {listed}): {sig.upper()} first crossed {first or 'never'}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/snapshot-2026-09.json")
