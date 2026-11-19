"""Pull the public FDA data CrossWatch needs and write a snapshot file.

For each product code in data/shortage_list.json this script collects:
  - monthly MAUDE adverse event counts (device/event, by date_received)
  - death and injury counts for the S2 windows (device/event, by event_type)
  - recall events (device/recall) and their class (device/enforcement)
  - labelers with devices in commercial distribution (device/udi)

It writes data/snapshot-<scoring month>.json in the same shape the prototype
page and pipeline/score.py read. Standard library only.

Usage:
    python pipeline/fetch_openfda.py 2026-09
    OPENFDA_API_KEY=... python pipeline/fetch_openfda.py 2026-09   # higher rate limits

The monthly GitHub Action runs this, then pipeline/build_latest.py, which checks
the snapshot before anything is published.
"""
import calendar
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

BASE = "https://api.fda.gov/device"
KEY = os.environ.get("OPENFDA_API_KEY")
PAUSE = 0.3 if KEY else 0.6  # stay under 240 requests per minute

CONFIG = {
    "version": "0.1",
    "w": {"s1": 0.5, "s2": 0.2, "s3": 0.3, "s4": 0.6, "s5": 0.4},
    "s1": {"z": 2, "min": 5, "base": 24, "cur": 3, "minHist": 12, "minBase": 30, "poissonBelow": 10},
    "s2": {"pp": 10, "minDI": 5},
    "s3": {"w": {"I": 3, "II": 2, "III": 1, "U": 2}, "thr": 4, "div": 8, "classIMin": 0.75},
    "tiers": {"high": 60, "elev": 35, "watch": 15},
    "conv": 0.5,
}

LOG = {"requests": 0, "not_found": 0, "errors": []}


def get(endpoint, search, **params):
    """Call openFDA. Returns the parsed JSON, or None when nothing matches (HTTP 404)."""
    q = {"search": search, **params}
    if KEY:
        q["api_key"] = KEY
    # openFDA expects literal + and : in search, so keep them unescaped
    url = f"{BASE}/{endpoint}.json?" + urllib.parse.urlencode(q, safe='+:[]"()')
    for attempt in range(3):
        LOG["requests"] += 1
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                time.sleep(PAUSE)
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                LOG["not_found"] += 1
                time.sleep(PAUSE)
                return None
            if e.code == 429 and attempt < 2:
                time.sleep(10 * (attempt + 1))
                continue
            LOG["errors"].append(f"{e.code} {url}")
            return None
        except urllib.error.URLError as e:
            LOG["errors"].append(f"{e.reason} {url}")
            time.sleep(5)
    return None


def ym(d):
    return f"{d[:4]}-{d[4:6]}"


def month_range(start, end):
    y, m = map(int, start.split("-"))
    out = []
    while f"{y:04d}-{m:02d}" <= end:
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def back(mo, n):
    y, m = map(int, mo.split("-"))
    m -= n
    while m <= 0:
        y, m = y - 1, m + 12
    return f"{y:04d}-{m:02d}"


def ae_monthly(code, start, end):
    """Monthly report counts, fetched in two-year chunks of daily counts."""
    counts = defaultdict(int)
    y0, y1 = int(start[:4]), int(end[:4])
    for y in range(y0, y1 + 1, 2):
        lo, hi = f"{y}0101", f"{min(y + 1, y1)}1231"
        j = get("event", f"device.device_report_product_code:{code}+AND+date_received:[{lo}+TO+{hi}]", count="date_received")
        for row in (j or {}).get("results", []):
            counts[ym(row["time"])] += row["count"]
    return {m: counts.get(m, 0) for m in month_range(start, end)}


def death_injury(code, lo, hi):
    """(death + injury, total) reports received between two YYYY-MM months inclusive."""
    y, m = map(int, hi.split("-"))
    last = calendar.monthrange(y, m)[1]
    j = get("event", f"device.device_report_product_code:{code}+AND+date_received:[{lo.replace('-', '')}01+TO+{hi.replace('-', '')}{last:02d}]", count="event_type.exact")
    rows = {r["term"]: r["count"] for r in (j or {}).get("results", [])}
    return rows.get("Death", 0) + rows.get("Injury", 0), sum(rows.values())


def recall_events(code, since):
    """One entry per recall event: [event number, initiated, class, firm, reason]."""
    events = {}
    skip = 0
    while True:
        j = get("recall", f"product_code:{code}+AND+event_date_initiated:[{since.replace('-', '')}01+TO+29991231]", limit=1000, skip=skip)
        res = (j or {}).get("results", [])
        for r in res:
            ev = r.get("res_event_number") or ""
            d = r.get("event_date_initiated") or ""
            cur = events.get(ev)
            if not cur or d < cur[1]:
                events[ev] = [ev, d, "U", r.get("recalling_firm", ""), (r.get("reason_for_recall") or "")[:160]]
        if len(res) < 1000:
            break
        skip += 1000
    for ev in events.values():
        if not ev[0]:
            continue
        j = get("enforcement", f"event_id:{ev[0]}", limit=1)
        cls = ((j or {}).get("results") or [{}])[0].get("classification", "")
        ev[2] = {"Class I": "I", "Class II": "II", "Class III": "III"}.get(cls, "U")
    return sorted(events.values(), key=lambda e: e[1])


def labelers(code):
    j = get("udi", f'product_codes.code:{code}+AND+commercial_distribution_status:"In Commercial Distribution"', count="company_name.exact", limit=1000)
    rows = (j or {}).get("results", [])
    top = [[r["term"], r["count"]] for r in rows[:5]]
    return len(rows), top, sum(r["count"] for r in rows)


def main(score_month):
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    lst = json.load(open(os.path.join(root, "data", "shortage_list.json")))
    cats = {}
    for code, meta in lst["categories"].items():
        print(f"{code}: adverse events", flush=True)
        ae = ae_monthly(code, meta.get("ae_start", "2022-01"), score_month)
        recent = (back(score_month, 5), score_month)
        prior = (back(score_month, 29), back(score_month, 6))
        rd, rt = death_injury(code, *recent)
        pd, pt = death_injury(code, *prior)
        print(f"{code}: recalls", flush=True)
        rec = recall_events(code, "2021-01")
        print(f"{code}: labelers", flush=True)
        n, top, devices = labelers(code)
        cats[code] = {**meta, "ae": ae, "s2": [rd, rt, pd, pt], "labelers": n, "top": top, "devices": devices, "rec": rec}
        if n >= 1000:
            cats[code]["labelersPlus"] = True
    snap = {
        "schema": "crosswatch-snapshot/0.1",
        "retrieved": time.strftime("%Y-%m-%d"),
        "scoring_month": score_month,
        "config": {**CONFIG, "scoreMonth": score_month, "runDate": time.strftime("%Y-%m-%d"),
                   "provisional": [back(score_month, 1), score_month]},
        "list_capture": {"date": lst["capture_date"], "source": lst["capture_source"]},
        "run_log": LOG,
        "categories": cats,
    }
    out = os.path.join(root, "data", f"snapshot-{score_month}.json")
    with open(out, "w") as f:
        json.dump(snap, f, indent=1)
    print(f"Wrote {out}: {LOG['requests']} requests, {LOG['not_found']} empty, {len(LOG['errors'])} errors")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python pipeline/fetch_openfda.py YYYY-MM")
    main(sys.argv[1])
