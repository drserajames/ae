#!/usr/bin/env python3
"""Verify the adjust stage's review loop: `slot.modify(...)` styles the selection and
`slot.plot()` draws it (MIGRATION.md Stage B, step 4).

An `adjust/0do` script's loop is *select -> look -> re-cut the polygon*, and it only works
if the selection is visibly marked on the numbered snapshot. AD did that through
`acmacs.ChartDraw`, which edits the legacy per-point plot spec; ae's styling is the
semantic style system, so the port is a translation. Four things are locked down here.

**The kwargs translation.** AD's `modify` keys (`fill`, `outline`, `outline_width`,
`show`, `shape`, `size`, `aspect`, `rotation`, `order`, `label`, `legend`) become
`Style.add_modifier` kwargs. Most pass through; `order` becomes `raise_`/`lower`, AD's
`PointLabel`/`PointLegend` dicts are remapped key by key, and what has no ae equivalent is
dropped with a warning rather than raising.

**The modifiers built.** One `selector={"!i": <per-side index>}` modifier per selected
point, with `only="antigens"`/`"sera"` — a serum arrives as `number_of_antigens +
serum_no` and has to be split back. A selection covering every antigen collapses to one
empty-selector modifier, which is the `modify(select_antigens(lambda ag: True), size=10)`
idiom that opens most real scripts. Later modifiers win over earlier ones, as successive
`ChartDraw.modify` calls do.

**The chart is not touched.** The style is built on a throw-away copy, so the `99.ace` a
slot writes carries only the geometry the adjust operations produced.

**A snapshot is actually drawn.** `slot.plot()` produces a real PDF (and a PNG at the
final step, as AD does) through `ae_backend.map_draw.export_styled_map`.

Everything runs on the synthetic test/chart1.ace with styling invented in the test, so it
does not drift with the report charts. Colours and style names here are made up.

Run::  PYTHONPATH=build:py python3 test/adjust_review.py
"""

import os
import sys
import json
import shutil
import tempfile
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_root / "build"), str(_root / "py")]

import ae_backend.chart_v3
from ae.adjust import Adjust, Zd, Slot
from ae import adjust_render


def _chart():
    "chart1.ace ships with no projection; relax so there is something to draw."
    chart = ae_backend.chart_v3.Chart(str(_root / "test" / "chart1.ace"))
    chart.relax(number_of_dimensions=2, number_of_optimizations=5, minimum_column_basis="none")
    chart.keep_projections(1)
    return chart


def _modifiers(chart, entries, base_style=""):
    "Build the snapshot style and read back the modifiers the renderer will consume."
    adjust_render.build_style(chart, entries, base_style=base_style)
    style = json.loads(chart.export())["c"]["R"][adjust_render.SNAPSHOT_STYLE]
    return style.get("A", [])          # an all-default style exports with no modifier list


# ----------------------------------------------------------------------
# the AD -> ae kwargs translation

def test_modify_keys_translate():
    "AD's modify keys become add_modifier kwargs; order/label/legend are remapped."
    straight = {"fill": "red", "outline": "blue", "outline_width": 3.0, "size": 10.0,
                "shape": "uglyegg", "aspect": 0.75, "rotation": 0.5, "show": False}
    assert adjust_render.normalize_modify(straight) == straight, "pass-through keys changed"

    assert adjust_render.normalize_modify({"order": "raise"}) == {"raise_": True}
    assert adjust_render.normalize_modify({"order": "lower"}) == {"lower": True}

    # AD's PointLabel dict: show -> shown, format -> text, font dropped (no ae equivalent)
    label = adjust_render.normalize_modify(
        {"label": {"show": True, "format": "{name}", "offset": [0, 1], "font": "helvetica"}})
    assert label == {"label": {"shown": True, "text": "{name}", "offset": [0, 1]}}, label

    # AD's PointLegend dict: format is the row text, the rest has no ae equivalent
    assert adjust_render.normalize_modify(
        {"legend": {"format": "group one", "show_if_none_selected": False}}) == {"legend": "group one"}

    # None is "not set" in AD's kwargs-from-locals idiom, and an unknown key is dropped
    assert adjust_render.normalize_modify({"fill": None, "nonsense": 1}) == {}
    print("OK [test_modify_keys_translate]: pass-through, order, label, legend, drops")


