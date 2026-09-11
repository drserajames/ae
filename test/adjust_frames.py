#!/usr/bin/env python3
"""Verify ae.adjust's coordinate frames against AD's (MIGRATION.md Stage B).

AD's `adjust/0do` scripts author every selection polygon (`slot.path`) and every move
destination (`slot.move(to=)`) in the **viewport-origin** frame: an offset from the origin
of the map viewport, measured in *transformed* (drawn) space. See
`acmacs_py/zero_do_5.py` (the `coordinates_relative_to="viewport-origin"` default) and
`acmacs-map-draw/cc/coordinates.cc`. The chart stores *untransformed* coordinates, so
reading such a literal as a raw layout coordinate silently selects the wrong points.

That viewport is not a stored setting — AD recomputes it in `ChartDraw::calculate_viewport()`
as the minimum bounding ball of the transformed layout (`acmacs-chart-2/cc/bounding-ball.cc`)
widened by `Viewport::whole_width()`. `Adjust.viewport()` reimplements exactly that.

Everything here runs on the synthetic test/chart1.ace with transformations applied in the
test itself, so there is no dependency on any real chart.

Run::  PYTHONPATH=build:py python3 test/adjust_frames.py
"""

import sys
import math
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_root / "build"), str(_root / "py")]

import ae_backend.chart_v3
from ae.adjust import Adjust


def _adjust(rotate=None, flip=None):
    "chart1.ace ships with no projection; relax so there is something to adjust."
    chart = ae_backend.chart_v3.Chart(str(_root / "test" / "chart1.ace"))
    chart.relax(number_of_dimensions=2, number_of_optimizations=5, minimum_column_basis="none")
    chart.keep_projections(1)
    if rotate is not None:
        chart.projection(0).transformation().rotate(rotate)
    if flip == "ew":
        chart.projection(0).transformation().flip_ew()
    return Adjust(chart)


def test_transform_roundtrip():
    "transform/inverse_transform are mutual inverses, and match the stored transformation."
    adj = _adjust(rotate=25.0)
    a, b, c, d = adj.transformation
    assert abs((a * d - b * c) - 1.0) < 1e-9, "a pure rotation must have determinant 1"
    for point in ([0.0, 0.0], [3.0, -1.5], [-7.25, 11.0]):
        there = adj.transform(point)
        back = adj.inverse_transform(there)
        assert all(abs(p - q) < 1e-12 for p, q in zip(point, back)), f"{point} -> {there} -> {back}"
    # transformed_layout agrees with transform() point by point
    for point_no, tc in enumerate(adj.transformed_layout()):
        raw = adj.coordinates(point_no)
        assert (tc is None) == (raw is None)
        if raw is not None:
            assert all(abs(p - q) < 1e-12 for p, q in zip(tc, adj.transform(raw)))
    print("OK [test_transform_roundtrip]: transform/inverse_transform invert, "
          "transformed_layout consistent")


def test_viewport_is_ad_bounding_ball():
    "viewport() = minimum bounding ball of the transformed layout, widened to a whole number."
    adj = _adjust(rotate=25.0)
    origin_x, origin_y, size = adj.viewport()
    points = [p for p in adj.transformed_layout() if p is not None]
    centre_x, centre_y = origin_x + size / 2.0, origin_y + size / 2.0

    assert size == float(math.ceil(size)), f"whole_width must round the diameter up: {size}"
    # every point is inside the ball (that is what "bounding" means) ...
    for px, py in points:
        assert math.hypot(px - centre_x, py - centre_y) <= size / 2.0 + 1e-9, \
            "a point fell outside the computed bounding ball"
    # ... and the ball is snug: shrinking it to the pre-rounding diameter still bounds,
    # but a ball materially smaller than that does not.
    radii = [math.hypot(px - centre_x, py - centre_y) for px, py in points]
    assert max(radii) > size / 2.0 - 1.0, "bounding ball is looser than whole_width allows"
    print(f"OK [test_viewport_is_ad_bounding_ball]: origin=[{origin_x:.4f}, {origin_y:.4f}] "
          f"size={size} bounds all {len(points)} points snugly")


def test_frames_differ_and_convert():
    "The three frames are genuinely different, and convert as AD documents them."
    adj = _adjust(rotate=25.0, flip="ew")
    origin_x, origin_y, _ = adj.viewport()
    point = [4.0, 3.0]

    raw = adj.to_layout_coordinates(point, "map-not-transformed")
    assert raw == point, "map-not-transformed must pass coordinates straight through"

    drawn = adj.to_layout_coordinates(point, "map-transformed")
    assert all(abs(p - q) < 1e-12 for p, q in zip(adj.transform(drawn), point)), \
        "map-transformed must be the inverse transform of the literal"

    viewport_relative = adj.to_layout_coordinates(point, "viewport-origin")
    expected = adj.inverse_transform([origin_x + point[0], origin_y + point[1]])
    assert all(abs(p - q) < 1e-12 for p, q in zip(viewport_relative, expected)), \
        "viewport-origin must add the viewport origin before inverse-transforming"
    assert any(abs(p - q) > 1e-6 for p, q in zip(viewport_relative, raw)), \
        "viewport-origin and map-not-transformed must not silently coincide"

    # a displacement is invariant to the origin; a position is not
    offset = adj.to_layout_offset(point, "viewport-origin")
    assert all(abs(p - q) < 1e-12 for p, q in zip(offset, adj.inverse_transform(point))), \
        "to_layout_offset must not apply the viewport origin"
    assert adj.to_layout_offset(point, "map-not-transformed") == point

    for bad in ("viewport", "transformed", ""):
        try:
            adj.to_layout_coordinates(point, bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"frame {bad!r} should have been rejected")
    print("OK [test_frames_differ_and_convert]: all three frames convert per AD and are distinct")


