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
tmp=$(mktemp -d "${TMPDIR:-/tmp}/test-draw-tree.XXXXXX")   # bare `mktemp -d` ignores TMPDIR on macOS and fails in a sandbox
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
"$bin" --settings="$tmp/mrca.json" "$here/tree-clades.json" "$tmp/mrca.pdf" 400 >/dev/null 2>&1
check "tree-clades.json (mrca_labels at MRCA(A,B))" "$tmp/mrca.pdf"
if command -v pdftotext >/dev/null 2>&1; then
    case "$(pdftotext "$tmp/mrca.pdf" - 2>/dev/null)" in
        *MRCALBL*) echo "  mrca_labels: label placed at the MRCA node" ;;
        *) echo "FAIL: mrca_labels label not rendered"; exit 1 ;;
    esac
fi

# aa-transition label-position dump (port of AD DrawAATransitions::report): a pasteable `[ … ]`
# block of one row per curated label, on stderr AND appended to <output>.taleg after the clade
# report — the manual label-moving loop reads it to get the offsets the placer chose.
# `show: false` is curation: the label is REPORTED but never drawn.
printf '{"labels": true, "clades": {"show": true}, "mrca_labels": [{"first": "A", "last": "B", "text": "SHOWNLBL", "node_id": "7.1", "pinned": true, "offset": [-0.05, 0.01]}, {"first": "C", "last": "E", "text": "HIDDENLBL", "node_id": "9.2", "show": false, "offset": [-0.02, 0.03]}]}' > "$tmp/dump.json"
"$bin" --settings="$tmp/dump.json" "$here/tree-clades.json" "$tmp/dump.pdf" 400 >/dev/null 2>"$tmp/dump.err"
check "tree-clades.json (aa-label position dump)" "$tmp/dump.pdf"
[ -f "$tmp/dump.taleg" ] || { echo "FAIL: no <output>.taleg written"; exit 1; }
for where in "$tmp/dump.taleg" "$tmp/dump.err"; do
    grep -q '>>> AA transition labels (2)' "$where" || { echo "FAIL: dump header/count missing from $where"; exit 1; }
done
# the clade report must survive: both diagnostics share one .taleg, the later one appending
grep -q '>>> Clades (' "$tmp/dump.taleg" || { echo "FAIL: aa-label dump overwrote the clade report in .taleg"; exit 1; }
# each row: echoed node_id, curated name, show/pinned, an offset+box, and the node's CURRENT extent
grep -Eq '"node_id": +"7\.1", +"name": +"SHOWNLBL", +"show": true, +"pinned": true, +"label": \{"offset": \[ *-?[0-9.]+, *-?[0-9.]+\], "\?box": \[[0-9.]+, [0-9.]+\]\}, +"first": +"A", +"last": +"B", +"\?before first": +null, +"\?after last": +"C"\}' "$tmp/dump.taleg" \
    || { echo "FAIL: shown label row malformed"; sed -n '/AA transition labels/,/^]/p' "$tmp/dump.taleg"; exit 1; }
grep -Eq '"name": +"HIDDENLBL", +"show": false, +"pinned": false,.*"first": +"C", +"last": +"E", +"\?before first": +"B", +"\?after last": +null\}' "$tmp/dump.taleg" \
    || { echo "FAIL: show:false label not reported"; exit 1; }
echo "  aa-label dump: 2 rows (1 shown, 1 show:false), appended after the clade report"
if command -v pdftotext >/dev/null 2>&1; then
    txt=$(pdftotext "$tmp/dump.pdf" - 2>/dev/null)
    case "$txt" in *HIDDENLBL*) echo "FAIL: a show:false label was drawn"; exit 1 ;; esac
    case "$txt" in *SHOWNLBL*) echo "  show:false reported but not drawn; shown label still drawn" ;;
                   *) echo "FAIL: the shown label vanished"; exit 1 ;; esac
fi

# .names output — leaf names in draw order (one per line); and ladderize reorders them
"$bin" "$here/tree-clades.json" "$tmp/order.names" >/dev/null
[ "$(tr '\n' ' ' < "$tmp/order.names")" = "A B C D E " ] || { echo "FAIL: .names draw order wrong: $(tr '\n' ' ' < "$tmp/order.names")"; exit 1; }
echo "  .names: A B C D E (draw order)"
"$bin" --ladderize=max-edge-length "$here/tree-clades.json" "$tmp/ladder.names" >/dev/null
[ "$(cat "$tmp/order.names")" != "$(cat "$tmp/ladder.names")" ] || { echo "FAIL: --ladderize=max-edge-length did not reorder"; exit 1; }
echo "  ladderize: max-edge-length reorders leaves ($(tr '\n' ' ' < "$tmp/ladder.names"))"

# --- hidden leaves and the eu-20200915 aa-transitions (cc/tree/aa-transitions.cc) ---------
# tree-aa-hidden.json: the inode with edge 9 (leaves H1,H2) is hidden by an edge_min mod and
# carries an imported O13J that flips its parent's imported J13O. acmacs-tal keeps the parent's
# label, because a hidden subtree contributes NO leaves to stage 3's flip ratio
# (Node::number_leaves, AD cc/tree.cc:755-763) -- and because Node::hide() hides the whole
# subtree, so H1/H2 are hidden too. Both are needed: count H1/H2 and the ratio is 2/5, over the
# 0.5% threshold, and the parent's substitution is dropped and reappears one level down.
printf '{"aa_transitions": {"compute": true, "method": "eu-20200915"}, "nodes": [{"select": {"edge_min": 5.0}, "apply": {"hide": true}}]}' > "$tmp/hidden.json"
"$bin" --settings="$tmp/hidden.json" --transitions-report="$tmp/hidden.tsv" "$here/tree-aa-hidden.json" "$tmp/hidden.pdf" >/dev/null
# columns: first leaf, last leaf, SHOWN leaves, labels
parent=$(awk -F'\t' '$1=="H1" && $2=="L5" {print $4}' "$tmp/hidden.tsv")
hidden_n=$(awk -F'\t' '$1=="H1" && $2=="H2" {print $3}' "$tmp/hidden.tsv")
[ "$hidden_n" = "0" ] || { echo "FAIL: hide did not reach the hidden inode's leaves (shown leaves: ${hidden_n:-<no such node>})"; exit 1; }
echo "  hidden subtree: 0 shown leaves (Node::hide reaches the whole subtree)"
case "$parent" in
    *J13O*) echo "  eu-20200915: the parent keeps J13O (hidden flip counts 0 leaves)" ;;
    *) echo "FAIL: eu-20200915 dropped the parent's J13O (labels: ${parent:-<none>})"; exit 1 ;;
esac

echo "OK: tal-draw renders valid PDFs"
