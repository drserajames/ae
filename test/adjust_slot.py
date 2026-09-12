#!/usr/bin/env python3
"""Verify ae.adjust's AD-compatibility layer: the predicate spellings, the frozen
viewport, and the Zd/Slot step chain (MIGRATION.md Stage B, steps 2 and 3).

Three things are locked down here.

**Predicate spellings** (audit §3). AD's adjust predicates read
`ag.aa["<pos><AA>"]` and `ag.clade_any_of([...])`; ae reaches the same data through
`sequence_aa()` and `semantic.clades()`. `Point` carries AD's names so a predicate
copied out of an `adjust/0do` script means here what it meant there.

**Frozen viewport** (audit §2, refined 2026-09-11). AD computes the map viewport once
and caches it, invalidating only in `ChartDraw::rotate` and `ChartDraw::flip`
(acmacs-map-draw/cc/draw.cc:106,117) — moving points and relaxing do not. So every
polygon and move destination in one slot resolves against one frame, even after earlier
steps moved points. Recomputing per call instead silently shifts the frame under the
`path -> move -> path` pattern real scripts use.

**The Zd/Slot chain** (audit §4/§5). `Zd.slot` names each step from the function's
qualname with `<locals>` replaced by a two-digit counter, gives it a directory of that
name, numbers snapshots `NN`, and on exit writes `99.ace`. Those paths are the
provenance `map-adjustments.txt` records, so the naming is load-bearing.

Everything here runs on the synthetic test/chart1.ace, with sequences, clades and
transformations applied in the test itself, so it does not drift with the report charts.
The amino acids and clade names are invented ("X.1", position 5) — never WHO data.

Run::  PYTHONPATH=build:py python3 test/adjust_slot.py
"""

import os
import sys
import shutil
import tempfile
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_root / "build"), str(_root / "py")]

import ae_backend.chart_v3
from ae.adjust import Adjust, Zd, Slot

# an invented sequence: position 5 is the only one that varies between the two groups
_SEQ_A = "MKTIA" + "AAAAA"
_SEQ_B = "MKTIB" + "AAAAA"


def _chart(rotate=None, sequences=False):
    "chart1.ace ships with no projection; relax so there is something to adjust."
    chart = ae_backend.chart_v3.Chart(str(_root / "test" / "chart1.ace"))
    chart.relax(number_of_dimensions=2, number_of_optimizations=5, minimum_column_basis="none")
    chart.keep_projections(1)
    if rotate is not None:
        chart.projection(0).transformation().rotate(rotate)
    if sequences:
        # even antigens get sequence A and clade X.1; odd ones B and X.2. Every third
        # antigen is left unsequenced and unclade-d, so the "no data" path is exercised.
        for no, ag in chart.select_all_antigens():
            if no % 3 == 2:
                continue
            ag.sequence_aa(_SEQ_A if no % 2 == 0 else _SEQ_B)
            ag.semantic.add_clade("X.1" if no % 2 == 0 else "X.2")
    return chart


# ----------------------------------------------------------------------
# predicate spellings (step 2)

def test_aa_predicate_matches_sequence_aa():
    "pt.aa[...] is AD's spelling of the same test pt.sequence_aa()[...] makes."
    adj = Adjust(_chart(sequences=True))

    by_alias = set(adj.select_antigens(lambda pt: bool(pt.aa["5A"])))
    by_backend = set(adj.select_antigens(lambda pt: bool(pt.sequence_aa()["5A"])))
    assert by_alias == by_backend, "pt.aa disagrees with the backend it delegates to"
    expected = {no for no in range(adj.number_of_antigens) if no % 3 != 2 and no % 2 == 0}
    assert by_alias == expected, f"expected {sorted(expected)}, got {sorted(by_alias)}"

    # negation and the multi-position "matches all" form, as AD documents them
    negated = set(adj.select_antigens(lambda pt: bool(pt.aa["!5A"])))
    assert negated & by_alias == set(), "a point cannot both have and not have an AA"
    both = set(adj.select_antigens(lambda pt: bool(pt.aa["1M 5A"])))
    assert both == by_alias, "multi-position query must match all of its terms"
    none = set(adj.select_antigens(lambda pt: bool(pt.aa["1M 5Z"])))
    assert none == set(), "a query with an unsatisfiable term must select nothing"

    # An unsequenced point answers False to a positive query and — vacuously — True to a
    # negated one: it has no position 5, so position 5 is not A. Verified against the real
    # AD extension over a whole report cycle, where AD's ag.aa["!<pos><AA>"] selects the
    # same index set, unsequenced antigens included.
    unsequenced = {no for no in range(adj.number_of_antigens) if no % 3 == 2}
    assert unsequenced, "the fixture should leave some antigens unsequenced"
    assert not (unsequenced & by_alias), "unsequenced antigens must not match a positive query"
    assert unsequenced <= negated, "unsequenced antigens must match a negated query"
    assert negated == set(range(adj.number_of_antigens)) - by_alias, \
        "negation must be the exact complement of the positive query"
    print(f"OK [test_aa_predicate_matches_sequence_aa]: {len(by_alias)} match, "
          f"{len(negated)} negated (incl. {len(unsequenced)} unsequenced, vacuously true)")


