#!/usr/bin/env python3
"""One registry for the horizontal rules that cross the time-series matrix.

AD keeps every such rule in a single collection keyed by the node it sits above, and a second
registration for the same node adds nothing (acmacs-tal cc/time-series.cc:138,
`TimeSeries::add_horizontal_line_above` — `std::find_if` on the node, then `emplace_back` only
when not found). Two producers call it: `Clades::add_separators_to_time_series` (cc/clades.cc:200,
GREY 0.5) and `HzSections::add_separators_to_time_series` (cc/hz-sections.cc:168, GREY 1.0). So
where an hz-section boundary lands on a leaf that already carries a clade rule, AD draws ONE
line, with the CLADE's parameters — because `Clades::prepare` registers at preparation stage 1
(cc/clades.cc:26, `if (!prepared_)`) and `HzSections::prepare` is guarded by `stage == 2`
(cc/hz-sections.cc:23), whatever order the two elements sit in the layout.

ae drew both, at different widths and different x-extents. That stayed invisible only while the
report trees never ran their `hz` sub-program.

What is asserted here, on tree-hz-clade-lines.json (8 synthetic leaves, invented clades P and Q):

  * a boundary shared by a clade and an hz section carries exactly ONE rule, at the clade's
    0.5 width -- clades register first;
  * an hz boundary clear of every clade still carries its own rule, at 0.4;
  * a clade's rules sit on ITS OWN rows -- top edge of the first, bottom edge of the last
    (AD LayoutElement::pos_y_above/pos_y_below, cc/layout.cc:253/261). ae fed a 0-based leaf
    INDEX to a 1-based vertical offset and drew every clade bracket one row high, which is what
    stopped a coincident boundary ever coinciding;
  * a clade's horizontal arm stays inside the clades column (AD Clades::draw runs it from the
    arrow to the viewport edge, cc/clades.cc:281-283) instead of being painted across the matrix;
  * two abutting sections share the one rule between them, because AD registers a bottom rule
    above `section.last->last_next_leaf` -- the leaf AFTER the section;
  * a section ending on the tree's LAST leaf registers no bottom rule at all: `last_next_leaf`
    is null there (cc/tree.hh:114).

Synthetic data only -- invented leaf names, dates and clade tokens.

    python3 cc/tal/test/test-hz-clade-lines.py

Needs `build/tal-draw` (or $TAL_DRAW).
"""

import os
import re
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]

GREY = (0.745, 0.745, 0.745)
BLACK = (0.0, 0.0, 0.0)
CLADE_W, HZ_W = 0.5, 1.0      # AD clades.hh:79 GREY 0.5; AD hz-sections.hh:60 GREY 1.0

failures: list[str] = []


