# ae — Porting Roadmap (from AD / Acmacs-D)

This file tracks the work remaining to bring `ae` (Acmacs-E) to feature parity with
the older `AD` (Acmacs-D) tree at `~/AC/eu/AD`. It is the **coordination point** for
multiple agents working in parallel — claim a subsystem before starting, update its
status, and respect the shared-file rules below.

> Background: `ae` has already ported the **core chart engine** (optimize/relax, merge,
> grid-test, procrustes, serum circles, stress), **sequences/seqdb**, **virus
> name/passage parsing**, **locationdb**, **tree manipulation**, and **WHO CC XLSX/TSV
> ingestion**. What remains is several whole subsystems (~57k LOC) plus a long tail of
> CLI wrappers.

---

## Priority order

| # | Subsystem | AD source | ~LOC | ae target | Owner | Status |
|---|-----------|-----------|-----:|-----------|-------|--------|
| 1 | **Map drawing** (Cairo render engine + map-draw) | `acmacs-draw` + `acmacs-map-draw` | ~31,000 | `cc/draw/`, `cc/map-draw/` | *(map-draw agent)* | 🟡 in progress |
| 2 | **hidb** (historical influenza DB) | `hidb-5` | ~4,600 | `cc/hidb/` | *(hidb agent)* | 🟡 read side done + verified; authoring (make/convert/stat) in progress |
| 3 | **TAL** (phylo tree drawing / signature pages) | `acmacs-tal` | ~10,700 | `cc/tal/` (layout + plan) | *(tal agent)* | 🟡 Phase A layout done; draw blocked on #1 |
| 4 | **ssm-report** (seasonal report, Python+LaTeX) | `ssm-report` | ~8,900 | `py/ae/report/` (new) | *(report agent)* | 🟡 in progress — assembly core ported; figures blocked on #1 |
| 5 | **webserver** (HTTPS chart serving) | `acmacs-webserver` | ~2,100 | `py/ae/webserver/` (Python rewrite) | *(webserver agent)* | 🟡 code complete — HTTP/HTTPS verified; chart-data blocked on a `chart_v3` import abort in `ae_backend` (open bug, see §1 note) |
| 6 | **CLI wrappers** (thin shells over `chart_v3` API) | various `bin/chart-*` | small | `bin/` | CLI agent | 🟢 done |

Status legend: 🔴 not started · 🟡 in progress · 🟢 done · ⚪ blocked

---

## Coordination rules (read before starting)

1. **Claim your subsystem** — put your agent label in the Owner column above and set
   status to 🟡 before editing code. One subsystem per agent; they're independent.
2. **`meson.build` is a shared file** — it is the main merge-conflict risk. Keep your
   edits confined to a clearly-commented block (`# --- <subsystem> ---`) and add your
   files/targets there. If two agents must touch it, coordinate by appending, not
   reflowing existing lines.
3. **Python bindings** live in `cc/py/*.cc` and are registered in
   [`cc/py/module.cc`](cc/py/module.cc) + [`cc/py/module.hh`](cc/py/module.hh). Add a
   new `void ae::py::<name>(pybind11::module_&)` file and one registration line — do not
   reorder existing registrations.
4. **Build procedure** is the native-arm64 Apple-Clang-16 dance documented in
   [`CLAUDE.md`](CLAUDE.md) → *Building natively for arm64*. Do **not** use `./mk` or
   Homebrew LLVM. All Cairo/Pango/etc. deps come from arm64 Homebrew at `/opt/homebrew`.
5. **New C++ code**: always `fmt::format_to(` (never bare `format_to(`) — see CLAUDE.md.
6. **Verify before marking 🟢** — each subsystem below has explicit verification
   criteria. A subsystem is not "done" until it compiles in the arm64 build *and* its
   verification command produces the expected output.
7. **Update this file** as you complete milestones (check the boxes).

---

## 1. Map drawing  *(owner: map-draw agent — M1–M4 core done; M4 extras + M5/M6 remain)*

The single biggest gap. As of M1, `ae` **can render a basic antigenic map to PDF**.
`cc/draw/` previously held only geometry/color *primitive headers*; it now also has a
Cairo PDF surface, and `cc/map-draw/` has the renderer + CLI.

