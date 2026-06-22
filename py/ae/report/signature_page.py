"""Signature-page driver for a seasonal-report working dir.

The ae analog of AD's ``ssm_report/signature_page.py`` ``signature_page_make()``:
for each per-lab chart dir it pairs the styled chart with that subtype's tree +
``.tal`` settings and calls :func:`ae.tal.signature_page.make_section_signature_page`,
writing ``sp/pdfs/<prefix>.<tree_infix>.sp.pdf`` (the same name AD used).

In AD the renderer was the single ``sigp``/``tal`` command and this file just drove
it per lab-subtype. ae has no single-canvas renderer, so the engine
(``ae.tal.signature_page``) composites the ``tal-draw`` tree and the kateri
per-section maps at the PDF level — but the driver's job is identical: discover
``(tree, tal, chart)`` triples and loop.

Conventions (from a real ``ac/results/ssm/<date>-ssm`` dir):
  * per-lab chart:  ``<prefix>/styled.ace``        (prefix e.g. ``h1-cdc``, ``h3-hint-cdc``)
  * tree:           ``tree/<subtype>.<tree_infix>.tjz``
  * tal settings:   ``tree/<subtype>.<tal_infix>.tal``
  * output:         ``sp/pdfs/<prefix>.<tree_infix>.sp.pdf``

Run (under the arm64 Python that imports ae_backend, with the kateri app on PATH):

    PYTHONPATH=.../ae-tree/build python3 -m ae.report.signature_page <report_dir>
    PYTHONPATH=.../ae-tree/build python3 -m ae.report.signature_page <report_dir> --prefix h1-cdc --prefix bvic-crick
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from ae.tal.signature_page import make_section_signature_page, SignaturePageError

# subtype token (prefix.split("-")[0]) -> tree basename + display title
SUBTYPE = {
    "h1": ("h1", "A(H1N1)"),
    "h3": ("h3", "A(H3N2)"),
    "bvic": ("bvic", "B/Victoria"),
    "byam": ("byam", "B/Yamagata"),
}

# assay token(s) (the prefix segments between subtype and lab) -> display label
ASSAY = {
    "": "HI",
    "hint": "HINT",
    "neut": "Neut",
    "fra": "FRA",
    "hi": "HI",
    "hi-guinea-pig": "HI",
    "hi-guinea-pig-big": "HI",
    "hi-turkey": "HI",
}


def parse_prefix(prefix: str) -> tuple[str, str, str]:
    """``"h3-hint-cdc"`` -> (subtype="h3", assay_token="hint", lab="cdc")."""
    parts = prefix.split("-")
    return parts[0], "-".join(parts[1:-1]), parts[-1]


def title_for(prefix: str) -> str:
    subtype, assay, lab = parse_prefix(prefix)
    subtype_title = SUBTYPE.get(subtype, (subtype, subtype.upper()))[1]
    assay_title = ASSAY.get(assay, assay.upper().replace("-", " ") if assay else "HI")
    return f"{subtype_title} {assay_title} {lab.upper()}"


def discover_prefixes(report_dir) -> list[str]:
    """Per-lab chart dirs (``<prefix>/styled.ace``) whose subtype has a tree."""
    report_dir = Path(report_dir)
    out = []
    for child in sorted(report_dir.iterdir()):
        if child.is_dir() and (child / "styled.ace").exists():
            subtype = parse_prefix(child.name)[0]
            if subtype in SUBTYPE:
                out.append(child.name)
    return out


# Default ae output dir — deliberately NOT sp/pdfs (that holds the AD `sigp`
# reference PDFs of the same name; writing there would overwrite them). Point
# --output-subdir at sp/pdfs explicitly only when intentionally replacing them.
DEFAULT_OUTPUT_SUBDIR = "sp/pdfs-ae"


def make_one(report_dir, prefix: str, *, tree_infix: str = "asr.after-2021", tal_infix: str = "after-2021",
             chart_name: str = "styled.ace", output_subdir: str = DEFAULT_OUTPUT_SUBDIR, title: Optional[str] = None,
             map_width: float = 800.0, defines: Optional[dict] = None) -> Path:
    """Build one signature page for `prefix`, returning the output PDF path."""
    report_dir = Path(report_dir)
    subtype = SUBTYPE[parse_prefix(prefix)[0]][0]
    tree = report_dir / "tree" / f"{subtype}.{tree_infix}.tjz"
    tal = report_dir / "tree" / f"{subtype}.{tal_infix}.tal"
    chart = report_dir / prefix / chart_name
    for needed in (tree, tal, chart):
        if not needed.exists():
            raise SignaturePageError(f"{prefix}: missing {needed}")
    out_dir = report_dir / output_subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / f"{prefix}.{tree_infix}.sp.pdf"
    return make_section_signature_page(tree, chart, tal, output, page_title=title or title_for(prefix),
                                       map_width=map_width, defines=defines)


def make_all(report_dir, prefixes: Optional[list[str]] = None, **kwargs) -> dict[str, object]:
    """Build signature pages for `prefixes` (default: all discovered). Returns
    ``{prefix: output_path_or_exception}`` and never aborts the whole run on one
    failure (mirrors AD building each lab independently)."""
    report_dir = Path(report_dir)
    prefixes = prefixes or discover_prefixes(report_dir)
    results: dict[str, object] = {}
    for prefix in prefixes:
        try:
            out = make_one(report_dir, prefix, **kwargs)
            print(f"[sigp] {prefix} -> {out}", file=sys.stderr)
            results[prefix] = out
        except Exception as err:  # keep going; record the failure
            print(f"[sigp] {prefix} FAILED: {err}", file=sys.stderr)
            results[prefix] = err
    return results


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Generate signature pages for a seasonal-report working dir")
    parser.add_argument("report_dir", help="report working dir (e.g. ac/results/ssm/2026-0223-ssm)")
    parser.add_argument("--prefix", action="append", dest="prefixes", metavar="PREFIX",
                        help="per-lab chart dir to render (repeatable; default: all discovered)")
    parser.add_argument("--tree-infix", default="asr.after-2021", help="tree basename infix (default asr.after-2021)")
    parser.add_argument("--tal-infix", default="after-2021", help=".tal basename infix (default after-2021)")
    parser.add_argument("--output-subdir", default=DEFAULT_OUTPUT_SUBDIR,
                        help=f"output dir under report_dir (default {DEFAULT_OUTPUT_SUBDIR}; "
                             "NOT sp/pdfs, which holds the AD reference PDFs)")
    parser.add_argument("--map-width", type=float, default=800.0)
    parser.add_argument("--list", action="store_true", help="just list discovered prefixes and exit")
    args = parser.parse_args(argv)

    if args.list:
        for prefix in discover_prefixes(args.report_dir):
            print(f"{prefix}\t{title_for(prefix)}")
        return 0

    results = make_all(args.report_dir, prefixes=args.prefixes, tree_infix=args.tree_infix,
                       tal_infix=args.tal_infix, output_subdir=args.output_subdir, map_width=args.map_width)
    failures = [p for p, r in results.items() if isinstance(r, Exception)]
    ok = len(results) - len(failures)
    print(f"\n{ok}/{len(results)} signature pages written"
          + (f"; failed: {', '.join(failures)}" if failures else ""), file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
