"""
Per-season subtype modifier — COPY + edit (clade definitions change each season).

NOTE the inheritance: the engine's ChartModifier inherits the *base* ConferenceData,
so a report's subtype modifier must ALSO mix in the report's *concrete* ConferenceData
for self.conferencence_date()/time_series() to resolve (validated end-to-end).
"""

from ae.report import chart_modifier as cm_m
import conference_data                            # the report's concrete ConferenceData


class H1_ChartModifier(cm_m.ChartModifier, conference_data.ConferenceData):

    def subtype(self) -> str:
        return "A(H1N1)"

    def title_subtype(self) -> str:
        return "A(H1N1)"

    def style_for_legacy_plot_spec(self) -> str:
        return "clades"

    def export_styles(self) -> list[str]:
        return ["clades", "clades-6m", "clades-12m", "serology"] + \
               [f"ts-{tse}" for tse in self.time_series().range_begin_str()]

    def export_info_styles(self) -> list[str]:
        return ["info-clades", "info-clades-6m", "info-clades-12m"]

    # clade attributes/styles come from `semantic_clades` (acmacs-data) keyed by subtype().
