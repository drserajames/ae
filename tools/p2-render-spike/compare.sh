#!/usr/bin/env bash
# ----------------------------------------------------------------------
# P2 render spike — pixel-compare the headless C++ map-draw renderer against a
# kateri-rendered report map figure.
#
# This is investigative scaffolding for the "can map-draw become the canonical
# ae.report figure engine?" spike (see P2-RENDER-SPIKE-PLAN.md). It renders a
# styled report chart through map-draw and diffs it against the golden PDF that
# kateri produced for the same chart+style.
#
# WHO-data note: pass the styled `.ace` and the kateri golden PDF as arguments —
# they live in a report working dir OUTSIDE the repo and are never committed.
# This script writes all output to a scratch dir, also outside the repo.
#
# Usage:
#   compare.sh <styled.ace> <kateri-golden.pdf> [out-dir] [size]
#
# Requires: map-draw (ae/build/map-draw), pdftoppm, ImageMagick (compare/montage).
# ----------------------------------------------------------------------
set -euo pipefail

STYLED_ACE=${1:?need path to a styled report .ace}
KATERI_PDF=${2:?need path to the kateri golden .pdf for the same chart+style}
OUTDIR=${3:-./p2-spike-out}
SIZE=${4:-800}

MAPDRAW=${MAPDRAW:-/Users/sarahjames/AC/eu/ae/build/map-draw}
mkdir -p "$OUTDIR"
export MAGICK_TMPDIR="$OUTDIR"

echo ">>> map-draw render (styles ignored by design — bare AD-chains render)"
# --no-populate: the report chart already carries clade attrs; skip seqdb so no env needed.
"$MAPDRAW" --no-populate --no-marks --no-vaccines --size "$SIZE" \
    "$STYLED_ACE" "$OUTDIR/mapdraw.pdf"

echo ">>> rasterise both PDFs to ${SIZE}px PNG"
pdftoppm -png -scale-to "$SIZE" "$KATERI_PDF"        "$OUTDIR/kateri"  >/dev/null 2>&1
pdftoppm -png -scale-to "$SIZE" "$OUTDIR/mapdraw.pdf" "$OUTDIR/mapdraw" >/dev/null 2>&1
KAT=$(ls "$OUTDIR"/kateri*.png | head -1)
MAP=$(ls "$OUTDIR"/mapdraw*.png | head -1)

echo ">>> RMSE (0..1; lower is closer):"
compare -metric RMSE "$KAT" "$MAP" "$OUTDIR/diff.png" 2>&1 || true
echo

echo ">>> side-by-side montage + difference heatmap"
montage "$KAT" "$MAP" -tile 2x1 -geometry +5+5 -background white "$OUTDIR/montage.png"
compare "$KAT" "$MAP" -compose src "$OUTDIR/heatmap.png"

echo ">>> wrote: $OUTDIR/{montage,heatmap,diff}.png"
