#!/usr/bin/env python3
# Tests for Chart.set_titers_from_layers — in-place re-gating of merged titers
# from the preserved layers. See cc/py/chart-v3.cc and cc/py/sd-gate.hh.
#
# This is an integration test that needs a merged multi-layer chart and a directory of
# source tables to merge. Those charts are NOT part of this repo; point the test at your
# own with two env vars (the test skips if they are unset):
#   AE_TEST_MERGE_CHART   a merged chart with many layers (.ace)
#   AE_TEST_TABLE_DIR     a directory of source .ace tables that can be merged together
#
# Run (from the ae worktree root; adjust <data-dir> to your reference-data path):
#   PYTHONPATH="$PWD/build-py314:$PWD/py" \
#   SEQDB_V4=<data-dir> ACMACS_DATA=<data-dir> \
#   AE_TEST_MERGE_CHART=<merged.ace> AE_TEST_TABLE_DIR=<tables-dir> \
#   arch -arm64 /opt/homebrew/bin/python3.14 test/test-set-titers-from-layers.py

import glob
import math
import os
import sys

import ae_backend

CV3 = ae_backend.chart_v3

MERGE_CHART = os.environ.get("AE_TEST_MERGE_CHART")
TBL_DIR = os.environ.get("AE_TEST_TABLE_DIR")

NAN = float("nan")

_failures = []


def check(cond, msg):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {msg}")
    if not cond:
        _failures.append(msg)


def main_titers(chart):
    """Tuple of str(titer) for every antigen×serum cell of the *main* (merged) titer table."""
    t = chart.titers()
    n_ag, n_sr = chart.number_of_antigens(), chart.number_of_sera()
    return tuple(str(t.titer(a, s)) for a in range(n_ag) for s in range(n_sr))


def count_non_dontcare(titers_tuple):
    return sum(1 for x in titers_tuple if x != "*")


def fresh_merge(paths, sd_limit, sd_denominator):
    """Independently merge the given source tables into a multi-layer chart (the merge path
    computes the main titers via the same set_from_layers the new method exposes)."""
    charts = [CV3.Chart(p) for p in paths]
    merged = charts[0]
    for c in charts[1:]:
        merged, _ = CV3.merge(merged, c, sd_limit=sd_limit, sd_denominator=sd_denominator)
    return merged


# ----------------------------------------------------------------------

def pick_source_tables(n=3):
    tables = sorted(glob.glob(os.path.join(TBL_DIR, "*.ace")))
    if len(tables) < n:
        raise SystemExit(f"need >= {n} source .ace tables in AE_TEST_TABLE_DIR, found {len(tables)}")
    return tables[:n]


# ----------------------------------------------------------------------
# Test 1: round-trip equivalence (the key test).
#   merge(T, sd_limit=X, denom) == merge(T, 1.0, denom) then set_titers_from_layers(X, denom)
# for X in {1.0, 1.5, NaN} and denom in {population, sample}.
# ----------------------------------------------------------------------

def test_round_trip_equivalence(paths):
    print("Test 1: round-trip equivalence (fresh merge vs merge@1.0 + in-place re-gate)")
    for denom in ("population", "sample"):
        for X in (1.0, 1.5, NAN):
            ref = fresh_merge(paths, sd_limit=X, sd_denominator=denom)
            base = fresh_merge(paths, sd_limit=1.0, sd_denominator=denom)
            base.set_titers_from_layers(sd_limit=X, sd_denominator=denom)
            xlab = "nan" if math.isnan(X) else X
            check(main_titers(ref) == main_titers(base),
                  f"denom={denom:10s} X={xlab!s:4}: in-place re-gate == fresh merge")


# ----------------------------------------------------------------------
# Test 2: shared-helper default matrix — merge and set_titers_from_layers resolve the
# context-dependent (sd_limit, sd_denominator) defaults identically.
#   sd_limit supplied, denominator omitted  -> sample (n-1)
#   neither supplied                        -> 1.0, population
# ----------------------------------------------------------------------

