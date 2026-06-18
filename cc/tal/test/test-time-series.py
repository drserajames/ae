#!/usr/bin/env python3
"""Verification for ae.tal.compute_time_series (TAL subsystem #3, Phase A).

Reuses the dated phylo-tree-v3 tree (leaf dates A=2020-01-15, B=2020-02-20,
C=2020-03-10, D=2021-01-05, E=2021-02-12) and checks year/month bucketing.

    /Library/Frameworks/Python.framework/Versions/3.10/bin/python3 cc/tal/test/test-time-series.py

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

    if failures:
        print("FAIL")
        for f in failures:
            print("  " + f)
        sys.exit(1)
    print(f"OK: time series verified (year: {year_slots}; month: {len(ts_month.slots)} slots, 5 leaves placed)")


if __name__ == "__main__":
    main()
