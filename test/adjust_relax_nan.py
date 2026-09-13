#!/usr/bin/env python3
"""Regression test: relax must not choke on a point that has no coordinates.

The optimisation engines reject NaN outright — alglib raises
``MinCGCreate: X contains infinite or NaN values!`` — so a point with no coordinates has
to be kept out of the optimisation. ``DisconnectedPointsHandler`` already zeroes and
restores the points a projection *lists* as disconnected, but nothing put an unlisted
NaN point on that list, and a single one of those aborted the whole relax.

That is not hypothetical: report-pipeline charts carry such points. Running
``ae.adjust`` over the 16 February-2026 ssm maps, 8 had NaN points that were all properly
listed as disconnected (one chart had 162, and relaxed fine) while 3 had one or two
unlisted ones — and those 3 were the only failures. AD disconnects such a point instead
of failing; ``Projection::relax`` now does the same
(``cc/chart/v3/projections.cc``, ``disconnect_points_without_coordinates``).

What this locks down:

* a relax with an **orphan** NaN point succeeds, and puts that point on the disconnected
  list rather than inventing coordinates for it;
* the orphan's coordinates stay NaN afterwards — it must not be dragged into the map at
  (0, 0), which is what zeroing without restoring would do;
* the stress that comes back is finite and excludes the orphan, i.e. it equals the stress
  of the same relax with the point disconnected up front;
* a chart whose NaN points were **already** disconnected is untouched — the fix is a
  no-op there, so it cannot perturb charts that relax today.

Everything runs on the synthetic test/chart1.ace — never WHO data.

Run::  PYTHONPATH=build:py python3 test/adjust_relax_nan.py
"""

import math
import sys
import tempfile
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_root / "build"), str(_root / "py")]

import ae_backend.chart_v3


def _chart():
    "chart1.ace ships with no projection; relax so there is something to re-relax."
    chart = ae_backend.chart_v3.Chart(str(_root / "test" / "chart1.ace"))
    chart.relax(number_of_dimensions=2, number_of_optimizations=5, minimum_column_basis="none")
    chart.keep_projections(1)
    return chart


def _nan_points(projection):
    layout = projection.layout()
    return {
        i for i in range(len(layout))
        if layout[i] is None or any(x is None or math.isnan(x) for x in list(layout[i]))
    }


def _orphan_nan(chart, point_no):
    """Give `point_no` NaN coordinates WITHOUT listing it as disconnected.

    This is the state a chart arrives in from the report pipeline: the point has no
    position, but nothing recorded it as disconnected.
    """
    projection = chart.projection()
    nan = float("nan")
    projection.set_coordinates(point_no, [nan] * projection.layout().number_of_dimensions())


def test_orphan_nan_point_relaxes():
    chart = _chart()
    point_no = 3
    _orphan_nan(chart, point_no)
    projection = chart.projection()
    assert point_no in _nan_points(projection), "fixture: the point should have no coordinates"
    assert point_no not in set(projection.disconnected()), "fixture: and should NOT be listed disconnected"

    projection.relax()          # used to raise: alglib MinCGCreate ... NaN values!

    stress = projection.stress()
    assert not math.isnan(stress) and math.isfinite(stress), f"stress came back {stress}"
    assert point_no in set(projection.disconnected()), \
        "relax should have put the coordinate-less point on the disconnected list"
    assert point_no in _nan_points(projection), \
        "the point must still have NO coordinates — not be pulled into the map at the origin"
    print(f"  orphan NaN point relaxes: stress {stress:.6f}, point {point_no} disconnected, still NaN")
    return stress


def test_matches_disconnecting_up_front(orphan_stress):
    """Relaxing with the point disconnected from the start gives the same answer.

    If the orphan were merely zeroed rather than excluded from the stress, it would pull
    on its titers from (0, 0) and this would not match.
    """
    chart = _chart()
    point_no = 3
    _orphan_nan(chart, point_no)
    projection = chart.projection()
    projection.disconnect_points_without_coordinates()   # the same thing relax now does
    projection.relax()
    assert math.isclose(projection.stress(), orphan_stress, rel_tol=1e-9), \
        f"{projection.stress()} != {orphan_stress}"
    print(f"  equals disconnect-then-relax: {projection.stress():.6f}")


def test_no_op_when_already_disconnected():
    """A chart with no coordinate-less points must come out bit-identical.

    Both runs must start from the *same* layout: the chart1 fixture is built with a
    5-optimization relax, which is randomized, so two independently built charts land on
    different (equally good) optima and would prove nothing. Write the fixture once and
    reload it twice instead — a relax of an already-positioned projection is deterministic.
    """
    def run(chart_path, disconnect_first):
        chart = ae_backend.chart_v3.Chart(str(chart_path))
        projection = chart.projection()
        if disconnect_first:
            assert projection.disconnect_points_without_coordinates() == [], \
                "fixture: this chart should have no coordinate-less points"
        projection.relax()
        layout = projection.layout()
        return projection.stress(), [None if layout[i] is None else list(layout[i]) for i in range(len(layout))]

    with tempfile.TemporaryDirectory() as tmp:
        fixture = Path(tmp) / "fixture.ace"
        _chart().write(str(fixture))
        stress_a, layout_a = run(fixture, False)
        stress_b, layout_b = run(fixture, True)
    assert stress_a == stress_b, f"{stress_a} != {stress_b}"
    assert layout_a == layout_b, "layout changed on a chart with no coordinate-less points"
    print(f"  no-op on a clean chart: stress {stress_a:.6f} unchanged, layout identical")


def main():
    print("relax with a coordinate-less point:")
    orphan_stress = test_orphan_nan_point_relaxes()
    test_matches_disconnecting_up_front(orphan_stress)
    test_no_op_when_already_disconnected()
    print("adjust_relax_nan: all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
