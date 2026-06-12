# ae.report — SSM / seasonal WHO CC report generation

Port of AD `ssm-report` (`~/AC/eu/AD/sources/ssm-report`, ~8,900 LOC), TODO.md
subsystem **#4**.

This package currently contains the **report-assembly core**: it takes a
`report.json` settings file plus a directory of pre-generated figure PDFs and
assembles them into one LaTeX document, compiled with `pdflatex` into the final
report PDF. The figure-*generation* half of AD ssm-report is **not yet ported**
because it depends on the map-drawing subsystem (TODO.md #1) — see
[Dependency boundary](#dependency-boundary) below.

## Usage

```bash
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
| `labs.py` | Lab-name constants (`sLabDisplayName`, `sLabOrder`). Extracted from AD `map.py`/`stat.py` so the assembler doesn't import the figure-generation modules. |
| `jsonio.py` | `read_json` replacing AD `acmacs_base.json.read_json`: transparent `.xz`/`.bz2` decompression + comment/trailing-comma tolerance. |
| `cli.py` | `--working-dir` command-line entry point (mirrors AD `bin/report-simple`, plus `--no-compile`/`--no-view`). |
| `templates/report.json` | Reference settings file copied from AD `template/report.json` — documents the canonical page sequence. |

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
PDFs into the final report PDF. Verifiable with no map-draw present (see below).

**Not yet ported — blocked on map-draw (#1):** the modules that *produce* the
figure PDFs the assembler embeds —
- `map.py` / `maker.py` — antigenic maps & time series (needs `cc/map-draw`)
- `signature_page.py` — tree + signature-page rendering (also needs TAL, #3)
- `geographic.py` — geographic time-series maps
- `stat.py` — `stat.json.xz` generation (counts; the *reader* is already ported
  here in `StatisticsTableMaker`)
- `serum_coverage.py`, `commands.py` / `maker.py` orchestration, `init.py`
  (working-dir scaffolding, template install, DB fetch)

These need `ae_backend` chart/map APIs that don't exist until map-draw lands.
The natural next milestones are: port `init.py` (pure-Python working-dir +
`report.json` scaffolding, no map-draw needed), then wire figure generation onto
`ae_backend` + the `chart-draw` path as map-draw M2+ matures.

## Verification

The assembly core is exercised end-to-end against a dummy 1-page figure PDF
(standing in for a real map/tree): a minimal `report.json` covering `cover`,
`toc`, sections, descriptions, an embedded `pdf`, a `maps` grid and `raw`/`latex`
blocks assembles and compiles cleanly to a **6-page PDF** via `pdflatex`. This
requires a TeX installation (`pdflatex` on `PATH`) but **no** map-draw and **no**
`ae_backend`. `--no-compile` produces just the `.tex` and needs neither.
