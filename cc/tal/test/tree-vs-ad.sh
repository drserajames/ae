#!/usr/bin/env bash
# tree-vs-ad.sh — pixel-diff a freshly rendered report tree against its AD reference.
#
# Renders the current tal-draw output for a subtype, rasterises it and the AD
# reference at the same geometry, and reports a whole-page + per-region RMSE plus
# a (new | AD | diff) montage so fidelity work can be tracked numerically instead
# of by eyeball. Lower RMSE = closer to AD; the diff image shows WHERE it differs.
#
# WHO-DATA: inputs (.tjz/.tal) and the rendered PDFs/PNGs contain real strain
# names. This script writes ONLY to /tmp — never commit its outputs. The script
# itself carries no data and is safe to commit.
#
# Usage:  sh cc/tal/test/tree-vs-ad.sh {h3|h1|bvic|all} [dpi]
set -uo pipefail

DPI="${2:-150}"
WT="$(cd "$(dirname "$0")/../../.." && pwd)"          # ae checkout root
# Report input dirs — override via env for another machine/report. Defaults are the
# maintainer's local ssm report trees (private; not shipped with the repo).
TREE="${TREE:-$HOME/AC/eu/ac/results/ssm/2026-0805-tc1/tree}"
ADDIR="${ADDIR:-$HOME/AC/eu/ac/results/ssm/2026-0223-ssm/tree}"
TALDRAW="${TALDRAW:-$WT/build/tal-draw}"
if [ ! -d "$TREE" ] || [ ! -d "$ADDIR" ]; then
    echo "error: TREE ($TREE) or ADDIR ($ADDIR) not found — set TREE=/… ADDIR=/… to your report trees." >&2
    exit 2
fi

one() {
  local SUB="$1" TJZ TAL
  case "$SUB" in
    h3)   TJZ=h3.asr.after-2021;  TAL=h3.after-2021.tal ;;
    h1)   TJZ=h1.asr.after-2021;  TAL=h1.after-2021.tal ;;
    bvic) TJZ=bvic.after-2021;    TAL=bvic.after-2021.tal ;;
    *) echo "unknown subtype: $SUB"; return 2 ;;
  esac
  local OUT=/tmp/treediff_$SUB
  mkdir -p "$OUT"
  local AD="$ADDIR/$TJZ.pdf"

  PYTHONPATH="$WT/py" python3 -c "import sys;sys.path.insert(0,'$WT/py');from ae.report import trees;trees.make_tree('$TREE/$TJZ.tjz','$TREE/$TAL','$OUT/new.pdf',tal_draw='$TALDRAW')" \
    >/dev/null 2>"$OUT/render.log" || { echo "$SUB: render FAILED (see $OUT/render.log)"; return 1; }

  pdftoppm -png -r "$DPI" "$OUT/new.pdf" "$OUT/new" 2>/dev/null
  pdftoppm -png -r "$DPI" "$AD"          "$OUT/ad"  2>/dev/null
  local NEW="$OUT/new-1.png" ADP="$OUT/ad-1.png"

  # normalise new to AD's exact pixel geometry so regions line up
  local WH; WH=$(magick identify -format "%w %h" "$ADP"); local W=${WH% *} H=${WH#* }
  magick "$NEW" -resize "${W}x${H}!" "$OUT/new_n.png"

  printf '\n== %s (%sdpi, %sx%s) ==\n' "$SUB" "$DPI" "$W" "$H"
  local whole
  whole=$(magick compare -metric RMSE "$OUT/new_n.png" "$ADP" "$OUT/diff.png" 2>&1)
  printf '  whole   RMSE=%s\n' "$whole"

  # vertical bands (fractions of width): tree | matrix/time-series | right(clades+aa bars)
  for spec in "tree 0 38" "matrix 38 74" "right 74 100"; do
    set -- $spec; local name=$1 x0=$2 x1=$3
    local cw=$(( W*(x1-x0)/100 )) xo=$(( W*x0/100 )) m
    magick "$OUT/new_n.png" -crop "${cw}x${H}+${xo}+0" +repage "$OUT/n_$name.png"
    magick "$ADP"           -crop "${cw}x${H}+${xo}+0" +repage "$OUT/a_$name.png"
    m=$(magick compare -metric RMSE "$OUT/n_$name.png" "$OUT/a_$name.png" "$OUT/diff_$name.png" 2>&1)
    printf '  %-7s RMSE=%s\n' "$name" "$m"
  done

  magick montage "$OUT/new_n.png" "$ADP" "$OUT/diff.png" -tile 3x1 -geometry +4+4 \
    -background grey "$OUT/montage.png" 2>/dev/null
  printf '  montage + per-region diffs in %s\n' "$OUT"
}

case "${1:-h3}" in
  all) for s in h3 h1 bvic; do one "$s"; done ;;
  *)   one "${1:-h3}" ;;
esac
