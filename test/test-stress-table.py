#! /usr/bin/env python3
"""Projection.stress_table(): each titer's part of the stress.

The table is made by the same C++ terms Stress::value() sums, so the invariant that
matters is nansum(stress_table()) == recalculate_stress(). A caller reimplementing the
table in Python from titers().logged_array() cannot meet it: logged_array() drops the
inequality, so a < titer is charged a full squared residual instead of ae's
sigmoid-weighted one-sided term.

Run:  PYTHONPATH=build python3 test/test-stress-table.py
"""

import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.environ.get("AE_BUILD", os.path.join(ROOT, "build")))
import ae_backend  # noqa: E402

CHART = os.path.join(ROOT, "test", "chart1.ace")

failures = []


def check(name, ok, detail):
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
    if not ok:
        failures.append(name)


def kinds(chart):
    """Classify cells from the titer strings, not from the accessor under test."""
    t = chart.titers()
    result = {}
    for ag in range(chart.number_of_antigens()):
        for sr in range(chart.number_of_sera()):
            s = str(t.titer(ag, sr))
            result[(ag, sr)] = "missing" if s == "*" else {"<": "less", ">": "more", "~": "dodgy"}.get(s[0], "regular")
    return result


def nansum(table):
    return math.fsum(v for row in table for v in row if not math.isnan(v))


def sums_to_stress(label, chart):
    proj = chart.projection(0)
    table = proj.stress_table()
    shape_ok = len(table) == chart.number_of_antigens() and all(len(row) == chart.number_of_sera() for row in table)
    check(f"{label}: shape", shape_ok, f"{len(table)} x {len(table[0]) if table else 0}")
    stress = proj.recalculate_stress()
    diff = nansum(table) - stress
    check(f"{label}: nansum(stress_table) == recalculate_stress", abs(diff) <= 1e-9 * max(1.0, stress), f"stress {stress:.6f}, diff {diff:.3e}")
    return table


def cells(table, kind_map, kind):
    return [table[ag][sr] for (ag, sr), k in kind_map.items() if k == kind]


# ------------------------------------------------ 2D, regular and < titers
chart = ae_backend.chart_v3.Chart(CHART)
chart.relax(number_of_dimensions=2, number_of_optimizations=3, minimum_column_basis="none", seed=1)
table = sums_to_stress("2D", chart)
km = kinds(chart)
less, regular = cells(table, km, "less"), cells(table, km, "regular")
check("2D: fixture has < titers", len(less) > 0, f"{len(less)} < cells")
check("2D: every regular titer has a finite part", all(math.isfinite(v) for v in regular), f"{len(regular)} regular cells")
check("2D: every < titer has a finite part", all(math.isfinite(v) for v in less), f"< total {math.fsum(less):.6f}")
check("2D: parts are non-negative", all(v >= 0 for v in less + regular), "")

# --------------------------- missing, > and dodgy titers are not fitted -> NaN
chart = ae_backend.chart_v3.Chart(CHART)
titers = chart.titers()
titers.set_titer(0, 0, "*")
titers.set_titer(1, 1, ">1280")
titers.set_titer(2, 2, "~80")
chart.relax(number_of_dimensions=2, number_of_optimizations=3, minimum_column_basis="none", seed=1)
table = sums_to_stress("unfitted titers", chart)
km = kinds(chart)
for kind, cell in (("missing", (0, 0)), ("more", (1, 1)), ("dodgy", (2, 2))):
    check(f"unfitted titers: {kind} cell is NaN", km[cell] == kind and math.isnan(table[cell[0]][cell[1]]), f"{km[cell]} -> {table[cell[0]][cell[1]]}")

# ------------------------------------ 3D, and after moving a point by hand
chart = ae_backend.chart_v3.Chart(CHART)
chart.relax(number_of_dimensions=3, number_of_optimizations=3, minimum_column_basis="none", seed=1)
sums_to_stress("3D", chart)
chart.projection(0).set_coordinates(0, [5.0, -5.0, 5.0])
sums_to_stress("3D, antigen 0 moved", chart)

if failures:
    print(f"\n{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("\nall passed")