# ----------------------------------------------------------------------
# the modifiers built from a selection

def test_subset_selection_becomes_one_modifier_per_point():
    "A partial antigen selection emits one '!i' modifier per point, antigens only."
    adj = Adjust(_chart())
    selected = adj.select_antigens(lambda pt: pt.no in (1, 4, 7))
    entries = [{"kind": "modify", "selected": selected,
                "modifier": {"outline": "magenta", "outline_width": 3.0}}]
    mods = _modifiers(adj.chart, entries)
    assert len(mods) == 3, f"expected 3 modifiers, got {len(mods)}"
    assert [m["T"]["!i"] for m in mods] == [1, 4, 7], mods
    assert all(m["A"] == 1 for m in mods), "modifiers are not restricted to antigens"
    assert all(m["O"] == "magenta" and m["o"] == 3.0 for m in mods), mods
    print("OK [test_subset_selection_becomes_one_modifier_per_point]: 3 '!i' modifiers")


def test_whole_side_selection_collapses_to_one_modifier():
    "Selecting every antigen collapses to a single empty-selector modifier."
    adj = Adjust(_chart())
    entries = [{"kind": "modify", "selected": adj.select_antigens(),
                "modifier": {"size": 10.0}}]
    mods = _modifiers(adj.chart, entries)
    assert len(mods) == 1, f"expected the all-antigens selection to collapse, got {len(mods)}"
    assert mods[0]["T"] == {} and mods[0]["A"] == 1 and mods[0]["s"] == 10.0, mods
    print("OK [test_whole_side_selection_collapses_to_one_modifier]: 1 modifier for all antigens")


def test_sera_get_their_own_index_space():
    "A serum arrives as number_of_antigens + serum_no and is split back for '!i'."
    adj = Adjust(_chart())
    n_ag = adj.number_of_antigens
    selected = adj.select_sera(lambda pt: pt.no in (0, 2))
    assert selected == [n_ag + 0, n_ag + 2], f"select_sera changed convention: {selected}"
    mods = _modifiers(adj.chart, [{"kind": "modify", "selected": selected,
                                   "modifier": {"fill": "cyan"}}])
    assert [m["T"]["!i"] for m in mods] == [0, 2], mods
    assert all(m["A"] == 0 for m in mods), "serum modifiers are not restricted to sera"
    print("OK [test_sera_get_their_own_index_space]: serum indexes are per-side")


def test_mixed_selection_splits_by_side():
    "One modify over antigens and sera together emits a modifier on each side."
    adj = Adjust(_chart())
    n_ag = adj.number_of_antigens
    mods = _modifiers(adj.chart, [{"kind": "modify", "selected": [2, n_ag + 1],
                                   "modifier": {"outline": "green"}}])
    assert [(m["T"]["!i"], m["A"]) for m in mods] == [(2, 1), (1, 0)], mods
    print("OK [test_mixed_selection_splits_by_side]: antigen 2 and serum 1")


def test_later_modify_wins():
    "Modifiers apply in order, so a second modify overrides the first on a shared point."
    adj = Adjust(_chart())
    entries = [{"kind": "modify", "selected": [0, 1], "modifier": {"outline": "green"}},
               {"kind": "modify", "selected": [1], "modifier": {"outline": "orange"}}]
    mods = _modifiers(adj.chart, entries)
    assert [(m["T"]["!i"], m["O"]) for m in mods] == [(0, "green"), (1, "green"), (1, "orange")], mods
    print("OK [test_later_modify_wins]: the last modifier for a point is applied last")


def test_base_style_becomes_a_parent_modifier():
    "A base style is referenced as the first modifier's parent, so it resolves first."
    adj = Adjust(_chart())
    mods = _modifiers(adj.chart, [], base_style="invented-base")
    assert mods == [{"R": "invented-base"}], mods
    assert _modifiers(_chart(), []) == [], "an empty base style should add no parent"
    print("OK [test_base_style_becomes_a_parent_modifier]: parent first, none when empty")


