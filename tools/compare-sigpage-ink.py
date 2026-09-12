#!/usr/bin/env python3
"""Compare an AD signature page with the ae one by the geometry the PDFs actually carry.

Rasterised ink ratios are a trap on these pages (audit 13.3): counting pixels of one exact
colour undercounts thin antialiased strokes non-linearly, so a stroke that is 4x too thin can
read as "74% of the ink" and the corrected one as "141%". Neither number is ink.

This reads the content streams instead, tracks the graphics state, and reports the stroke
width in force at every painted path, grouped by stroke colour. Widths are PDF points, which
is the unit AD's settings are authored in (AD `PointStyle::size`/`outline_width` are both
`Pixels` and go through the same `context::convert`).

ae's widths are NOT expected to equal AD's. ae draws its map cells wider than AD does, and a
point is sized to span the same fraction OF ITS MAP (section_maps.AD_UNITS_TO_KATERI_PX), so
the target ratio is the ratio of the two cell widths. This tool measures both cell widths off
the same PDFs -- the map-border rectangles -- and reports each class against that target, so
"0% off" means correct rather than identical. Do not "fix" a uniform 5% here.

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
_BORDER_PT = 2.0   # map cell border thickness, the same on both sides

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


def painted_paths(pdf, cell_widths=None):
    """Yield (stroke_colour, fill_colour, line_width, paint_op) for each painted path.

    Map-cell border rectangles are appended to `cell_widths` on the way past.
    """
    if cell_widths is None:
        cell_widths = []
    with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as tmp:
        qdf = os.path.join(tmp, "q.pdf")
        subprocess.run(["qpdf", "--qdf", "--object-streams=disable", pdf, qdf], check=True)
        data = open(qdf, "rb").read()

    stroke = fill = None
    width = 1.0
    stack = []
    nums = []
    rects = cell_widths          # collected by side effect; see cell_width()
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
        elif tok == b"re" and len(nums) >= 4:
            w_, h_ = nums[-2], nums[-1]
            if abs(h_ - _BORDER_PT) < 0.01 and w_ > 50:
                rects.append(round(w_, 3))
            elif abs(w_ - _BORDER_PT) < 0.01 and h_ > 50:
                rects.append(round(h_, 3))
        elif tok in _PAINT:
            yield stroke, fill, width, tok.decode()
        nums = []


def widths_by_class(pdf):
    """-> ({class label: Counter(line width -> paths)}, map cell width in pt)"""
    out = collections.defaultdict(collections.Counter)
    rects = []
    for stroke, _fill, width, op in painted_paths(pdf, rects):
        label = CLASSES.get((stroke, op))
        if label is not None:
            out[label][width] += 1
    cell = collections.Counter(rects).most_common(1)[0][0] if rects else float("nan")
    return out, cell


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
    (ad, cell_ad), (ae, cell_ae) = widths_by_class(argv[1]), widths_by_class(argv[2])
    target = cell_ae / cell_ad   # a point spans the same fraction of its own map

    if brief is not None:
        cells, worst = [], 0.0
        for label in CLASSES.values():
            if label not in ad or label not in ae:
                cells.append("   --  "); continue
            wa, _, _ = modal(ad[label])
            wb, _, _ = modal(ae[label])
            ratio = wb / wa if wa else float("nan")
            worst = max(worst, abs(ratio / target - 1.0))
            cells.append(f"{wa:5.3f}/{wb:5.3f}")
        print(f"{brief:<28} " + "  ".join(cells) +
              f"   cell {cell_ad:.1f}/{cell_ae:.1f}   worst {worst*100:3.0f}%")
        return 0

    print(f"map cell width: AD {cell_ad:.3f} pt, ae {cell_ae:.3f} pt "
          f"-> points should be {target:.4f}x AD's")
    print()
    print(f"{'point class':<34} {'AD w':>8} {'ae w':>8} {'ae/AD':>7} {'vs target':>10}   paths AD/ae")
    print("-" * 88)
    worst = 0.0
    for label in CLASSES.values():
        if label not in ad or label not in ae:
            continue
        wa, na, ta = modal(ad[label])
        wb, nb, tb = modal(ae[label])
        ratio = wb / wa if wa else float("nan")
        off = ratio / target - 1.0
        worst = max(worst, abs(off))
        print(f"{label:<34} {wa:8.3f} {wb:8.3f} {ratio:7.3f} {off * 100:9.1f}%   {ta}  {tb}")
    print()
    print(f"largest deviation from the map-relative target: {worst * 100:.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