def test_figure_selection_matches_ad_semantics():
    """A viewport-origin polygon selects the points AD would: those whose *transformed*
    coordinates fall inside the polygon once the viewport origin is added."""
    adj = _adjust(rotate=25.0, flip="ew")
    origin_x, origin_y, size = adj.viewport()

    # A box authored the way an adjust/0do script authors one — as an offset from the
    # viewport origin. It is anchored on the layout's own median point rather than on a
    # fixed quadrant of the viewport: chart1.ace is relaxed from random starts here, so a
    # fixed quadrant lands on an empty part of the map every so often and the "is this
    # test exercising anything" guard below trips at random.
    transformed = adj.transformed_layout()
    known = [tc for no in range(adj.number_of_antigens)
             if (tc := transformed[no]) is not None]
    median_x = sorted(p[0] for p in known)[len(known) // 2]
    median_y = sorted(p[1] for p in known)[len(known) // 2]
    half = size / 4.0
    cx, cy = median_x - origin_x, median_y - origin_y      # median, viewport-relative
    vertices = [[cx - half, cy - half], [cx + half, cy - half],
                [cx + half, cy + half], [cx - half, cy + half]]

    selected = set(adj.select_antigens(lambda pt: pt.inside(adj.figure(vertices))))

    # AD's reference semantics, computed directly: transformed coords vs the polygon
    # shifted by the viewport origin.
    absolute = [[origin_x + vx, origin_y + vy] for vx, vy in vertices]
    lo_x, hi_x = absolute[0][0], absolute[1][0]
    lo_y, hi_y = absolute[0][1], absolute[2][1]
    expected = {no for no in range(adj.number_of_antigens)
                if (tc := transformed[no]) is not None
                and lo_x < tc[0] < hi_x and lo_y < tc[1] < hi_y}

    assert selected == expected, (f"selection disagrees with AD semantics: "
                                  f"only-ae={sorted(selected - expected)} "
                                  f"only-AD={sorted(expected - selected)}")
    assert expected, "the test polygon selected nothing — it is not exercising anything"

    # and the un-converted reading is genuinely different (the bug this guards against)
    naive = set(adj.select_antigens(
        lambda pt: pt.inside(adj.figure(vertices, frame="map-not-transformed"))))
    assert naive != selected, "raw-layout reading coincided with the AD frame by accident"
    print(f"OK [test_figure_selection_matches_ad_semantics]: {len(selected)} antigens, "
          f"identical to AD semantics ({len(naive)} under the un-converted reading)")


def test_move_writes_inverse_transformed_target():
    "move(to=) writes AD's target: inverse_transform(viewport origin + to)."
    adj = _adjust(rotate=25.0)
    origin_x, origin_y, _ = adj.viewport()
    to = [5.0, 7.0]
    expected = adj.inverse_transform([origin_x + to[0], origin_y + to[1]])

    points = adj.select_antigens(lambda pt: pt.no < 3)
    adj.move(points, to=to)
    for point_no in points:
        got = adj.coordinates(point_no)
        assert all(abs(p - q) < 1e-12 for p, q in zip(got, expected)), \
            f"point {point_no} landed at {got}, expected {expected}"
    # and the moved points sit where the literal says, once drawn
    drawn = adj.transform(adj.coordinates(points[0]))
    assert all(abs(p - (o + t)) < 1e-9 for p, o, t in zip(drawn, (origin_x, origin_y), to)), \
        "the moved point is not at the authored viewport-relative position when drawn"

    # map-not-transformed still writes the literal verbatim
    adj.move(points, to=to, frame="map-not-transformed")
    assert all(abs(p - q) < 1e-12 for p, q in zip(adj.coordinates(points[0]), to))
    print("OK [test_move_writes_inverse_transformed_target]: move/set_coordinates honour the frame")


def test_move_by_and_flip_honour_frame():
    "move_by treats its argument as a displacement; flip_over_line converts both endpoints."
    adj = _adjust(rotate=25.0)
    point_no = adj.select_antigens(lambda pt: pt.no == 0)[0]

    before = adj.coordinates(point_no)
    adj.move_by([point_no], [1.0, 0.0])
    after = adj.coordinates(point_no)
    delta = [after[0] - before[0], after[1] - before[1]]
    assert all(abs(p - q) < 1e-12 for p, q in zip(delta, adj.inverse_transform([1.0, 0.0]))), \
        "move_by must apply only the linear part, never the viewport origin"

    # reflecting twice over the same line is the identity, whichever frame names it
    start = adj.coordinates(point_no)
    adj.flip_over_line([point_no], [0.0, 0.0], [3.0, 4.0])
    assert any(abs(p - q) > 1e-9 for p, q in zip(adj.coordinates(point_no), start)), \
        "flip_over_line did not move the point"
    adj.flip_over_line([point_no], [0.0, 0.0], [3.0, 4.0])
    assert all(abs(p - q) < 1e-9 for p, q in zip(adj.coordinates(point_no), start)), \
        "flipping twice over one line must be the identity"
    print("OK [test_move_by_and_flip_honour_frame]: move_by is a displacement, flip is an involution")


def main():
    test_transform_roundtrip()
    test_viewport_is_ad_bounding_ball()
    test_frames_differ_and_convert()
    test_figure_selection_matches_ad_semantics()
    test_move_writes_inverse_transformed_target()
    test_move_by_and_flip_honour_frame()
    print("all adjust-frame checks passed")


if __name__ == "__main__":
    main()
