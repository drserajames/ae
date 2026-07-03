#! /usr/bin/env python3
"""Plot per-serum column basis versus chain step for an incremental chain.

Self-contained port of AD's ``whocc-column-bases-plot-for-chain``.  The AD tool
read a pre-computed JSON (produced by a separate step) of per-serum
column-basis-per-table and drew it with acmacs_draw_backend/PdfCairo.  This
version instead reads the chain output directory directly: it walks the ordered
steps, reads each step's merge chart, and extracts every serum's column basis
via ``chart.column_bases("none")`` keyed by ``serum.designation()``.

For each step it plots the column basis (y, = log2 of the max titre of the
serum) against the table-step index (x).  One line per serum, plus an
"All sera" overview page.  As in AD, a serum's line is broken across any gap
in the steps in which it is present.

Usage:
    whocc-column-bases-plot-for-chain.py CHAIN_DIR -o output.pdf

CHAIN_DIR is an incremental-chain output directory such as
    .../chains/f-20221130-none/
containing numbered step files (000.<date>.ace, 001.<dates>.merge.ace, ...).
"""

import argparse
import re
import sys
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


STEP_PREFIX_RE = re.compile(r"^(\d+)\.")
BARE_TABLE_RE = re.compile(r"^\d+\.[0-9-]+\.ace$")


def chain_step_files(chain_dir):
    """Return the ordered list of (step_index, chart_path) for a chain dir.

    Per step index we use the incremental ``.merge.ace`` (the accumulated merged
    table for that step) when present, otherwise the bare first-table ``.ace``
    (step 000).  Grid/incremental/scratch/mcb charts are ignored.
    """
    steps = {}
    for path in sorted(chain_dir.glob("*.ace")):
        name = path.name
        m = STEP_PREFIX_RE.match(name)
        if not m:
            continue
        idx = int(m.group(1))
        if name.endswith(".merge.ace"):
            steps[idx] = path                       # preferred: accumulated merge
        elif idx not in steps and BARE_TABLE_RE.match(name):
            steps[idx] = path                       # bare source table (step 000)
    return [(i, steps[i]) for i in sorted(steps)]


def collect(chain_dir, chart_v3):
    """serum designation -> {step_index: column_basis}, plus number of steps."""
    steps = chain_step_files(chain_dir)
    if not steps:
        sys.exit(f"error: no chain step .ace files found in {chain_dir}")
    per_serum = {}
    for idx, path in steps:
        chart = chart_v3.Chart(str(path))
        cbs = chart.column_bases("none")
        for sr_no in range(chart.number_of_sera()):
            key = chart.serum(sr_no).designation()
            per_serum.setdefault(key, {})[idx] = cbs[sr_no]
    return per_serum, [i for i, _ in steps]


def broken_segments(step_to_cb):
    """Yield contiguous (xs, ys) runs, breaking where step indices are not adjacent."""
    xs, ys = [], []
    prev = None
    for step in sorted(step_to_cb):
        if prev is not None and step != prev + 1 and xs:
            yield xs, ys
            xs, ys = [], []
        xs.append(step)
        ys.append(step_to_cb[step])
        prev = step
    if xs:
        yield xs, ys


def draw_serum(ax, step_to_cb, steps, ymax, color="0.35", lw=1.0, title=None):
    for xs, ys in broken_segments(step_to_cb):
        ax.plot(xs, ys, color=color, lw=lw)
    ax.set_xlim(-0.5, (steps[-1] if steps else 1) + 0.5)
    ax.set_ylim(0, ymax)
    ax.set_yticks(range(0, ymax + 1))
    ax.grid(True, axis="y", color="0.9", lw=0.5)
    if title is not None:
        ax.set_title(title, fontsize=7)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("chain_dir", type=Path, help="incremental chain output directory")
    parser.add_argument("-o", "--output", required=True, help="output PDF/PNG path")
    parser.add_argument("--per-page", type=int, default=12,
                        help="per-serum panels per page (default 12 = 3x4)")
    args = parser.parse_args()

    plt = setup_matplotlib()
    from matplotlib.backends.backend_pdf import PdfPages
    chart_v3 = import_chart_v3()

    per_serum, steps = collect(args.chain_dir, chart_v3)
    import math
    all_cb = [v for d in per_serum.values() for v in d.values()]
    ymax = math.ceil(max(all_cb)) + 1 if all_cb else 1
    subtitle = f"{args.chain_dir.name}  —  {len(steps)} tables, {len(per_serum)} sera"

    out = Path(args.output)
    if out.suffix.lower() == ".pdf":
        with PdfPages(str(out)) as pdf:
            # Page 1: all sera overlaid.
            fig, ax = plt.subplots(figsize=(11, 6))
            for d in per_serum.values():
                draw_serum(ax, d, steps, ymax, color="0.4", lw=0.5)
            ax.set_title("All sera\n" + subtitle, fontsize=10)
            ax.set_xlabel(f"table step (0..{steps[-1]})")
            ax.set_ylabel("column basis  (log2 max titre)")
            pdf.savefig(fig); plt.close(fig)
            # Following pages: per-serum small multiples.
            names = sorted(per_serum)
            cols, per = 3, args.per_page
            rows = (per + cols - 1) // cols
            for start in range(0, len(names), per):
                chunk = names[start:start + per]
                fig, axes = plt.subplots(rows, cols, figsize=(11, 8.5), squeeze=False)
                for ax in axes.flat:
                    ax.axis("off")
                for k, name in enumerate(chunk):
                    ax = axes.flat[k]; ax.axis("on")
                    draw_serum(ax, per_serum[name], steps, ymax, title=name)
                fig.suptitle(subtitle, fontsize=9)
                fig.tight_layout(rect=(0, 0, 1, 0.97))
                pdf.savefig(fig); plt.close(fig)
    else:
        # Single-image output: just the all-sera overview.
        fig, ax = plt.subplots(figsize=(11, 6))
        for d in per_serum.values():
            draw_serum(ax, d, steps, ymax, color="0.4", lw=0.5)
        ax.set_title("All sera\n" + subtitle, fontsize=10)
        ax.set_xlabel(f"table step (0..{steps[-1]})")
        ax.set_ylabel("column basis  (log2 max titre)")
        fig.savefig(str(out), dpi=120, bbox_inches="tight"); plt.close(fig)

    print(f"wrote {out}  ({len(steps)} steps, {len(per_serum)} sera)")


if __name__ == "__main__":
    main()