# ----------------------------------------------------------------------
# picking the style to draw on

def test_default_base_style_prefers_the_current_clade_style():
    "'clades' wins outright; otherwise the highest clades-v<N>; otherwise nothing."
    chart = _chart()

    def named(*names):
        exported = json.loads(chart.export())
        exported["c"]["R"] = {name: {} for name in names}
        return json.dumps(exported).encode()

    assert adjust_render.default_base_style(exported=named("-reset", "clades", "clades-6m")) == "clades"
    assert adjust_render.default_base_style(
        exported=named("clades-v1", "clades-v12", "clades-v2", "info-clades-v12")) == "clades-v12"
    assert adjust_render.default_base_style(exported=named("-reset", "info-clades")) == ""
    assert adjust_render.default_base_style(chart=chart) == "", "chart1.ace has no clade style"
    print("OK [test_default_base_style_prefers_the_current_clade_style]: clades > clades-v12 > none")


# ----------------------------------------------------------------------
# the slot: drawing, and leaving the chart alone
#
# The sections below are module-level, as in test/adjust_slot.py: `Zd.slot` derives the
# slot directory from the function's __qualname__, so nesting them inside a test would
# put the test's own name in the path.

_source = None          # the chart every section starts from, written per test run


def draw_section(zd):
    "Mark a selection and let the default renderer draw the numbered snapshots."
    @zd.slot
    def marked(slot: Slot):
        slot.chart_filename = _source
        slot.modify(selected=slot.select_antigens(report=False, snapshot=False), size=10)
        region = slot.path([[0, 0], [40, 0], [40, 40], [0, 40]], outline="magenta")
        slot.select_antigens(lambda pt: pt.inside(region), report=False,
                             modify={"outline": "magenta", "outline_width": 3})
        return slot.final_ace()
    return marked


def test_slot_draws_a_snapshot(tmp):
    "A slot's snapshots are real PDFs, with a PNG at the final step as AD writes."
    global _source
    _source = tmp / "source.ace"
    _chart().write(str(_source))

    final = draw_section(Zd("draw_section", directory=tmp))
    subdir = tmp / "draw_section.00.marked"
    assert final == subdir / "99.ace" and final.exists(), f"no 99.ace at {final}"
    for name in ("00.pdf", "99.pdf", "99.png"):
        drawn = subdir / name
        assert drawn.exists() and drawn.stat().st_size > 1000, f"{name} was not drawn"
    assert (subdir / "00.pdf").read_bytes()[:5] == b"%PDF-", "00.pdf is not a PDF"
    assert (subdir / "99.png").read_bytes()[:4] == b"\x89PNG", "99.png is not a PNG"
    print(f"OK [test_slot_draws_a_snapshot]: {subdir.name}/00.pdf, 99.pdf, 99.png drawn")


def clean_section(zd):
    "Style a selection, draw it, and hand back the final chart."
    @zd.slot
    def styled(slot: Slot):
        slot.chart_filename = _source
        slot.modify(selected=slot.select_antigens(lambda pt: pt.no < 3, report=False,
                                                  snapshot=False),
                    outline="orange", outline_width=3)
        slot.plot()
        return slot.final_ace()
    return styled


def test_final_ace_carries_no_snapshot_style(tmp):
    "Styling is built on a throw-away copy, so 99.ace keeps only the adjusted geometry."
    global _source
    _source = tmp / "clean-source.ace"
    _chart().write(str(_source))

    final = clean_section(Zd("clean_section", directory=tmp))
    styles = json.loads(ae_backend.chart_v3.Chart(final).export())["c"].get("R", {})
    assert adjust_render.SNAPSHOT_STYLE not in styles, \
        f"the snapshot style leaked into 99.ace: {sorted(styles)}"
    print("OK [test_final_ace_carries_no_snapshot_style]: 99.ace is unpolluted")


