#!/usr/bin/env python3
"""Verification for ae.tal.compute_time_series (TAL subsystem #3, Phase A).

Reuses the dated phylo-tree-v3 tree (leaf dates A=2020-01-15, B=2020-02-20,
C=2020-03-10, D=2021-01-05, E=2021-02-12) and checks year/month bucketing, plus the
half-open [start, end) range: an explicit `end` is excluded exactly ONCE (matching
acmacs-base time_series::make), while an auto end still includes the latest leaf's bucket.

Then renders the matrix with tal-draw (tree-hz-clade-lines.json: 8 synthetic leaves dated
2020-01 .. 2021-10) for the two `time-series` drawing keys:

  * "dates": false / {"top": .., "bottom": ..} -> schema time_series.dates_top/dates_bottom: a
    hidden band draws nothing visible, the matrix grows into its reserve, and the Mon/YY words
    stay in the PDF text layer (1/255-opaque fill) at the SAME x as when drawn, inside the matrix
    edge — slides/build.py locates the year columns from those words;
  * "year-separator": N -> schema time_series.year_separator: the separator where a slot's year
    differs from the previous slot's is N wide, the rest stay 0.5; the default leaves every
    separator (and so the report trees) unchanged.

    python3 cc/tal/test/test-time-series.py

Needs `build/tal-draw` (or $TAL_DRAW) and `pdftotext` for the rendering half.

Loads the freshly built ae_backend.so by path via importlib, to bypass any
editable-install copy of ae_backend that may shadow it.
"""

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
# Discover the built module by glob so the test is portable (…-darwin.so on macOS,
# …-linux-gnu.so on Linux); it is loaded by path to bypass any editable-install shadow.
import glob as _glob
_built = _glob.glob(os.path.join(ROOT, "build", "ae_backend*.so"))
SO = _built[0] if _built else os.path.join(ROOT, "build", "ae_backend.cpython-310-darwin.so")


def load_ae_backend():
    spec = importlib.util.spec_from_file_location("ae_backend", SO)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ----------------------------------------------------------------------
# rendering: "dates" and "year-separator" on the time-series command
# ----------------------------------------------------------------------

MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def _content(pdf):
    data = open(pdf, "rb").read()
    text = ""
    for st in re.finditer(rb"stream\r?\n", data):
        chunk = data[st.end():data.find(b"endstream", st.end())]
        try:
            text += zlib.decompress(chunk).decode("latin1")
        except zlib.error:
            text += chunk.decode("latin1")
    return text


def _vertical_strokes(pdf):
    """(width, x, y0, y1) of every straight vertical stroked segment, in tal-draw's top-down space."""
    out, width, nums, pt, segs = [], 1.0, [], None, []
    for tok in _content(pdf).split():
        try:
            nums.append(float(tok))
            del nums[:-8]
            continue
        except ValueError:
            pass
        if tok == "w" and nums:
            width = round(nums[-1], 4)
        elif tok == "m" and len(nums) >= 2:
            pt = (nums[-2], nums[-1])
        elif tok == "l" and len(nums) >= 2 and pt is not None:
            nxt = (nums[-2], nums[-1])
            segs.append((pt, nxt))
            pt = nxt
        elif tok in ("S", "s"):
            out += [(width, a[0], min(a[1], b[1]), max(a[1], b[1])) for a, b in segs if abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) > 0.5]
            pt, segs = None, []
        elif tok in ("f", "F", "f*", "B", "B*", "b", "b*", "n"):
            pt, segs = None, []
        nums = []
    return out


def _separators(pdf):
    """the matrix's slot separators: the verticals sharing the commonest (y0, y1) span, sorted by x."""
    vs = _vertical_strokes(pdf)
    spans = {}
    for s in vs:
        spans.setdefault((round(s[2], 3), round(s[3], 3)), []).append(s)
    return sorted(max(spans.values(), key=len), key=lambda s: s[1])


