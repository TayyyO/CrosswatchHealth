"""Check a snapshot, score it, and publish it to the site.

Writes:
  data/runs/YYYY-MM.json  the snapshot plus scores, notes and warnings for that month
  data/latest.json        a copy of the newest month; the landing page and prototype open on it
  data/runs.json          one entry per scoring month, for the month selector and run history

Rescoring an older month updates that month's file and leaves latest.json alone.

Refuses to publish (exit code 1) when the snapshot looks wrong, so a bad pull
never replaces good data on the live site.

Usage:
    python pipeline/build_latest.py data/snapshot-2026-10.json
"""
import calendar
import json
import os
import sys
from statistics import median

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from score import months_back, months_fwd, score  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")


def month_end(m):
    y, mo = map(int, m.split("-"))
    return f"{m}-{calendar.monthrange(y, mo)[1]:02d}"


def load(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def fail(msg):
    print(f"NOT PUBLISHED: {msg}")
    sys.exit(1)


def validate(snap, previous):
    M, cats = snap["scoring_month"], snap["categories"]
    log = snap.get("run_log") or {}
    if log.get("errors"):
        fail(f"{len(log['errors'])} openFDA requests failed, for example: {log['errors'][0]}")
    for code, c in cats.items():
        if M not in c.get("ae", {}):
            fail(f"{code} has no adverse event count for {M}")
        if not isinstance(c.get("s2"), list) or len(c["s2"]) != 4:
            fail(f"{code} is missing severity windows")
    if not previous:
        return
    # Months both runs cover, excluding the last 3 of the earlier one (still filling in)
    cutoff = months_back(min(previous["scoring_month"], M), 3)
    for code, c in cats.items():
        old = previous["categories"].get(code, {}).get("ae", {})
        keys = [k for k in old if k <= cutoff and k in c["ae"]]
        a, b = sum(old[k] for k in keys), sum(c["ae"][k] for k in keys)
        if a >= 200 and not (0.7 * a <= b <= 1.3 * a):
            fail(f"{code} history changed too much ({a} reports before, {b} now). Check the pull before publishing.")


def list_change_callouts(snap, capture_date):
    """Shortage list changes FDA made after the scoring month, up to the list capture date."""
    end = month_end(snap["scoring_month"])
    added, removed = [], []
    for code, c in snap["categories"].items():
        L = c.get("list", {})
        if L.get("on") and end < L["on"] <= capture_date:
            added.append(f"{code} ({L['on']})")
        if L.get("off") and end < L["off"] <= capture_date:
            removed.append(f"{code} ({L['off']})")
    if not (added or removed):
        return []
    parts = []
    if removed:
        parts.append("removed " + ", ".join(removed))
    if added:
        parts.append("added " + ", ".join(added))
    return [{"title": "List changed after the scoring month",
             "text": f"FDA's list {' and '.join(parts)}. The next run reflects these changes."}]


def auto_warnings(snap):
    M, out = snap["scoring_month"], []
    lo = months_back(M, 11)
    for code, c in snap["categories"].items():
        ae = c["ae"]
        for m in sorted(ae):
            if m < months_back(M, 23):
                continue
            prior = [ae[k] for k in (months_back(m, i) for i in range(1, 25)) if k in ae]
            if len(prior) >= 12:
                base = median(prior)
                nbrs = [ae[k] for k in (months_back(m, 1), months_fwd(m, 1)) if k in ae]
                if ae[m] >= 50 and ae[m] > 3 * max(base, 1) and all(ae[m] > 2 * n for n in nbrs):
                    out.append(f"{code} shows a single-month spike in {m} ({ae[m]} reports against a typical {base:.0f}). "
                               "It may be summary malfunction reports and should be checked in MAUDE before review.")
        unresolved = [e[0] or "(no event number)" for e in c.get("rec", []) if e[2] == "U" and lo <= e[1][:7] <= M]
        if unresolved:
            out.append(f"{code} has recall events in the 12-month window with no class in the enforcement data: "
                       f"{', '.join(unresolved)}. They are weighted as unknown (2).")
    return out


def main(path):
    snap = load(path)
    if not snap:
        fail(f"cannot read {path}")
    lst = load(os.path.join(DATA, "shortage_list.json"), {})
    previous = load(os.path.join(DATA, "latest.json"))
    validate(snap, previous)

    M, cfg, cats = snap["scoring_month"], snap["config"], snap["categories"]
    cfg.setdefault("scoreMonth", M)
    cfg.setdefault("runDate", snap.get("retrieved"))
    capture = (snap.get("list_capture") or {}).get("date") or lst.get("capture_date", "")

    results = []
    for code, c in cats.items():
        s = score(c, M, cfg)
        results.append({"code": code, "name": c["name"], "score": round(s["score"], 1), "tier": s["tier"],
                        "convergence": s["conv"], "safety": round(s["safety"], 3), "supply": round(s["supply"], 3)})
    results.sort(key=lambda r: -r["score"])

    published = {**snap,
              "list_capture": {"date": capture, "source": lst.get("capture_source", "")},
              "scores": results,
              "callouts": list_change_callouts(snap, capture),
              "warnings": list(lst.get("warnings", [])) + auto_warnings(snap)}
    os.makedirs(os.path.join(DATA, "runs"), exist_ok=True)
    with open(os.path.join(DATA, "runs", f"{M}.json"), "w") as f:
        json.dump(published, f, indent=1)
    is_newest = not previous or M >= previous["scoring_month"]
    if is_newest:
        with open(os.path.join(DATA, "latest.json"), "w") as f:
            json.dump(published, f, indent=1)

    runs = [r for r in load(os.path.join(DATA, "runs.json"), []) if r["month"] != M]
    runs.append({"month": M, "run_date": cfg["runDate"], "config_version": cfg["version"],
                 "file": f"runs/{M}.json", "snapshot": os.path.basename(path), "list_capture": capture, "scores": results})
    runs.sort(key=lambda r: r["month"])
    with open(os.path.join(DATA, "runs.json"), "w") as f:
        json.dump(runs, f, indent=1)

    conv = [r["code"] for r in results if r["convergence"]]
    print(f"Published {M}{'' if is_newest else ' (older month; latest.json unchanged)'}: top {results[0]['code']} {results[0]['score']}, convergence {', '.join(conv) or 'none'}, "
          f"{len(published['warnings'])} warnings")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python pipeline/build_latest.py data/snapshot-YYYY-MM.json")
    main(sys.argv[1])
