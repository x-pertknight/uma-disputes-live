"""Rebuild the first README table (outcome of settled disputes) from data/outcome_shares_by_month.csv and compare.

Also checks the figures of the summary at the top of the README against the 12 month row.
Offline, standard library only. Exits 1 on any mismatch.   python3 -I check_readme.py
"""
import csv
import os
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
    print("All README checks passed." if not fails else f"{fails} README checks failed.")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
