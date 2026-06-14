# ae.report — seasonal / SSM WHO CC report tooling

**Engine consolidated; not yet remake-ready end-to-end** (see [`MIGRATION.md`](MIGRATION.md)
for the full plan, history (AD → `vcm`), audit, and as-built notes — in particular the
[2026-0223 gap analysis](MIGRATION.md#gap-analysis-2026-0223-capstone-attempt)). The
**library tier** is a verified-faithful copy of a real report's `vcm`, and the adjust stage
is ported (`ae.adjust` + kateri point-drag). But a full faithful **remake** of a real
report on `ae.report` is **not yet achievable** — the capstone attempt surfaced three gaps:
(a) ✅ **closed** — `geographic.py` now has a `color_by="coloring"` mode that consumes the
report's `geographic_coloring` aa/clade `apply` rules (AD `ColoringByAminoAcid` port + geo-draw
packed-dots renderer), built + verified on real H1 hidb; (b) tree `.tal`→`tal-draw` translation
fidelity is unverified vs a real report's `.tal`; (c) the per-report glue isn't applied to a real
report's config. Remaining: (b), (c), then the full assembled-report run.

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

## Landed (Phase 1b — the ConferenceData-coupled engine)

| module | role |
|--------|------|
| `conference_data_base.py` | thin base `class ConferenceData(dirs.VcmDirs)` — the per-report interface (`conferencence_date`/`time_series`/`current_vaccine_years`/`geographic_*`) as `NotImplementedError` stubs. The report's concrete `conference_data.py` subclasses it. |
| `chart_modifier.py` | base `class ChartModifier(conference_data_base.ConferenceData)` — semantic styling. `semantic_clades`/`semantic_vaccines` (acmacs-data) and per-report `serology` are **guarded imports** (resolved at report runtime), so `ae.report` imports standalone. |
| `geographic.py` | geographic time-series maps via ae's **`geo-draw`**: `make_geo(geo_dir, time_series, hidb_dir, color_by=…)` counts hidb antigens by (month, location), writes geo-draw's `--data` records JSON, and renders `<geo_dir>/<subtype>-<YYYY-MM>.pdf`. Decoupled from `ConferenceData`. **`color_by="continent"`** (default) → one continent-coloured dot per location; **`color_by="clade"`** → one clade-coloured **pie** per location (wedges per clade + legend), clade resolved from **seqdb** (name/reassortant/passage match; unresolved → "unknown"). |
| `trees.py` | phylogenetic-tree PDFs via ae's **`tal-draw`**: `make_trees(specs)` translates the report's `.tal` settings-v3 config (`ae.tal.settings_v3`) → tal-draw schema and renders the tree file (`.tjz`/`tree.json[.xz]`) → the `<subtype>.pdf` the `phylogenetic_tree` page embeds. Replaces AD's `tal -s …`. |
| `commander.py` | the `@command` surface (`download`/`populate`/`prestyle`/`style`/`export`). |

**Per-report adaptations a report needs** (one-time, in the report dir — not in `ae`):
- `conference_data.py`: `class ConferenceData(ae.report.conference_data_base.ConferenceData)`.
- the subtype modifier must **mix in the concrete ConferenceData** so its data is in the
  MRO (since the engine's `ChartModifier` now inherits the *base*): e.g.
  `class H1_ChartModifier(ae.report.chart_modifier.ChartModifier, conference_data.ConferenceData)`.
- whatever calls `make_geo`: pass the ConferenceData instance: `make_geo(ConferenceData(), geo_dir)`.
- `serology.py` and `semantic_clades`/`semantic_vaccines` must be on the report's path.
- (working-dir-derived values like `title_lab`/`chart_name_prefix` come from the report
  dir name automatically — only needed an override in the isolated `/tmp` test.)

All 11 engine modules import clean under Python 3.10 + `ae_backend`.

### ✅ End-to-end validated against a real report

Using the real `2026-0119-tc2/h1-cdc` chart (`prestyled.ace`) with the adapted per-report
classes above, `Downloaded_ChartModifier.populate_for_style()` ran the full
`ae.report.chart_modifier` styling (clades, vaccine resolution, serology via `ae.semantic`),
and `ae.utils.kateri` drove **kateri** to export the styled map PDFs. The `clades` map is a
**1-page 800×800 pt PDF visually identical to the known-good `out.1.clades.pdf`** (same
"CDC A(H1N1) by clade" title, clade legend, antigen cloud). This exercises the whole Phase 1a+1b
engine end-to-end: `chart_modifier` + `conference_data_base` mixin + `commander`/kateri export.
(Needs the kateri fix below.)

## Done — Phase 2 (de-AD the stat path) + Phase 3 (drop AD scaffolding)

- **Phase 2:** `stat_tables._compute_stat` now calls `ae.report.stat.make_stat_json`
  (`ae_backend.hidb` + `locdb_v3`) instead of shelling the AD `hidb5-stat` C++ binary.
  So the consolidated tree has **no AD/C++ dependency** for stats.
- **Phase 3:** removed the leftover AD scaffolding — `init.py`, `templates/`,
  `bin/ssm-report-init`. The vcm world uses `dirs.py` conventions, not `report.json`.

## kateri launcher fix

End-to-end surfaced a real bug in [`ae.utils.kateri`](../utils/kateri.py): `KATERI_EXE = "kateri"`
resolves to the `/usr/local/bin/kateri` **symlink**, and macOS dyld derives `@executable_path`
from the launch path (not the resolved target), so kateri can't find its Flutter frameworks
(`@executable_path/../Frameworks` → `/usr/local/Frameworks`, missing) and never connects. Fixed by
resolving the symlink: `KATERI_EXE = os.path.realpath(shutil.which("kateri") or "kateri")`.

## What remains

- **TAL `.tal` translation fidelity** (TAL subsystem): the report-side tree glue (`trees.py`)
  works, but the settings-v3 `.tal` → tal-draw translator skips a few features (arbitrary
  positioned labels, `edge >=` selection, non-object select/apply). Signature-page composition
  (tree + map) is `bin/tal-signature-page` (TAL).
- **Geographic clade/lineage colouring — DONE.** `geo-draw` now draws per-location **pies**
  (wedges per clade + legend) in addition to continent dots; `make_geo(color_by="clade")`
  resolves each hidb antigen's clade from **seqdb** and emits the pie `--data`. (Note: clade
  resolution depends on the seqdb being available and matching the hidb antigen by
  name/reassortant/passage; unmatched antigens bucket as "unknown".)
- **Adjust stage** (the last AD dependency) — the **programmatic (agent-facing) front-end is
  done**: [`ae.adjust`](../adjust.py) (`Adjust`: select-by-geometry / move / flip / pin / relax /
  procrustes / save), the scriptable equivalent of AD's `0do`. The interactive (human) half —
  kateri antigen-point dragging — remains, owned by kateri. See `MIGRATION.md` Stage B.

## Bootstrapping a new report

[`skeleton/`](skeleton/) has copy-and-edit templates (`conference_data.py`,
`h1_chart_modifier.py`, `serology.py`, a per-map `0do`) + a guide encoding the validated
per-report wiring — in particular the subtype-modifier mix-in
`class H1_ChartModifier(ae.report.chart_modifier.ChartModifier, conference_data.ConferenceData)`.
Use synthetic placeholders; real strain data stays in the report dir only.

## Verification

- **Engine:** all 11 modules import clean (Python 3.10 + `ae_backend`).
- **Geographic (continent):** `geographic.make_geo` over real hidb (2-month H3 window) extracts
  per-month location counts → records JSON → `geo-draw` renders `h3-2024-01.pdf` /
  `-02.pdf` — world maps with continent-coloured, count-sized dots; rasterised and eyeballed.
- **Geographic (clade pies):** `geo-draw` clade-pie rendering verified with synthetic
  `cc/geo/test/pie-records.json` via `sh cc/geo/test/test-geo-pie.sh` (pies sized/ordered by
  count, stable per-clade colours, legend). `make_geo(color_by="clade")` resolves clades from
  real seqdb (counts only — no strain data emitted, per TODO rule 8).
- **Trees:** `trees.make_trees` on a real report tree (`.tjz` + 93 KB `.tal`) translates the
  `.tal` → tal-draw schema and renders a phylo-tree PDF (88 k leaves, clades, time-series
  matrix); rasterised and eyeballed. (3 `.tal` translation warnings — features the TAL
  settings-v3 translator doesn't cover yet — are TAL-subsystem follow-ups.)
- **Stat (Phase 2):** `stat_tables.make_stat` over real hidb produces `stat.json.xz` +
  per-lab/subtype `*-tab.txt` + `stat.csv` + `index.html` via `ae.report.stat` (no
  `hidb5-stat`). `make_stat_json` cross-product invariants verified earlier (Σ vt = all,
  Σ labs = all, Σ months = year, `sera_unique` ≥ deduped `sera`).
