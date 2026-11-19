"""Check whether FDA has updated the Medical Device Shortages List page.

FDA publishes the list only as a web page, so data/shortage_list.json is kept
by hand. This script reads the page's "Content current as of" date and compares
it with the capture date in data/shortage_list.json.

In GitHub Actions it writes changed=true|false|unknown and page_date to
$GITHUB_OUTPUT. It never fails the run: if FDA's site cannot be read, it reports
"unknown".
"""
import json
import os
import re
import sys
import urllib.request
from datetime import datetime

URL = "https://www.fda.gov/medical-devices/medical-device-supply-chain-and-shortages/medical-device-shortages-list"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def output(**kv):
    path = os.environ.get("GITHUB_OUTPUT")
    lines = [f"{k}={v}" for k, v in kv.items()]
    print("\n".join(lines))
    if path:
        with open(path, "a") as f:
            f.write("\n".join(lines) + "\n")


def main():
    captured = json.load(open(os.path.join(ROOT, "data", "shortage_list.json")))["capture_date"]
    try:
        req = urllib.request.Request(URL, headers={"User-Agent": "CrossWatch-Health-research/1.0 (+https://github.com)"})
        with urllib.request.urlopen(req, timeout=60) as r:
            html = r.read().decode("utf-8", "replace")
    except Exception as e:  # FDA's site sometimes refuses automated requests
        print(f"Could not read the FDA page: {e}", file=sys.stderr)
        return output(changed="unknown", page_date="", captured=captured)
    m = re.search(r"Content current as of:?\s*(?:<[^>]+>\s*)*(\d{1,2}/\d{1,2}/\d{4})", html)
    if not m:
        print("No 'Content current as of' date found on the page.", file=sys.stderr)
        return output(changed="unknown", page_date="", captured=captured)
    page_date = datetime.strptime(m.group(1), "%m/%d/%Y").strftime("%Y-%m-%d")
    output(changed=str(page_date > captured).lower(), page_date=page_date, captured=captured)


if __name__ == "__main__":
    main()
