"""Rebuild the first README table (outcome of settled disputes) from data/outcome_shares_by_month.csv and compare.

Also checks the figures of the summary at the top of the README against the 12 month row, and the
'as of block' phrase in README.md and SCORECARD.md against data/state.json.
Offline, standard library only. Exits 1 on any mismatch.   python3 -I check_readme.py
"""
import csv
import datetime as dt
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HEADER = "| Period | Settled disputes | Reset | Overturned | Upheld | Midpoint | Overturned of decided | Under 7 days old, left out |"


def expected_rows():
    """The table rows as report.py writes them, from the saved CSV."""
    out = []
    for r in csv.DictReader(open(os.path.join(HERE, "data", "outcome_shares_by_month.csv"))):
        cells = [r["period"], r["settled_disputes"]] + [r[k] + "%" for k in
                 ("reset_pct", "overturned_pct", "upheld_pct", "settled_at_midpoint_pct", "decided_overturn_pct")]
        out.append("| " + " | ".join(cells + [r["younger_than_7d"]]) + " |")
    return out


def readme_rows(lines):
    """The rows under the table header in README.md (up to the first line that is not a table row)."""
    i = lines.index(HEADER) + 2   # skip the header and the separator row
    rows = []
    while i < len(lines) and lines[i].startswith("|"):
        rows.append(lines[i]); i += 1
    return rows


def check_as_of():
    """README.md and SCORECARD.md each hold one 'as of block N (D Month YYYY HH:MM UTC)' phrase,
    and it must equal data/state.json. Built independently of report.write_as_of on purpose."""
    state = json.load(open(os.path.join(HERE, "data", "state.json")))
    d = dt.datetime.fromtimestamp(state["head_ts"], dt.timezone.utc)
    months = ("January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December")
    want = f"as of block {state['head_block']:,} ({d.day} {months[d.month - 1]} {d.year} {d:%H:%M} UTC)"
    fails = 0
    for name in ("README.md", "SCORECARD.md"):
        found = re.findall(r"as of block [^)]*\)", open(os.path.join(HERE, name)).read())
        ok = found == [want]
        fails += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name} says '{want}' (found {found})")
    return fails


def main():
    lines = open(os.path.join(HERE, "README.md")).read().splitlines()
    want, got = expected_rows(), readme_rows(lines)
    fails = 0
    for w in want:
        ok = w in got
        fails += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {w}")
    if len(got) != len(want):
        print(f"FAIL  README table has {len(got)} rows, the CSV has {len(want)}"); fails += 1
    year = next(r for r in csv.DictReader(open(os.path.join(HERE, "data", "outcome_shares_by_month.csv"))) if r["period"] == "12 months")
    top = "\n".join(lines[:6])
    for v in (f'{int(year["settled_disputes"]):,}', year["reset_pct"] + "%", year["overturned_pct"] + "%", year["upheld_pct"] + "%"):
        ok = v in top
        fails += not ok
        print(f"{'PASS' if ok else 'FAIL'}  summary at the top quotes {v}")
    fails += check_as_of()
    print("All README checks passed." if not fails else f"{fails} README checks failed.")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
