#!/usr/bin/env python3
"""Regression test for the signature page's hz-section marker column (AD
`HzSectionMarker::draw`, acmacs-tal cc/hz-sections.cc).

`draw-tree.cc` gates the whole bracket + section-letter column on
`!params.hz_sections.empty()`, and that list is filled from the tal-draw schema's
`hz_sections`. `settings_v3.translate` only fills it from an `hz-sections` command the
`.tal`'s program actually RUNS — which no report `.tal` from 2026-0805-tc1 on does (they
keep the block but dropped the `hz` sub-program). So the schema's list came out empty, the
column drew nothing, and the page lost the A/B/C keys tying each map panel to its section.
`_tal_to_settings(hz_sections=…)` now writes the sections the page is really built from.

Pure Python (no ae_backend, no rendering); fully synthetic `.tal` and section list — no
real strain names, no chart.

    python3 cc/tal/test/test-sigpage-hz-marker.py
"""

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "py"))

from ae.tal.signature_page import _tal_to_settings

# A `.tal` shaped like the report ones: it DEFINES hz-sections but its `tal` program never
# reaches the `hz` sub-array, so `find_command` correctly ignores the block.
INERT_TAL = {
    "tal": [{"N": "nodes"}],
    "hz": [{"N": "hz-sections", "sections": [
        {"show": True, "id": "STALE-0", "L": "Z", "first": "LEAF_STALE", "last": "LEAF_STALE"},
    ]}],
}

# What the driver computes (SM.sections_for + SM.assign_prefixes): letters in tree order.
SECTIONS = [
    {"id": "SEC1-0", "prefix": "A", "first": "LEAF_01", "last": "LEAF_09", "label": "c.1"},
    {"id": "SEC2-0", "prefix": "B", "first": "LEAF_10", "last": "LEAF_19", "label": "c.2"},
    {"id": "SEC3-0", "prefix": "C", "first": "LEAF_20", "last": "LEAF_29", "label": "c.3"},
    # a degenerate entry (no `last`) must be dropped, not passed to the C++ as a half-section
    {"id": "BAD-0", "prefix": "D", "first": "LEAF_30", "last": "", "label": "bad"},
]


def build(tmpdir, **kwargs):
    tal = os.path.join(tmpdir, "synthetic.tal")
    with open(tal, "w", encoding="utf-8") as out:
        json.dump(INERT_TAL, out)
    import pathlib
    path, _ = _tal_to_settings(tal, pathlib.Path(tmpdir), None, clades_before_time_series=True, **kwargs)
    return json.loads(open(path, encoding="utf-8").read())


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        without = build(tmpdir, hz_sections=None)
        with_sections = build(tmpdir, hz_sections=SECTIONS)
        # the driver also passes the {first_seq_id: letter} map; it must not clobber the
        # prefixes already carried by the section list
        prefixed = build(tmpdir, hz_sections=SECTIONS,
                         section_prefixes={"LEAF_01": "A", "LEAF_10": "B", "LEAF_20": "C"})

    marker = with_sections.get("hz_sections")
    checks = {
        # the bug: an inert `hz-sections` block leaves the schema list empty, so draw-tree.cc
        # draws no marker column at all
        "inert .tal block alone yields no sections": not without.get("hz_sections"),
        "hz_section_labels enabled on a sig page": with_sections.get("hz_section_labels") is True,
        "driver sections reach the schema": isinstance(marker, list) and len(marker) == 3,
        "letters in tree order": [s.get("prefix") for s in marker or []] == ["A", "B", "C"],
        "first/last carried through": [s.get("first") for s in marker or []] == ["LEAF_01", "LEAF_10", "LEAF_20"],
        "labels carried through": [s.get("label") for s in marker or []] == ["c.1", "c.2", "c.3"],
        "half-section dropped": all(s.get("id") != "BAD-0" for s in marker or []) and all(
            s.get("first") and s.get("last") for s in marker or []),
        "stale .tal 'L' not used": all(s.get("prefix") != "Z" for s in marker or []),
        "section_prefixes agrees, does not clobber": [s.get("prefix") for s in prefixed.get("hz_sections", [])] == ["A", "B", "C"],
    }
    failures = [name for name, ok in checks.items() if not ok]
    if failures:
        print("FAIL:")
        for name in failures:
            print(f"  - {name}")
        print(f"  hz_sections={marker}")
        sys.exit(1)
    print(f"OK: sig-page hz-section marker column ({len(checks)} checks)")


if __name__ == "__main__":
    main()