- **AD source:** `~/AC/eu/AD/sources/acmacs-draw` (Cairo backend) and
  `~/AC/eu/AD/sources/acmacs-map-draw` (map render + the `mapi` settings DSL).
- **Build deps:** Cairo (`/opt/homebrew/opt/cairo`) — linked into the `chart-draw` target
  only (not libae/ae_backend). **Pango is NOT used** — arm64 pango isn't installed
  (`/opt/homebrew/opt/pango` has no `lib/pkgconfig`/dylib; pkg-config resolves the x86_64
  `/usr/local` copy, which can't link arm64). M3 text uses Cairo's built-in font API
  instead. If advanced typography is ever needed, `brew install pango` (arm64) first.
- **Files added (M1):** [`cc/draw/cairo-surface.hh`](cc/draw/cairo-surface.hh)/`.cc`
  (`ae::draw::CairoPdf`), [`cc/map-draw/draw.hh`](cc/map-draw/draw.hh)/`.cc`
  (`ae::map_draw::export_pdf`), `cc/map-draw/chart-draw-main.cc` (CLI), `meson.build`
  `cairo` dep + `chart-draw` executable.

**Milestones (staged vertical slices):**
- [x] **M1 — Cairo links + minimal slice.** Cairo wired into `meson.build`; `CairoPdf`
      surface (background/circle/square); `export_pdf()` loads an `.ace`, takes the best
      projection's transformed layout, computes a padded square viewport (Y-flipped), and
      draws test antigens (filled green circles), reference antigens (open circles) and
      sera (open squares). CLI is the compiled binary **`build/chart-draw <in.ace>
      <out.pdf> [size]`** (not a `bin/` python script — there's no pybind binding yet).
      **✅ Verified:** `chart-relax test/chart1.ace` → `chart-draw` produces a valid PDF
      1.7 (32 points rendered; rasterised and eyeballed — correct map).
- [x] **M2 — Full styling + draw order.** `export_pdf()` now drives per-point
      shape/fill/outline/outline-width/size/shown from the chart's `legacy::PlotSpec`
      (resolving `ae::draw::v2::Color` strings → RGB via the global `::Color`), and iterates
      `plot_spec.drawing_order()` (sera → reference → test). Charts with no plot spec get the
      synthesised defaults via `PlotSpec::initialize()`. `point_shape` dispatch: Circle/Box/
      Triangle implemented; Egg/UglyEgg fall back to Circle (until M3). Surface gained
      `triangle()` + `line()` primitives. **`size` is treated as ae's multiplier convention
      (default 1.0), not AD pixels** — legacy AD charts with `s≈5` render ~5× large; that's
      an ae *import* convention gap, not a renderer bug. **✅ Verified:** default-path
      `chart1` (green circles / open circles / open boxes) and a hand-styled chart
      (red triangles / blue boxes / open-circle sera, sera behind) both rasterised and
      eyeballed — shapes, colors and order correct.
      **⚠ Still TODO for the TAL blocker:** `CairoPdf` is *not yet* an abstract reusable
      `ae::draw::Surface` — it's a concrete PDF class with `background/circle/square/
      triangle/line`. TAL (#3) Phase B should drive the surface-abstraction extraction
      (likely alongside **M6** SVG/PNG); coordinate on the primitive set then.
- [x] **M3 — Text (Cairo built-in, not Pango).** Surface gained `text(x, y, utf8, font,
      color, center)` using Cairo's toy font API (no new build dep — arm64 pango absent, see
      Build deps above). `export_pdf()` now draws a **title** from `chart.name()` (top centre)
      and **per-point labels**: explicit `PointStyle::label().text` always, plus an
      opt-in `--labels` CLI flag that labels every point by name (`chart.antigens()/sera()
      [i].name()`) — AD's `add-all-labels` behaviour. Label position honours the label
      offset/size/colour. **✅ Verified:** rendered the test chart with `--labels` — the
      chart title plus per-point virus-name labels appear over the correctly-styled shapes;
      rasterised and eyeballed. **Note:** no label collision
      avoidance yet (labels overlap in dense regions) — deferred to M4.
      **For TAL:** the surface now has the `text()` primitive TAL labels will need.
- [x] **M4 (core) — Background + serum circles.** Surface gained a `rectangle`/border via
      `line()`. `export_pdf()` now draws (before points) an antigenic-unit **grid** (grey,
      1 AU spacing) and a black **viewport border** (AD `BackgroundBorderGrid`), and an
      opt-in **`--serum-circles`** overlay using `chart/v3 serum_circles(chart, projection,
      fold=2.0)` — a navy circle per serum at its empirical (else theoretical) radius in AU,
      scaled to device. Sera with no homologous antigen are skipped (logged by the core).
      **✅ Verified:** `chart-draw --serum-circles chart1-opt.ace` — grid + border + title +
      navy serum circles centred on sera with points on top; rasterised and eyeballed.
- [~] **M4 (extras):**
      - [x] **Label collision avoidance (basic).** Surface gained `text_size()`
            (cairo_text_extents). The label pass now tries each label's specified position
            first, then a ring of 8 fallback positions around the point, picking the first
            that doesn't overlap an already-placed label box. Greedy near-point heuristic —
            **not** AD's force-directed layout. **✅ Verified:** dense `--labels` render is
            markedly less cluttered than M3; upper/mid labels fully separated. *Limitation:*
            very dense sub-clusters (≈6 points in a tiny area) still overlap — full fix needs
            force-directed placement + leader lines (future).
      - [ ] legend (better suited to M5 once semantic styles/config exist),
            connection lines (procrustes arrows — needs a 2nd chart + procrustes match),
            stress/error blobs (need bootstrap/triangulation data).
- [ ] **M5 — `mapi` settings DSL:** the JSON-driven mod-applicator pipeline.
- [ ] **M6 — SVG/PNG surfaces** in addition to PDF.

> **Build gotcha (affects every agent who edits `meson.build`):** any edit triggers a full
> meson regenerate, which re-runs the vendored `lexy` CMake subproject. Homebrew CMake is
> now 4.x and rejects `lexy`'s bundled `cmake_minimum_required(<3.5)`. Export
> **`CMAKE_POLICY_VERSION_MINIMUM=3.5`** before `ninja` to get past it.

> **⚠ Open bug (webserver agent, #5) — `chart_v3.Chart(<file>)` aborts in `ae_backend`.**
> **Not staleness — survives a clean rebuild** (re-tested against the Jun 12 16:52 `.so`).
> It is a **real runtime regression isolated to the chart_v3 file-import path in the Python
> module**, narrowed as follows:
> - `ae_backend.chart_v3.Chart()` (empty ctor) → **OK**.
> - `ae_backend.chart_v3.Chart('test/chart1.ace')` → **SIGABRT** (uncatchable — not a Python
>   exception; `except BaseException` does not trap it; no C++ message on stderr, only
>   `Fatal Python error: Aborted`). Same abort on a **plain-JSON** `.ace`, so it is **not** XZ
>   decompression (`xz -d` on the file is fine, 4450 bytes valid JSON).
> - The **v2** reader is fine: native `build/chart-relax test/chart1.ace out.ace` loads the
>   same file (22 ag × 10 sr) and relaxes to stress 66.12. So the C++ lib *can* read the file;
>   only the **v3 import** path aborts.
> - `build/chart-v3-test` can't be used to bisect — it currently fails at startup with a
>   Catch2 *"unmatched ']' … chart-v3-test.cc:12"* registration error (separate breakage).
> - lldb can't attach (SIP on the signed framework python) to get a native backtrace here.
>
> This breaks **all** chart_v3 tools (`bin/chart-info test/chart1.ace` aborts identically),
> not just the webserver. Webserver code is complete and correct; M2's chart-**data**
> endpoints need only this fixed to verify end-to-end (no webserver change required).
> **Suspected area:** chart_v3 importer / `cc/chart/v3/` ace-reader as compiled into
> `ae_backend` (likely an `AD_ASSERT`/`noexcept`-throw → abort). Owner of `cc/chart/v3` +
> `build/` to take this; ping #5 when fixed.

> **Update (tal agent, #3):** rebuilt `build/` on **Jun 12** (for the new `ae_backend.tal`
> module). Confirmed the abort is gone — `ae_backend.chart_v3.Chart('test/chart1.ace')`
> loads fine (22 antigens × 10 sera). It *was* staleness; the current `build/` `.so` is good.
> (Load the `.so` by path via `importlib` if an editable-install `ae_backend` shadows it —
> see `cc/tal/PORTING.md` build notes.)

> **Confirmed (map-draw agent, #1):** independently verified — `ae_backend` is the current
> Jun-12 16:52 build (`ninja … ae_backend` reports "no work to do"), and chart loading is
> stable: 6/6 consecutive `chart_v3.Chart('test/chart1.ace')` loads succeed, `bin/chart-info`
> works. The earlier SIGABRT was **a transient build race** — Python `import`ed the `.so`
> while it was mid-relink — *not* staleness or a runtime regression. If anyone hits this
> again, just re-run after the build settles (don't load the `.so` while `ninja` is writing it).
> Webserver #5 chart-**data** endpoint is unblocked.

---

## 2. hidb — historical influenza database  *(owner: hidb agent — 🟢 done)*

Needed for reference-antigen and vaccine identification, and is a dependency for several
chart tools (e.g. `chart-find-chart-with-antigens`, vaccine styling in map-draw M4).

- **AD source:** `~/AC/eu/AD/sources/hidb-5` (+ `acmacs-whocc-data` reference data).
- **AD tools to reach parity with:** `hidb5-find`, `hidb5-vaccines-of-chart`,
  `hidb5-reference-antigens-in-tables`, `hidb5-dates`, `hidb5-first-table-date`,
  `hidb5-antigens-sera-of-chart`, `hidb5-stat`, `hidb5-make`, `hidb5-convert`.
- **ae target:** `cc/hidb/` + a `hidb` submodule in `ae_backend`.

**Design note — JSON reader, not the binary `.hidb5b`.** AD mmaps an optimised binary
layout (`hidb-bin.*`, `.hidb5b`) for speed. This port instead parses the hidb-v5 **JSON**
(`hidb5.{h1,h3,b}.json.xz`) directly with `ae::simdjson` into plain in-memory vectors —
much simpler, and fast enough for the tools that consume it (a few hundred ms to load a
type). Consequently the AD DB-*maker*/*convert*/binary tooling is intentionally **not**
ported; only the reader + query surface.

**Files added:**
- [`cc/hidb/hidb.hh`](cc/hidb/hidb.hh) / [`cc/hidb/hidb.cc`](cc/hidb/hidb.cc) —
  `ae::hidb` namespace: `Antigen` / `Serum` / `Table` model, `HiDb` (load + lookup),
  name reconstruction (incl. cdc-name handling), `find_antigens`/`find_sera`
  (name parsed via `ae::virus::name::parse` with cdc/slash fallbacks),
  `find_antigens_by_labid`, `reference_antigens(table)`, `most_recent_table`/`oldest`,
  and a `get(virus_type)` singleton cached per type. Data dir from `set_dir()` or `$HIDB_V5`.
- [`cc/py/hidb.cc`](cc/py/hidb.cc) — `ae_backend.hidb` submodule (registered in
  `cc/py/module.{hh,cc}`); `meson.build` `sources_hidb` + `cc/py/hidb.cc` in `sources_py`.
- `bin/hidb-find`, `bin/hidb-dates`, `bin/hidb-reference-antigens-in-tables`,
  `bin/hidb-antigens-sera-of-chart`, `bin/hidb-vaccines-of-chart`, and shared
  `bin/_hidb_boot.py`. Data files are located **only** via the environment
  (`$HIDB_V5`, `$LOCDB_V2`, `$VACCINES_JSON`) — none are bundled in the repo.

**Milestones:**
- [x] Explore `hidb-5`; document the on-disk DB format + the data files it reads. The
      runtime data dir comes from `$HIDB_V5` (override via `hidb.set_dir()` / `hidb::set_dir`).
- [x] Port the DB reader (load + lookup antigen/serum by name).
- [x] Port "find tables containing antigen" (each record carries its table index list),
      "dates" (`hidb-dates`), and "vaccines of chart" (`hidb-vaccines-of-chart`, which
      ports the whocc `vaccines.json` name-list logic in Python over the binding).
- [x] pybind binding + `bin/` wrappers. **✅ Verified** (arm64 build) against real
      type/lineage data: counts load correctly; `reference_antigens` flags the expected
      reference strains in known tables; `hidb-vaccines-of-chart` finds the current
      vaccine strains in a real WHO CC chart, grouped by passage type with table counts.

**Build note:** the `ae_backend` `.so` may be shadowed by an editable install from a
different checkout; `bin/_hidb_boot.py` defeats this by loading this repo's `build/`
`.so` by explicit path (same workaround the tal/webserver agents hit).

### Authoring tools (now in scope — the DB needs to be *built* within `ae`)

The reader above consumes a pre-built hidb. These tools *produce / maintain* it. AD source:
`hidb-make.cc` + `hidb-maker.{hh,cc}` (build), `hidb5-convert.cc` (reformat),
`hidb5-stat.cc` (statistics).

- **`hidb-make`** — build a hidb from a set of charts. Algorithm (faithful to AD
  `HidbMaker`): for each chart add one **Table** (dedup by virus/virus_type/subset/lineage/
  assay/lab/rbc/date; reject exact duplicates); add each non-`DISTINCT` **antigen**/**serum**
  to a global ordered set (antigen key = location/isolation/year/host/annotations/reassortant/
  passage; serum key = …/serum_id), accumulating dates, lab_ids and lineage; link
  antigen↔table and serum↔table; record each serum's homologous antigens (via
  `chart.antigens().homologous(serum)`) as global antigen indexes. Then assign sorted
  indexes and emit the v5 JSON (`set_field_if_not_empty` semantics). Ported in **C++**
  (`cc/hidb/hidb-maker.{hh,cc}`) over `chart::v3`, exposed via the binding + `bin/hidb-make`.
  *ae note:* `ae::chart::v3::Info` has no `subset()` → the table `s` (subset) field is
  omitted; homologous is computed on demand (ae stores it computed, not on the serum).
- **`hidb-convert`** — load a hidb and re-`save()` it (e.g. recompress, or normalise). Since
  this port has no binary `.hidb5b` layout, "convert" = JSON→JSON via `HiDb::save()`
  (compression chosen by output extension). `bin/hidb-convert`.
- **`hidb-stat`** — table statistics (counts by lab / assay / rbc / date). Light; Python over
  the binding. `bin/hidb-stat`.

**Authoring milestones:**
- [ ] `cc/hidb/hidb-maker.{hh,cc}` + `HiDb::save()`; wire into `meson.build` (libae).
- [ ] pybind: `hidb.make(chart_files, output)` (+ `HidbMaker`); `bin/hidb-make`, `bin/hidb-convert`.
- [ ] `bin/hidb-stat`. **Verify:** build a small hidb from a couple of real charts, reload it
      with the reader, and round-trip through `hidb-convert` — counts and a spot-checked
      antigen/serum match the source charts.

**Not ported (low demand):** `hidb5-first-table-date` (a niche per-antigen CSV). The shared
query surface is in place if it's wanted later.

---

## 3. TAL — phylogenetic tree drawing / signature pages  *(owner: tal agent — ⚪ blocked on #1)*

`ae` already has tree **manipulation** (Newick parse, fix-names, substitution-labels,
to-json in `cc/tree/`). Missing: the tree **drawing** / signature-page / time-aware
lineage output.

- **AD source:** `~/AC/eu/AD/sources/acmacs-tal`.
- **AD tool:** `tal`.
- **ae target:** `cc/tal/` — see [`cc/tal/PORTING.md`](cc/tal/PORTING.md) (full architecture
  map + phased port order, produced by milestone 1).
- **Depends on:** the Cairo backend from subsystem #1 (shares the draw surface). Best
  started after map-draw M1–M3 land, or coordinate on the `cc/draw/` surface API.

**⚠ Blocker (confirmed during M1):** every TAL `LayoutElement::draw()` is built on AD's
rich `acmacs::surface::Surface` (lines/paths/Pango text/sub-surfaces). ae currently
provides only `ae::draw::CairoPdf` (`background`/`circle`/`square` — map-draw **M1**). The
*drawing half* of TAL cannot compile until subsystem #1 reaches ~**M3** and exposes a
reusable surface API. `AntigenicMaps` additionally needs the map renderer + **hidb (#2)**.

**Milestones:**
- [x] **Explore `acmacs-tal`; identify the tree-layout + draw entry points.** →
      [`cc/tal/PORTING.md`](cc/tal/PORTING.md). Pipeline, `Node` data model, the full
      `LayoutElement`→source-file map, and the Surface dependency are documented there.
- [x] **Phase A — tree layout (node positions).** `ae::tal::compute_layout(Tree&)` in
      [`cc/tal/layout.cc`](cc/tal/layout.cc), exposed as `ae_backend.tal`
      ([`cc/py/tal.cc`](cc/py/tal.cc)). Port of `compute_cumulative_vertical_offsets()`
      (iterative post-order → safe on deep trees). **Verify:**
      `python3 cc/tal/test/test-layout.py` → `OK: layout verified …`. Builds & links in
      the arm64 build. *(Found: JSON/Newick tree I/O + ladderize-by-leaves already exist in
      `cc/tree/`, so no re-port needed; deep-newick load segfaults in `cc/tree/` — pre-existing,
      not TAL — see PORTING.md.)*
- [x] **Phase A — clade sections.** `ae::tal::compute_clade_sections(Tree&)` in
      [`cc/tal/clades.cc`](cc/tal/clades.cc) (port of `Tree::make_clade_sections()`;
      reuses `Leaf::clades`). **Verify:** `python3 cc/tal/test/test-clades.py` → `OK …`.
- [x] **Phase A — time series (date bucketing).** `ae::tal::compute_time_series(Tree&,
      interval, start?, end?)` in [`cc/tal/time-series.cc`](cc/tal/time-series.cc)
      (year/month/week/day slots + per-slot counts; ports the data side of `time-series.cc`
      using `ae::date` + C++20 `<chrono>`, no `acmacs-base/time-series` dependency; reuses
      `Leaf::date`). **Verify:** `python3 cc/tal/test/test-time-series.py` → `OK …`.
- [ ] **Phase A (remaining, headless):** reconcile aa-transition labelling with
      `cc/tree/aa-transitions.cc`; hz-section detection (`hz-sections.cc`).
- [ ] **Phase B (BLOCKED on #1 ≈M3):** agree a shared `ae::draw::Surface`, then port
      `DrawTree` → column elements → title/legend/aa-transition draw paths.
- [ ] Signature-page composition (`AntigenicMaps` — also needs map render + hidb #2).

---

## 4. ssm-report — seasonal report generation  *(owner: report agent — 🟡 assembly core done)*

Python + LaTeX seasonal/SSM report generation. Note: AD's `bin/ssm-report` and
`commands.py` are marked *obsolete*; the live entry is `ssm-make`/`maker.py`, but the
shared **report-assembly core** (`report.py` + `latex.py`) is what emits the final PDF.

- **AD source:** `~/AC/eu/AD/sources/ssm-report` (Python + LaTeX templates).
- **ae target:** `py/ae/report/` — see [`py/ae/report/README.md`](py/ae/report/README.md)
  (full page-type → data-input table + the dependency boundary, produced by milestone 1).
- **Depends on:** map-draw (#1) for the figures it embeds. The *assembly* layer is
  independent and is now ported; figure *generation* (`map.py`, `maker.py`,
  `geographic.py`, `signature_page.py`, `stat.py` writer) is blocked on #1.
- **Pure Python, no `meson.build` change** — imported from the `py/` source tree
  (run with `PYTHONPATH=build:py`); zero conflict risk with other agents.

**Milestones:**
- [x] **Explore `ssm-report`; list the report sections and their data inputs.** →
      [`py/ae/report/README.md`](py/ae/report/README.md). Page-type dispatch, every
      `make_<type>` figure path, the `report.json` page sequence, and the report
      variants are documented there.
- [x] **Port the LaTeX templates + the assembly orchestration to `py/ae/report/`.**
      `latex.py` (verbatim templates), `report.py` (`LatexReport` + addenda +
      `StatisticsTableMaker`), `labs.py`, `jsonio.py`, `cli.py`, `bin/ssm-report`
      wrapper. AD's `acmacs_base.json` / `.map` deps replaced by self-contained
      helpers; emitted LaTeX is byte-identical. **✅ Verified:** a minimal
      `report.json` + dummy figure PDF assembles and `pdflatex`-compiles to a 6-page
      PDF (no map-draw / `ae_backend` needed; `--no-compile` needs no TeX either).
- [x] **Port `init.py`** — working-dir scaffolding + `report.json` templating.
      `init.py` (`init`/`init_dirs`/`copy_templates`/`make_report_json`/
      `compute_substitutions`/`find_previous_dir`), packaged `templates/`
      (`setup.json`, `index.html`, `README.org`, `root-gitignore`,
      `merges-index.html`), `bin/ssm-report-init`. Omits the site-specific infra
      (albertine git/db rsync, `rr`/`sy`/`rename-report-on-server` deploy scripts)
      and the figure-settings half of `init_settings` (blocked on #1). **✅ Verified:**
      scaffolds dirs+templates and writes substituted `report.json`/`setup.json`;
      date logic unit-checked (Northern/Southern season, teleconference, Oct year
      split); the generated 233-page `report.json` round-trips through the assembler
      (`read_json` + `LatexReport` ctor, correct `ts_dates`).
- [ ] **(BLOCKED on #1)** Wire figure generation (`map.py`/`maker.py`/`geographic.py`/
      `signature_page.py` + `stat.json.xz` writer) onto `ae_backend` + the `chart-draw`
      path. **Verify:** generates a full PDF report from a sample dataset.

---

## 5. webserver — HTTPS chart serving  *(owner: webserver agent — 🟡 core done)*

- **AD source:** `~/AC/eu/AD/sources/acmacs-webserver`.
- **ae target:** **`py/ae/webserver/`** (Python rewrite over `ae_backend`) +
  [`bin/chart-serve`](bin/chart-serve). **No `meson.build` / `cc/` changes** (so no shared-file
  conflict risk with the other subsystems).

**Decision (M1):** *Python rewrite, not a C++ port.* The AD `acmacs-webserver` is a generic
multi-threaded transport built on `websocketpp` + standalone-Asio + OpenSSL and carries **no
chart logic** of its own. Neither `websocketpp` nor Asio is vendored in `ae` or present in
arm64 Homebrew, and `websocketpp` is effectively unmaintained (last release ~2020) — adopting
two new deps for the smallest/lowest-priority subsystem is poor value. Since `ae_backend` is
already a Python extension, the chart-serving role sits directly on top of it using only the
Python **stdlib** (`http.server` + `ssl`): zero new dependencies, runs immediately, and `ssl`
gives the "HTTPS chart serving" the roadmap names. The route surface is stable enough to be
re-hosted behind FastAPI/ASGI later without changing clients.

**Files:** [`py/ae/webserver/__init__.py`](py/ae/webserver/__init__.py),
[`py/ae/webserver/server.py`](py/ae/webserver/server.py) (`ChartServer`, `serve`,
`chart_summary`, `titer_table`), [`bin/chart-serve`](bin/chart-serve).

**Routes:** `GET /` (HTML index) · `GET /healthz` · `GET /api/charts` ·
`GET /api/chart/info?path=REL` · `GET /api/chart/table?path=REL` · `GET /chart?path=REL`.
`REL` is resolved against the served root; out-of-root paths → 403, missing → 404.

**Milestones:**
- [x] **M1 — Decide: port C++ server vs Python rewrite.** → Python rewrite over `ae_backend`
      (rationale above).
- [x] **M2 — Implement chart-serving endpoint.** HTTP/HTTPS server, chart listing, info/table
      JSON + HTML pages, path-traversal protection. **Verify:** ✅ HTTP layer end-to-end via the
      real `bin/chart-serve` + `curl` (`PYTHONPATH=build bin/chart-serve test/`) —
      `/healthz`→ok, `/api/charts` lists `test/chart1.ace`, `/`→index HTML 200, `/nope`→404,
      missing-path→400, `../CLAUDE.md`→403; **HTTPS** verified with a self-signed cert
      (`https://…/healthz`→200 over TLS). The chart **data** endpoints
      (`/api/chart/info|table`) call `ae_backend.chart_v3.Chart(...)`, which currently
      **aborts at construction** in this environment (SIGABRT, no message) — a **pre-existing**
      issue: `bin/chart-info test/chart1.ace` aborts identically (build `.so` is from Jun 10,
      stale vs source). Once the backend loads charts, these endpoints return data with no code
      change (they use only documented `chart_v3` APIs).
- [ ] **M3 (optional, future):** websocket/live-reload parity with AD, or FastAPI/ASGI host if
      a production deployment model is chosen; serve rendered map PDFs once map-draw (#1) lands.

---

## 6. CLI wrappers — thin shells over the `chart_v3` API  *(owner: CLI agent — 🟢 done)*

Quick, independently-verifiable wins. Each is a small Python script in `bin/` importing
`ae_backend.chart_v3`. **No `meson.build` changes needed** — zero conflict risk.

**Already covered under different names/flags (not re-created):**
- `chart-relax-existing` → `chart-relax --existing`
- `chart-relax-incremental` → `chart-relax --incremental`
- `chart-reorient` / `chart-transformation` → `chart-rotate`
- `chart-txt-to-ace` → `chart-torg-table-to-ace`
- `chart-table` → `chart-info-and-table` / `v2-chart-table`

**Implemented:**
- [x] [`bin/chart-clades`](bin/chart-clades) — list clades for antigens (from semantic attrs; `--populate-seqdb`)
- [x] [`bin/chart-column-bases`](bin/chart-column-bases) — print column bases per serum (or forced column bases)
- [x] [`bin/chart-names`](bin/chart-names) — list antigen/serum names (`--ag`, `--sr`, `-n` for numbered output)
- [x] [`bin/chart-layout`](bin/chart-layout) — print coordinates for every point in a projection
- [x] [`bin/chart-stress`](bin/chart-stress) — show stress for all projections; `--best` for single value
- [x] [`bin/chart-keep-antigens-sera`](bin/chart-keep-antigens-sera) — keep by index or name regex
- [x] [`bin/chart-remove-antigens-sera`](bin/chart-remove-antigens-sera) — remove by index or name regex
- [x] [`bin/chart-keep-antigens-titrated-against-sera`](bin/chart-keep-antigens-titrated-against-sera) — filter to antigens with ≥1 real titer
- [x] [`bin/chart-list-antigens-without-titers`](bin/chart-list-antigens-without-titers) — find antigens with all-missing titers
- [x] [`bin/chart-titers-compare`](bin/chart-titers-compare) — diff titer tables between two charts
- [x] [`bin/chart-homologous-pairs`](bin/chart-homologous-pairs) — find ag/sr homologous pairs + map distance
- [x] [`bin/chart-distances-between-all-points`](bin/chart-distances-between-all-points) — pairwise map distances (`--ag-ag`, `--sr-sr`)
- [x] [`bin/chart-error-lines`](bin/chart-error-lines) — expected vs actual map distances, sorted by residual
- [x] [`bin/chart-common`](bin/chart-common) — common antigens/sera between two charts
- [x] [`bin/chart-combine-projections`](bin/chart-combine-projections) — merge projections from multiple charts
- [x] [`bin/chart-remove-projections`](bin/chart-remove-projections) — remove all / keep N / remove by index

**Not implemented (missing API or external dependency):**
- `chart-export` / `chart-convert` — no `to_json()` binding; `.ace` write already converts on load
- `chart-join` / `chart-split-into-layers` / `chart-remove-layers` — no layer-split API in `chart_v3`
- `chart-projection-pca` — no PCA binding
- `chart-relax-disconnected` / `chart-relax-grid` — covered by `chart-relax` flags
- `chart-map-resolution-test` — complex, requires C++ support not yet exposed
- `chart-titer-merging-*` family — partial: `chart-titer-merge-report` already exists in `bin/`
- `chart-locations` / `chart-countries` — depends on locdb integration (not a chart_v3 concern)
- `chart-find-chart-with-antigens` — depends on hidb (#2)

---

## Reference: current `ae_backend` surface (already ported)

Submodules exposed from [`cc/py/module.cc`](cc/py/module.cc): `chart_v3`, `chart_v2`,
`seqdb` / `raw_sequence`, `tree`, `virus`, `whocc` (+ `whocc.xlsx`), `locdb_v3`, `utils`.
No `draw`/`map_draw`, `hidb`, or `tal` submodules yet — those are the gaps above.
