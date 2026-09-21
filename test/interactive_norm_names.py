#!/usr/bin/env python3
"""Verify interactive/export_interactive.py norm_tree_name() / norm_chart_name(): a tree leaf
and the chart antigen it came from normalise to the same key.

The regression: norm_tree_name stripped exactly one passage token plus the hash, so a leaf
with two passage tokens (_OR_IR), none, or a space written as '_' never matched its chart
antigen. Those antigens got no AA sequence and showed grey under colour-by-position.

All strings here are invented placeholders — no WHO data.

Run::  PYTHONPATH=build:py python3 test/interactive_norm_names.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "interactive"))
from export_interactive import norm_chart_name, norm_tree_name

H = "0BADC0DE"   # stands in for the 8-hex sequence hash every leaf ends with

# (tree leaf, chart antigen name it must match)
PAIRS = [
    (f"EXAMPLECITY/36/2026_{H}",                  "A(H1N1)/EXAMPLECITY/36/2026"),      # no passage
    (f"EXAMPLECITY/1/2025_OR_{H}",                "A(H1N1)/EXAMPLECITY/1/2025"),       # 1 passage token
    (f"EXAMPLECITY/1/2025_OR_IR_{H}",             "A(H1N1)/EXAMPLECITY/1/2025"),       # 2 passage tokens
    (f"EXAMPLECITY/2/2025_MDCK1/SIAT1_{H}",       "EXAMPLECITY/2/2025"),               # '/' inside passage
    (f"EXAMPLETOWN_EXAMPLEISLES/7/2025_OR_{H}",   "A(H3N2)/EXAMPLETOWN EXAMPLEISLES/7/2025"),  # space as '_'
    (f"EXAMPLETOWN_EXAMPLEISLES/EXAMPLE_6/2026_OR_{H}", "A(H1N1)/EXAMPLETOWN EXAMPLEISLES/EXAMPLE_6/2026"),  # literal '_' in isolate
    (f"EXAMPLECITY/1234_25/2025_OR_{H}",          "EXAMPLECITY/1234_25/2025"),         # 4-digit isolate is not the year
    (f"EXAMPLECITY/9/2024_A/EXAMPLECITY/9/2024_{H}", "EXAMPLECITY/9/2024"),            # second name in the passage field
    (f"A/EXAMPLECITY/3/2025_OR_{H}",              "A(H1N1)/EXAMPLECITY/3/2025"),       # subtype prefix on the leaf
    (f"B/EXAMPLECITY/4/2025_E1/E1_{H}",           "B/EXAMPLECITY/4/2025"),
    (f"EXAMPLELANDR123/2022_OR_{H}",              "A(H1N1)/EXAMPLELANDR123/2022"),     # one field before the year
]


def main():
    for leaf, chart in PAIRS:
        t, c = norm_tree_name(leaf), norm_chart_name(chart)
        assert t == c, f"{leaf!r} -> {t!r} but {chart!r} -> {c!r}"

    # exact keys, so both sides can't drift together into something wrong
    assert norm_tree_name(f"EXAMPLETOWN_EXAMPLEISLES/7/2025_OR_IR_{H}") == "EXAMPLETOWN EXAMPLEISLES/7/2025"
    assert norm_chart_name("A(H1N1)/EXAMPLETOWN EXAMPLEISLES/EXAMPLE_6/2026") == "EXAMPLETOWN EXAMPLEISLES/EXAMPLE 6/2026"
    assert norm_chart_name("BEXAMPLE/212/2019") == "BEXAMPLE/212/2019"   # no prefix to strip

    # no /YYYY: only the hash goes; the rest is kept whole, so it can miss but never mis-match
    assert norm_tree_name(f"EXAMPLE/DHSS-11_{H}") == "EXAMPLE/DHSS-11"
    assert norm_tree_name(f"A/EXAMPLE-958-23_OR_{H}") == "EXAMPLE-958-23 OR"
    assert norm_tree_name(f"EXAMPLECITY/EXAMPLE1/2024.0_{H}") == "EXAMPLECITY/EXAMPLE1/2024.0"

    # distinct strains stay distinct
    assert norm_tree_name(f"EXAMPLECITY/1/2025_OR_{H}") != norm_tree_name(f"EXAMPLECITY/11/2025_OR_{H}")

    print(f"interactive_norm_names: {len(PAIRS)} pairs + 7 fixed keys OK")


if __name__ == "__main__":
    main()