def _words(pdf):
    bbox = subprocess.run(["pdftotext", "-bbox", str(pdf), "-"], capture_output=True, text=True, check=True).stdout
    return [(float(m[1]), float(m[2]), float(m[3]), float(m[4]), m[5])
            for m in re.finditer(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>', bbox)]


def _date_words(pdf):
    return sorted((w for w in _words(pdf) if w[4] in MONTHS or (w[4].isdigit() and len(w[4]) == 2)), key=lambda w: (w[0], w[1]))


def _fill_alphas(pdf):
    """the /ca (fill alpha) values of the page's ExtGStates."""
    return sorted({float(v) for v in re.findall(r"/ca\s+([\d.]+)", _content(pdf) + open(pdf, "rb").read().decode("latin1"))})


def check_rendering(failures):
    tal_draw = os.environ.get("TAL_DRAW", os.path.join(ROOT, "build", "tal-draw"))
    if not os.access(tal_draw, os.X_OK):
        failures.append(f"{tal_draw} not built")
        return

    # translator: the keys reach the schema only when set
    sys.path.insert(0, os.path.join(ROOT, "py"))
    from ae.tal.settings_v3 import translate
    ts = lambda cmd: translate({"tal": [{"N": "time-series", **cmd}]})[0].get("time_series", {})
    if {k for k in ts({}) if k.startswith("dates") or k == "year_separator"}:
        failures.append(f"translator: dates/year_separator emitted when absent: {ts({})}")
    if (ts({"dates": False}).get("dates_top"), ts({"dates": False}).get("dates_bottom")) != (False, False):
        failures.append(f"translator: dates false -> {ts({'dates': False})}")
    one = ts({"dates": {"top": False}})
    if one.get("dates_top") is not False or "dates_bottom" in one:
        failures.append(f"translator: dates {{top: false}} -> {one}")
    if ts({"year-separator": 2}).get("year_separator") != 2.0:
        failures.append(f"translator: year-separator 2 -> {ts({'year-separator': 2})}")

    fixture = os.path.join(HERE, "tree-hz-clade-lines.json")
    with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as tmp:
        def render(name, extra):
            cfg = os.path.join(tmp, f"{name}.json")
            with open(cfg, "w") as f:
                json.dump({"image_size": 800, "time_series": {"show": True, "interval": "month",
                                                              "label_rotation": "clockwise",
                                                              # the report's small labels, so both bands fit on the page
                                                              "slot_width": 0.01, "label_scale": 0.7, **extra}}, f)
            pdf = os.path.join(tmp, f"{name}.pdf")
            subprocess.run([tal_draw, f"--settings={cfg}", fixture, pdf], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return pdf

        default = render("default", {})
        explicit = render("explicit", {"dates_top": True, "dates_bottom": True, "year_separator": 0.5})
        heavy = render("heavy", {"year_separator": 2.0})
        hidden = render("hidden", {"dates_top": False, "dates_bottom": False})
        top_off = render("top-off", {"dates_top": False})

        # explicit defaults == absent keys (content streams; the header carries a timestamp)
        if _content(default).split("CreationDate")[0] != _content(explicit).split("CreationDate")[0]:
            failures.append("explicit default keys change the drawing")

        d_sep = _separators(default)
        n_slots = 22                                                # 2020-01 .. 2021-10
        if len(d_sep) != n_slots + 1 or len({s[0] for s in d_sep}) != 1:
            failures.append(f"default: {n_slots + 1} separators of one width (got {len(d_sep)}, widths {sorted({s[0] for s in d_sep})})")
        base_w = d_sep[0][0]
        h_sep = _separators(heavy)
        heavy_at = [i for i, s in enumerate(h_sep) if abs(s[0] - 4.0 * base_w) < 1e-3]
        if heavy_at != [12]:                                        # left edge of Jan 2021, the 13th slot
            failures.append(f"year-separator 2.0: 4x-wide separator only at slot 12 (got {heavy_at}, "
                            f"widths {[s[0] for s in h_sep]})")
        if any(abs(s[0] - base_w) > 1e-6 for i, s in enumerate(h_sep) if i != 12):
            failures.append("year-separator 2.0: the other separators stay 0.5")
        if [round(s[1], 3) for s in h_sep] != [round(s[1], 3) for s in d_sep]:
            failures.append("year-separator 2.0: separators moved")

        top, bottom = d_sep[0][2], d_sep[0][3]
        d_words = _date_words(default)
        if len(d_words) != 4 * n_slots:
            failures.append(f"default: two Mon/YY pairs per slot (got {len(d_words)} date words)")
        if any(top - 0.5 < (w[1] + w[3]) / 2 < bottom + 0.5 for w in d_words):
            failures.append("default: date words lie outside the matrix")
        if any(a < 0.1 for a in _fill_alphas(default)):
            failures.append("default: nothing is drawn near-transparent")

        # dates false: matrix grows into both reserves, words kept (same x), inside the matrix, invisible
        x_sep = _separators(hidden)
        htop, hbottom = x_sep[0][2], x_sep[0][3]
        if not (htop < top - 5.0 and hbottom > bottom + 5.0):
            failures.append(f"dates false: the matrix grows into both bands ({top:.1f}..{bottom:.1f} -> {htop:.1f}..{hbottom:.1f})")
        h_words = _date_words(hidden)
        if [(w[4], round(w[0], 2)) for w in h_words] != [(w[4], round(w[0], 2)) for w in d_words] and \
                sorted((w[4], round(w[0], 2)) for w in h_words) != sorted((w[4], round(w[0], 2)) for w in d_words):
            failures.append(f"dates false: the same date words at the same x ({len(h_words)} vs {len(d_words)})")
        if not all(htop < (w[1] + w[3]) / 2 < hbottom for w in h_words):
            failures.append("dates false: hidden words sit inside the matrix")
        if not any(a < 0.01 for a in _fill_alphas(hidden)):
            failures.append(f"dates false: no near-transparent fill (alphas {_fill_alphas(hidden)})")

        # top off only: bottom band as drawn by default, top hidden and freed
        t_sep = _separators(top_off)
        if not (t_sep[0][2] < top - 5.0 and abs(t_sep[0][3] - bottom) < 1e-3):
            failures.append(f"dates top:false: only the top band freed ({t_sep[0][2]:.1f}..{t_sep[0][3]:.1f})")
        t_words = _date_words(top_off)
        below = [w for w in t_words if (w[1] + w[3]) / 2 > t_sep[0][3]]
        inside = [w for w in t_words if t_sep[0][2] < (w[1] + w[3]) / 2 < t_sep[0][3]]
        if len(below) != 2 * n_slots or len(inside) != 2 * n_slots:
            failures.append(f"dates top:false: {2 * n_slots} words below, {2 * n_slots} hidden inside (got {len(below)}, {len(inside)})")
        d_below = sorted((w[4], round(w[0], 2), round(w[1], 2)) for w in d_words if (w[1] + w[3]) / 2 > bottom)
        # the drawn bottom band keeps its words' positions relative to the matrix bottom
        if sorted((w[4], round(w[0], 2), round(w[1], 2)) for w in below) != d_below:
            failures.append("dates top:false: the bottom band is drawn exactly as by default")
    return len(d_words), base_w


def main():
    ae_backend = load_ae_backend()
    tree = ae_backend.tree.load(os.path.join(HERE, "tree-clades.json"))
    failures = []

    # --- yearly: 2020 (A,B,C=3), 2021 (D,E=2) ---
    ts_year = ae_backend.tal.compute_time_series(tree, "year")
    year_slots = [(s.first, s.after_last, s.count) for s in ts_year.slots]
    if year_slots != [("2020-01-01", "2021-01-01", 3), ("2021-01-01", "2022-01-01", 2)]:
        failures.append(f"year slots: {year_slots}")
    if (ts_year.dated_leaves, ts_year.undated_leaves) != (5, 0):
        failures.append(f"year dated/undated: {ts_year.dated_leaves}/{ts_year.undated_leaves}")

    # --- monthly: 2020-01 .. 2021-02 = 14 slots; counts at Jan/Feb/Mar 2020 and Jan/Feb 2021 ---
    ts_month = ae_backend.tal.compute_time_series(tree, "month")
    month_counts = {s.first: s.count for s in ts_month.slots}
    if len(ts_month.slots) != 14:
        failures.append(f"month slot count: {len(ts_month.slots)} (want 14)")
    expected_nonzero = {"2020-01-01": 1, "2020-02-01": 1, "2020-03-01": 1, "2021-01-01": 1, "2021-02-01": 1}
    for first, cnt in expected_nonzero.items():
        if month_counts.get(first) != cnt:
            failures.append(f"month {first}: got {month_counts.get(first)}, want {cnt}")
    if sum(s.count for s in ts_month.slots) != 5:
        failures.append(f"month total assigned: {sum(s.count for s in ts_month.slots)} (want 5)")
    # An AUTO end must stay INCLUSIVE of the bucket holding the latest leaf (2021-02-12), so the
    # last month drawn is Feb 2021 — not Jan. This is the case the exclusive-end rule must not eat.
    if ts_month.slots[-1].first != "2021-02-01":
        failures.append(f"auto end, last month: {ts_month.slots[-1].first} (want 2021-02-01)")

    # ------------------------------------------------------------------
    # explicit `end` is EXCLUSIVE, and excluded exactly ONCE
    # (acmacs-base time_series::make: a slot is emitted iff its START < after_last).
    # Applying it twice — stepping `end` back a day AND stopping the loop early — dropped the
    # final slot of every explicit range, at every interval.
    # ------------------------------------------------------------------
    def slots(interval, start, end):
        return [(s.first, s.after_last) for s in ae_backend.tal.compute_time_series(tree, interval, start, end).slots]

    # months of [start, end): 2020-01 .. 2020-12 inclusive = 12 slots, NOT 11.
    m = slots("month", "2020-01", "2021-01")
    if len(m) != 12 or m[0][0] != "2020-01-01" or m[-1][0] != "2020-12-01":
        failures.append(f"month 2020-01..2021-01: {len(m)} slots, {m[0][0] if m else None}..{m[-1][0] if m else None} "
                        "(want 12, 2020-01-01..2020-12-01)")
    # the same range a year the tree knows nothing about: the slots are still drawn (empty), and
    # every dated leaf falls outside. Guards the page-width path, which sizes the column off this.
    ts_empty = ae_backend.tal.compute_time_series(tree, "month", "2024-01", "2025-01")
    if len(ts_empty.slots) != 12:
        failures.append(f"month 2024-01..2025-01: {len(ts_empty.slots)} slots (want 12)")
    if ts_empty.outside_range != 5 or sum(s.count for s in ts_empty.slots) != 0:
        failures.append(f"month 2024-01..2025-01: outside_range {ts_empty.outside_range} (want 5), "
                        f"placed {sum(s.count for s in ts_empty.slots)} (want 0)")

    # a DAY-of-month end is exclusive on the slot START, not on the month index: a slot beginning
    # 2020-03-01 precedes 2020-03-15, so March is drawn. (The old month-index comparison dropped it.)
    m = slots("month", "2020-01", "2020-03-15")
    if [f for f, _ in m] != ["2020-01-01", "2020-02-01", "2020-03-01"]:
        failures.append(f"month 2020-01..2020-03-15: {[f for f, _ in m]} (want Jan, Feb, Mar 2020)")

    # year: 2020 only — 2021-01-01 is not < 2021-01-01.
    y = slots("year", "2020-01", "2021-01")
    if y != [("2020-01-01", "2021-01-01")]:
        failures.append(f"year 2020-01..2021-01: {y} (want the single 2020 slot)")

    # day: [15, 18) = 15th, 16th, 17th — three slots, not two.
    d = slots("day", "2020-01-15", "2020-01-18")
    if [f for f, _ in d] != ["2020-01-15", "2020-01-16", "2020-01-17"]:
        failures.append(f"day 2020-01-15..2020-01-18: {[f for f, _ in d]} (want the 15th, 16th, 17th)")

    # week: slots are 7 days from the Monday on/before `start`; one is emitted while its Monday
    # precedes `end`. 2020-01-15 is a Wednesday -> first Monday 2020-01-13.
    w = slots("week", "2020-01-15", "2020-01-27")
    if [f for f, _ in w] != ["2020-01-13", "2020-01-20"]:
        failures.append(f"week 2020-01-15..2020-01-27: {[f for f, _ in w]} (want Mondays 13th, 20th)")

    # ------------------------------------------------------------------
    # AD's own oracle. These five (parameters -> expected series) cases are transcribed from
    # acmacs-base cc/test-time-series.cc, where AD's author wrote the expected slots out by
    # hand — so they pin ae to AD's semantics without needing AD built. Synthetic dates only.
    # (Its two weekly cases are deliberately NOT included: AD's detail::first() leaves a week
    # range's start un-snapped, while ae aligns to the Monday on/before `start` — a pre-existing,
    # documented ae choice. Same slot COUNT, offset by up to 6 days. Not touched here.)
    # ------------------------------------------------------------------
    ad_yearly = [("2016-01-01", "2017-01-01"), ("2017-01-01", "2018-01-01"), ("2018-01-01", "2019-01-01")]
    ad_monthly1 = [("2018-11-01", "2018-12-01"), ("2018-12-01", "2019-01-01"), ("2019-01-01", "2019-02-01"),
                   ("2019-02-01", "2019-03-01"), ("2019-03-01", "2019-04-01")]
    for interval, start, end, want in (
        ("year", "2016-01-01", "2019-01-01", ad_yearly),   # exact bounds
        ("year", "2016-01-10", "2018-01-10", ad_yearly),   # mid-month bounds snap to whole years
        ("year", "2016-02-01", "2018-02-10", ad_yearly),
        ("month", "2018-11-10", "2019-04-01", ad_monthly1),
        ("month", "2018-11-10", "2019-03-02", ad_monthly1),  # end mid-March still draws March
    ):
        got = slots(interval, start, end)
        if got != want:
            failures.append(f"AD oracle {interval} {start}..{end}: got {got}, want {want}")

    rendered = check_rendering(failures)

    if failures:
        print("FAIL")
        for f in failures:
            print("  " + f)
        sys.exit(1)
    print(f"OK: time series verified (year: {year_slots}; month: {len(ts_month.slots)} slots, 5 leaves placed; "
          "explicit end exclusive once across month/year/day/week; "
          "dates hidden-but-extractable, matrix grows into the freed bands, year-separator width)")


if __name__ == "__main__":
    main()
