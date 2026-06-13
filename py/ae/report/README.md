# ae.report — seasonal / SSM WHO CC report tooling

**Consolidation in progress** — see [`MIGRATION.md`](MIGRATION.md) for the full plan,
history (AD → `vcm`), audit, and phased steps.

This package holds the ae-based **report engine** (the library tier of the team's
`vcm` tool). The AD-faithful re-port that previously lived here (`report.py`,
`latex.py` declarative assembler, `report.json` templates, `jsonio.py`, `labs.py`,
`cli.py`) has been **shelved** — it is preserved on the `report-shelved` branch.

## Landed (Phase 1 — engine/library tier)

| module | role | source |
|--------|------|--------|
| `latex.py` | LaTeX assembler — functions returning `list[str]` (`cover`, `toc`, `section_title`, `time_series`, `phylogenetic_tree`, `maps_in_columns`, `geographic`, the WhoccStatisticsTable builder) | vcm `latex.py` |
| `dirs.py` | working-dir conventions; `lab_title` / `lab_of_dir` | vcm `dirs.py` |
| `main_loop.py` | async command loop + kateri `Task`; the `@command` / `no_kateri` / `no_loop` decorators | vcm `main_loop.py` |
| `modules.py` | hot-reload module machinery | vcm `modules.py` |
| `download.py` | chart download / `relax` / `orient_to` / `merge` via `ae_backend.chart_v3` | vcm `download.py` |
| `stat_tables.py` | `stat.json.xz` → tabs / csv / html | vcm `stat.py` |
| `stat.py` | **`stat.json.xz` writer** (`make_stat_json`) from `ae_backend.hidb` + `locdb_v3` — the Python port of AD `hidb5-stat` | this repo (kept) |
| `bin/ssm-report-stat` | CLI over `stat.py` | this repo (kept) |

All `vcm.v2.*` imports were rewritten to `ae.report.*`; `latex.py`'s inherited
invalid-escape `SyntaxWarning`s were fixed output-preservingly. All modules import
clean under Python 3.10 + `ae_backend` (the engine needs `ae_backend`, pulled in via
`ae.utils.datetime`; `main_loop`/`download` also use kateri at runtime).

## Still per-report (live in each report working dir, NOT here)

`conference_data.py` (report definition), `serology.py` (season's serology antigens),
the subtype `chart_modifier`s (`h1`/`h3`/`b` — season clades), and the report-dir
scripts (`report.py`, the `addendum-*.py`, `data.py`, the top-level and per-map `0do`
runners). These encode season-specific scientific decisions and are edited every report.

## Pending — Phase 1b refactor (awaiting review)

The `ConferenceData`-coupled engine modules are **not yet landed**: `chart_modifier.py`
(base `ChartModifier(ConferenceData)`), `geographic.py`, `commander.py`. Bringing them
in cleanly needs a small refactor — `ae.report` defines a thin `ConferenceData` base
(interface + defaults), and each report's concrete `conference_data.py` subclasses it.
See MIGRATION.md → "The one knot to resolve".

Also pending: **Phase 2** — point `stat_tables.py`'s `_compute_stat` at
`ae.report.stat.make_stat_json` (it currently still shells the AD `hidb5-stat` binary);
and the AD scaffolding still present here (`init.py`, `templates/`, `bin/ssm-report-init`)
to be removed/replaced.

## Verification (stat writer)

`ae.report.stat.make_stat_json` is verified against real H1/H3 hidb: cross-product
invariants hold (Σ vt = all, Σ labs = all, Σ months = year, `sera_unique` ≥ deduped
`sera`) and the output feeds the LaTeX statistics tables. ⚠ B is skipped — the B hidb
fails to load in `ae_backend.hidb` (`STRING_ERROR`, open hidb-side bug).
