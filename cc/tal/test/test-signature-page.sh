#!/bin/sh
# Verification for bin/tal-signature-page (TAL subsystem #3): compose a tree + a
# (stand-in) antigenic map into one signature-page PDF.
#
#   sh cc/tal/test/test-signature-page.sh
#
# Skips cleanly if tal-draw isn't built or pdfjam (MacTeX/TeX Live) isn't installed.
# The map here is a stand-in tal-draw render; in production it is a kateri-rendered
# antigenic-map PDF (passed via --map, or produced from a chart via --chart).
set -eu

here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../../.." && pwd)
bin="$root/bin/tal-signature-page"
taldraw="$root/build/tal-draw"

[ -x "$taldraw" ] || { echo "SKIP: $taldraw not built"; exit 0; }
command -v pdfjam >/dev/null 2>&1 || { echo "SKIP: pdfjam not installed (MacTeX/TeX Live)"; exit 0; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# stand-in "map" PDF (placeholder for the kateri-rendered antigenic map)
"$taldraw" --color-by-clade --clades "$here/tree-clades.json" "$tmp/map.pdf" 400 >/dev/null

# compose tree + map side by side, highlighting two strains on the tree
"$bin" --labels --color-by-clade --clades --mark "A,E" --map "$tmp/map.pdf" \
       "$here/tree-clades.json" "$tmp/sig.pdf" >/dev/null

[ "$(head -c4 "$tmp/sig.pdf")" = "%PDF" ] || { echo "FAIL: output is not a PDF"; exit 1; }
size=$(wc -c < "$tmp/sig.pdf")
[ "$size" -gt 1000 ] || { echo "FAIL: signature page too small ($size bytes)"; exit 1; }
echo "OK: signature page composed (tree + map, $size bytes)"