def check(ok: bool, what: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {what}")
    if not ok:
        failures.append(what)


def segments(pdf: Path) -> list[tuple[tuple, float, float, float, float, float]]:
    """(stroke_colour, width, x0, y0, x1, y1) for every stroked straight segment.

    Coordinates are read straight out of the content stream, which is already the TREE's
    top-down space: tal-draw emits one leading "1 0 0 -1 0 H cm" and every number after it is
    what dev_y() / dev_x() produced. So a y here is directly comparable to a row boundary.
    """
    data = pdf.read_bytes()
    text = ""
    for st in re.finditer(rb"stream\r?\n", data):
        chunk = data[st.end():data.find(b"endstream", st.end())]
        try:
            text += zlib.decompress(chunk).decode("latin1")
        except zlib.error:
            text += chunk.decode("latin1")

    out = []
    stroke, width, nums, pt, path = BLACK, 1.0, [], None, []
    for tok in text.split():
        try:
            nums.append(float(tok))
            del nums[:-8]
            continue
        except ValueError:
            pass
        if tok == "RG" and len(nums) >= 3:
            stroke = tuple(round(c, 3) for c in nums[-3:])
        elif tok == "w" and nums:
            width = round(nums[-1], 3)
        elif tok == "m" and len(nums) >= 2:
            pt = (nums[-2], nums[-1])
        elif tok == "l" and len(nums) >= 2 and pt is not None:
            nxt = (nums[-2], nums[-1])
            path.append((pt, nxt))
            pt = nxt
        elif tok in ("S", "s"):      # STROKED only: the clade arrowheads are filled triangles,
            for a, b in path:        # whose horizontal base would otherwise read as a rule
                out.append((stroke, width, a[0], a[1], b[0], b[1]))
            pt, path = None, []
        elif tok in ("f", "F", "f*", "B", "B*", "b", "b*", "n"):
            pt, path = None, []
        nums = []
    return out


def main() -> int:
    tal_draw = os.environ.get("TAL_DRAW", str(ROOT / "build" / "tal-draw"))
    if not os.access(tal_draw, os.X_OK):
        print(f"FAIL: {tal_draw} not built")
        return 1

    with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as tmpdir:
        pdf = Path(tmpdir) / "hz-clade-lines.pdf"
        subprocess.run([tal_draw, f"--settings={HERE / 'draw-settings-hz-clade-lines.json'}",
                        str(HERE / "tree-hz-clade-lines.json"), str(pdf)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        segs = segments(pdf)

    horiz = [s for s in segs if abs(s[3] - s[5]) < 1e-6]
    verts = [s for s in segs if abs(s[2] - s[4]) < 1e-6 and abs(s[3] - s[5]) > 0.5]

    # Row geometry straight off the page: the leaf tip edges and the time-series dash marks are
    # the only BLACK horizontals, and both sit on leaf-row centres, so their distinct y values
    # are the 8 centres. Row i then spans [c[i] - vstep/2, c[i] + vstep/2].
    centres = sorted({round(s[3], 3) for s in horiz if s[0] == BLACK})
    check(len(centres) == 8, f"8 leaf rows found on the page (got {len(centres)})")
    if len(centres) != 8:
        return 1
    vstep = centres[1] - centres[0]
    top = [c - vstep / 2.0 for c in centres]          # top[i]    = top edge of leaf i's row
    bottom = [c + vstep / 2.0 for c in centres]       # bottom[i] = bottom edge of leaf i's row

    def at(y_expected, group):
        return [s for s in group if abs(s[3] - y_expected) < 0.01]

    # The matrix's x-extent, from the black vertical slot separators: they are the only group of
    # >= 3 verticals sharing one exact height (each spans the whole tree band). The tree's own
    # root connector is a one-off and must not be mistaken for the matrix's left edge.
    heights: dict[float, list[float]] = {}
    for s in verts:
        if s[0] == BLACK:
            heights.setdefault(round(abs(s[5] - s[3]), 2), []).append(round(s[2], 2))
    sep_x = sorted(set(max((v for v in heights.values() if len(v) >= 3), key=len)))
    matrix_l, matrix_r = sep_x[0], sep_x[-1]
    grey = [s for s in horiz if s[0] == GREY]
    matrix_rules = [s for s in grey if abs(s[2] - matrix_l) < 0.01]
    clade_arms = [s for s in grey if abs(s[2] - matrix_l) >= 0.01]

    # --- the registry: one rule per boundary, clades winning a shared one ------------------
    # Clade P covers L3..L5 = leaf indices 2..4; clade Q covers L7 = index 6. hz sections:
    # H1 = L1 (index 0), H2 = L3..L5, H3 = L7, H4 = L8 (index 7, the last leaf).
    shared = {"clade P top (= hz H2 top)": top[2], "clade P bottom (= hz H2 bottom)": bottom[4],
              "clade Q top (= hz H3 top)": top[6], "clade Q bottom (= hz H3 bottom, = hz H4 top)": bottom[6]}
    for what, y in shared.items():
        found = at(y, matrix_rules)
        check(len(found) == 1, f"{what}: exactly one matrix rule (got {len(found)})")
        check(bool(found) and found[0][1] == CLADE_W,
              f"{what}: kept the CLADE's width {CLADE_W} (got {found[0][1] if found else None}) — clades register first")

    for what, y in {"hz H1 top": top[0], "hz H1 bottom": bottom[0]}.items():
        found = at(y, matrix_rules)
        check(len(found) == 1, f"{what}, clear of every clade: exactly one matrix rule (got {len(found)})")
        check(bool(found) and found[0][1] == HZ_W,
              f"{what}: drawn at the hz width {HZ_W} (got {found[0][1] if found else None})")

    check(len(matrix_rules) == 6,
          f"6 matrix rules in total, one per distinct boundary (got {len(matrix_rules)})")
    ys = [round(s[3], 3) for s in matrix_rules]
    check(len(ys) == len(set(ys)), "no two matrix rules share a y")

    # H4 ends on the LAST leaf: AD has no `last_next_leaf` to key its bottom rule on.
    check(not at(bottom[7], matrix_rules),
          "hz H4 ends on the last leaf: no bottom rule (AD Node::last_next_leaf is null)")

    # --- the clade bracket sits on its own rows, and stays out of the matrix ---------------
    for what, y in {"clade P top arm": top[2], "clade P bottom arm": bottom[4],
                    "clade Q top arm": top[6], "clade Q bottom arm": bottom[6]}.items():
        check(len(at(y, clade_arms)) == 1, f"{what} on clade's own row (got {len(at(y, clade_arms))})")
    check(len(clade_arms) == 4, f"4 clade arms in total (got {len(clade_arms)})")
    check(all(s[2] >= matrix_r - 0.01 for s in clade_arms),
          "no clade arm is painted across the matrix (AD draws it inside the clades viewport)")
    # The one-row-high bug: clade P's rules would have landed on top[1] / bottom[3]. Test for a
    # rule of the CLADE width there, not for any grey rule — top[1] is also hz H1's bottom
    # boundary, which legitimately carries a 0.4 one.
    stray = at(top[1], grey) + at(bottom[3], grey)
    check(all(s[1] != CLADE_W for s in stray),
          "clade P is not drawn one row high (the 0-based index vs 1-based offset slip)")

    print()
    if failures:
        print(f"FAILED ({len(failures)}):")
        for f in failures:
            print(f"  {f}")
        return 1
    print("OK: matrix horizontal rules go through one registry, clades first (AD parity)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
