#!/usr/bin/env bash
# Offline checks of the published tables, standard library Python only, no network.
# Stops with a non zero exit on the first mismatch.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 0. every required data file is present, non empty and matches its line in data/SHA256SUMS"
# Kept here, not derived from SHA256SUMS, so a file removed together with its SHA256SUMS line fails.
required="
  adapter_reset_logic.json
  block_times.csv
  checks.json
  concentration_by_month.csv
  daily_disputes_90d.csv
  daily_proposals_90d.csv
  disputes.csv
  market_type_by_month.csv
  monthly_disputes.csv
  open_disputes.csv
  outcome_shares_by_month.csv
  overturn_by_cluster.csv
  overturn_by_month.csv
  overturn_by_requester.csv
  overturn_by_requester_month.csv
  overturn_by_value_class.csv
  overturn_first_vs_later_dispute.csv
  rates.csv
  requester_labels.json
  requester_split_90d.csv
  second_source_sample.csv
  state.json
  time_to_settle_by_month.csv
  verification.json
"
# Python does the matching so the layout is exact: one "<64 hex>  <name>" line per file, and
# the hash is recomputed here, whatever sha256sum or shasum make of a malformed line in step 1.
REQUIRED="$required" python3 -I -B - <<'PY'
import hashlib, os, re, sys
required = os.environ["REQUIRED"].split()
bad = []
hashes = {}
with open("data/SHA256SUMS", "rb") as fh:
    for n, raw in enumerate(fh, 1):
        line = raw.decode("utf-8", "replace").rstrip("\n")
        m = re.fullmatch(r"([0-9a-f]{64})  (\S.*)", line)
        if not m:
            bad.append("data/SHA256SUMS line %d is malformed: %r" % (n, line))
        elif m.group(2) in hashes:
            bad.append("data/SHA256SUMS line %d repeats %s" % (n, m.group(2)))
        else:
            hashes[m.group(2)] = m.group(1)
for f in required:
    path = os.path.join("data", f)
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        bad.append("MISSING data/" + f)
    elif f not in hashes:
        bad.append("NOT IN SHA256SUMS data/" + f)
    elif hashlib.sha256(open(path, "rb").read()).hexdigest() != hashes[f]:
        bad.append("HASH MISMATCH data/" + f)
# The reverse direction, hidden files included: a data file not in the list means the list is out of date.
for f in sorted(os.listdir("data")):
    if f != "SHA256SUMS" and f not in required:
        bad.append("NOT IN THE REQUIRED LIST data/" + f)
print("\n".join(bad) if bad else "all %d required files present and matching" % len(required))
sys.exit(1 if bad else 0)
PY

echo "== 1. data files match data/SHA256SUMS"
(cd data && sha256sum -c --quiet SHA256SUMS 2>/dev/null || shasum -a 256 -c --quiet SHA256SUMS)
echo "all $(wc -l < data/SHA256SUMS | tr -d ' ') files OK"

echo "== 2. every module compiles"
python3 -I -B -c 'import glob, sys; [compile(open(f).read(), f, "exec") for f in sorted(glob.glob("*.py"))]; print(len(glob.glob("*.py")), "modules OK")'

echo "== 3. SVG charts rebuilt from data/ match the committed ones"
# charts.py writes into charts/, so it runs in a scratch copy; PNG rendering is skipped (no Chrome needed).
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
cp -R charts.py data charts "$tmp"/
(cd "$tmp" && UMA_CHROME=/usr/bin/true python3 -I -B charts.py > /dev/null)
for f in charts/*.svg; do
  cmp -s "$f" "$tmp/$f" || { echo "MISMATCH $f"; exit 1; }
  echo "same $f"
done

echo "== 4. tables rebuilt from data/disputes.csv match the committed ones"
python3 -I -B recompute_tables.py

echo "== 5. README tables match data/"
python3 -I -B check_readme.py

echo "All checks passed."
