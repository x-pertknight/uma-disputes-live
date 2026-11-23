#!/usr/bin/env bash
# Offline checks of the published tables, standard library Python only, no network.
# Stops with a non zero exit on the first mismatch.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 0. every required data file is present, non empty and has a hash line in data/SHA256SUMS"
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
missing=0
for f in $required; do
  if [ ! -s "data/$f" ]; then echo "MISSING data/$f"; missing=1
  elif ! awk -v f="$f" '$2 == f && $1 ~ /^[0-9a-f]+$/ && length($1) == 64 { found = 1 } END { exit !found }' data/SHA256SUMS; then echo "NOT IN SHA256SUMS data/$f"; missing=1; fi
done
# The reverse direction: a data file that is not in the list means the list is out of date.
for p in data/*; do
  f="${p#data/}"
  [ "$f" = SHA256SUMS ] && continue
  case " $(echo $required) " in *" $f "*) ;; *) echo "NOT IN THE REQUIRED LIST data/$f"; missing=1;; esac
done
[ "$missing" = 0 ] || exit 1
echo "all $(echo $required | wc -w | tr -d ' ') required files present"

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
