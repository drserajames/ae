#! /usr/bin/env python3
"""Histogram of titre values for one or more charts.

Self-contained port of AD's ``whocc-titer-histograms`` driver, which shelled out
to the C++ ``whocc-histogram-of-titers``.  That C++ tool accumulates a
``map<Titer, size_t>`` over every antigen x serum cell of the given charts and
draws one orange bar per *distinct titre string*, bar height = count, x-labels =
the titre strings in titre order.  This version reproduces that directly from
``ae_backend.chart_v3`` (no C++ / cairo).

Two binning modes:

  * ``categorical`` — exact reproduction: one bar per distinct titre string
    (ideal for discrete HI tables: 10, 20, 40, ... plus <10, >1280).
  * ``log2`` — one bar per doubling-dilution bucket on a log2 axis, labelled
    10, 20, 40, ...; ``<`` / ``>`` / ``*`` grouped into their own bars.  Useful
    when titres are continuous (e.g. HINT / neutralisation charts) and the
    distinct-string histogram would be hundreds of one-count bars.

  * ``auto`` (default) — categorical when the number of distinct regular titre
    strings is small (<= --auto-threshold), else log2.

Usage:
    whocc-titer-histograms.py CHART.ace [CHART.ace ...] -o output.pdf [--mode auto|categorical|log2]

Missing (``*``) cells are counted and shown as their own bar (as the AD C++ tool
does); pass --drop-missing to omit them.
"""

import argparse
import math
import sys
from collections import Counter
from pathlib import Path

import os
import tempfile


def setup_matplotlib():
    """Import matplotlib (Agg backend, writable config dir); return pyplot."""
    os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), "mpl-cache"))
    try:
        import matplotlib
    except ImportError:
        sys.exit("error: matplotlib is not importable. Install it into the build "
                 "python (see proj/whocc-chains-diagnostics/README.md).")
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def import_chart_v3():
    """Import ae_backend.chart_v3 (source ae-env.sh first)."""
    try:
        import ae_backend.chart_v3 as chart_v3
    except ImportError:
        sys.exit("error: cannot import ae_backend.chart_v3 — source ae-env.sh first.")
    return chart_v3


ORANGE = "#f4a338"


def parse_label(s):
    """Classify a titre string -> (group, sort_numeric).

    group in {'lt','reg','gt','dc'}; sort_numeric is log2(value/10) with a small
    nudge so <N sorts just below N and >N just above.
    """
    if s in ("*", ".", ""):
        return "dc", math.inf
    if s.startswith("<"):
        try:
            return "lt", math.log2(float(s[1:]) / 10.0) - 0.25
        except ValueError:
            return "lt", -math.inf
    if s.startswith(">"):
        try:
            return "gt", math.log2(float(s[1:]) / 10.0) + 0.25
        except ValueError:
            return "gt", math.inf
    body = s[1:] if s[:1] == "~" else s
    try:
        return "reg", math.log2(float(body) / 10.0)
    except ValueError:
        return "reg", 0.0


def accumulate(charts, chart_v3, drop_missing):
    counts = Counter()
    for path in charts:
        chart = chart_v3.Chart(str(path))
        titers = chart.titers()
        nag, nsr = chart.number_of_antigens(), chart.number_of_sera()
        for ag in range(nag):
            for sr in range(nsr):
                s = str(titers.titer(ag, sr))
                if drop_missing and parse_label(s)[0] == "dc":
                    continue
                counts[s] += 1
    return counts


def plot_categorical(plt, counts, title, output):
    labels = sorted(counts, key=lambda s: (0 if parse_label(s)[0] != "dc" else 1, parse_label(s)[1]))
    values = [counts[l] for l in labels]
    fig_w = max(8.0, min(40.0, 0.22 * len(labels) + 3))
    fig, ax = plt.subplots(figsize=(fig_w, fig_w / 1.6))
    ax.bar(range(len(labels)), values, color=ORANGE, edgecolor="black", linewidth=0.3)
    ax.set_xticks(range(len(labels)))
    fs = 7 if len(labels) <= 60 else max(3, int(7 * 60 / len(labels)))
    ax.set_xticklabels(labels, rotation=90, fontsize=fs)
    ax.set_ylabel("count")
    ax.set_title(title)
    ax.margins(x=0.005)
    fig.tight_layout()
    fig.savefig(str(output), dpi=120, bbox_inches="tight")
    plt.close(fig)


def plot_log2(plt, counts, title, output):
    reg = Counter()          # integer log2 bucket -> count
    lt = gt = dc = 0
    for s, n in counts.items():
        grp, num = parse_label(s)
        if grp == "reg":
            reg[int(round(num))] += n
        elif grp == "lt":
            lt += n
        elif grp == "gt":
            gt += n
        else:
            dc += n
    positions, heights, labels = [], [], []
    if reg:
        lo, hi = min(reg), max(reg)
        for k in range(lo, hi + 1):
            positions.append(k); heights.append(reg.get(k, 0))
            labels.append(str(10 * (2 ** k)) if k >= 0 else f"{10 * (2.0 ** k):g}")
    base = min(positions) if positions else 0
    top = max(positions) if positions else 0
    if lt:
        positions.insert(0, base - 1.5); heights.insert(0, lt); labels.insert(0, "<")
    if gt:
        positions.append(top + 1.5); heights.append(gt); labels.append(">")
    if dc:
        positions.append((top if not gt else top + 1.5) + 1.5); heights.append(dc); labels.append("*")
    fig, ax = plt.subplots(figsize=(11, 6.5))
    ax.bar(positions, heights, width=0.9, color=ORANGE, edgecolor="black", linewidth=0.3)
    ax.set_xticks(positions)
    ax.set_xticklabels(labels, rotation=90, fontsize=8)
    ax.set_ylabel("count")
    ax.set_xlabel("titre (log2 dilution buckets)")
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(str(output), dpi=120, bbox_inches="tight")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("charts", type=Path, nargs="+", help="one or more chart .ace files")
    parser.add_argument("-o", "--output", required=True, help="output PDF/PNG path")
    parser.add_argument("--mode", choices=["auto", "categorical", "log2"], default="auto")
    parser.add_argument("--auto-threshold", type=int, default=25,
                        help="max distinct regular titres for auto->categorical (default 25)")
    parser.add_argument("--drop-missing", action="store_true", help="omit '*' (missing) cells")
    args = parser.parse_args()

    plt = setup_matplotlib()
    chart_v3 = import_chart_v3()

    counts = accumulate(args.charts, chart_v3, args.drop_missing)
    if not counts:
        sys.exit("error: no titres found")

    n_regular = sum(1 for s in counts if parse_label(s)[0] == "reg")
    mode = args.mode
    if mode == "auto":
        mode = "categorical" if n_regular <= args.auto_threshold else "log2"

    total = sum(counts.values())
    name = args.charts[0].name if len(args.charts) == 1 else f"{len(args.charts)} charts"
    title = f"Titre histogram — {name}  ({total} cells, {len(counts)} distinct, mode={mode})"

    if mode == "categorical":
        plot_categorical(plt, counts, title, args.output)
    else:
        plot_log2(plt, counts, title, args.output)

    print(f"wrote {args.output}  ({total} cells, {len(counts)} distinct titres, mode={mode})")


if __name__ == "__main__":
    main()
