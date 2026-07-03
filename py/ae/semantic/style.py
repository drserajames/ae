"""
ae.semantic.style — helper to build a semantic style consisting of a single modifier.
"""
import sys
import ae_backend

# ======================================================================

def style_with_one_modifier(chart: ae_backend.chart_v3.Chart, style_name: str, selector: dict[str, object], modifier: dict[str, object], priority: int) -> set[str]:
    """Create style `style_name` at `priority` with a single `modifier` applied to
    `selector`; returns `{style_name}`."""
    style = chart.styles()[style_name]
    style.priority = priority
    style.add_modifier(selector=selector, **modifier)
    return set([style_name])

# ======================================================================
