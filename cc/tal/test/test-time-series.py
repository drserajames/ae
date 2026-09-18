#!/usr/bin/env python3
"""Verification for ae.tal.compute_time_series (TAL subsystem #3, Phase A).

Reuses the dated phylo-tree-v3 tree (leaf dates A=2020-01-15, B=2020-02-20,
C=2020-03-10, D=2021-01-05, E=2021-02-12) and checks year/month bucketing, plus the
half-open [start, end) range: an explicit `end` is excluded exactly ONCE (matching
acmacs-base time_series::make), while an auto end still includes the latest leaf's bucket.

    python3 cc/tal/test/test-time-series.py

Loads the freshly built ae_backend.so by path via importlib, to bypass any
editable-install copy of ae_backend that may shadow it.
"""

import importlib.util
import os
import sys

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

    if failures:
        print("FAIL")
        for f in failures:
            print("  " + f)
        sys.exit(1)
    print(f"OK: time series verified (year: {year_slots}; month: {len(ts_month.slots)} slots, 5 leaves placed; "
          "explicit end exclusive once across month/year/day/week)")


if __name__ == "__main__":
    main()
