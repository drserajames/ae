#!/usr/bin/env python3
# Tests for the optional date-order drawing of map points (`ae.semantic.date_order`, switched by
# `AE_POINT_DRAW_ORDER` in `ae.report.chart_modifier`).
#
# On the in-repo test chart `test/chart1.ace`, with invented changes made in the test (one test
# antigen's date cleared, one test antigen marked as a vaccine), it checks after flattening the
# front style with `Chart.semantic_style_to_legacy`:
#   1. `-date-order` has one entry per distinct test-antigen date, each with an explicit `first`;
#   2. with it referenced, dated test antigens are drawn in ascending date order, newest on top,
#      overriding a legend-style raise that runs the other way;
#   3. the vaccine, raised after `-date-order`, is still drawn last;
#   4. the undated test antigen stays below every dated test antigen;
#   5. sera and reference antigens keep their place below the test antigens;
#   6. only the drawing order changes: the per-point palette is identical with and without it;
#   7. `point_draw_order()` defaults to "legend", follows the env var, and rejects unknown values.
#
# No WHO data: the only input is the in-repo test chart.
#
# Run (from the ae worktree root):
#   PYTHONPATH="$PWD/py:$PWD/build" \
#   arch -arm64 /opt/homebrew/bin/python3.14 test/test-date-order.py

import faulthandler
import json
import os
import signal
import sys
from pathlib import Path

faulthandler.enable()
faulthandler.register(signal.SIGTRAP)

import ae_backend

from ae import semantic
from ae.report.chart_modifier import ChartModifier

CHART = Path(__file__).resolve().parent / "chart1.ace"

failures: list[str] = []


def check(condition: bool, what: str, detail: str = ""):
    print(f"{'ok  ' if condition else 'FAIL'}  {what}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures.append(what)


def prepared_chart() -> tuple[ae_backend.chart_v3.Chart, int, int]:
    """The test chart with a legend-like raise (test antigens raised one by one in descending
    index order, so the lowest index ends on top), a vaccines style, and the `-date-order`
    style. Returns the chart, the undated antigen and the vaccine antigen."""
    chart = ae_backend.chart_v3.Chart(str(CHART))
    if chart.number_of_projections() == 0:
        chart.relax(number_of_dimensions=2, number_of_optimizations=3, minimum_column_basis="none")
    semantic.reference.attributes(chart=chart)
    reference = set(no for no, _ in chart.select_reference_antigens())
    test = [no for no, _ in chart.select_all_antigens() if no not in reference]
    undated, vaccine = test[-1], test[0]
    for no, ag in chart.select_all_antigens():
        if no == undated:
            ag.date("")
        if no == vaccine:
            ag.semantic.set("V", "test")

    clades = chart.styles()["-clades"]
    for no in reversed(test):
        clades.add_modifier(selector={"!i": no}, only="antigens", fill="green", outline="black", raise_=True)
    vaccines = chart.styles()["-vaccines"]
    vaccines.add_modifier(selector={"V": True}, only="antigens", raise_=True, size=40.0)
    semantic.date_order.style(chart=chart)

    semantic.front_style.add(chart=chart, style_name="legend", references=["-clades", "-vaccines"], title="legend")
    semantic.front_style.add(chart=chart, style_name="date", references=["-clades", "-date-order", "-vaccines"], title="date")
    return chart, undated, vaccine


def flattened(chart: ae_backend.chart_v3.Chart, style: str) -> dict:
    chart.semantic_style_to_legacy(style)
    return json.loads(chart.export())["c"]


def test_date_order():
    chart, undated, vaccine = prepared_chart()
    c_legend = flattened(chart, "legend")
    c_date = flattened(chart, "date")
    ags = c_date["a"]
    n_ag = len(ags)
    reference = set(no for no, _ in chart.select_reference_antigens())
    test = [no for no in range(n_ag) if no not in reference]
    dated = [no for no in test if no not in (undated, vaccine)]

    entries = c_date["R"]["-date-order"]["A"]
    distinct = sorted(set(ags[no]["D"] for no in test if ags[no].get("D")))
    check(len(entries) == len(distinct), "one -date-order entry per distinct test-antigen date", f"{len(entries)} entries, {len(distinct)} dates")
    check(all(en["T"]["!D"][0] for en in entries), "every entry has an explicit first date")

    pos_legend = {pt: i for i, pt in enumerate(c_legend["p"]["d"])}
    pos = {pt: i for i, pt in enumerate(c_date["p"]["d"])}
    by_pos = sorted(dated, key=lambda no: pos[no])
    dates_in_draw_order = [ags[no]["D"] for no in by_pos]
    check(dates_in_draw_order == sorted(dates_in_draw_order), "dated test antigens drawn oldest to newest", " ".join(dates_in_draw_order))
    by_pos_legend = sorted(dated, key=lambda no: pos_legend[no])
    check([ags[no]["D"] for no in by_pos_legend] != sorted(dates_in_draw_order), "control: the legend-style raise alone is not in date order")

    check(pos[vaccine] == len(pos) - 1, "vaccine drawn last", f"position {pos[vaccine]} of {len(pos)}")
    check(pos[undated] < min(pos[no] for no in dated), "undated test antigen below all dated test antigens")
    below = [no for no in pos if no >= n_ag or no in reference]
    check(max(pos[no] for no in below) < min(pos[no] for no in test), "sera and reference antigens stay below test antigens")
    check((c_legend["p"]["p"], c_legend["p"]["P"]) == (c_date["p"]["p"], c_date["p"]["P"]), "palette unchanged, only the drawing order differs")


def test_switch():
    chart = ae_backend.chart_v3.Chart(str(CHART))
    modifier = ChartModifier(chart=chart)
    saved = os.environ.pop(ChartModifier.POINT_DRAW_ORDER_ENV, None)
    try:
        check(modifier.point_draw_order() == "legend", "default draw order is legend")
        for value in ("date", "legend"):
            os.environ[ChartModifier.POINT_DRAW_ORDER_ENV] = value
            check(modifier.point_draw_order() == value, f"AE_POINT_DRAW_ORDER={value}")
        os.environ[ChartModifier.POINT_DRAW_ORDER_ENV] = "date-new-on-top"   # the variant not chosen
        try:
            modifier.point_draw_order()
            check(False, "unknown value rejected")
        except ValueError:
            check(True, "unknown value rejected")
    finally:
        os.environ.pop(ChartModifier.POINT_DRAW_ORDER_ENV, None)
        if saved is not None:
            os.environ[ChartModifier.POINT_DRAW_ORDER_ENV] = saved


test_date_order()
test_switch()
print(f"\n{'FAILED: ' + ', '.join(failures) if failures else 'all passed'}")
sys.exit(1 if failures else 0)