def quiet_section(zd):
    "Two selections with renderer=None: the numbering must still advance."
    @zd.slot
    def quiet(slot: Slot):
        slot.renderer = None
        slot.chart_filename = _source
        slot.select_antigens(lambda pt: pt.no < 2, report=False)
        slot.select_antigens(lambda pt: pt.no < 3, report=False)
        return slot            # finalized (and so numbered 99) by the time we see it
    return quiet


def test_renderer_none_numbers_without_drawing(tmp):
    "Setting renderer=None keeps AD's NN numbering and draws nothing."
    global _source
    _source = tmp / "quiet-source.ace"
    _chart().write(str(_source))

    slot = quiet_section(Zd("quiet_section", directory=tmp))
    steps = [step for step, _ in slot.snapshots]
    assert steps == [0, 1, 99], f"snapshot numbering changed: {steps}"
    assert not list((tmp / "quiet_section.00.quiet").glob("*.pdf")), \
        "renderer=None still drew something"
    print("OK [test_renderer_none_numbers_without_drawing]: steps 00, 01, 99, no files")


def path_section(zd):
    "One polygon with an outline and one without; only the first is recorded."
    @zd.slot
    def cut(slot: Slot):
        slot.renderer = None
        slot.chart_filename = _source
        slot.path([[0, 0], [4, 0], [4, 4], [0, 4]], outline="cyan", outline_width=3)
        slot.path([[0, 0], [1, 1]], close=False)
        return list(slot.styling)
    return cut


def test_path_outline_is_recorded_not_drawn(tmp):
    "slot.path(outline=...) records the request; ae has no polygon primitive to draw it."
    global _source
    _source = tmp / "path-source.ace"
    _chart().write(str(_source))

    styling = path_section(Zd("path_section", directory=tmp))
    kinds = [entry["kind"] for entry in styling]
    assert kinds == ["path"], f"expected one recorded path, got {kinds}"
    assert styling[0]["outline"] == "cyan" and styling[0]["outline_width"] == 3, styling
    assert "polygon" in adjust_render.polygon_support_note()
    print("OK [test_path_outline_is_recorded_not_drawn]: recorded, and says why")


def reset_section(zd):
    "Style something, then reset back to the renderer's grey baseline."
    @zd.slot
    def reset(slot: Slot):
        slot.renderer = None
        slot.chart_filename = _source
        slot.modify(selected=[0, 1], outline="magenta")
        assert slot.styling, "modify recorded nothing"
        slot.reset_plot_spec()
        return slot.base_style, list(slot.styling)
    return reset


def test_reset_plot_spec_drops_style_and_history(tmp):
    "reset_plot_spec goes back to the renderer's grey baseline and forgets the styling."
    global _source
    _source = tmp / "reset-source.ace"
    _chart().write(str(_source))

    base_style, styling = reset_section(Zd("reset_section", directory=tmp))
    assert base_style == "" and styling == [], f"base_style={base_style!r} styling={styling}"
    print("OK [test_reset_plot_spec_drops_style_and_history]: grey baseline, no styling")


# ----------------------------------------------------------------------

def main():
    test_modify_keys_translate()
    test_subset_selection_becomes_one_modifier_per_point()
    test_whole_side_selection_collapses_to_one_modifier()
    test_sera_get_their_own_index_space()
    test_mixed_selection_splits_by_side()
    test_later_modify_wins()
    test_base_style_becomes_a_parent_modifier()
    test_default_base_style_prefers_the_current_clade_style()

    tmp = Path(tempfile.mkdtemp(prefix="ae-adjust-review-"))
    cwd = os.getcwd()
    try:
        test_slot_draws_a_snapshot(tmp)
        test_final_ace_carries_no_snapshot_style(tmp)
        test_renderer_none_numbers_without_drawing(tmp)
        test_path_outline_is_recorded_not_drawn(tmp)
        test_reset_plot_spec_drops_style_and_history(tmp)
    finally:
        os.chdir(cwd)
        shutil.rmtree(tmp, ignore_errors=True)
    print("all adjust-review checks passed")


if __name__ == "__main__":
    main()
