#!/usr/bin/env python3
"""Clade-column geometry: fractional / negative `slot`, and the settable column gap.

A clade bracket sits at `slot.width * (slot + 1)` from the clades column's inner edge
(AD acmacs-tal cc/clades.cc:269), and the column itself is one inter-column `gap` away from
the time-series matrix. So the matrix -> bracket distance is `gap + slot.width*(slot+1)`, and
until now the only `.tal` lever on it was `slot.width` — which also sets the pitch between
clade levels and the label size, so pulling one bracket in shrank the whole staircase.

Two levers are checked here:

* a per-clade `slot` that keeps its fraction and sign (ae accepts -0.5 / 0.5 / 2.2; AD's own
  slot_no is an unsigned size_t and truncates, so this is a deliberate superset), and
* `clades.gap_ratio`, which overrides the gap before the clades column. AD spells this as an
  explicit `{"N": "gap"}` element in the `.tal` program; ae lays the columns out itself.

Synthetic data only — the existing synthetic test tree (clades X, Y) and an invented config.

    python3 cc/tal/test/test-clade-slots.py

Needs `build/tal-draw` (or $TAL_DRAW).
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import zlib
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]

failures: list[str] = []


def check(ok: bool, what: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {what}")
    if not ok:
        failures.append(what)


def vertical_segments(pdf: Path) -> list[tuple[float, float]]:
    """(x, height) for every vertical line segment in the page's content streams."""
    data = pdf.read_bytes()
    num = r"(-?\d+\.?\d*)"
    seg = re.compile(rf"{num} {num} m\s+{num} {num} l", re.S)
    out: list[tuple[float, float]] = []
    for st in re.finditer(rb"stream\r?\n", data):
        chunk = data[st.end():data.find(b"endstream", st.end())]
        try:
            text = zlib.decompress(chunk).decode("latin1")
        except zlib.error:
            continue
        for x0, y0, x1, y1 in seg.findall(text):
            x0, y0, x1, y1 = float(x0), float(y0), float(x1), float(y1)
            if abs(x1 - x0) < 0.05 and abs(y1 - y0) > 0.5:
                out.append((x0, round(abs(y1 - y0), 1)))
    return out


def geometry(pdf: Path) -> tuple[float, float, float, int]:
    """(matrix right edge x, clade-X bracket x, clade-Y bracket x, n time-series slots).

    The matrix separators are the only group of >= 3 verticals sharing one exact height (each
    spans the whole tree band); the clade brackets are one-offs to the right of them. Clade X
    covers A..E and clade Y only C..D, so X is the taller arm.
    """
    segs = vertical_segments(pdf)
    heights = Counter(h for _, h in segs)
    sep_h = max((h for h, n in heights.items() if n >= 3), key=lambda h: heights[h])
    separators = sorted({x for x, h in segs if h == sep_h})
    matrix_right = separators[-1]
    arms = [(x, h) for x, h in segs if x > matrix_right + 0.5 and h != sep_h]
    x_arm = max(arms, key=lambda a: a[1])[0]
    y_arm = min(arms, key=lambda a: a[1])[0]
    return matrix_right, x_arm, y_arm, len(separators) - 1


SIZE, RATIO = 1000, 0.6
CLADE_SLOT_W, TS_SLOT_W = 0.02, 0.01
SLOT_PX = CLADE_SLOT_W * SIZE     # 20pt — one clade slot
DEFAULT_GAP_PX = 0.012 * SIZE * RATIO   # 7.2pt — draw-tree.cc's fixed inter-column gap


