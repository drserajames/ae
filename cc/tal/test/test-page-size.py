#!/usr/bin/env python3
"""Page geometry parity with acmacs-tal (AD).

AD sizes a tree page as exactly ``height * width_to_height_ratio``:

    acmacs-tal cc/draw.cc:33  width_to_height_ratio_ =
        (layout().width_relative_to_height() + margins().left + margins().right)
        / (1.0 + margins().top + margins().bottom);
    acmacs-tal cc/draw.cc:43  PdfCairo{filename, height_ * width_to_height_ratio_, height_, …}

Two things have to hold for ae to draw the same page:

1. ``settings_v3`` must compute the same ratio from the `.tal` — and keep enough
   precision that the rounded value still lands on AD's page width (the ratio
   multiplies a 1000pt canvas, so 4 decimals costs up to 0.05pt).
2. ``tal-draw`` must draw a page of exactly ``image_size * ratio``. It briefly added a
   5%-of-page left band for the auto-placed aa-transition labels ON TOP of that, which
   made every ae tree page exactly 5% wider than AD's; the band now comes out of the
   drawable width instead.

Synthetic data only — an invented `.tal` program and the existing synthetic test tree.

    python3 cc/tal/test/test-page-size.py

Needs `build/tal-draw` (or $TAL_DRAW) for part 2; part 1 is pure Python.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "py"))

from ae.tal import settings_v3  # noqa: E402
from ae.tal.settings_v3 import _time_series_slots  # noqa: E402

failures: list[str] = []


def check(ok: bool, what: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {what}")
    if not ok:
        failures.append(what)


# ----------------------------------------------------------------------
# 1. settings_v3 reproduces AD's Draw::set_width_to_height_ratio
# ----------------------------------------------------------------------

# margins: left/right named, top/bottom left at acmacs-tal's 0.025 defaults.
# elements: tree .40 + gap .03 + time-series 12 monthly slots * .01 + clades .06 = .61
# ratio = (.61 + .01 + .01) / (1 + .025 + .025) = .63 / 1.05 = .60 exactly
TAL_EXACT = {
    "tal": [
        {"N": "canvas", "height": 1000},
        {"N": "margins", "left": 0.01, "right": 0.01},
        {"N": "tree", "width-to-height-ratio": 0.40},
        {"N": "gap", "width-to-height-ratio": 0.03},
        {"N": "time-series", "start": "2024-01", "end": "2025-01", "slot": {"width": 0.01}},
        {"N": "clades", "width-to-height-ratio": 0.06},
    ]
}

schema, _ = settings_v3.translate(TAL_EXACT)
check(schema.get("width_to_height_ratio") == 0.6,
      f"tree/gap/time-series/clades sum -> ratio 0.6 (got {schema.get('width_to_height_ratio')})")

# A ratio that does not terminate: (0.41 + 0.025 + 0.0) / 1.05 = 0.4142857142…
# 6 decimals keeps the 1000pt page within 0.001pt of AD; 4 decimals (0.4143) is 0.014pt out.
TAL_REPEATING = {"tal": [{"N": "tree", "width-to-height-ratio": 0.41}]}
schema_r, _ = settings_v3.translate(TAL_REPEATING)
ratio_r = schema_r.get("width_to_height_ratio")
check(ratio_r == 0.414286, f"default margins, repeating ratio kept to 6 dp (got {ratio_r})")
check(abs(ratio_r * 1000.0 - (0.41 + 0.025) / 1.05 * 1000.0) < 0.001,
      "6-dp ratio lands within 0.001pt of AD's page width on a 1000pt canvas")

# ----------------------------------------------------------------------
# 2. tal-draw draws image_size * ratio — no band added to the page
# ----------------------------------------------------------------------

def media_box(pdf: Path) -> tuple[float, float]:
    """Page size in points. cairo puts /MediaBox in a compressed object stream."""
    data = pdf.read_bytes()
    m = re.search(rb"/MediaBox\s*\[\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)", data)
    if m is None:
        for st in re.finditer(rb"stream\r?\n", data):
            chunk = data[st.end():data.find(b"endstream", st.end())]
            try:
                dec = zlib.decompress(chunk)
            except zlib.error:
                continue
            m = re.search(rb"/MediaBox\s*\[\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)", dec)
            if m:
                break
    if m is None:
        raise AssertionError(f"no /MediaBox in {pdf}")
    x0, y0, x1, y1 = (float(v) for v in m.groups())
    return x1 - x0, y1 - y0


def count_time_series_slots(pdf: Path) -> int:
    """Slots tal-draw actually DREW, from the matrix's vertical separators.

    The separators are the only group of >=3 vertical segments sharing one exact height (they
    span the whole tree band); clade brackets and the tree itself are taller/shorter one-offs.
    n slots = n separators - 1.
    """
    from collections import Counter
    segs = []
    for st in re.finditer(rb"stream\r?\n", pdf.read_bytes()):
        chunk = pdf.read_bytes()[st.end():pdf.read_bytes().find(b"endstream", st.end())]
        try:
            text = zlib.decompress(chunk).decode("latin1")
        except zlib.error:
            continue
        num = r"(-?\d+\.?\d*)"
        for x0, y0, x1, y1 in re.findall(rf"{num} {num} m\s+{num} {num} l", text, re.S):
            x0, y0, x1, y1 = float(x0), float(y0), float(x1), float(y1)
            if abs(x1 - x0) < 0.05 and abs(y1 - y0) > 0.5:
                segs.append((x0, round(abs(y1 - y0), 1)))
    heights = Counter(h for _, h in segs)
    candidates = [h for h, n in heights.items() if n >= 3]
    if not candidates:
        raise AssertionError(f"no separator group in {pdf}")
    sep_h = max(candidates, key=lambda h: heights[h])
    return len({x for x, h in segs if h == sep_h}) - 1


tal_draw = os.environ.get("TAL_DRAW") or str(ROOT / "build" / "tal-draw")
if not os.access(tal_draw, os.X_OK):
    print(f"  SKIP tal-draw page size — {tal_draw} not built")
else:
    RATIO, SIZE = 0.6, 1000
    base = {
        "_": "synthetic page-geometry fixture — see cc/tal/test/test-page-size.py",
        "image_size": SIZE,
        "width_to_height_ratio": RATIO,
        "labels": True,
        "clades": {"show": True},
        "time_series": {"show": True, "interval": "year"},
    }
    # The band is only reserved when there are auto-placed aa-transition labels, so the
    # regression needs a tree drawn BOTH ways: the page must be the same either way.
    with_labels = dict(base)
    with_labels["mrca_labels"] = [{"first": "A", "last": "C", "text": "T1K", "node_id": "3.5"}]
    with_labels["mrca_labels_auto_place"] = True

    with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as tmp:
        tmp = Path(tmp)
        for tag, settings in (("no aa labels", base), ("auto-placed aa labels", with_labels)):
            sfile = tmp / f"{tag.replace(' ', '-')}.json"
            sfile.write_text(json.dumps(settings))
            pdf = tmp / f"{tag.replace(' ', '-')}.pdf"
            subprocess.run([tal_draw, f"--settings={sfile}", str(HERE / "tree-clades.json"), str(pdf)],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            w, h = media_box(pdf)
            check(abs(w - SIZE * RATIO) < 0.01 and abs(h - SIZE) < 0.01,
                  f"page is image_size*ratio with {tag} "
                  f"(expected {SIZE * RATIO:.1f}x{SIZE}, got {w:.1f}x{h:.1f})")

        # ----------------------------------------------------------------------
        # 3. tal-draw must DRAW the same number of slots settings_v3 sized the page for
        # ----------------------------------------------------------------------
        # The two live in different languages — `_time_series_slots()` in settings_v3.py sizes
        # the column, `compute_time_series()` in C++ fills it — and they drifted: the Python
        # counted AD's 12 months of [2024-01, 2025-01) while the C++ applied the exclusive `end`
        # a second time and drew 11, so every report tree lost its most recent month while the
        # page stayed the right width. Pin them to each other.
        want_slots = _time_series_slots({"start": "2024-01", "end": "2025-01"}, [])
        check(want_slots == 12, f"settings_v3 sizes [2024-01, 2025-01) at 12 monthly slots (got {want_slots})")
        drawn = dict(base)
        drawn["time_series"] = {"show": True, "interval": "month", "start": "2024-01", "end": "2025-01",
                                "slot_width": 0.01}
        sfile = tmp / "drawn-slots.json"
        sfile.write_text(json.dumps(drawn))
        pdf = tmp / "drawn-slots.pdf"
        subprocess.run([tal_draw, f"--settings={sfile}", str(HERE / "tree-clades.json"), str(pdf)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        got_slots = count_time_series_slots(pdf)
        check(got_slots == want_slots,
              f"tal-draw draws the slot count settings_v3 sized for "
              f"(sized {want_slots}, drew {got_slots})")

# ----------------------------------------------------------------------
# 4. `"side": "left"` dash bars: own column between the page margin and the tree root
# ----------------------------------------------------------------------
# Synthetic tree-aa.json (leaves L1-L6, position 3 = T or A). Two bars: a pos-3 dash-bar-aa-at
# (always on the right) and a black select-bar for 3A (L4, L5), drawn right (default) and left.

def stroked_segments(pdf: Path) -> list[tuple[tuple[float, float, float], float, float, float, float]]:
    """Every `x0 y0 m x1 y1 l` stroke in the page content, with the stroke colour in force."""
    out = []
    data = pdf.read_bytes()
    num = r"(-?\d+\.?\d*)"
    for st in re.finditer(rb"stream\r?\n", data):
        try:
            text = zlib.decompress(data[st.end():data.find(b"endstream", st.end())]).decode("latin1")
        except zlib.error:
            continue
        color = (0.0, 0.0, 0.0)
        for m in re.finditer(rf"{num} {num} {num} RG|{num} {num} m\s+{num} {num} l", text):
            if m.group(1) is not None:
                color = (float(m.group(1)), float(m.group(2)), float(m.group(3)))
            else:
                out.append((color, *(float(m.group(i)) for i in range(4, 8))))
    return out


if os.access(tal_draw, os.X_OK):
    SIZE, RATIO = 400, 0.8
    sel_bar = {"selects": [{"aa": ["3A"], "color": "black"}]}
    variants = {
        "default": {"dash_bars": [{"pos": 3}, sel_bar]},
        "right": {"dash_bars": [{"pos": 3, "side": "right"}, {**sel_bar, "side": "right"}]},
        "left": {"dash_bars": [{"pos": 3}, {**sel_bar, "side": "left"}]},
    }
    segs, sizes = {}, {}
    with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as tmp:
        tmp = Path(tmp)
        for tag, extra in variants.items():
            settings = {"_": "synthetic left-dash-bar fixture — see cc/tal/test/test-page-size.py",
                        "image_size": SIZE, "width_to_height_ratio": RATIO, "labels": False, **extra}
            sfile, pdf = tmp / f"side-{tag}.json", tmp / f"side-{tag}.pdf"
            sfile.write_text(json.dumps(settings))
            subprocess.run([tal_draw, f"--settings={sfile}", str(HERE / "tree-aa.json"), str(pdf)],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            segs[tag], sizes[tag] = stroked_segments(pdf), media_box(pdf)
    BLACK = (0.0, 0.0, 0.0)

    def horizontal(tag):
        return [sg for sg in segs[tag] if abs(sg[2] - sg[4]) < 1e-6 and sg[3] != sg[1]]

    def tree_edges(tag):   # the tree is drawn first: black horizontals up to the first coloured stroke
        out = []
        for sg in segs[tag]:
            if sg[0] != BLACK:
                break
            out.append(sg)
        return out

    def black_dashes(tag):  # the select bar's marks: black horizontals after the tree
        n_tree = len(tree_edges(tag))
        return sorted((min(sg[1], sg[3]), max(sg[1], sg[3]), sg[2]) for sg in segs[tag][n_tree:]
                      if sg[0] == BLACK and abs(sg[2] - sg[4]) < 1e-6)

    check(segs["right"] == segs["default"], '"side": "right" draws exactly what no side key draws')
    check(sizes["left"] == sizes["default"], f"left bar keeps the page size ({sizes['left']} vs {sizes['default']})")
    root_default = min(min(sg[1], sg[3]) for sg in tree_edges("default"))
    root_left = min(min(sg[1], sg[3]) for sg in tree_edges("left"))
    right_default = max(max(sg[1], sg[3]) for sg in tree_edges("default"))
    right_left = max(max(sg[1], sg[3]) for sg in tree_edges("left"))
    dl, dr = black_dashes("left"), black_dashes("default")
    check(len(dl) == 2 and len(dr) == 2, f"select bar draws the two 3A leaves both ways (left {len(dl)}, right {len(dr)})")
    margin = 0.03 * SIZE * RATIO
    check(all(margin <= x0 and x1 < root_left for x0, x1, _ in dl),
          f"left bar sits between the margin ({margin:.2f}) and the tree root ({root_left:.2f}): {dl}")
    check(all(x0 > right_default for x0, _, _ in dr), "default bar is right of the tree")
    check([y for _, _, y in dl] == [y for _, _, y in dr], "left bar marks the same rows (y) as the right-hand one")
    check(root_left > root_default, f"tree root moves right to make room ({root_default:.2f} -> {root_left:.2f})")
    w_default, w_left = right_default - root_default, right_left - root_left
    gap = 0.012 * SIZE * RATIO
    check(abs(w_default - w_left - gap) < 0.01,
          f"tree loses only the left column's gap, not the bar (width {w_default:.2f} -> {w_left:.2f}, gap {gap:.2f})")
    pos3_left = [sg for sg in horizontal("left") if sg[0] != BLACK]
    pos3_default = [sg for sg in horizontal("default") if sg[0] != BLACK]
    # the right band is one column narrower and still ends at the same place, so the pos-3 bar
    # (now the only right bar) moves right by exactly one column pitch, rows unchanged
    col = 0.022 * (SIZE * RATIO * (1.0 - 0.06))
    check(len(pos3_left) == len(pos3_default) == 6
          and all(abs(a[1] - b[1] - col) < 0.01 and abs(a[3] - b[3] - col) < 0.01 and a[2] == b[2]
                  for a, b in zip(pos3_left, pos3_default)),
          f"the right-hand pos-3 bar shifts one column ({col:.2f}) right into the freed slot, rows unchanged")

print("FAIL: " + "; ".join(failures) if failures else "OK: page geometry matches AD's formula")
sys.exit(1 if failures else 0)
