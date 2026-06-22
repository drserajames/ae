#! /usr/bin/env python3
"""Unit tests for the signature-page section<->map coupling logic
(py/ae/tal/section_maps.py). Pure-Python; uses only synthetic data (no chart /
ae_backend / WHO data needed), so it runs under any interpreter.

  python3 cc/tal/test/test-section-maps.py
"""

import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(_ROOT, "py"))

from ae.tal import section_maps as SM


def test_bezier_gradient_endpoints():
    # AD viridis anchors; endpoints are exact, ported bit-for-bit
    scale = SM.bezier_gradient(0x440154, 0x40FFFF, 0xFDE725, 24)
    assert len(scale) == 24
    assert scale[0] == 0x440154, hex(scale[0])
    assert scale[-1] == 0xFDE725, hex(scale[-1])


def test_date_color_scale():
    scale = SM.DateColorScale("2024-03", "2026-03")
    assert scale.n_slots == 24
    assert scale.color_for("2024-03-15") == "#440154"   # first slot
    assert scale.color_for("2026-02-28") == "#fde725"   # last slot
    assert scale.color_for("2023-01-01") is None         # before window -> grey
    assert scale.color_for("2030-01-01") is None         # after window -> grey
    assert scale.color_for("") is None
    lo, hi = scale.slot_date_range(0)
    assert (lo, hi) == ("2024-03-01", "2024-04-01"), (lo, hi)
    lo, hi = scale.slot_date_range(11)                   # 2025-02 (wraps the year)
    assert (lo, hi) == ("2025-02-01", "2025-03-01"), (lo, hi)


def test_parse_sections():
    tal = (
        '{"hz": [{"N": "hz-sections", "sections": [\n'
        '  {"show": true,  "id": "A0", "L": "A", "first": "LOC/1/2024_X", "last": "LOC/9/2024_Y", "label": "Clade.A", "aa_transitions": "T1K"},\n'
        '  {"show": false, "id": "B0", "L": "B", "first": "LOC/10/2024", "last": "LOC/19/2024", "label": "Clade.B", "aa_transitions": ""},\n'  # noqa: E501
        ']}],\n'
        '"tal": [{"N": "time-series", "start": "2024-03", "end": "2026-03"}]}\n'
    )
    with tempfile.NamedTemporaryFile("w", suffix=".tal", delete=False) as fh:
        fh.write(tal)
        path = fh.name
    try:
        secs = SM.parse_sections(path)
        assert len(secs) == 1, secs                       # only the shown one
        assert secs[0]["prefix"] == "A" and secs[0]["label"] == "Clade.A"
        assert SM.section_title(secs[0]) == "A. Clade.A  T1K", SM.section_title(secs[0])
        assert SM.parse_time_series(path) == ("2024-03", "2026-03")
    finally:
        os.unlink(path)


class _FakeChart:
    """Minimal chart stand-in for match_leaf_names: antigens/sera by (no, obj)."""

    class _Pt:
        def __init__(self, name, date=""):
            self._name, self._date = name, date

        def name(self):
            return self._name

        def date(self):
            return self._date

    def __init__(self, antigens, sera):
        self._a = [self._Pt(*x) for x in antigens]
        self._s = [self._Pt(*x) for x in sera]

    def select_all_antigens(self):
        return list(enumerate(self._a))

    def select_all_sera(self):
        return list(enumerate(self._s))

    def antigen(self, i):
        return self._a[i]


def test_matching_and_section_membership():
    # leaves in draw order; some match antigens, one matches a serum
    leaves = [
        "LOC/1/2024_E5_AB",      # antigen 0
        "LOC/2/2024_OR_CD",      # antigen 1 + serum 0 (same strain)
        "OTHER/5/2025_XX",       # no match
        "LOC/3/2025_MDCK1_EF",   # antigen 2
        "LOC/9/2024_GH",         # antigen 3 (section A boundary 'last')
        "LOC/20/2025_IJ",        # outside section A
    ]
    chart = _FakeChart(
        antigens=[("A(H1N1)/LOC/1/2024", "2024-03-10"), ("A(H1N1)/LOC/2/2024", "2025-01-10"),
                  ("A(H1N1)/LOC/3/2025", "2025-06-10"), ("A(H1N1)/LOC/9/2024", "2024-12-10"),
                  ("A(H1N1)/LOC/20/2025", "2025-09-10")],
        sera=[("A(H1N1)/LOC/2/2024", "")],
    )
    match = SM.match_leaf_names(leaves, chart)
    # section A spans first=LOC/1/2024_E5_AB .. last=LOC/9/2024_GH (leaves 0..4)
    ag, sr = SM.antigens_sera_in_section(match, "LOC/1/2024_E5_AB", "LOC/9/2024_GH")
    assert ag == [0, 1, 2, 3], ag          # antigens on leaves 0,1,3,4 (2 is OTHER, unmatched)
    assert sr == [0], sr                    # serum 0 owned by leaf 1, in range
    assert 4 not in ag                      # LOC/20 (leaf 5) is outside the section

    # strain fallback: a 'last' that names a variant not present resolves by strain
    ag2, _ = SM.antigens_sera_in_section(match, "LOC/1/2024_E5_AB", "LOC/9/2024_ZZ_DIFFERENT")
    assert ag2 == [0, 1, 2, 3], ag2


def run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok: {t.__name__}")
    print(f"OK: {len(tests)} section-maps tests passed")


if __name__ == "__main__":
    run()
