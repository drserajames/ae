import sys, pprint
from typing import Any

import ae_backend
from . import front_style

# ======================================================================

def with_opacity(color: str, opacity: float) -> str:
    """Return `color` with the given fill opacity baked into an alpha channel.

    Antigen clade colours are 7-char hex (e.g. "#03569b"); kateri renders a
    9-char "#AARRGGBB" hex as a fill with that alpha (fillOpacity), so making
    antigens semi-transparent to relieve overplotting just means prepending an
    alpha byte. opacity is 0.0 (transparent) .. 1.0 (opaque).

    Colours that aren't a 7-char "#RRGGBB" hex (named colours, already-alpha'd
    9-char hex, ":bright"/":pale" modifiers) are returned unchanged."""
    if opacity >= 1.0 or not isinstance(color, str) or not (len(color) == 7 and color[0] == "#"):
        return color
    alpha = max(0, min(255, round(opacity * 255)))
    return f"#{alpha:02x}{color[1:]}"

# ======================================================================

def attributes(chart: ae_backend.chart_v3.Chart, entries: list[dict[str, str]]):
    """expected entries: [{"name": "3C.2a1b.2a.2 156S", "clade": "3C.2a1b.2a.2", "aa": "156S", **ignored}]"""

    def set_by_clade_aa(name: str, clade: str, aa: str):
        for selector in [chart.select_antigens, chart.select_sera]:
            for no, ag_sr in selector(lambda en: en.has_clade(clade) and en.aa[aa]):
                ag_sr.semantic.add_clade(name)

    def set_by_aa(name: str, aa: str):
        for selector in [chart.select_antigens, chart.select_sera]:
            for no, ag_sr in selector(lambda en: en.aa[aa]):
                ag_sr.semantic.add_clade(name)

    # pprint.pprint(entries)
    for data in entries:
        if data.get("clade"):
            set_by_clade_aa(**data)
        else:
            set_by_aa(**data)

    # set sequenced
    for no, ag_sr in chart.select_antigens(lambda en: en.is_sequenced()):
        ag_sr.semantic.set("sequenced", True)
    # print(f">>>> sequenced: {chart.select_antigens(lambda en: en.is_sequenced())}", file=sys.stderr)

# ======================================================================

def style(chart: ae_backend.chart_v3.Chart, style_name: str, data: list[dict[str, str]], add_counter: bool = True, legend_style: dict[str, Any] = {}, priority: int = 1000, mark_sequenced: dict = None, antigen_fill_opacity: float = 1.0):
    """expected data: [{"name": "3C.2a1b.2a.2 156S", "legend": "2a1b.2a.2 156S", "color": "red", **ignored}]

    antigen_fill_opacity: opacity (0..1) applied to antigen *fill* colours to
    relieve overplotting; outlines stay solid and sera are unaffected. Default
    1.0 keeps antigens fully opaque (previous behaviour)."""
    sname = f"-{style_name}-sera"
    style = chart.styles()[sname]
    style.priority = priority + 1
    for modifier in data:
        style.add_modifier(selector={"C": modifier["name"]}, outline=modifier["color"], outline_width=3.0, rais=True, only="sera")

    sname = f"-{style_name}"
    style = chart.styles()[sname]
    style.priority = priority
    style.legend.add_counter = add_counter
    front_style.legend_style(style.legend, legend_style)
    legend_priority = 99
    if mark_sequenced:
        style.add_modifier(selector={"sequenced": True}, **mark_sequenced, only="antigens")
    for modifier in data:
        style.add_modifier(selector={"C": modifier["name"]}, fill=with_opacity(modifier["color"], antigen_fill_opacity), outline="black", rais=True, only="antigens", legend=modifier["legend"], legend_priority=legend_priority)
        legend_priority -= 1

# ======================================================================
