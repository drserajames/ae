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
bin="${TAL_DRAW:-$root/build/tal-draw}"
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

# colour-by-continent + geo inset (continent-coloured world map lower-left; doubles as the legend)
"$bin" --labels --color-by-continent --geo-inset "$here/tree-geo.json" "$tmp/geo-inset.pdf" 500 >/dev/null
check "tree-geo.json (--color-by-continent --geo-inset)" "$tmp/geo-inset.pdf"

# continent legend (top-right) + clade bracket column together (the report tree-page shape):
# curated clades via per-clade hide/display-name, leaves coloured by continent, legend shown.
printf '{"color_by_continent": true, "legend": {"show": true}, "clades": {"show": true}, "time_series": {"show": true}, "clade_styles": [{"name": "C2", "hide": true}, {"name": "C1", "display_name": "c-one"}]}' > "$tmp/legend-clades.json"
"$bin" --settings="$tmp/legend-clades.json" "$here/tree-geo.json" "$tmp/legend-clades.pdf" 600 >/dev/null
check "tree-geo.json (continent legend top-right + clade column)" "$tmp/legend-clades.pdf"

# colour-by-pos (aa-at-position) + legend on the aa-sequence tree (pos 3: T vs A)
"$bin" --labels --color-by-pos=3 --legend "$here/tree-aa.json" "$tmp/by-pos.pdf" 500 >/dev/null
check "tree-aa.json (--color-by-pos=3 --legend)" "$tmp/by-pos.pdf"

# nodes.select {edge_min} — hide the long-edge outlier; OUTLIER must be gone, E1-E3 kept
printf '{"labels": true, "nodes": [{"select": {"edge_min": 1.0}, "apply": {"hide": true}}]}' > "$tmp/edge-hide.json"
"$bin" --settings="$tmp/edge-hide.json" "$here/tree-edges.json" "$tmp/edge.pdf" 300 >/dev/null
check "tree-edges.json (edge_min hides long-edge outlier)" "$tmp/edge.pdf"
if command -v pdftotext >/dev/null 2>&1; then
    txt=$(pdftotext "$tmp/edge.pdf" - 2>/dev/null)
    case "$txt" in
        *OUTLIER*) echo "FAIL: edge_min did not hide OUTLIER"; exit 1 ;;
        *E1*) echo "  edge_min: OUTLIER hidden, kept leaves present" ;;
        *) echo "FAIL: edge_min hid too much"; exit 1 ;;
    esac
fi

# mrca_labels — curated on-tree label placed at MRCA(first,last) (draw-aa-transitions per-node).
# tree-clades.json: leaves A,B share a parent; a label at MRCA(A,B) must render its text.
printf '{"labels": true, "mrca_labels": [{"first": "A", "last": "B", "text": "MRCALBL"}]}' > "$tmp/mrca.json"
"$bin" --settings="$tmp/mrca.json" "$here/tree-clades.json" "$tmp/mrca.pdf" 400 >/dev/null
check "tree-clades.json (mrca_labels at MRCA(A,B))" "$tmp/mrca.pdf"
if command -v pdftotext >/dev/null 2>&1; then
    case "$(pdftotext "$tmp/mrca.pdf" - 2>/dev/null)" in
        *MRCALBL*) echo "  mrca_labels: label placed at the MRCA node" ;;
        *) echo "FAIL: mrca_labels label not rendered"; exit 1 ;;
    esac
fi

# .names output — leaf names in draw order (one per line); and ladderize reorders them
"$bin" "$here/tree-clades.json" "$tmp/order.names" >/dev/null
[ "$(tr '\n' ' ' < "$tmp/order.names")" = "A B C D E " ] || { echo "FAIL: .names draw order wrong: $(tr '\n' ' ' < "$tmp/order.names")"; exit 1; }
echo "  .names: A B C D E (draw order)"
"$bin" --ladderize=max-edge-length "$here/tree-clades.json" "$tmp/ladder.names" >/dev/null
[ "$(cat "$tmp/order.names")" != "$(cat "$tmp/ladder.names")" ] || { echo "FAIL: --ladderize=max-edge-length did not reorder"; exit 1; }
echo "  ladderize: max-edge-length reorders leaves ($(tr '\n' ' ' < "$tmp/ladder.names"))"

echo "OK: tal-draw renders valid PDFs"