def test_default_matrix(paths):
    print("Test 2: shared-helper default matrix (merge vs set_titers_from_layers)")

    # sd_limit given, denominator omitted -> sample on BOTH paths.
    ref_sample = fresh_merge(paths, sd_limit=1.5, sd_denominator="sample")
    merge_default = fresh_merge(paths, sd_limit=1.5, sd_denominator=None)
    check(main_titers(merge_default) == main_titers(ref_sample),
          "merge(sd_limit=1.5, denom=None) resolves to sample")
    set_default = fresh_merge(paths, sd_limit=1.0, sd_denominator="sample")
    set_default.set_titers_from_layers(sd_limit=1.5)  # denom omitted -> sample
    check(main_titers(set_default) == main_titers(ref_sample),
          "set_titers_from_layers(sd_limit=1.5, denom=None) resolves to sample")

    # neither supplied -> 1.0, population (AD parity) on BOTH paths.
    ref_pop_1 = fresh_merge(paths, sd_limit=1.0, sd_denominator="population")
    merge_handsoff = fresh_merge(paths, sd_limit=None, sd_denominator=None)
    check(main_titers(merge_handsoff) == main_titers(ref_pop_1),
          "merge(no args) resolves to 1.0/population (AD parity)")
    set_handsoff = fresh_merge(paths, sd_limit=1.0, sd_denominator="population")
    set_handsoff.set_titers_from_layers()  # no args -> 1.0, population
    check(main_titers(set_handsoff) == main_titers(ref_pop_1),
          "set_titers_from_layers(no args) resolves to 1.0/population (AD parity)")


# ----------------------------------------------------------------------
# Test 3: forced column bases after in-place re-gate == those from the equivalent fresh merge.
# ----------------------------------------------------------------------

def test_forced_column_bases(paths):
    print("Test 3: forced column bases (in-place re-gate vs fresh merge)")
    for denom in ("population", "sample"):
        for X in (1.0, 1.5, NAN):
            ref = fresh_merge(paths, sd_limit=X, sd_denominator=denom)
            base = fresh_merge(paths, sd_limit=1.0, sd_denominator=denom)
            base.set_titers_from_layers(sd_limit=X, sd_denominator=denom)
            xlab = "nan" if math.isnan(X) else X
            check(list(ref.forced_column_bases()) == list(base.forced_column_bases()),
                  f"denom={denom:10s} X={xlab!s:4}: forced column bases match")
    fcb = list(fresh_merge(paths, sd_limit=1.0, sd_denominator="population").forced_column_bases())
    print(f"    (note: forced column bases {'non-empty (>-in-layers path exercised)' if fcb else 'empty for this table set'})")


def build_injected_tables(paths):
    """Two source tables with >-thresholded titers injected on a shared serum, so the merged
    chart's layers contain more-than titers and set_from_layers takes its has_morethan branch
    (which computes and stores forced column bases)."""
    t1, t2 = CV3.Chart(paths[0]), CV3.Chart(paths[1])
    for a in range(3):
        t1.titers().set_titer(a, 0, ">5120")
        t2.titers().set_titer(a, 0, ">5120")
    return t1, t2


# ----------------------------------------------------------------------
# Test 3b: same, but with >-thresholded titers present in the layers so the has_morethan
# branch actually runs and forced column bases are non-empty (source tables may have none).
# ----------------------------------------------------------------------

def test_forced_column_bases_with_morethan(paths):
    print("Test 3b: forced column bases with >-titers in layers (has_morethan branch)")
    for denom in ("population", "sample"):
        for X in (1.0, 1.5, NAN):
            t1, t2 = build_injected_tables(paths)
            ref, _ = CV3.merge(t1, t2, sd_limit=X, sd_denominator=denom)
            base, _ = CV3.merge(t1, t2, sd_limit=1.0, sd_denominator=denom)
            base.set_titers_from_layers(sd_limit=X, sd_denominator=denom)
            ref_fcb, base_fcb = list(ref.forced_column_bases()), list(base.forced_column_bases())
            xlab = "nan" if math.isnan(X) else X
            check(len(ref_fcb) > 0, f"denom={denom:10s} X={xlab!s:4}: forced CB non-empty (>-path exercised)")
            check(ref_fcb == base_fcb, f"denom={denom:10s} X={xlab!s:4}: in-place forced CB == fresh-merge forced CB")
            check(main_titers(ref) == main_titers(base), f"denom={denom:10s} X={xlab!s:4}: main titers match with >-path active")


