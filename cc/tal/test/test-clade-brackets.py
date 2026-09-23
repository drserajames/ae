#!/usr/bin/env python3
"""Clade brackets in the Feb slide style: no arrowheads, a settable line width, two-line names.

The report trees draw each clade band as AD's double arrow — a 1.0-wide black spine between two
filled triangular heads. The info-meeting slides (Feb 2026 decks) mark clades with a plain,
thicker line and a label to its right, a two-nomenclature clade written as two lines (new name
over old), never "new (old)". Three clades-command keys cover that:

  * `"arrows": false`    -> schema clades.arrows = false: a plain line over the band's FULL extent
                            (top edge of its first row to the bottom edge of its last), no heads;
  * `"line-width": 2.5`  -> schema clades.line_width: the bracket's stroke width (default 1.0);
  * a display name holding "\\n" -> a horizontal label stacked over several lines, left-aligned
                            on one x, the block centred on the band.

What is asserted here, on tree-hz-clade-lines.json (8 synthetic leaves, invented clades P and Q):

  * the defaults are unchanged: two filled heads per band and a 1.0 spine;
  * `arrows: false` leaves no filled triangles, and each bracket is one stroke from the band's
    top edge to its bottom edge, where the default spine stops short at the two head bases;
  * `line_width` reaches the stroke, relative to the default;
  * "P-one\\nP-two" renders as two words, P-two below P-one on the same left x, the pair centred
    where the one-line label sits; with no literal backslash-n on the page (the settings reader
    decodes the JSON escape — rjson keeps strings raw);
  * the settings-v3 translator emits the two keys only when set.

Synthetic data only -- invented leaf names, dates and clade tokens.

    python3 cc/tal/test/test-clade-brackets.py

Needs `build/tal-draw` (or $TAL_DRAW) and `pdftotext`.
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

BLACK = (0.0, 0.0, 0.0)

failures: list[str] = []


def check(ok: bool, what: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {what}")
    if not ok:
        failures.append(what)


def content(pdf: Path) -> str:
    data = pdf.read_bytes()
    text = ""
    for st in re.finditer(rb"stream\r?\n", data):
        chunk = data[st.end():data.find(b"endstream", st.end())]
        try:
            text += zlib.decompress(chunk).decode("latin1")
        except zlib.error:
            text += chunk.decode("latin1")
    return text


def paths(pdf: Path) -> tuple[list, list]:
    """(strokes, fills): strokes are (colour, width, x0, y0, x1, y1) straight segments; fills are
    the point lists of filled paths. Coordinates are the tree's top-down space (tal-draw emits one
    leading "1 0 0 -1 0 H cm")."""
    strokes, fills = [], []
    # cairo closes a filled triangle with "h" and then re-issues a bare "x y m" before "f", so the
    # fill's outline is the point list as it stood at the "h".
    stroke, width, nums, pt, path, pts, closed = BLACK, 1.0, [], None, [], [], None
    for tok in content(pdf).split():
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
            pts.append(pt)
        elif tok == "l" and len(nums) >= 2 and pt is not None:
            nxt = (nums[-2], nums[-1])
            path.append((pt, nxt))
            pts.append(nxt)
            pt = nxt
        elif tok == "h":
            closed = list(pts)
        elif tok in ("S", "s"):
            strokes += [(stroke, width, a[0], a[1], b[0], b[1]) for a, b in path]
            pt, path, pts, closed = None, [], [], None
        elif tok in ("f", "F", "f*"):
            fills.append(closed if closed is not None else pts)
            pt, path, pts, closed = None, [], [], None
        elif tok in ("B", "B*", "b", "b*", "n"):
            pt, path, pts, closed = None, [], [], None
        nums = []
    return strokes, fills


def render(tal_draw: str, tmpdir: Path, name: str, clades: dict, styles: list | None = None) -> Path:
    settings = {"image_size": 800, "clades": {"show": True, "report": False, **clades},
                "time_series": {"show": True, "interval": "year"}}
    if styles:
        settings["clade_styles"] = styles
    cfg = tmpdir / f"{name}.json"
    cfg.write_text(json.dumps(settings))
    pdf = tmpdir / f"{name}.pdf"
    subprocess.run([tal_draw, f"--settings={cfg}", str(HERE / "tree-hz-clade-lines.json"), str(pdf)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return pdf


def rows(strokes) -> tuple[list[float], list[float]]:
    """Row top/bottom edges from the 8 leaf-row centres (the black horizontals: leaf tips and
    time-series dashes), as test-hz-clade-lines.py does."""
    centres = sorted({round(s[3], 3) for s in strokes if s[0] == BLACK and abs(s[3] - s[5]) < 1e-6})
    vstep = centres[1] - centres[0]
    return [c - vstep / 2.0 for c in centres], [c + vstep / 2.0 for c in centres]


def brackets(strokes, x_min: float) -> list:
    """black verticals right of x_min (the clades column sits right of the matrix)."""
    return [s for s in strokes if s[0] == BLACK and abs(s[2] - s[4]) < 1e-6 and abs(s[3] - s[5]) > 0.5 and s[2] > x_min]


def words(pdf: Path) -> list[tuple[float, float, float, float, str]]:
    bbox = subprocess.run(["pdftotext", "-bbox", str(pdf), "-"], capture_output=True, text=True, check=True).stdout
    return [(float(m[1]), float(m[2]), float(m[3]), float(m[4]), m[5])
            for m in re.finditer(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>', bbox)]


def baselines(pdf: Path) -> dict[str, float]:
    """{text: baseline y} for every text run, from its Tm and any following Td (cairo writes the
    lines of one label as one BT block, "(P-one)Tj 0 -1.15 Td (P-two)Tj"), in the tree's top-down
    space."""
    out: dict[str, float] = {}
    for bt in re.finditer(r"BT(.*?)ET", content(pdf), re.S):
        y, d, nums = 0.0, 1.0, []
        for tok in re.findall(r"\([^)]*\)|\S+", bt[1]):
            if tok == "Tm" and len(nums) >= 6:
                d, y = nums[-3], nums[-1]
            elif tok == "Td" and len(nums) >= 2:
                y += nums[-1] * d
            elif tok.startswith("("):
                out[tok[1:-1]] = y
            try:
                nums.append(float(tok))
            except ValueError:
                if not tok.startswith("("):
                    nums = []
    return out


def check_translator() -> None:
    from ae.tal.settings_v3 import translate
    on, _ = translate({"tal": [{"N": "clades", "arrows": False, "line-width": 2.5}]})
    off, _ = translate({"tal": [{"N": "clades"}]})
    check(on.get("clades", {}).get("arrows") is False, "translator: \"arrows\": false -> clades.arrows false")
    check(on.get("clades", {}).get("line_width") == 2.5, "translator: \"line-width\" -> clades.line_width")
    check("arrows" not in off.get("clades", {}) and "line_width" not in off.get("clades", {}),
          "translator: neither key emitted when absent (C++ defaults apply)")


def main() -> int:
    tal_draw = os.environ.get("TAL_DRAW", str(ROOT / "build" / "tal-draw"))
    if not os.access(tal_draw, os.X_OK):
        print(f"FAIL: {tal_draw} not built")
        return 1

    check_translator()

    with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as tmp:
        tmpdir = Path(tmp)
        default_pdf = render(tal_draw, tmpdir, "default", {})
        plain_pdf = render(tal_draw, tmpdir, "plain", {"arrows": False, "line_width": 2.5})
        two_line_pdf = render(tal_draw, tmpdir, "two-line", {"arrows": False},
                              [{"name": "P", "display_name": "P-one\nP-two", "rotation_degrees": 0}])
        default_strokes, default_fills = paths(default_pdf)
        plain_strokes, plain_fills = paths(plain_pdf)
        two_line_words = words(two_line_pdf)
        one_line_pdf = render(tal_draw, tmpdir, "one-line", {"arrows": False}, [{"name": "P", "rotation_degrees": 0}])
        one_base = baselines(one_line_pdf)
        two_base = baselines(two_line_pdf)

    top, bottom = rows(default_strokes)
    # the clades column: right of the matrix, whose right edge is its last slot separator (the
    # black verticals running the full height of the tree band); +1pt clears it
    band = max(abs(s[5] - s[3]) for s in default_strokes if s[0] == BLACK and abs(s[2] - s[4]) < 1e-6)
    x_min = max(s[2] for s in default_strokes
                if s[0] == BLACK and abs(s[2] - s[4]) < 1e-6 and abs(abs(s[5] - s[3]) - band) < 0.01) + 1.0

    # --- defaults: AD's double arrow, unchanged -------------------------------------------------
    heads = [f for f in default_fills if len(f) == 3 and min(p[0] for p in f) > x_min]
    check(len(heads) == 4, f"default: 2 filled heads per band, 2 bands -> 4 (got {len(heads)})")
    spines = brackets(default_strokes, x_min)
    check(len(spines) == 2, f"default: one spine per band (got {len(spines)})")
    check(all(min(s[3], s[5]) > y0 + 1.0 and max(s[3], s[5]) < y1 - 1.0
              for s, y0, y1 in zip(sorted(spines, key=lambda s: s[3]), (top[2], top[6]), (bottom[4], bottom[6]))),
          "default: each spine stops short of its band's ends (the heads fill the rest)")
    default_w = spines[0][1] if spines else None

    # --- arrows false: plain full-extent lines ---------------------------------------------------
    heads = [f for f in plain_fills if len(f) == 3 and min(p[0] for p in f) > x_min]
    check(not heads, f"arrows false: no filled heads (got {len(heads)})")
    plain = brackets(plain_strokes, x_min)
    check(len(plain) == 2, f"arrows false: one line per band (got {len(plain)})")
    for name, y0, y1 in (("P", top[2], bottom[4]), ("Q", top[6], bottom[6])):
        hit = [s for s in plain if abs(min(s[3], s[5]) - y0) < 0.01 and abs(max(s[3], s[5]) - y1) < 0.01]
        check(len(hit) == 1, f"arrows false: {name}'s line spans its band's full extent {y0:.1f}..{y1:.1f}")

    # --- line width ------------------------------------------------------------------------------
    check(bool(plain) and default_w is not None and all(abs(s[1] - 2.5 * default_w) < 1e-3 for s in plain),
          f"line_width 2.5: stroke is 2.5x the default width {default_w} (got {sorted({s[1] for s in plain})})")

    # --- two-line label --------------------------------------------------------------------------
    one = [w for w in two_line_words if w[4] == "P-one"]
    two = [w for w in two_line_words if w[4] == "P-two"]
    check(len(one) == 1 and len(two) == 1, "two-line: \"P-one\" and \"P-two\" drawn as separate words")
    check(not any("\\n" in w[4] or "P-one\nP-two" in w[4] for w in two_line_words), "two-line: no literal newline text")
    if len(one) == 1 and len(two) == 1:
        (ox0, oy0, _, oy1, _), (tx0, ty0, _, ty1, _) = one[0], two[0]
        check(ty0 > oy1 - 0.5, f"two-line: P-two sits below P-one ({ty0:.1f} vs {oy1:.1f})")
        check(abs(ox0 - tx0) < 0.05, f"two-line: both lines share the left x ({ox0:.2f} vs {tx0:.2f})")
    # centred as a block: the two baselines straddle where the single-line label's baseline sits
    if {"P-one", "P-two"} <= two_base.keys() and "P" in one_base:
        mid = (two_base["P-one"] + two_base["P-two"]) / 2.0
        check(abs(mid - one_base["P"]) < 0.01,
              f"two-line: block centred where the one-line label sits (baselines' mid {mid:.2f}, one-line {one_base['P']:.2f})")
    else:
        check(False, "two-line: baselines found for P-one, P-two and the one-line P")

    print()
    if failures:
        print(f"FAILED ({len(failures)}):")
        for f in failures:
            print(f"  {f}")
        return 1
    print("OK: clade brackets — arrows off, line width, two-line labels")
    return 0


if __name__ == "__main__":
    sys.exit(main())
