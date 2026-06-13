#!/bin/sh
# Opt-in LIVE kateri test for the signature page's --chart path.
#
#   TAL_TEST_KATERI=1 sh cc/tal/test/test-signature-page-kateri.sh
#
# Skipped by default: kateri is a Flutter GUI app, so this can't run in headless
# CI. It opts in via TAL_TEST_KATERI=1 and still skips cleanly if any prerequisite
# (kateri / pdfjam / tal-draw / an ae_backend-capable python3.10) is missing.
# Optimises the bundled test/chart1.ace (kateri needs a projection to draw), then
# composes tree + the kateri-rendered map into a signature page.
#
# Override the interpreter with TAL_TEST_PYTHON if your arm64 python3.10 is elsewhere.
set -eu

[ "${TAL_TEST_KATERI:-}" = "1" ] || { echo "SKIP: set TAL_TEST_KATERI=1 to run the live kateri test"; exit 0; }

here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../../.." && pwd)
bin="$root/bin/tal-signature-page"
py="${TAL_TEST_PYTHON:-/Library/Frameworks/Python.framework/Versions/3.10/bin/python3}"

command -v kateri >/dev/null 2>&1 || { echo "SKIP: kateri not on PATH"; exit 0; }
command -v pdfjam >/dev/null 2>&1 || { echo "SKIP: pdfjam not installed"; exit 0; }
[ -x "$root/build/tal-draw" ] || { echo "SKIP: tal-draw not built"; exit 0; }
[ -x "$py" ] || { echo "SKIP: python3.10 not found at $py (set TAL_TEST_PYTHON)"; exit 0; }

# Force arm64 on macOS: the framework python is universal and the ae_backend .so is arm64.
arch_prefix=""
if [ "$(uname -s)" = "Darwin" ] && command -v arch >/dev/null 2>&1; then arch_prefix="arch -arm64"; fi

$arch_prefix "$py" -c "import sys; sys.path.insert(0, '$root/build'); import ae_backend" 2>/dev/null \
    || { echo "SKIP: ae_backend not importable under $py"; exit 0; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# optimise the bundled chart so kateri has a projection to render
$arch_prefix "$py" - "$root" "$tmp/chart.ace" <<'PYEOF'
import sys, glob, importlib.util
root, out = sys.argv[1], sys.argv[2]
spec = importlib.util.spec_from_file_location("ae_backend", glob.glob(f"{root}/build/ae_backend*.so")[0])
ae = importlib.util.module_from_spec(spec); spec.loader.exec_module(ae)
chart = ae.chart_v3.Chart(f"{root}/test/chart1.ace")
chart.relax(number_of_dimensions=2, number_of_optimizations=5, minimum_column_basis="none")
chart.keep_projections(1)
chart.write(out)
PYEOF

$arch_prefix "$py" "$bin" --chart "$tmp/chart.ace" "$here/tree-clades.json" "$tmp/sig.pdf" >/dev/null

[ "$(head -c4 "$tmp/sig.pdf")" = "%PDF" ] || { echo "FAIL: output is not a PDF"; exit 1; }
size=$(wc -c < "$tmp/sig.pdf")
[ "$size" -gt 1000 ] || { echo "FAIL: signature page too small ($size bytes)"; exit 1; }
echo "OK: live kateri signature page composed (tree + kateri map, $size bytes)"
