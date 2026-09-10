#! /usr/bin/env python3
"""T9c end-to-end check against the real downstream use case.

Mirrors chain-pages-repro's `fixing_maps.py:method_reference_panel`: build a map
from the reference antigens (those with a homologous antiserum) + all sera, freeze
*only those antigens*, incrementally add the test antigens, relax, and confirm the
sera are still free to move.  Read-only w.r.t. chain-pages-repro.

Usage:
    AE_BUILD=build python3 test/t9c-reference-panel-check.py [merge.ace]
"""

import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.environ.get("AE_BUILD", os.path.join(ROOT, "build")))
import ae_backend  # noqa: E402

MERGE = sys.argv[1] if len(sys.argv) > 1 else (
    "/Users/sarahjames/AC/projects/chain-pages-repro/cdc/h3-hint/out/h3-hint-cdc-merge.ace")
N_OPT_REF = 20        # optimisations for the reference-panel map
N_OPT_INCR = 20       # optimisations for the incremental placement of test antigens


def key(name):
    """strain+passage identity, as chain-pages-repro's _strain_passage_key does"""
    return name.split(" (")[0].strip().upper()


def layout_coords(chart, projection_no=0):
    return [list(c) for c in chart.projection(projection_no).layout()]


def finite(pt):
    return all(not math.isnan(v) for v in pt)


merged = ae_backend.chart_v3.Chart(MERGE)
n_ag, n_sr = merged.number_of_antigens(), merged.number_of_sera()
print(f"merged chart: {os.path.basename(MERGE)}  {n_ag} antigens x {n_sr} sera")

ag_by_key = {}
for i, ag in merged.select_all_antigens():
    ag_by_key.setdefault(key(ag.name()), []).append(i)
serum_keys = {key(sr.name()) for _, sr in merged.select_all_sera()}
ref_ag = sorted({i for k in serum_keys for i in ag_by_key.get(k, [])})
test_ag = [i for i in range(n_ag) if i not in set(ref_ag)]
print(f"reference antigens (homologous to a serum): {len(ref_ag)};  test antigens: {len(test_ag)}")
assert ref_ag and test_ag, "need both a reference panel and test antigens"

# --- reference-panel map: reference antigens + all sera, well optimised -------
ref = ae_backend.chart_v3.Chart(merged)
ref.remove_antigens_sera(antigens=ref.select_antigens(lambda d, s=set(test_ag): d.no in s))
ref.relax(number_of_dimensions=2, number_of_optimizations=N_OPT_REF, minimum_column_basis="none")
ref.keep_projections(1)
print(f"reference map: {ref.number_of_antigens()}ag x {ref.number_of_sera()}sr  "
      f"stress {ref.projection(0).stress():.2f}")

# --- test-only side: same table minus the reference antigens (disjoint) -------
test_only = ae_backend.chart_v3.Chart(merged)
test_only.remove_antigens_sera(antigens=test_only.select_antigens(lambda d, s=set(ref_ag): d.no in s))

incr = ae_backend.chart_v3.merge(ref, test_only, match="auto", merge_type="incremental",
                                 combine_cheating_assays=False, sd_limit=float("nan"))[0]
i_ag, i_sr = incr.number_of_antigens(), incr.number_of_sera()
print(f"incremental merge: {i_ag}ag x {i_sr}sr")

start = layout_coords(incr)
frozen_ag = [p for p in range(i_ag) if finite(start[p])]          # reference antigens
nan_ag = [p for p in range(i_ag) if not finite(start[p])]          # test antigens to place
sera_pts = list(range(i_ag, i_ag + i_sr))
print(f"antigens with coordinates (to freeze): {len(frozen_ag)};  "
      f"antigens at NaN (to place): {len(nan_ag)};  sera: {len(sera_pts)}")


def report(label, chart, before):
    after = layout_coords(chart)
    ag_moves = [math.dist(before[p], after[p]) for p in frozen_ag]
    sr_moves = [math.dist(before[p], after[p]) for p in sera_pts]
    placed = [p for p in nan_ag if finite(after[p])]
    spread = 0.0
    if placed:
        xs = [after[p][0] for p in placed]
        ys = [after[p][1] for p in placed]
        spread = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
    print(f"\n--- {label} ---")
    print(f"  frozen reference antigens: max move {max(ag_moves):.3e}  mean {sum(ag_moves)/len(ag_moves):.3e}")
    print(f"  sera:                      max move {max(sr_moves):.6f}  mean {sum(sr_moves)/len(sr_moves):.6f}")
    print(f"  test antigens placed:      {len(placed)}/{len(nan_ag)}  bounding-box diagonal {spread:.3f}")
    print(f"  projection stress:         {chart.projection(0).stress():.4f}")
    return max(ag_moves), max(sr_moves), len(placed), spread, chart.projection(0).stress()


# --- the fix: freeze only the reference antigens -----------------------------
new = ae_backend.chart_v3.Chart(incr)
new.relax_incremental(0, number_of_optimizations=N_OPT_INCR, unmovable_points=frozen_ag)
ag_max, sr_max, placed, spread, stress = report(
    "unmovable_points = reference antigens only  (T9c, the fix)", new, start)

# --- the old behaviour, for contrast -----------------------------------------
old = ae_backend.chart_v3.Chart(incr)
old.relax_incremental(0, number_of_optimizations=N_OPT_INCR, unmovable_non_nan_points=True)
o_ag_max, o_sr_max, o_placed, o_spread, o_stress = report(
    "unmovable_non_nan_points=True  (what was available before)", old, start)

# --- verdict ------------------------------------------------------------------
print()
ok = True


def check(name, cond, detail):
    global ok
    print(f"{'PASS' if cond else 'FAIL'}  {name}: {detail}")
    ok = ok and cond


check("frozen reference antigens do not move", ag_max < 1e-9, f"max move {ag_max:.3e}")
check("sera DO move (this is the fix)", sr_max > 1e-3, f"max serum move {sr_max:.6f}")
# ae disconnects antigens with too few numeric titers (disconnect_too_few_numeric_titers
# defaults to yes), and those stay at NaN on both paths -- so compare against the old path
# rather than demanding every antigen be placed.
new_coords = layout_coords(new)
unplaced = [p for p in nan_ag if not finite(new_coords[p])]
titer_counts = sorted(
    sum(1 for sr in range(i_sr) if not incr.titers().titer(p, sr).is_dont_care())
    for p in unplaced)
check("test antigens placed: no worse than the old path", placed >= o_placed,
      f"{placed}/{len(nan_ag)} vs {o_placed}/{len(nan_ag)} with unmovable_non_nan_points=True")
check("the few unplaced antigens are ae's too-few-titers disconnects",
      all(c < 3 for c in titer_counts),
      f"{len(unplaced)} unplaced, numeric-titer counts {titer_counts}")
check("placed test antigens are non-degenerate", spread > 1.0, f"bbox diagonal {spread:.3f}")
check("stress is finite", math.isfinite(stress), f"{stress:.4f}")
check("old path froze the sera (limitation reproduced)", o_sr_max < 1e-9,
      f"max serum move with unmovable_non_nan_points=True: {o_sr_max:.3e}")

print()
print("OK" if ok else "FAILURES ABOVE")
sys.exit(0 if ok else 1)
