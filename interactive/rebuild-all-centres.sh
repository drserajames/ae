#!/usr/bin/env zsh
# Rebuild the 5-WHO-CC all-centres interactive viewer in one step.
#
#   ./rebuild-all-centres.sh            # build only
#   ./rebuild-all-centres.sh --open     # build then open in the browser
#
# Charts: the five WHO Collaborating Centres (cdc, cnic, crick, niid, vidrl).
# Output goes with the report data (never the repo) — see README.md.
set -e

SSM="${SSM:-$HOME/AC/eu/ac/results/ssm/2026-0223-ssm}"
OUT="$SSM/interactive"
HERE="${0:A:h}"
mkdir -p "$OUT"

"$HERE/run.sh" --tree "$SSM/tree/h3.asr.after-2021.tjz" \
  --chart "cdc=$SSM/h3-hi-guinea-pig-cdc/styled.ace" \
  --chart "cnic=$SSM/h3-hi-guinea-pig-cnic/styled.ace" \
  --chart "crick=$SSM/h3-hi-guinea-pig-crick/styled.ace" \
  --chart "niid=$SSM/h3-hi-guinea-pig-niid/styled.ace" \
  --chart "vidrl=$SSM/h3-hi-guinea-pig-vidrl/styled.ace" \
  --subtype "A(H3N2)" --assay HI --out "$OUT/h3-hi-all-centres.html"

if [[ "$1" == "--open" ]]; then
  open "$OUT/h3-hi-all-centres.html"
fi