def test_clade_predicates():
    "clade_any_of / has_clade / has_any_clade_of agree, and read semantic.clades()."
    adj = Adjust(_chart(sequences=True))

    x1 = set(adj.select_antigens(lambda pt: pt.clade_any_of(["X.1"])))
    assert x1 == set(adj.select_antigens(lambda pt: pt.has_clade("X.1")))
    assert x1 == set(adj.select_antigens(lambda pt: pt.has_any_clade_of(["X.1"])))
    assert x1 == {no for no in range(adj.number_of_antigens) if no % 3 != 2 and no % 2 == 0}

    either = set(adj.select_antigens(lambda pt: pt.clade_any_of(["X.1", "X.2"])))
    x2 = set(adj.select_antigens(lambda pt: pt.clade_any_of(["X.2"])))
    assert either == x1 | x2, "any-of must be the union of its terms"
    assert x1 and x2 and not (x1 & x2), "the fixture should split the antigens in two"
    assert not adj.select_antigens(lambda pt: pt.clade_any_of(["X.3"])), \
        "an absent clade must select nothing"
    assert not adj.select_antigens(lambda pt: pt.clade_any_of([])), \
        "an empty clade list must select nothing"

    # a point with no clades answers False rather than raising
    for no in (no for no in range(adj.number_of_antigens) if no % 3 == 2):
        assert no not in either, "an unclade-d antigen must not match any clade query"
    print(f"OK [test_clade_predicates]: X.1={len(x1)} X.2={len(x2)} union={len(either)}, "
          "has_clade/has_any_clade_of/clade_any_of agree")


