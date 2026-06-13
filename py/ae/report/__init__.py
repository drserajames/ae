"""
ae.report — seasonal/SSM WHO CC report generation.

Ported from AD ``ssm-report`` (~/AC/eu/AD/sources/ssm-report). This package
contains the *report-assembly* core: it takes a ``report.json`` settings file
plus a directory of pre-generated figure PDFs (antigenic maps, phylogenetic
trees, geographic time series, signature pages) and assembles them into a single
LaTeX document that is compiled with ``pdflatex`` into the final report PDF.

The figure *generation* side of AD ssm-report (map.py, maker.py, commands.py,
stat.py, geographic.py, signature_page.py) is not yet ported. The figures it
would produce now come from different places in ae: antigenic-map PDFs from
**kateri** (the Dart map viewer/PDF generator, driven over a socket via
``ae.utils.kateri``), phylogenetic trees from **TAL** (``tal-draw``, TODO.md #3).
See README.md for the full status and the dependency boundary.

Public entry points:
    make_report(...)        — build + compile + view a report from report.json
    LatexReport             — the page-by-page assembler class
"""

from .report import (
    make_report,
    make_report_abbreviated,
    make_report_serumcoverage,
    make_signature_page_addendum,
    make_signature_page_addendum_interleave,
    LatexReport,
    LatexReportError,
    LatexSignaturePageAddendum,
    LatexSerumCoverageAddendum,
    StatisticsTableMaker,
)
from .init import init, make_report_json, compute_substitutions
from .stat import make_stat, make_stat_json, write_stat

__all__ = [
    "make_report",
    "make_report_abbreviated",
    "make_report_serumcoverage",
    "make_signature_page_addendum",
    "make_signature_page_addendum_interleave",
    "LatexReport",
    "LatexReportError",
    "LatexSignaturePageAddendum",
    "LatexSerumCoverageAddendum",
    "StatisticsTableMaker",
    "init",
    "make_report_json",
    "compute_substitutions",
    "make_stat",
    "make_stat_json",
    "write_stat",
]