# ----------------------------------------------------------------------
# Test 4: monotonicity on the real 196-layer merged chart.
# Higher sd_limit keeps >= as many non-* cells; NaN (gate off) keeps the most.
# ----------------------------------------------------------------------

def test_monotonicity(merged_path):
    print("Test 4: monotonicity of non-* count vs sd_limit (real merged chart)")
    for denom in ("population", "sample"):
        chart = CV3.Chart(merged_path)
        counts = []
        for X in (0.5, 1.0, 1.5, 2.0, NAN):
            chart.set_titers_from_layers(sd_limit=X, sd_denominator=denom)
            counts.append(count_non_dontcare(main_titers(chart)))
        finite = counts[:-1]  # 0.5, 1.0, 1.5, 2.0
        nan_count = counts[-1]
        non_decreasing = all(finite[i] <= finite[i + 1] for i in range(len(finite) - 1))
        check(non_decreasing, f"denom={denom:10s}: non-* count non-decreasing in sd_limit  {finite}")
        check(nan_count >= max(counts), f"denom={denom:10s}: NaN (gate off) keeps the most non-* cells ({nan_count})")


# ----------------------------------------------------------------------
# Test 5: idempotence — two successive re-gates give the same result.
# ----------------------------------------------------------------------

def test_idempotence(merged_path):
    print("Test 5: idempotence of repeated re-gate")
    for denom in ("population", "sample"):
        for X in (1.0, NAN):
            chart = CV3.Chart(merged_path)
            chart.set_titers_from_layers(sd_limit=X, sd_denominator=denom)
            first = main_titers(chart)
            first_fcb = list(chart.forced_column_bases())
            chart.set_titers_from_layers(sd_limit=X, sd_denominator=denom)
            second = main_titers(chart)
            second_fcb = list(chart.forced_column_bases())
            xlab = "nan" if math.isnan(X) else X
            check(first == second and first_fcb == second_fcb,
                  f"denom={denom:10s} X={xlab!s:4}: second re-gate identical to first")


# ----------------------------------------------------------------------
# Test 6: fewer than 2 layers raises a clear error.
# ----------------------------------------------------------------------

def test_too_few_layers(paths):
    print("Test 6: chart with < 2 layers raises")
    single = CV3.Chart(paths[0])  # a raw source table has no layers
    check(single.titers().number_of_layers() < 2, f"raw table has < 2 layers ({single.titers().number_of_layers()})")
    raised = False
    try:
        single.set_titers_from_layers(sd_limit=1.0)
    except Exception as e:  # noqa: BLE001
        raised = True
        print(f"    raised: {type(e).__name__}: {e}")
    check(raised, "set_titers_from_layers on < 2 layers raises")


# ----------------------------------------------------------------------

def main():
    if not TBL_DIR or not MERGE_CHART or not os.path.isdir(TBL_DIR) or not os.path.exists(MERGE_CHART):
        print("SKIP: set AE_TEST_MERGE_CHART (a merged multi-layer chart) and "
              "AE_TEST_TABLE_DIR (a dir of source .ace tables) to run this test")
        return
    paths = pick_source_tables(3)
    print(f"source tables: {[os.path.basename(p) for p in paths]}")
    probe = fresh_merge(paths, sd_limit=1.0, sd_denominator="population")
    print(f"fresh-merge probe: AG={probe.number_of_antigens()} SR={probe.number_of_sera()} "
          f"layers={probe.titers().number_of_layers()}")
    if probe.titers().number_of_layers() < 2:
        raise SystemExit("fresh merge did not accumulate >= 2 layers; adjust source-table selection")

    big = CV3.Chart(MERGE_CHART)
    print(f"merged chart:      AG={big.number_of_antigens()} SR={big.number_of_sera()} "
          f"layers={big.titers().number_of_layers()}")
    print()

    test_round_trip_equivalence(paths)
    test_default_matrix(paths)
    test_forced_column_bases(paths)
    test_forced_column_bases_with_morethan(paths)
    test_monotonicity(MERGE_CHART)
    test_idempotence(MERGE_CHART)
    test_too_few_layers(paths)

    print()
    if _failures:
        print(f"RESULT: {len(_failures)} FAILURE(S)")
        for f in _failures:
            print(f"  - {f}")
        sys.exit(1)
    print("RESULT: ALL PASS")


if __name__ == "__main__":
    main()
