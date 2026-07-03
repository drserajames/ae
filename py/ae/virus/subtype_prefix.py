"""
ae.virus.subtype_prefix — prefix a strain name with its subtype/type.
"""
import ae_backend

# ======================================================================

def add_subtype_prefix_for_chart(chart: ae_backend.chart_v3.Chart, name: str) -> str:
    """Prefix `name` with the chart's type/subtype (e.g. `A(H3N2)/…`) unless it already
    starts with `A/`, `A(` or `B/`."""
    if name and name[:2] not in ["A/", "A(", "B/"]:
        name = f"{chart.info().type_subtype()}/{name}"
    return name
# ----------------------------------------------------------------------

def add_subtype_prefix(type_subtype: str, name: str) -> str:
    """Prefix `name` with `type_subtype` unless it already starts with `A/`, `A(` or `B/`."""
    if name and name[:2] not in ["A/", "A(", "B/"]:
        name = f"{type_subtype}/{name}"
    return name

# ======================================================================
