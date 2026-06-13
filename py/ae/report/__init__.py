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

Still per-report (live in each report working dir, not here): conference_data,
serology, the subtype chart_modifiers, report.py + the addenda + 0do scripts.

Still pending (Phase 1b refactor — see MIGRATION.md): the ConferenceData-coupled
modules `chart_modifier`, `geographic`, `commander`.

Import the submodules explicitly, e.g. `from ae.report import latex, download`.
The engine submodules require `ae_backend` (Python 3.10) and, at runtime, the
`kateri` executable; they are intentionally not eagerly imported here so that
`import ae.report` stays lightweight.
"""

# Lightweight, dependency-free convenience re-exports only.
# (Engine submodules pull ae_backend / kateri and are imported on demand.)
from .stat import make_stat_json, write_stat  # noqa: F401  (lazy ae_backend inside)

__all__ = ["make_stat_json", "write_stat"]
