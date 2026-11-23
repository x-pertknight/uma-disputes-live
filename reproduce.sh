#!/usr/bin/env bash
# Offline checks of the published tables, standard library Python only, no network.
# Stops with a non zero exit on the first mismatch.
set -euo pipefail
cd "$(dirname "$0")"

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
