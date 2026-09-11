#!/usr/bin/env python3
"""Verify ae.adjust's port of AD's `slot.compare_sequences(set1, set2)`
(MIGRATION.md Stage B, step 5 / audit §6).

AD's `Slot.compare_sequences` (acmacs_py/zero_do_5.py:387) writes a sequence comparison
of two selections into the slot's directory as `<chart stem>.compare-seq.html`, skipping
the work if the file is already there. The comparison behind it
(acmacs-py/cc/py-mapi.cc:191 -> seqdb-3/cc/compare.{hh,cc}) counts the amino acids of each
group at every position and reports the positions where more than one amino acid occurs
across the groups together.

What is locked down here:

* the **file name and directory** AD writes into, because the report's
  `map-adjustments.txt` records those paths as provenance;
* `overwrite=False`, AD's default — an existing file is left alone;
* the **substance** of the comparison: which positions are reported, the per-group amino
  acid counts, and that unsequenced points are kept in the listing but contribute to no
  counter (AD's `subset_to_compare_selected_t::make_counters` iterates the whole
  selection, and a zero-length sequence simply counts nothing);
* that the page's data lands in a **valid JavaScript identifier**, which the file names
  the adjust stage uses (a dot inside the stem) did not previously produce.

Everything runs on the synthetic test/chart1.ace with invented sequences applied in the
test — never WHO data. Parity with the real AD extension was checked separately, outside
the repo, on the report charts.

Run::  PYTHONPATH=build:py python3 test/adjust_compare_sequences.py
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_root / "build"), str(_root / "py")]

import ae_backend.chart_v3
from ae.adjust import Adjust, Zd
from ae.sequences.compare import Comparison, Group, html_var_name

# invented sequences; position 5 is the only one that varies between the two groups
_SEQ_A = "MKTIA" + "AAAAA"
_SEQ_B = "MKTIB" + "AAAAA"


def _chart():
    """chart1.ace ships with no projection; relax so there is something to adjust. Even
    antigens get sequence A, odd ones B, every third is left unsequenced."""
    chart = ae_backend.chart_v3.Chart(str(_root / "test" / "chart1.ace"))
    chart.relax(number_of_dimensions=2, number_of_optimizations=5, minimum_column_basis="none")
    chart.keep_projections(1)
    for no, ag in chart.select_all_antigens():
        if no % 3 == 2:
            continue
        ag.sequence_aa(_SEQ_A if no % 2 == 0 else _SEQ_B)
    return chart


def _groups(adj, set1, set2):
    "The comparison as the viewer receives it."
    return json.loads(adj.compare_sequences(set1, set2).format_json())


# ----------------------------------------------------------------------

def test_only_varying_positions_are_reported():
    "Only positions where the groups disagree reach the report, as AD's do."
    adj = Adjust(_chart())
    n = adj.number_of_antigens
    set1 = [no for no in range(n) if no % 3 != 2 and no % 2 == 0]      # sequence A
    set2 = [no for no in range(n) if no % 3 != 2 and no % 2 == 1]      # sequence B
    assert set1 and set2, "fixture must give both groups something to compare"

    data = _groups(adj, set1, set2)
    assert data["pos1"] == [5], f"only position 5 varies; got {data['pos1']}"
    assert [g["name"] for g in data["groups"]] == ["1", "2"], \
        "AD names the two groups 1 and 2"
    assert data["groups"][0]["pos1"]["5"] == [{"a": "A", "c": len(set1)}], \
        data["groups"][0]["pos1"]
    assert data["groups"][1]["pos1"]["5"] == [{"a": "B", "c": len(set2)}], \
        data["groups"][1]["pos1"]

    # comparing a group against itself leaves nothing to report
    same = _groups(adj, set1, set1)
    assert same["pos1"] == [], f"identical groups must report no positions; got {same['pos1']}"
    print("OK [test_only_varying_positions_are_reported]: position 5, and only position 5")


def test_unsequenced_points_are_listed_but_count_nothing():
    "An unsequenced point stays in the listing and contributes to no counter, as in AD."
    adj = Adjust(_chart())
    n = adj.number_of_antigens
    sequenced = [no for no in range(n) if no % 3 != 2 and no % 2 == 0]
    unsequenced = [no for no in range(n) if no % 3 == 2]
    assert sequenced and unsequenced, "fixture must have both kinds of point"

    data = _groups(adj, sequenced + unsequenced, [no for no in range(n) if no % 3 != 2 and no % 2 == 1])
    group1 = data["groups"][0]
    assert len(group1["seq"]) == len(sequenced) + len(unsequenced), \
        "every selected point must appear in the listing"
    assert sum(1 for s in group1["seq"] if s["seq"] == "") == len(unsequenced), \
        "unsequenced points must appear with an empty sequence"
    assert group1["pos1"]["5"] == [{"a": "A", "c": len(sequenced)}], \
        f"unsequenced points must not be counted: {group1['pos1']['5']}"
    print("OK [test_unsequenced_points_are_listed_but_count_nothing]: listed, not counted")


def test_empty_selection_is_survivable():
    "An empty group warns (as AD does) rather than raising."
    adj = Adjust(_chart())
    same_sequence = [no for no in range(adj.number_of_antigens) if no % 3 != 2 and no % 2 == 0]
    data = _groups(adj, [], same_sequence)
    assert data["groups"][0]["seq"] == [], "an empty group must contribute no sequences"
    assert data["pos1"] == [], \
        f"one group, all of it identical, leaves nothing to report; got {data['pos1']}"
    print("OK [test_empty_selection_is_survivable]: empty group warns, does not raise")


def test_sera_are_addressed_by_point_index():
    "Sera are `number_of_antigens + serum_no`, the indices select_sera returns."
    adj = Adjust(_chart())
    sera = adj.select_sera()
    assert sera == list(range(adj.number_of_antigens,
                              adj.number_of_antigens + adj.number_of_sera)), sera
    antigens = [no for no in range(adj.number_of_antigens) if no % 3 != 2 and no % 2 == 0]
    data = _groups(adj, antigens, sera)
    assert len(data["groups"][1]["seq"]) == len(sera), \
        "every serum must appear in its group's listing"
    print("OK [test_sera_are_addressed_by_point_index]: sera compared by point index")


def test_html_data_variable_is_a_valid_identifier():
    """The page puts its data in a variable named after the file. The adjust stage's name
    has a dot in the stem (`prestyled.compare-seq.html`), so every non-identifier
    character has to go, not just the hyphens."""
    name = html_var_name(Path("some/dir/prestyled.compare-seq.html"))
    assert name == "compare_sequences_prestyled_compare_seq", name
    assert name.isidentifier(), f"{name} is not a usable JavaScript variable name"
    print("OK [test_html_data_variable_is_a_valid_identifier]:", name)


def test_group_counters_are_one_based():
    """`counters[n]` holds position `n + 1`, matching `ae_backend.SequenceAA`'s 1-based
    indexing and AD's 1-based reporting. Off by one here would silently shift every
    reported position."""
    comparison = Comparison([Group("1", [("a", _Seq(_SEQ_A))]),
                             Group("2", [("b", _Seq(_SEQ_B))])])
    assert comparison.positions_to_report() == [4], comparison.positions_to_report()
    assert json.loads(comparison.format_json())["pos1"] == [5]
    print("OK [test_group_counters_are_one_based]: counters[4] is reported as position 5")


class _Seq:
    "A minimal 1-based sequence, the shape ae_backend.SequenceAA presents."

    def __init__(self, text):
        self._text = text

    def __len__(self):
        return len(self._text)

    def __getitem__(self, pos1):
        return self._text[pos1 - 1] if 1 <= pos1 <= len(self._text) else " "

    def __str__(self):
        return self._text


# ----------------------------------------------------------------------

def compare_section(zd):
    "One slot that compares two selections, the shape a real adjust/0do uses."
    @zd.slot
    def move_outliers(slot):
        slot.chart_filename = _source
        ags1 = slot.select_antigens(lambda pt: bool(pt.aa["5A"]), report=False, snapshot=False)
        ags2 = slot.select_antigens(lambda pt: bool(pt.aa["5B"]), report=False, snapshot=False)
        assert ags1 and ags2, "fixture must give both groups something to compare"
        first = slot.compare_sequences(ags1, ags2, open=False)

        # overwrite=False (AD's default) must leave an existing file alone
        first.write_text("SENTINEL")
        again = slot.compare_sequences(ags1, ags2, open=False)
        assert again == first, (again, first)
        assert first.read_text() == "SENTINEL", "overwrite=False regenerated the file"

        # overwrite=True regenerates it
        slot.compare_sequences(ags1, ags2, overwrite=True, open=False)
        assert first.read_text() != "SENTINEL", "overwrite=True did not regenerate"

        slot.export_final_ace = False
        return first

    return move_outliers    # the decorator has rebound the name to the slot's return value


def test_slot_writes_ads_filename(tmp):
    "The output goes where AD puts it: <slot dir>/<chart stem>.compare-seq.html."
    global _source
    _source = tmp / "prestyled.ace"
    _chart().write(str(_source))

    out = compare_section(Zd("compare_section", directory=tmp))
    assert out == tmp / "compare_section.00.move_outliers" / "prestyled.compare-seq.html", out
    assert out.exists(), out

    page = out.read_text()
    assert "compare_sequences_prestyled_compare_seq" in page, "data variable missing"
    assert '<div id="compare-sequences"' in page, "viewer body missing"
    data = json.loads(page[page.index("compare_sequences_prestyled_compare_seq = ")
                           + len("compare_sequences_prestyled_compare_seq = "):].split(";\n", 1)[0])
    assert data["pos1"] == [5], data["pos1"]
    print("OK [test_slot_writes_ads_filename]:", out.name, "in", out.parent.name)


# ----------------------------------------------------------------------

def main():
    test_only_varying_positions_are_reported()
    test_unsequenced_points_are_listed_but_count_nothing()
    test_empty_selection_is_survivable()
    test_sera_are_addressed_by_point_index()
    test_html_data_variable_is_a_valid_identifier()
    test_group_counters_are_one_based()

    tmp = Path(tempfile.mkdtemp(prefix="ae-adjust-compare-seq-"))
    try:
        test_slot_writes_ads_filename(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("all adjust compare-sequences checks passed")


if __name__ == "__main__":
    main()
