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

print("FAIL: " + "; ".join(failures) if failures else "OK: page geometry matches AD's formula")
sys.exit(1 if failures else 0)
