"""
ae.chart.merge — merge several charts into one, with validation and optional reporting.
"""
import sys
from pathlib import Path
import ae_backend.chart_v3

# Distinct "argument not supplied" sentinel — cannot use None, because None is now forwarded to the
# backend as "not supplied" and NaN is the explicit "no gate" request. See the defaults matrix below.
_UNSET = object()

# ======================================================================

def merge(sources: list[Path]|list[ae_backend.chart_v3.Chart], match: str, merge_type: str, combine_cheating_assays: bool, duplicates_distinct: bool, report: bool, remove_semantic: bool = True,
          sd_limit=_UNSET, sd_denominator=_UNSET) -> ae_backend.chart_v3.Chart:
    """match: "strict", "relaxed", "ignored", "auto"
    merge_type: "type1", "simple", "type2", "incremental", "type3", "overlay", "type4", "type5"

    Across-layer titer-merge SD gate (lispmds rule 5: a cell whose across-layer log2 titers have
    SD > sd_limit becomes "*"). sd_limit / sd_denominator have context-dependent defaults:

      sd_limit supplied? | sd_denominator supplied? | effective threshold | effective denominator
      ------------------ | ------------------------ | ------------------- | ---------------------
      no                 | no                       | 1.0                 | population (n)   <- AD parity
      yes                | no                       | as given            | sample (n-1)     <- Racmacs
      no                 | yes                      | 1.0                 | as given
      yes                | yes                      | as given            | as given

    i.e. hands-off reproduces the legacy AD toolkit (population SD @ 1.0); tuning the threshold falls
    back to the sample (n-1, R sd()) denominator unless a denominator is given explicitly. Pass
    sd_limit=float("nan") to disable the gate entirely. sd_denominator is "population" or "sample".
    """

    # Forward only the options the caller actually supplied, so the backend's context-dependent
    # defaults (nullopt paths) fire for the omitted ones.
    merge_sd_kwargs = {}
    if sd_limit is not _UNSET:
        merge_sd_kwargs["sd_limit"] = sd_limit
    if sd_denominator is not _UNSET:
        merge_sd_kwargs["sd_denominator"] = sd_denominator

    def get(src: Path|ae_backend.chart_v3.Chart) -> ae_backend.chart_v3.Chart:
        """Load `src` (a path or a Chart) as a Chart, applying `duplicates_distinct` if
        requested."""
        if not isinstance(src, ae_backend.chart_v3.Chart):
            src = ae_backend.chart_v3.Chart(src)
        if duplicates_distinct:
            src.duplicates_distinct()
        return src

    def report_chart(chart: ae_backend.chart_v3.Chart) -> str:
        """`<name> <nAg>:<nSr>` one-line summary of a chart."""
        return f"{chart.name()} {chart.number_of_antigens()}:{chart.number_of_sera()}"

    if len(sources) < 2:
        raise ValueError("too few sources")
    if match not in ["strict", "relaxed", "ignored", "auto"]:
        raise ValueError("invalid match")
    if merge_type not in ["type1", "simple", "type2", "incremental", "type3", "overlay", "type4", "type5"]:
        raise ValueError("invalid merge_type")

    merge: ae_backend.chart_v3.Chart = get(sources[0])
    for src in sources[1:]:
        chart = get(src)
        merge, merge_data = ae_backend.chart_v3.merge(merge, chart, match=match, merge_type=merge_type, combine_cheating_assays=combine_cheating_assays, **merge_sd_kwargs)
        if report:
            print(report_chart(merge), report_chart(chart), merge_data.common(), "-" * 70, sep="\n", end="\n\n")
    if remove_semantic:
        for ag_no, antigen in merge.select_all_antigens():
            antigen.semantic.remove_all()
        for sr_no, serum in merge.select_all_sera():
            serum.semantic.remove_all()
    return merge

# ======================================================================
