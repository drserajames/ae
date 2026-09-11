#! /usr/bin/env python3
"""T9c regression test: an explicit, caller-specified subset of points can be held
fixed through Chart.relax_incremental().

Before this change the only Python-exposed freezing mechanism was
relax_incremental(unmovable_non_nan_points=True), which freezes *every* point that
has coordinates.  Projection.set_unmovable() existed but relax_incremental ignored
it: the pybind lambda passed a hardcoded empty ae::unmovable_points{} to
Chart::relax_incremental, which never looks at the source projection's own set.

Run:  PYTHONPATH=build python3 test/t9c-per-point-unmovable.py
"""

import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.environ.get("AE_BUILD", os.path.join(ROOT, "build")))
import ae_backend  # noqa: E402

CHART = os.path.join(ROOT, "test", "chart1.ace")
PINNED_AT = [50.0, 50.0]

failures = []


def check(name, ok, detail):
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
    if not ok:
        failures.append(name)


def displaced_chart():
    """chart1 relaxed once, then antigen 0 dragged far away from its optimum."""
    chart = ae_backend.chart_v3.Chart(CHART)
    chart.relax(number_of_dimensions=2, number_of_optimizations=1, minimum_column_basis="none")
    chart.projection(0).set_coordinates(0, PINNED_AT)
    return chart


def coords(chart, point_no, projection_no=0):
    return list(chart.projection(projection_no).layout()[point_no])


def moved(chart, point_no, reference):
    return math.dist(coords(chart, point_no), reference)


# ---------------------------------------------------------------- baseline
chart = displaced_chart()
chart.relax_incremental(0, number_of_optimizations=1)
check("baseline: nothing pinned -> antigen 0 moves",
      moved(chart, 0, PINNED_AT) > 1.0,
      f"antigen 0 moved {moved(chart, 0, PINNED_AT):.4f} away from {PINNED_AT}")

# ------------------------------------------- explicit unmovable_points list
chart = displaced_chart()
chart.relax_incremental(0, number_of_optimizations=1, unmovable_points=[0])
check("unmovable_points=[0] -> antigen 0 stays put",
      moved(chart, 0, PINNED_AT) < 1e-12,
      f"antigen 0 at {coords(chart, 0)}")

# ------------------------------- default None inherits set_unmovable() set
chart = displaced_chart()
chart.projection(0).set_unmovable([0])
chart.relax_incremental(0, number_of_optimizations=1)
check("set_unmovable([0]) is honoured by default -> antigen 0 stays put",
      moved(chart, 0, PINNED_AT) < 1e-12,
      f"antigen 0 at {coords(chart, 0)}")

# --------------------------------------- explicit [] overrides set_unmovable
chart = displaced_chart()
chart.projection(0).set_unmovable([0])
chart.relax_incremental(0, number_of_optimizations=1, unmovable_points=[])
check("unmovable_points=[] overrides set_unmovable -> antigen 0 moves",
      moved(chart, 0, PINNED_AT) > 1.0,
      f"antigen 0 moved {moved(chart, 0, PINNED_AT):.4f}")

# ------------------- the point of the exercise: pin antigens, let sera move
chart = displaced_chart()
n_ag = chart.number_of_antigens()
n_sr = chart.number_of_sera()
before = [coords(chart, p) for p in range(n_ag + n_sr)]
chart.relax_incremental(0, number_of_optimizations=1, unmovable_points=list(range(n_ag)))
after = [coords(chart, p) for p in range(n_ag + n_sr)]
ag_max = max(math.dist(before[p], after[p]) for p in range(n_ag))
sr_max = max(math.dist(before[p], after[p]) for p in range(n_ag, n_ag + n_sr))
check("pin all antigens -> antigens frozen",
      ag_max < 1e-12, f"largest antigen movement {ag_max:.3e}")
check("pin all antigens -> sera still free to move",
      sr_max > 1e-6, f"largest serum movement {sr_max:.6f}")

# --------------------------------------------- unmovable_non_nan_points is unchanged
chart = displaced_chart()
before = [coords(chart, p) for p in range(n_ag + n_sr)]
chart.relax_incremental(0, number_of_optimizations=1, unmovable_non_nan_points=True)
after = [coords(chart, p) for p in range(n_ag + n_sr)]
all_max = max(math.dist(before[p], after[p]) for p in range(n_ag + n_sr))
check("unmovable_non_nan_points=True still freezes everything (unchanged)",
      all_max < 1e-12, f"largest movement of any point {all_max:.3e}")

# ------------------------------------------------------------ bounds checks
chart = displaced_chart()
try:
    chart.relax_incremental(0, number_of_optimizations=1, unmovable_points=[9999])
    check("out-of-range unmovable_points rejected", False, "no exception raised")
except Exception as exc:
    check("out-of-range unmovable_points rejected", True, f"{type(exc).__name__}: {exc}")

try:
    chart.projection(0).set_unmovable([9999])
    check("out-of-range set_unmovable rejected", False, "no exception raised")
except Exception as exc:
    check("out-of-range set_unmovable rejected", True, f"{type(exc).__name__}: {exc}")

print()
if failures:
    print(f"{len(failures)} FAILED: {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
