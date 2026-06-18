"""
ae.report — seasonal/SSM WHO CC report tooling.

**Migration in progress** (see `MIGRATION.md`). This package is being consolidated
around the team's ae-based report tool `vcm`. As of Phase 1, the **engine/library
tier** has landed here:

    latex         — the LaTeX assembler (functions → list[str])
    dirs          — working-dir conventions, lab_title / lab_of_dir
    main_loop     — async command loop + kateri task, the @command decorator
    modules       — hot-reload module machinery
    download      — chart download / relax / orient / merge (ae_backend.chart_v3)
    stat_tables   — stat.json.xz → tabs / csv / html
    stat          — stat.json.xz writer (ae_backend.hidb; replaces AD hidb5-stat)
    conference_data_base — base ConferenceData(VcmDirs); the report subclasses it
    chart_modifier       — base ChartModifier(ConferenceData); semantic styling
    geographic           — geo settings/maps; make_geo(conference_data, …) injected
    commander            — the @command surface (download/populate/prestyle/style/export)

Still per-report (live in each report working dir, not here): the concrete
`conference_data.py` (subclasses `ae.report.conference_data_base.ConferenceData`),
`serology.py`, the subtype chart_modifiers, report.py + the addenda + 0do scripts.

Import the submodules explicitly, e.g. `from ae.report import latex, download`.
The engine submodules require `ae_backend` (Python 3.10) and, at runtime, the
`kateri` executable; they are intentionally not eagerly imported here so that
`import ae.report` stays lightweight.
"""

# Lightweight, dependency-free convenience re-exports only.
# (Engine submodules pull ae_backend / kateri and are imported on demand.)
from .stat import make_stat_json, write_stat  # noqa: F401  (lazy ae_backend inside)

__all__ = ["make_stat_json", "write_stat"]
