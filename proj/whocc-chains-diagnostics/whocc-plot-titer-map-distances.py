#! /usr/bin/env python3
"""Per-serum plot of logged titre versus map distance for a chart with a projection.

Self-contained port of AD's ``whocc-plot-titer-map-distances`` (an R script that
consumed ``chart-export --names --logged-titers --map-distances --column-bases``).
This version computes everything from the chart via ``ae_backend.chart_v3``: for
each serum it scatters logged titre (y) against map distance (x) over the serum's
antigens, and overlays

  * a linear regression line (black),
  * a LOWESS local-regression curve (blue),
  * the red reference line y = column_basis - distance.

The y-axis is labelled in titres (10, 20, 40, ... 10240 for log 0..10).  Only
regular titres are used (``<`` / ``>`` / ``*`` are skipped, matching AD's
x>=0, y>=0 filter).  Sera are laid out in a grid (6 columns by default).

Usage:
    whocc-plot-titer-map-distances.py CHART.ace -o output.pdf [--projection N] [--no-jitter]

CHART.ace must contain at least one projection (e.g. a chain's
``*.incremental.ace`` / ``*.scratch.ace`` step).
"""

import argparse
import math
import sys
from pathlib import Path

import os
import tempfile

import numpy as np


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


def lowess(x, y, frac=0.6, n_out=100):
    """Simple tricube-weighted local linear regression (LOWESS).

    Returns (xs, ys) evaluated on a sorted grid across the x range.  numpy-only
    (scipy/statsmodels are not available in the build python).
    """
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    order = np.argsort(x)
    x, y = x[order], y[order]
    n = len(x)
    if n < 2:
        return x, y
    r = max(2, int(math.ceil(frac * n)))
    xs = np.linspace(x.min(), x.max(), n_out)
    ys = np.empty_like(xs)
    for i, x0 in enumerate(xs):
        dist = np.abs(x - x0)
        h = np.sort(dist)[min(r - 1, n - 1)]
        if h <= 0:
            h = dist.max() or 1.0
        w = np.clip(dist / h, 0.0, 1.0)
        w = (1.0 - w ** 3) ** 3
        sw = w.sum()
        if sw <= 0:
            ys[i] = y.mean()
            continue
        mx = np.sum(w * x) / sw
        my = np.sum(w * y) / sw
        sxx = np.sum(w * (x - mx) ** 2)
        b = np.sum(w * (x - mx) * (y - my)) / sxx if sxx > 0 else 0.0
        ys[i] = my + b * (xs[i] - mx)
    return xs, ys


def serum_points(chart, titers, layout, nag, sr_no):
    """Return (map_distances, logged_titers) over regular titres for one serum."""
    try:
        sx, sy = layout[nag + sr_no][0], layout[nag + sr_no][1]
    except Exception:
        return np.array([]), np.array([])
    if sx is None or (isinstance(sx, float) and math.isnan(sx)):
        return np.array([]), np.array([])
    xs, ys = [], []
    for ag_no in range(nag):
        t = titers.titer(ag_no, sr_no)
        if not t.is_regular():
            continue
        try:
            ax, ay = layout[ag_no][0], layout[ag_no][1]
        except Exception:
            continue
        if ax is None or (isinstance(ax, float) and math.isnan(ax)):
            continue
        dist = math.hypot(ax - sx, ay - sy)
        logged = t.logged()
        if dist >= 0 and logged >= 0:
            xs.append(dist)
            ys.append(logged)
    return np.asarray(xs), np.asarray(ys)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("chart", type=Path, help="chart .ace with a projection")
    parser.add_argument("-o", "--output", required=True, help="output PDF/PNG path")
    parser.add_argument("--projection", type=int, default=0, help="projection index (default 0)")
    parser.add_argument("--columns", type=int, default=6, help="grid columns (default 6)")
    parser.add_argument("--no-jitter", action="store_true", help="disable small y jitter")
    parser.add_argument("--seed", type=int, default=1, help="jitter RNG seed")
    args = parser.parse_args()

    plt = setup_matplotlib()
    chart_v3 = import_chart_v3()

    chart = chart_v3.Chart(str(args.chart))
    if chart.number_of_projections() <= args.projection:
        sys.exit(f"error: chart has no projection {args.projection}")
    proj = chart.projection(args.projection)
    layout = proj.layout()
    titers = chart.titers()
    nag, nsr = chart.number_of_antigens(), chart.number_of_sera()
    col_bases = chart.column_bases(proj.minimum_column_basis())

    rng = np.random.default_rng(args.seed)
    cols = args.columns
    rows = (nsr + cols - 1) // cols

    # global axis ranges (as in AD: xlim 0..ceil(max dist), ylim 0..ceil(max logged))
    all_x, all_y = [], []
    per = []
    for sr_no in range(nsr):
        xs, ys = serum_points(chart, titers, layout, nag, sr_no)
        per.append((xs, ys))
        all_x.extend(xs.tolist()); all_y.extend(ys.tolist())
    max_x = math.ceil(max(all_x)) if all_x else 1
    max_y = max(10, math.ceil(max(all_y)) if all_y else 10)

    fig_w = 3.3 * cols
    fig_h = 3.0 * rows
    fig, axes = plt.subplots(rows, cols, figsize=(fig_w, fig_h), squeeze=False)
    for ax in axes.flat:
        ax.axis("off")

    yticks = list(range(0, max_y + 1))
    ylabels = [str(10 * (2 ** k)) for k in yticks]

    for sr_no in range(nsr):
        ax = axes.flat[sr_no]; ax.axis("on")
        xs, ys = per[sr_no]
        name = chart.serum(sr_no).designation()
        ax.set_xlim(0, max_x); ax.set_ylim(0, max_y)
        ax.set_yticks(yticks); ax.set_yticklabels(ylabels, fontsize=6)
        ax.tick_params(axis="x", labelsize=6)
        ax.set_title(f"{sr_no}  {name}", fontsize=6)
        if len(xs) > 1:
            plot_y = ys + (rng.normal(0, 0.05, size=len(ys)) if not args.no_jitter else 0.0)
            ax.scatter(xs, plot_y, s=6, facecolors="none", edgecolors="0.3", linewidths=0.4)
            # linear regression
            b1, b0 = np.polyfit(xs, ys, 1)
            xr = np.array([0, max_x])
            ax.plot(xr, b0 + b1 * xr, color="black", lw=0.8)
            # lowess
            lx, ly = lowess(xs, ys, frac=0.6)
            ax.plot(lx, ly, color="blue", lw=0.9)
            # red reference y = column_basis - distance
            cb = col_bases[sr_no]
            ax.plot([0, cb], [cb, 0], color="red", lw=0.8)
            ax.legend([f"regr {round((2 ** b0) * 10)}, {round(b1, 2)}", "loess"],
                      loc="upper right", fontsize=5, frameon=False)
        else:
            ax.text(0.5, 0.5, "insufficient data", ha="center", va="center",
                    fontsize=6, transform=ax.transAxes)

    fig.suptitle(f"{args.chart.name}  —  logged titre vs map distance (projection {args.projection})",
                 fontsize=10)
    fig.supxlabel("map distance", fontsize=9)
    fig.supylabel("titre", fontsize=9)
    fig.tight_layout(rect=(0.01, 0.01, 1, 0.98))
    fig.savefig(str(args.output), dpi=110, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {args.output}  ({nsr} sera)")


if __name__ == "__main__":
    main()
