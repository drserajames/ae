"""
Base ``ConferenceData`` — the interface the report engine (`chart_modifier`,
`geographic`) relies on. Each report's concrete ``conference_data.py`` subclasses
this and fills in the season-specific values; that concrete file stays in the
report working directory (it is edited every report).

Inherits `dirs.VcmDirs` (working-dir conventions / chart filenames), so a concrete
ConferenceData is also a VcmDirs. The methods below are the per-report data the
engine consumes — override them in the report's ConferenceData.

Extracted during the vcm→ae.report consolidation (Phase 1b); see MIGRATION.md.
"""

from typing import Any
from . import dirs


class ConferenceData(dirs.VcmDirs):
    # --- consumed by chart_modifier.ChartModifier ---
    def conferencence_date(self):
        "datetime.date of the meeting"
        raise NotImplementedError("override in the report's conference_data.py")

    def antigen_fill_opacity(self) -> float:
        """Opacity (0..1) for antigen *fill* colours on the maps; outlines stay
        solid, sera unaffected. Default 1.0 = fully opaque (previous behaviour).
        Override in a report's conference_data.py to relieve overplotting."""
        return 1.0

    def time_series(self):
        "ae.utils.time_series.TimeSeriesRange covering the report window"
        raise NotImplementedError("override in the report's conference_data.py")

    def current_vaccine_years(self) -> list[str]:
        raise NotImplementedError("override in the report's conference_data.py")

    # --- consumed by geographic.make_geo ---
    def geographic_settings(self) -> dict[str, Any]:
        raise NotImplementedError("override in the report's conference_data.py")

    def geographic_coloring(self, subtype: str) -> dict[str, Any]:
        raise NotImplementedError("override in the report's conference_data.py")