def test_clade_and_aa_and_geometry_combine():
    """The dominant AD idiom: clade or AA *and* geometry, in one predicate. This is the
    combination that had no ae expression before (audit §3): geometry lived on the adjust
    Point, sequence and clade only on chart_v3's SelectionData."""
    adj = Adjust(_chart(sequences=True))
    x1 = set(adj.select_antigens(lambda pt: pt.clade_any_of(["X.1"])))
    aa = set(adj.select_antigens(lambda pt: bool(pt.aa["5A"])))

    # The map is relaxed from a random start, so a fixed half-plane catches an arbitrary
    # share of it — sometimes none of x1 & aa, which left the test proving nothing (it
    # flaked on the "selected nothing" guard roughly one run in eight). Cut instead at the
    # median x of the very points the sequence terms pick out, which always leaves some of
    # them inside and some outside, whatever orientation the optimizer landed on.
    coords = {}
    adj.select_antigens(lambda pt: bool(coords.__setitem__(pt.no, pt.coords)))
    xs = sorted(coords[no][0] for no in (x1 & aa) if coords.get(no))
    cut = xs[len(xs) // 2]
    far = max(abs(v) for co in coords.values() if co for v in co) + 1.0
    region = adj.figure([[cut, -far], [far, -far], [far, far], [cut, far]],
                        frame="map-not-transformed")

    inside = set(adj.select_antigens(lambda pt: pt.inside(region)))
    combined = set(adj.select_antigens(
        lambda pt: pt.clade_any_of(["X.1"]) and bool(pt.aa["5A"]) and pt.inside(region)))
    assert combined == x1 & aa & inside, "combined predicate is not the intersection"
    assert combined, "the fixture selected nothing — the test is not exercising anything"
    assert combined < (x1 & aa), "the geometry term excluded nothing — test proves nothing"
    print(f"OK [test_clade_and_aa_and_geometry_combine]: {len(combined)} antigens = "
          f"clade({len(x1)}) AND aa({len(aa)}) AND inside({len(inside)})")


# ----------------------------------------------------------------------
# frozen viewport (step 1, refined)

def test_viewport_is_frozen_until_invalidated():
    "Moving points must not shift the frame; rotate/flip must."
    adj = Adjust(_chart(rotate=25.0))
    before = adj.viewport()

    # move a chunk of the map a long way: the bounding ball genuinely changes
    movable = adj.select_antigens(lambda pt: pt.no < max(2, adj.number_of_antigens // 2))
    adj.move(movable, to=[40.0, 40.0])
    assert adj.viewport() == before, "a move must not shift the cached viewport (AD does not)"
    adj.relax()
    assert adj.viewport() == before, "a relax must not shift the cached viewport (AD does not)"

    recomputed = adj._calculate_viewport()
    assert any(abs(p - q) > 1e-6 for p, q in zip(recomputed, before)), \
        "the fixture did not actually change the layout's extent — test proves nothing"

    adj.invalidate_viewport()
    assert adj.viewport() == recomputed, "invalidate_viewport must force a recomputation"

    # rotate and flip invalidate on their own, as ChartDraw::rotate/flip do
    for op in (lambda a: a.rotate(0.3), lambda a: a.flip_ew(), lambda a: a.flip_ns()):
        adj = Adjust(_chart(rotate=25.0))
        settled = adj.viewport()
        op(adj)
        assert adj.viewport() != settled, f"{op} must invalidate the viewport"
    print("OK [test_viewport_is_frozen_until_invalidated]: frozen across move/relax, "
          "recomputed on invalidate/rotate/flip")


def test_frozen_viewport_keeps_later_polygons_meaningful():
    """A polygon authored *after* a move resolves in the same frame as one authored
    before it — the `path -> move -> path` pattern real adjust scripts use."""
    adj = Adjust(_chart(rotate=25.0))
    origin_x, origin_y, size = adj.viewport()
    target = [size / 2, size / 2]

    movers = adj.select_antigens(lambda pt: pt.no < 3)
    adj.move(movers, to=target)

    # a small box around where they landed, authored in the same viewport-origin frame
    box = [[target[0] - 1, target[1] - 1], [target[0] + 1, target[1] - 1],
           [target[0] + 1, target[1] + 1], [target[0] - 1, target[1] + 1]]
    caught = set(adj.select_antigens(lambda pt: pt.inside(adj.figure(box))))
    assert set(movers) <= caught, \
        f"the moved points {movers} are not inside a box around their destination: {sorted(caught)}"
    print(f"OK [test_frozen_viewport_keeps_later_polygons_meaningful]: a post-move polygon "
          f"caught all {len(movers)} moved points")


# ----------------------------------------------------------------------
# the Zd / Slot chain (step 3)

# The section functions below sit at module level because that is where an adjust/0do
# script puts them, and it matters: the slot name is the *qualname* with every "<locals>"
# replaced, so a section nested one level deeper would name its slots
# "outer.00.section.00.step" rather than "section.00.step".

_names = []


def a_section(zd):
    "Two slots, recording their names — mirrors a two-step adjust/0do script."
    @zd.slot
    def first(slot):
        _names.append(slot.slot_name)

    @zd.slot
    def second(slot):
        _names.append(slot.slot_name)


def test_slot_names_follow_ad_scheme():
    "Slot names are the qualname with <locals> replaced by a two-digit slot counter."
    _names.clear()
    a_section(Zd("a_section"))
    assert _names == ["a_section.00.first", "a_section.01.second"], _names
    print(f"OK [test_slot_names_follow_ad_scheme]: {_names}")


_drawn = []
_source = None


def snapshot_section(zd):
    "One slot that takes two snapshots, so the NN numbering can be checked."
    @zd.slot
    def make(slot):
        slot.renderer = lambda sl, path, png, open: _drawn.append(path.name)
        slot.chart_filename = _source
        slot.select_antigens(lambda pt: pt.no < 2, report=False)      # snapshot 00
        slot.select_antigens(lambda pt: pt.no < 3, report=False)      # snapshot 01
        return slot.final_ace()

    return make            # the decorator has rebound `make` to the slot's return value


def test_slot_writes_99_ace_and_numbers_snapshots(tmp):
    "A slot creates its directory, numbers snapshots from 00, and writes 99.ace on exit."
    global _source
    source = _source = tmp / "source.ace"
    _chart().write(str(source))
    drawn = _drawn
    drawn.clear()

    final = snapshot_section(Zd("snapshot_section", directory=tmp))
    subdir = tmp / "snapshot_section.00.make"
    assert subdir.is_dir(), f"slot directory {subdir} was not created"
    assert final == subdir / "99.ace", final
    assert final.exists(), "99.ace was not written"
    assert drawn == ["00.pdf", "01.pdf", "99.pdf"], drawn
    # the written chart is readable and has the same antigen count
    assert ae_backend.chart_v3.Chart(str(final)).number_of_antigens() == \
        ae_backend.chart_v3.Chart(str(source)).number_of_antigens()
    print(f"OK [test_slot_writes_99_ace_and_numbers_snapshots]: {subdir.name}/99.ace, "
          f"snapshots {drawn}")


_seen = {}


def move_them(zd):
    "Two chained slots: the second starts from whatever the first returned."
    @zd.slot
    def first(slot):
        slot.chart_filename = _source
        moved = slot.select_antigens(lambda pt: pt.no < 3, report=False, snapshot=False)
        slot.move(moved, to=[40.0, 40.0], snapshot=False)
        _seen["first_coords"] = [slot.adjust.coordinates(i) for i in moved]
        return slot.final_ace()

    @zd.slot
    def second(slot):
        slot.chart_filename = first          # the decorator rebound this to a Path
        _seen["second_source"] = slot.chart_filename
        _seen["second_coords"] = [slot.adjust.coordinates(i) for i in range(3)]
        return slot.final_ace()


def test_slot_chain_passes_the_chart_on(tmp):
    """The real chaining idiom: the second slot sets `chart_filename` to what the first
    returned, and so starts from the first slot's 99.ace, moves included."""
    global _source
    source = _source = tmp / "source.ace"
    _chart().write(str(source))
    seen = _seen
    seen.clear()

    move_them(Zd("move_them", directory=tmp))

    assert seen["second_source"] == tmp / "move_them.00.first" / "99.ace", seen["second_source"]
    for a, b in zip(seen["first_coords"], seen["second_coords"]):
        assert all(abs(p - q) < 1e-9 for p, q in zip(a, b)), \
            f"the chained slot did not inherit the move: {a} vs {b}"
    assert (tmp / "move_them.01.second" / "99.ace").exists(), "second slot wrote no 99.ace"
    print("OK [test_slot_chain_passes_the_chart_on]: slot 01 started from slot 00's 99.ace "
          "with the moves applied")


def boom(zd):
    "A slot whose body raises after opening a chart."
    @zd.slot
    def step(slot):
        slot.chart_filename = _source
        raise RuntimeError("deliberate")


def test_slot_finalizes_even_when_the_body_raises(tmp):
    "AD finalizes in a `finally`; a failing step still leaves its 99.ace behind."
    global _source
    _source = tmp / "source.ace"
    _chart().write(str(_source))

    try:
        boom(Zd("boom", directory=tmp))
    except RuntimeError as err:
        assert str(err) == "deliberate"
    else:
        raise AssertionError("the exception should have propagated")
    assert (tmp / "boom.00.step" / "99.ace").exists(), \
        "finalize must run even when the slot body raises"
    print("OK [test_slot_finalizes_even_when_the_body_raises]: 99.ace written on the way out")


def nothing(zd):
    "A slot that never touches a chart."
    @zd.slot
    def step(slot):
        return "no chart here"

    return step            # the decorator has rebound `step` to the slot's return value


def test_slot_without_a_chart_touches_nothing(tmp):
    "A slot that never sets chart_filename creates no directory, as AD's does not."
    assert nothing(Zd("nothing", directory=tmp)) == "no chart here"
    assert not (tmp / "nothing.00.step").exists(), "an empty slot must not create a directory"
    print("OK [test_slot_without_a_chart_touches_nothing]: no directory created")


def serum_section(zd):
    "One slot that selects and moves sera by point index."
    @zd.slot
    def step(slot):
        slot.chart_filename = _source
        nag = slot.adjust.number_of_antigens
        sera = slot.select_sera(report=False, snapshot=False)
        assert sera == list(range(nag, nag + slot.adjust.number_of_sera)), sera
        before = slot.adjust.coordinates(sera[0])
        slot.move(sera[:1], to=[3.0, 3.0], snapshot=False)
        after = slot.adjust.coordinates(sera[0])
        assert any(abs(p - q) > 1e-9 for p, q in zip(before, after)), \
            "moving by point index did not move the serum"
        return len(sera)

    return step            # the decorator has rebound `step` to the slot's return value


def test_select_returns_point_indices(tmp):
    "Slot.select_sera returns *point* indices (nag + serum_no), what move() consumes."
    global _source
    _source = tmp / "source.ace"
    _chart().write(str(_source))
    assert serum_section(Zd("serum_section", directory=tmp)) > 0
    print("OK [test_select_returns_point_indices]: serum point indices move correctly")


# ----------------------------------------------------------------------

def main():
    test_aa_predicate_matches_sequence_aa()
    test_clade_predicates()
    test_clade_and_aa_and_geometry_combine()
    test_viewport_is_frozen_until_invalidated()
    test_frozen_viewport_keeps_later_polygons_meaningful()
    test_slot_names_follow_ad_scheme()

    tmp = Path(tempfile.mkdtemp(prefix="ae-adjust-slot-"))
    cwd = os.getcwd()
    try:
        test_slot_writes_99_ace_and_numbers_snapshots(tmp)
        test_slot_chain_passes_the_chart_on(tmp)
        test_slot_finalizes_even_when_the_body_raises(tmp)
        test_slot_without_a_chart_touches_nothing(tmp)
        test_select_returns_point_indices(tmp)
    finally:
        os.chdir(cwd)
        shutil.rmtree(tmp, ignore_errors=True)
    print("all adjust-slot checks passed")


if __name__ == "__main__":
    main()
