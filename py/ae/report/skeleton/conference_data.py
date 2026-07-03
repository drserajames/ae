"""
Per-report definition — COPY into your report dir and edit each season.

Subclasses the ae.report base so the engine (chart_modifier / geographic) can rely
on the interface. The whole concrete class stays per-report (it changes every WHO CC
meeting). Replace the placeholder values below; no real strain names belong here.
"""

from ae.utils.datetime import parse_date
from ae.utils.time_series import TimeSeriesRange
from ae.report.conference_data_base import ConferenceData as _ConferenceDataBase


class ConferenceData(_ConferenceDataBase):
    """Per-report `ConferenceData` skeleton — copy into a report dir and fill in the
    season-specific values (placeholders here)."""

    # --- required by chart_modifier ---------------------------------------
    def conferencence_date(self):
        """The WHO CC meeting date (placeholder — set per report)."""
        return parse_date("YYYY-MM-DD")            # the meeting date

    def time_series(self):
        """The report's month time-series window (placeholder — set per report)."""
        return TimeSeriesRange(first="YYYY-MM", last_inclusive="YYYY-MM", period="month")

    def current_vaccine_years(self) -> list[str]:
        """Current-season vaccine-period codes (placeholder — set per report)."""
        return ["YYYYMM", "YYYYMM"]                # vaccine-period codes

    # --- required by geographic.make_geo (only if you render geo maps) ----
    def geographic_settings(self) -> dict:
        """Geographic-map settings (placeholder — set per report)."""
        return {}                                  # (geo-draw colours by continent)

    def geographic_coloring(self, subtype: str) -> dict:
        """Geographic-map colouring for a subtype (placeholder — set per report)."""
        return {}

    # --- report assembly (report.py drives latex.* with these) ------------
    # def report_content(self) -> list[str]: ...   # see a real report's conference_data.py
