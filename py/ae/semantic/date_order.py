"""
ae.semantic.date_order — draw test antigens in isolation-date order, newest on top.

Builds one background style (`-date-order`) made only of raise modifiers, one per distinct
test-antigen date, oldest first: the newest day is raised last and so is drawn on top. The
modifiers carry no fill, outline, size or legend, so the style changes the drawing order and
nothing else. It uses only the existing `!D` date-range selector, so the `.ace` format and
both renderers (native `cc/map-draw`, kateri) are unchanged.

`!D` is half-open (`first <= date < last`). Each entry selects `[d_i, d_{i+1})`, where
`d_{i+1}` is the next distinct test-antigen date on the chart (the last entry is open-ended),
so an entry matches exactly the antigens dated `d_i`. Every entry has a non-empty `first`,
which keeps undated antigens out: `!D` matches an empty date only when `first` is empty. They
are never raised and so sit below all dated test antigens. `"R": False` keeps reference
antigens out, and `!D` never matches sera, so both keep their existing place underneath.

Whether a front style references `-date-order` is decided by
`ChartModifier.point_draw_order()` (env `AE_POINT_DRAW_ORDER`), see ae.report.chart_modifier.
"""
import sys
import ae_backend

# ======================================================================

def test_antigen_dates(chart: ae_backend.chart_v3.Chart) -> tuple[list[str], int]:
    """Distinct non-empty dates of the test (non-reference) antigens, ascending, and the number
    of undated test antigens."""
    reference = set(no for no, _ in chart.select_reference_antigens())
    dates: set[str] = set()
    undated = 0
    for no, ag in chart.select_all_antigens():
        if no in reference:
            continue
        if date := ag.date():
            dates.add(date)
        else:
            undated += 1
    return sorted(dates), undated

def style(chart: ae_backend.chart_v3.Chart, style_name: str = "-date-order", priority: int = 10450) -> str:
    """Add the `-date-order` background style (raise-only, one entry per distinct test-antigen
    date, oldest first). Returns the style name."""
    dates, undated = test_antigen_dates(chart)
    style = chart.styles()[style_name]
    style.priority = priority
    for first, last in zip(dates, dates[1:] + [""]):
        style.add_modifier(selector={"R": False, "!D": [first, last]}, raise_=True, only="antigens")
    print(f">>>> {style_name}: {len(dates)} entries (distinct test-antigen dates), {undated} undated test antigens left at the bottom", file=sys.stderr)
    return style_name

# ======================================================================
