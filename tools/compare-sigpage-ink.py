#!/usr/bin/env python3
"""Compare an AD signature page with the ae one by the geometry the PDFs actually carry.

Rasterised ink ratios are a trap on these pages (audit 13.3): counting pixels of one exact
colour undercounts thin antialiased strokes non-linearly, so a stroke that is 4x too thin can
read as "74% of the ink" and the corrected one as "141%". Neither number is ink.

This reads the content streams instead, tracks the graphics state, and reports the stroke
width in force at every painted path, grouped by stroke colour. Widths are PDF points, which
is the unit AD's settings are authored in (AD `PointStyle::size`/`outline_width` are both
`Pixels` and go through the same `context::convert`), so AD's column is the authored value
and ae's column should match it.

  usage: compare-sigpage-ink.py [--brief LABEL] AD.pdf ae.pdf

--brief prints one line per page (for sweeping a whole report) instead of the table.
"""

import collections
import re
import subprocess
import sys
import tempfile
import os

_TOKEN = re.compile(rb"[^\s]+")
_PAINT = (b"S", b"s", b"B", b"B*", b"b", b"b*", b"f", b"f*", b"F")

# stroke colours that identify a point class on a signature page
# (stroke colour, paint op) -> point class. The op matters: the tree's 49k black edge
# hairlines are stroke-only `S` and would otherwise swamp the in-section antigens, which are
# fill+stroke `B`.
CLASSES = {
    ((0.878431, 0.878431, 0.878431), "B"): "grey88 base antigen (solid)",
    ((0.878431, 0.878431, 0.878431), "S"): "grey88 reference/serum (hollow)",
    ((1.0, 1.0, 1.0), "B"): "white  in-tree separator",
    ((0.0, 0.0, 0.0), "B"): "black  in-section antigen",
}


def painted_paths(pdf):
    """Yield (stroke_colour, fill_colour, line_width, paint_op) for each painted path."""
    with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as tmp:
        qdf = os.path.join(tmp, "q.pdf")
        subprocess.run(["qpdf", "--qdf", "--object-streams=disable", pdf, qdf], check=True)
        data = open(qdf, "rb").read()

    stroke = fill = None
    width = 1.0
    stack = []
    nums = []
    for tok in _TOKEN.findall(data):
        try:
            nums.append(float(tok))
            if len(nums) > 8:
                nums.pop(0)
            continue
        except ValueError:
            pass
        if tok == b"RG" and len(nums) >= 3:
            stroke = tuple(round(v, 6) for v in nums[-3:])
        elif tok == b"rg" and len(nums) >= 3:
            fill = tuple(round(v, 6) for v in nums[-3:])
        elif tok == b"G" and nums:
            stroke = (round(nums[-1], 6),) * 3
        elif tok == b"g" and nums:
            fill = (round(nums[-1], 6),) * 3
        elif tok == b"w" and nums:
            width = round(nums[-1], 6)
        elif tok == b"q":
            stack.append((stroke, fill, width))
        elif tok == b"Q" and stack:
            stroke, fill, width = stack.pop()
        elif tok in _PAINT:
            yield stroke, fill, width, tok.decode()
        nums = []


def widths_by_class(pdf):
    """-> {class label: Counter(line width -> number of paths)}"""
    out = collections.defaultdict(collections.Counter)
    for stroke, _fill, width, op in painted_paths(pdf):
        label = CLASSES.get((stroke, op))
        if label is not None:
            out[label][width] += 1
    return out


def modal(counter):
    """The width most of the class's paths are drawn at, and how dominant that is."""
    width, n = counter.most_common(1)[0]
    return width, n, sum(counter.values())


def main(argv):
    brief = None
    if len(argv) > 2 and argv[1] == "--brief":
        brief = argv[2]
        argv = [argv[0]] + argv[3:]
    if len(argv) != 3:
        sys.exit(__doc__)
    ad, ae = widths_by_class(argv[1]), widths_by_class(argv[2])

    if brief is not None:
        cells, worst = [], 0.0
        for label in CLASSES.values():
            if label not in ad or label not in ae:
                cells.append("   --  "); continue
            wa, _, _ = modal(ad[label])
            wb, _, _ = modal(ae[label])
            ratio = wb / wa if wa else float("nan")
            worst = max(worst, abs(ratio - 1.0))
            cells.append(f"{wa:5.3f}/{wb:5.3f}")
        print(f"{brief:<28} " + "  ".join(cells) + f"   worst {worst*100:3.0f}%")
        return 0

    print(f"{'point class':<34} {'AD w':>8} {'ae w':>8} {'ae/AD':>7}   paths AD/ae")
    print("-" * 76)
    worst = 0.0
    for label in CLASSES.values():
        if label not in ad or label not in ae:
            continue
        wa, na, ta = modal(ad[label])
        wb, nb, tb = modal(ae[label])
        ratio = wb / wa if wa else float("nan")
        worst = max(worst, abs(ratio - 1.0))
        print(f"{label:<34} {wa:8.3f} {wb:8.3f} {ratio:7.2f}   {ta}  {tb}")
    print()
    print(f"largest stroke-width deviation from AD: {worst * 100:.0f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