def render(tmp: Path, tal_draw: str, tag: str, slot, gap_ratio=None) -> tuple[float, float, float, int]:
    clades: dict = {"show": True, "slot_width": CLADE_SLOT_W}
    if gap_ratio is not None:
        clades["gap_ratio"] = gap_ratio
    cfg = {
        "_": "synthetic clade-slot geometry fixture — see cc/tal/test/test-clade-slots.py",
        "image_size": SIZE,
        "width_to_height_ratio": RATIO,
        "labels": False,
        "clades": clades,
        "time_series": {"show": True, "interval": "month", "start": "2020-01", "end": "2021-01",
                        "slot_width": TS_SLOT_W},
        "clade_styles": [{"name": "X", "slot": slot}, {"name": "Y"}],
    }
    sfile = tmp / f"{tag}.json"
    sfile.write_text(json.dumps(cfg))
    pdf = tmp / f"{tag}.pdf"
    subprocess.run([tal_draw, f"--settings={sfile}", str(HERE / "tree-clades.json"), str(pdf)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return geometry(pdf)


tal_draw = os.environ.get("TAL_DRAW") or str(ROOT / "build" / "tal-draw")
if not os.access(tal_draw, os.X_OK):
    print(f"  SKIP clade slot geometry — {tal_draw} not built")
else:
    with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as tmpname:
        tmp = Path(tmpname)

        # --- the reference: clade X at slot 0, default gap ---
        m0, x0, _, n0 = render(tmp, tal_draw, "slot-0", 0)
        check(n0 == 12, f"[2020-01, 2021-01) draws 12 monthly slots (got {n0})")
        check(abs((x0 - m0) - (DEFAULT_GAP_PX + SLOT_PX)) < 0.05,
              f"slot 0: matrix -> bracket is gap + one slot = {DEFAULT_GAP_PX + SLOT_PX:.2f}pt "
              f"(got {x0 - m0:.2f})")

        # --- a fraction of a slot, either way. The bracket must move by exactly that fraction,
        #     and `slot.width` (hence the level pitch and the label size) must not change. ---
        for slot in (-0.5, 0.5, 2.2):
            m, x, _, n = render(tmp, tal_draw, f"slot-{slot}", slot)
            # the clade column widens with the deepest slot, moving the matrix; measure the
            # bracket against the column's own inner edge, which is `gap` past the matrix.
            column_left = m + DEFAULT_GAP_PX
            want = SLOT_PX * (slot + 1.0)
            check(abs((x - column_left) - want) < 0.05,
                  f"slot {slot}: bracket sits slot.width*(slot+1) = {want:.2f}pt into the column "
                  f"(got {x - column_left:.2f})")
            check(n == 12, f"slot {slot}: time-series still 12 slots (got {n})")

        # --- the gap is separately settable, and 0 is honoured (columns flush) ---
        for gap_ratio in (0.0, 0.004):
            m, x, _, _ = render(tmp, tal_draw, f"gap-{gap_ratio}", 0, gap_ratio)
            want = gap_ratio * SIZE * RATIO + SLOT_PX
            check(abs((x - m) - want) < 0.05,
                  f"gap_ratio {gap_ratio}: matrix -> bracket is {want:.2f}pt (got {x - m:.2f})")

        # --- the two levers compose: gap 0 + slot -0.5 puts the bracket half a slot out ---
        m, x, _, _ = render(tmp, tal_draw, "gap0-slot-0.5", -0.5, 0.0)
        check(abs((x - m) - SLOT_PX * 0.5) < 0.05,
              f"gap_ratio 0 + slot -0.5: matrix -> bracket is half a slot = {SLOT_PX * 0.5:.2f}pt "
              f"(got {x - m:.2f})")

        # --- an auto-placed clade must still be kept off a fractional clade's column ---
        _, x_expl, y_auto, _ = render(tmp, tal_draw, "auto-vs-2.2", 2.2)
        check(abs(x_expl - y_auto) > SLOT_PX * 0.9,
              f"auto-placed clade keeps clear of an explicit fractional slot "
              f"(brackets {SLOT_PX * 0.9:.2f}pt apart at least, got {abs(x_expl - y_auto):.2f})")

print("FAIL: " + "; ".join(failures) if failures else "OK: clade slot + column gap geometry verified")
sys.exit(1 if failures else 0)
