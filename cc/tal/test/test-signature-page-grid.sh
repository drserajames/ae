#!/bin/sh
# Verification for the finer signature-page layout (TAL subsystem #3): compose a tree +
# an R×C grid of *captioned* antigenic maps, with a page title, via pdflatex.
#
#   sh cc/tal/test/test-signature-page-grid.sh
#
# Skips cleanly if tal-draw isn't built or pdflatex (MacTeX/TeX Live) isn't installed.
# The "maps" here are stand-in tal-draw renders (placeholders for kateri antigenic maps).
set -eu

here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../../.." && pwd)
bin="$root/bin/tal-signature-page"
taldraw="$root/build/tal-draw"

[ -x "$taldraw" ] || { echo "SKIP: $taldraw not built"; exit 0; }
command -v pdflatex >/dev/null 2>&1 || { echo "SKIP: pdflatex not installed (MacTeX/TeX Live)"; exit 0; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# three stand-in "map" PDFs (placeholders for kateri-rendered antigenic maps)
"$taldraw" --color-by-clade --clades "$here/tree-clades.json" "$tmp/m1.pdf" 300 >/dev/null
"$taldraw" --color-by-continent "$here/tree-geo.json"        "$tmp/m2.pdf" 300 >/dev/null
"$taldraw" --color-by-pos=3 "$here/tree-aa.json"             "$tmp/m3.pdf" 300 >/dev/null

# compose: tree + 3 captioned maps in a 2-column grid, with a page title
"$bin" --labels --color-by-clade --clades \
       --map "$tmp/m1.pdf" --caption "2019-2020" \
       --map "$tmp/m2.pdf" --caption "2020-2021" \
       --map "$tmp/m3.pdf" --caption "by position 3" \
       --columns 2 --page-title "H3N2 signature page" --tree-caption "phylogenetic tree" \
       "$here/tree-clades.json" "$tmp/sig.pdf" >/dev/null

[ "$(head -c4 "$tmp/sig.pdf")" = "%PDF" ] || { echo "FAIL: output is not a PDF"; exit 1; }
size=$(wc -c < "$tmp/sig.pdf")
[ "$size" -gt 1000 ] || { echo "FAIL: signature page too small ($size bytes)"; exit 1; }

# captions + title must be present in the composed text
if command -v pdftotext >/dev/null 2>&1; then
    text=$(pdftotext "$tmp/sig.pdf" - 2>/dev/null)
    for want in "H3N2 signature page" "2019-2020" "2020-2021" "by position 3" "phylogenetic tree"; do
        case "$text" in
            *"$want"*) ;;
            *) echo "FAIL: composed page missing text: $want"; exit 1 ;;
        esac
    done
    echo "OK: grid signature page composed with title + captions ($size bytes; all 5 texts present)"
else
    echo "OK: grid signature page composed ($size bytes; pdftotext absent, text not checked)"
fi
