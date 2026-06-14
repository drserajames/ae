#!/bin/sh
# Verification for tal-draw (TAL subsystem #3, Phase B M1): render a tree to PDF.
#
#   sh cc/tal/test/test-draw-tree.sh
#
# Builds nothing — expects build/tal-draw to exist (see CLAUDE.md for the arm64
# build). Asserts each test tree renders to a valid, non-trivial PDF.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../../.." && pwd)
bin="$root/build/tal-draw"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

[ -x "$bin" ] || { echo "FAIL: $bin not built"; exit 1; }

check() {
    pdf="$2"
    [ "$(head -c4 "$pdf")" = "%PDF" ] || { echo "FAIL: $1 -> not a PDF"; exit 1; }
    size=$(wc -c < "$pdf")
    [ "$size" -gt 400 ] || { echo "FAIL: $1 -> PDF too small ($size bytes)"; exit 1; }
    echo "  $1: valid PDF ($size bytes)"
}

"$bin" "$here/tree-small.newick" "$tmp/small.pdf" 400 >/dev/null
check "tree-small.newick" "$tmp/small.pdf"

"$bin" --labels "$here/tree-clades.json" "$tmp/clades.pdf" 600 >/dev/null
check "tree-clades.json (--labels)" "$tmp/clades.pdf"

# M2: leaf coloring + clades column + time-series dash column
"$bin" --labels --color-by-clade --clades --time-series "$here/tree-clades.json" "$tmp/m2.pdf" 600 >/dev/null
check "tree-clades.json (M2: color/clades/time-series)" "$tmp/m2.pdf"

# M3: title + legend + aa-transitions + rotated slot labels
"$bin" --title="test" --legend --aa-transitions --color-by-clade --clades --time-series --interval=year \
       "$here/tree-clades.json" "$tmp/m3.pdf" 700 >/dev/null
check "tree-clades.json (M3: title/legend/aa-transitions)" "$tmp/m3.pdf"

# Phase C M1: declarative JSON settings (incl. per-clade colour/display-name overrides)
"$bin" --settings="$here/draw-settings.json" "$here/tree-clades.json" "$tmp/settings.pdf" >/dev/null
check "tree-clades.json (settings DSL)" "$tmp/settings.pdf"

# Phase C M2: node select/apply mods (hide / recolour edge / restyle label)
"$bin" --settings="$here/draw-settings-nodes.json" "$here/tree-clades.json" "$tmp/nodes.pdf" >/dev/null
check "tree-clades.json (settings DSL: node select/apply)" "$tmp/nodes.pdf"

# Label-collision avoidance: default is ON; --labels-overlap turns it off (both must render)
"$bin" --labels --labels-overlap "$here/tree-clades.json" "$tmp/overlap.pdf" 400 >/dev/null
check "tree-clades.json (--labels-overlap)" "$tmp/overlap.pdf"

# hz-sections (horizontal section bands, left marker column)
"$bin" --settings="$here/draw-settings-hz.json" "$here/tree-clades.json" "$tmp/hz.pdf" >/dev/null
check "tree-clades.json (hz-sections)" "$tmp/hz.pdf"

# dash-bar-aa-at (per-leaf aa-at-position dash column) on the aa-sequence tree
"$bin" --labels --dash-bar=3 "$here/tree-aa.json" "$tmp/dash.pdf" 400 >/dev/null
check "tree-aa.json (dash-bar-aa-at pos 3)" "$tmp/dash.pdf"

# per-clade show:false hiding + positioned text labels (DrawOnTree / apply.text)
"$bin" --settings="$here/draw-settings-labels-hide.json" "$here/tree-clades.json" "$tmp/labels-hide.pdf" >/dev/null
check "tree-clades.json (per-clade hide + positioned labels)" "$tmp/labels-hide.pdf"

# colour-by-continent + legend (geo tree carries continents)
"$bin" --labels --color-by-continent --legend "$here/tree-geo.json" "$tmp/continent.pdf" 500 >/dev/null
check "tree-geo.json (--color-by-continent --legend)" "$tmp/continent.pdf"

# colour-by-pos (aa-at-position) + legend on the aa-sequence tree (pos 3: T vs A)
"$bin" --labels --color-by-pos=3 --legend "$here/tree-aa.json" "$tmp/by-pos.pdf" 500 >/dev/null
check "tree-aa.json (--color-by-pos=3 --legend)" "$tmp/by-pos.pdf"

echo "OK: tal-draw renders valid PDFs"
