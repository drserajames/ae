# ae.report — SSM / seasonal WHO CC report generation

Port of AD `ssm-report` (`~/AC/eu/AD/sources/ssm-report`, ~8,900 LOC), TODO.md
subsystem **#4**.

This package currently contains the **report-assembly core**: it takes a
`report.json` settings file plus a directory of pre-generated figure PDFs and
assembles them into one LaTeX document, compiled with `pdflatex` into the final
report PDF. The figure-*generation* half of AD ssm-report is **not yet ported**;
in ae the figures it produces come from elsewhere (antigenic maps from **kateri**,
trees from **TAL**) rather than the AD `acmacs-map-draw` pipeline — see
[Dependency boundary](#dependency-boundary) below.

## Usage

```bash
# scaffold a new report working dir (subdirs + templates + report.json/setup.json)
# a dir named like YYYY-MMDD (e.g. 2026-0219) is parsed as the meeting date
PYTHONPATH=build:py bin/ssm-report-init --working-dir <dir>

# working dir contains report.json + the figure PDFs it references
PYTHONPATH=build:py bin/ssm-report --working-dir <dir>

# write the .tex only (no pdflatex / no viewer) — handy headless / for inspection
PYTHONPATH=build:py bin/ssm-report --working-dir <dir> --no-compile

# compile but don't open a viewer
PYTHONPATH=build:py bin/ssm-report --working-dir <dir> --no-view
```

Or from Python:

```python
from pathlib import Path
from ae.report import make_report
make_report(source_dir=Path("."), source_dir_2=Path(""),
            output_dir=Path("report"), report_settings_file="report.json")
```

## Module layout

| file | role |
|------|------|
| `report.py` | `LatexReport` page-by-page assembler, the signature-page / serum-coverage addendum subclasses, and `StatisticsTableMaker`. Ported from AD `report.py`. |
| `latex.py` | LaTeX template strings (`T_Head`, `T_Cover`, `T_Section`, descriptions, table/figure environments, …). Ported **verbatim** from AD `latex.py`. |
| `init.py` | Working-dir scaffolding: subdirs, static templates, and the date-substituted `report.json` / `setup.json`. Ported from the unblocked parts of AD `init.py`. |
| `stat.py` | **`stat.json.xz` writer** (`make_stat_json` / `make_stat`): antigen/sera counts by virus type / lab / date / continent, from `ae_backend.hidb` + `locdb_v3`. Port of AD's C++ `hidb5-stat`. Feeds `StatisticsTableMaker`. |
| `labs.py` | Lab-name constants (`sLabDisplayName`, `sLabOrder`). Extracted from AD `map.py`/`stat.py` so the assembler doesn't import the figure-generation modules. |
| `jsonio.py` | `read_json` replacing AD `acmacs_base.json.read_json`: transparent `.xz`/`.bz2` decompression + comment/trailing-comma tolerance. |
| `cli.py` | `--working-dir` command-line entry point for *assembly* (mirrors AD `bin/report-simple`, plus `--no-compile`/`--no-view`). |
| `templates/` | Reference templates copied from AD `template/`: `report.json` (canonical page sequence), `setup.json`, `index.html`, `README.org`, `root-gitignore`, `merges-index.html`. |

`bin/ssm-report-init` scaffolds a working dir; `bin/ssm-report` assembles it;
`bin/ssm-report-stat` writes `stat/stat.json.xz` from hidb.

The only deviation from the AD source is the import wiring (`jsonio`/`labs`
instead of `acmacs_base` / the `.map` figure module); the emitted LaTeX is
byte-for-byte equivalent.

## How a report is described

`report.json` has a `cover` block, an optional `time_series` (`{date:{start,end}}`,
used to expand month-by-month figure filenames), and a **`pages`** list. Each page
is either a string (`"new_page"`, `"toc"`, …) or an object with a `"type"` that
dispatches to a `LatexReport.make_<type>` method. A leading `?` on a `type` (or a
`?type` key) comments a page out.

### Page types and their data inputs

| page `type` | emits | reads from disk |
|-------------|-------|-----------------|
| `cover` | title page (hemisphere / year / meeting date, or simple title) | — (settings only) |
| `toc` | `\tableofcontents` | — |
| `section_begin` / `subsection_begin` | section headings | — |
| `new_page` / `blank_page` | page breaks | — |
| `latex` / `raw` / `description` | inline LaTeX / text | — |
| `*_description` (antigenic / neut / geographic / phylogenetic / serum-circle) | fixed explanatory paragraphs, chosen by `coloring` / variant | — |
| `phylogenetic_tree` | embeds a tree PDF | `tree/<subtype>.tree[<infix>].pdf` |
| `geographic_ts` | grid of monthly geographic maps | `geo/<SUBTYPE>-geographic-<YYYY-MM>.pdf` |
| `antigenic_ts` | 6-per-page grid of monthly antigenic maps | `<subtype>-<assay>/ts-<lab>-<YYYY-MM>.pdf` |
| `statistics_table` | a WHO CC counts table (antigens/sera by continent, with deltas vs previous report) | `stat/stat.json.xz` (+ optional `previous` report's `stat/stat.json.xz`) |
| `map` / `maps` / `map_with_title` | one / a grid / a captioned antigenic map | `<subtype>-<assay>/<map_type>-<lab>.pdf`, or explicit `images:[...]` paths |
| `pdf` / `signature_page` | embeds an arbitrary PDF / a signature page | explicit `image:` path |
| `serum_coverage_map_set` | serum-coverage map pairs (empirical/theoretical) | `serumcoverage-reviewed-*.json` + the referenced PDFs |

### Report variants (top-level `type`)

- `report` (default) → `LatexReport`
- `signature_pages` → `LatexSignaturePageAddendum` (a cover + a sequence of
  signature-page PDFs, by lab/subtype/assay)
- serum-coverage and interleaved-signature-page addenda via the `make_report_*`
  helpers.

## Dependency boundary

**Ported now (this package):** everything that turns a `report.json` + existing
PDFs into the final report PDF — and the working-dir scaffolding that produces
`report.json` / `setup.json`. Both halves are verifiable with no figure-renderer
present (see below). The site-specific infra `init.py` omits (a bare git repo +
hidb/seqdb/locationdb rsync from the CPE `albertine` host; the
`rr`/`sy`/`rename-report-on-server` deploy scripts that shell out to
`ssm-make`/`ssh i19`/`syput`) is left to the operator — see the `init.py`
docstring.

**Not yet ported — the figure-*generation* modules** that produce the PDFs the
assembler embeds. These do **not** depend on the (shelved) C++ map-draw subsystem;
in ae the figures come from different renderers, so each needs rebuilding on the
ae side rather than a straight AD port:

| AD module | produces | ae source of the figure |
|-----------|----------|--------------------------|
| `map.py` / `maker.py` | antigenic maps & time series | **kateri** — the Dart map viewer/PDF generator (`drserajames/kateri`), driven over a Unix socket via [`ae.utils.kateri`](../utils/kateri.py) (`send_chart` → `set_style` → `get_pdf`). Not yet wired into a report-figure pipeline. |
| `signature_page.py` | trees + signature pages | **TAL** (`tal-draw`, TODO.md #3 — Phase B in progress) |
| `geographic.py` | geographic time-series maps | **no ae renderer yet** — and *not* a kateri job (kateri draws antigenic maps, not world geography). In AD this was a separate `geographic-draw` binary (acmacs-draw/acmacs-map-draw), see note below. On the ae side it would be a small standalone Cairo renderer reusing `cc/draw/cairo-surface.*` (the kept surface, also used by TAL) + `locdb_v3` + hidb (#2) + seqdb. |
| `stat.py` | `stat.json.xz` (counts) | **ported** → `stat.py` here (`make_stat_json`, `bin/ssm-report-stat`), from `ae_backend.hidb` + `locdb_v3`. ⚠ B counts pending an open hidb B-load bug (`STRING_ERROR`); H1/H3 work. |
| `serum_coverage.py`, `commands.py`/`maker.py` orchestration, the figure half of `init_settings` | per-serum coverage maps + the overall maker driver | depends on the above |

**How AD rendered the geographic maps** (for when this is rebuilt): `geographic.py`
only wrote a settings JSON and shelled out to a `geographic-draw` binary
(`--time-series monthly`). That binary (acmacs-draw `geographic-map.cc` /
`continent-map.cc` + acmacs-map-draw `geographic-draw.cc`) drew a **built-in
equirectangular world map** — a constant continent-outline vector path baked into
C++ (`acmacs-draw/cc/geographic-path.cc`, bounds `[-168.24,90 … 191.76,-90]` →
`1261.3×632.591`) — then, for each **hidb** antigen in the month's date slot, looked
up its location in **locationdb** for `(latitude, longitude)` and dropped a dot at
that point (co-located strains fanned into a small ring), coloured by
continent/clade/lineage/amino-acid. One PDF per month →
`geo/<VT>-geographic-<YYYY-MM>.pdf`, which is exactly what `make_geographic_ts`
globs for. It is **not** related to the antigenic-map (chart) renderer.

**Next milestone:** build a report-figure pipeline that loads charts via
`ae_backend.chart_v3`, drives **kateri** through `ae.utils.kateri` to emit the
antigenic-map PDFs at the filenames `report.py` expects
(e.g. `<subtype>-<assay>/clade-<lab>.pdf`, `ts-<lab>-<YYYY-MM>.pdf`), embeds
**TAL** tree PDFs, and adds a small Cairo **geographic** renderer (on
`cc/draw/cairo-surface.*` + `locdb_v3` + hidb + seqdb, per the note above). The
`chart_v3.Chart(<file>)` import-abort that previously blocked this is **fixed**
(TODO.md §1; verified — load + `export()` work, the `ae.utils.kateri.send_chart`
path), so the only remaining prerequisite is having the `kateri` executable
installed.

## Verification

**Assembly core** — exercised end-to-end against a dummy 1-page figure PDF
(standing in for a real map/tree): a minimal `report.json` covering `cover`,
`toc`, sections, descriptions, an embedded `pdf`, a `maps` grid and `raw`/`latex`
blocks assembles and compiles cleanly to a **6-page PDF** via `pdflatex`. This
requires a TeX installation (`pdflatex` on `PATH`) but **no** figure renderer and
**no** `ae_backend`. `--no-compile` produces just the `.tex` and needs neither.

**Scaffolding (`init.py`)** — `bin/ssm-report-init --working-dir 2026-0219`
creates the subdirs + static templates and writes a `report.json` / `setup.json`
with the date fields substituted; the meeting date is parsed from the dir name.
The date logic is unit-checked against AD semantics (Northern/Southern season,
teleconference selection, the October year split). The generated 233-page
`report.json` round-trips through the assembler's `read_json` and constructs a
`LatexReport` with the correct `ts_dates` — proving the init→assembly handoff
with no figure data. (A *full* compile of that template still needs the figure
and stat PDFs from the not-yet-ported figure-generation pipeline.)

**Stat writer (`stat.py`)** — run against the real H1/H3 hidb over a date window,
the output satisfies the cross-product invariants (Σ virus-types = `all`;
Σ labs = `all` lab; Σ continents ≤ `all` continent; Σ months = year; `sera_unique`
≥ name-deduped `sera`), and feeds straight into `StatisticsTableMaker` to render a
real LaTeX statistics table. Needs Python 3.10 + `ae_backend`, a hidb dir and
locationdb — and **not** `chart_v3` at all (so it was never affected by the
now-fixed chart-import abort).
(B is currently skipped: the B hidb fails to load in `ae_backend.hidb` —
`STRING_ERROR` — an open hidb-side bug; H1/H3 are complete.)
