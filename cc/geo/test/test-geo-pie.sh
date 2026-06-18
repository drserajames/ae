#!/bin/bash
# Verify geo-draw's clade-pie mode (TODO #1 geo-pie).
#
# Renders the synthetic pie-records.json into per-month world maps where each location is a
# clade-coloured pie with a legend, and confirms the continent single-dot mode still works.
# Output PDFs go to /tmp (no real surveillance data is used — pie-records.json is synthetic).
#
# Usage: sh cc/geo/test/test-geo-pie.sh [path-to-geo-draw]
#   Requires LOCDB_V2 to point at a locationdb so the location names resolve.
#
# Eyeball the PDFs: each pie's wedges should be sized by count and clockwise from 12 o'clock,
# every clade keeps one stable colour across both months, "3C.3a" is forced red, SYDNEY (no
# categories) stays a single continent-coloured dot, and a clade legend sits lower-left.

set -e
here="$(cd "$(dirname "$0")" && pwd)"
geo_draw="${1:-}"
if [ -z "$geo_draw" ]; then
    for cand in "$here/../../../build/geo-draw" "$here/../../../build-arm64/geo-draw" "$(command -v geo-draw 2>/dev/null)"; do
        if [ -x "$cand" ]; then geo_draw="$cand"; break; fi
    done
fi
[ -x "$geo_draw" ] || { echo "ERROR: geo-draw not found (build it first, or pass its path)"; exit 1; }

out="/tmp/geo-pie-test"
rm -f "$out"*.pdf
"$geo_draw" --data "$here/pie-records.json" --prefix "$out-" --width 1200

ls -l "$out"-2024-01.pdf "$out"-2024-02.pdf
echo "OK: rendered $out-2024-01.pdf and $out-2024-02.pdf — eyeball the pies + legend."
