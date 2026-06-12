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
| 2 | **hidb** (historical influenza DB) | `hidb-5` | ~4,600 | `cc/hidb/` | *(hidb agent)* | 🟡 in progress |
| 3 | **TAL** (phylo tree drawing / signature pages) | `acmacs-tal` | ~10,700 | `cc/tal/` (port plan only) | *(tal agent)* | ⚪ blocked on #1 — M1 explore done |
| 4 | **ssm-report** (seasonal report, Python+LaTeX) | `ssm-report` | ~8,900 | `py/ae/report/` (new) | *(report agent)* | 🟡 in progress — assembly core ported; figures blocked on #1 |
| 5 | **webserver** (HTTPS chart serving) | `acmacs-webserver` | ~2,100 | `py/ae/webserver/` (Python rewrite) | *(webserver agent)* | 🟡 in progress |
| 6 | **CLI wrappers** (thin shells over `chart_v3` API) | various `bin/chart-*` | small | `bin/` | CLI agent | 🟡 in progress |

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

## 1. Map drawing  *(owner: map-draw agent — M1 done, M2 next)*

The single biggest gap. As of M1, `ae` **can render a basic antigenic map to PDF**.
`cc/draw/` previously held only geometry/color *primitive headers*; it now also has a
Cairo PDF surface, and `cc/map-draw/` has the renderer + CLI.

- **AD source:** `~/AC/eu/AD/sources/acmacs-draw` (Cairo backend) and
  `~/AC/eu/AD/sources/acmacs-map-draw` (map render + the `mapi` settings DSL).
- **Build deps:** Cairo (`/opt/homebrew/opt/cairo`) — linked into the `chart-draw` target
  only (not libae/ae_backend). Pango (`/opt/homebrew/opt/pango`) needed at M3 for text.
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
- [ ] **M2 — Full styling + reusable surface.** Drive per-point fill/outline/size/shape
      from the chart plot-spec (`legacy::PlotSpec`, resolving `ae::draw::v2::Color` strings
      → RGB); correct draw order (sera, then antigens, selected on top). **Also generalise
      `CairoPdf` into a reusable `ae::draw::Surface`** (lines, paths, set-color/line-width,
      sub-surfaces) — TAL (#3) Phase B is blocked on this shared API, so design it with
      that consumer in mind.
- [ ] **M3 — Text:** Pango integration for point labels and titles (unblocks TAL labels).
- [ ] **M4 — Decorations:** legends, serum circles, connection lines, blobs.
- [ ] **M5 — `mapi` settings DSL:** the JSON-driven mod-applicator pipeline.
- [ ] **M6 — SVG/PNG surfaces** in addition to PDF.

> **Build gotcha (affects every agent who edits `meson.build`):** any edit triggers a full
> meson regenerate, which re-runs the vendored `lexy` CMake subproject. Homebrew CMake is
> now 4.x and rejects `lexy`'s bundled `cmake_minimum_required(<3.5)`. Export
> **`CMAKE_POLICY_VERSION_MINIMUM=3.5`** before `ninja` to get past it.

---

## 2. hidb — historical influenza database  *(owner: hidb agent — 🟡 in progress)*

Needed for reference-antigen and vaccine identification, and is a dependency for several
chart tools (e.g. `chart-find-chart-with-antigens`, vaccine styling in map-draw M4).

- **AD source:** `~/AC/eu/AD/sources/hidb-5` (+ `acmacs-whocc-data` reference data).
- **AD tools to reach parity with:** `hidb5-find`, `hidb5-vaccines-of-chart`,
  `hidb5-reference-antigens-in-tables`, `hidb5-dates`, `hidb5-first-table-date`,
  `hidb5-antigens-sera-of-chart`, `hidb5-stat`, `hidb5-make`, `hidb5-convert`.
- **ae target:** `cc/hidb/` (empty stub) + a `hidb` submodule in `ae_backend`.

**Milestones:**
- [ ] First task: explore `hidb-5` and document the on-disk DB format + the data files
      it reads (where AD finds them via `$HIDB_V5`).
- [ ] Port the DB reader (load + lookup antigen/serum by name).
- [ ] Port "find tables containing antigen", "dates", "vaccines of chart".
- [ ] pybind binding + `bin/` wrappers. **Verify:** identify reference antigens and
      vaccine strains in a known chart, matching AD output.

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
- [ ] **Phase A (unblocked, headless):** port JSON tree I/O, layout numbering/ladderize,
      aa-transition labelling, time-series/clade computation — reusing `cc/tree/`.
      Verifiable against AD `tal` `.json`/`.names` output without Cairo.
- [ ] **Phase B (BLOCKED on #1 ≈M3):** agree a shared `ae::draw::Surface`, then port
      `DrawTree` → column elements → title/legend/aa-transition draw paths.
- [ ] Port tree layout (node positions) reusing `cc/tree/`.  *(folded into Phase A)*
- [ ] Port the draw path onto the shared Cairo surface.  *(Phase B)*
- [ ] Signature-page composition (`AntigenicMaps` — also needs map render + hidb #2).

---

## 4. ssm-report — seasonal report generation  *(unclaimed)*

Python + LaTeX seasonal/SSM report generation.

- **AD source:** `~/AC/eu/AD/sources/ssm-report` (Python + LaTeX templates).
- **ae target:** new `py/ae/report/`.
- **Depends on:** map-draw (#1) for the figures it embeds. Can scaffold the Python/LaTeX
  templating independently, but end-to-end output needs map PDFs.

**Milestones:**
- [ ] Explore `ssm-report`; list the report sections and their data inputs.
- [ ] Port the LaTeX templates + the Python orchestration to `py/ae/report/`.
- [ ] Wire to `ae_backend` chart/map APIs. **Verify:** generates a PDF report from a
      sample dataset.

---

## 5. webserver — HTTPS chart serving  *(unclaimed)*

- **AD source:** `~/AC/eu/AD/sources/acmacs-webserver`.
- **ae target:** new `cc/webserver/` (or a thin Python service — evaluate first whether a
  modern Python/ASGI front-end over `ae_backend` is simpler than porting the C++ server).
- **Note:** smallest subsystem; lowest priority. Confirm the intended deployment model
  before committing to the C++ port vs a Python rewrite.

**Milestones:**
- [ ] Decide: port C++ server vs Python rewrite over `ae_backend`.
- [ ] Implement chart-serving endpoint. **Verify:** serves a chart over HTTP locally.

---

## 6. CLI wrappers — thin shells over the `chart_v3` API  *(unclaimed, low-risk)*

Quick, independently-verifiable wins. Each is a small Python script in `bin/` importing
`ae_backend.chart_v3`. **No `meson.build` changes needed** — lowest conflict risk, good
for a parallel agent.

**Already covered under different names/flags (do NOT re-create):**
- `chart-relax-existing` → `chart-relax --existing`
- `chart-relax-incremental` → `chart-relax --incremental`
- `chart-reorient` / `chart-transformation` → `chart-rotate`
- `chart-txt-to-ace` → `chart-torg-table-to-ace`
- `chart-table` → `chart-info-and-table` / `v2-chart-table`

**Genuinely missing (confirm underlying `chart_v3` support before writing each):**
- [ ] `chart-clades`
- [ ] `chart-column-bases`
- [ ] `chart-names`
- [ ] `chart-layout`
- [ ] `chart-stress` / `chart-stresses`
- [ ] `chart-export` / `chart-convert`
- [ ] `chart-keep-antigens-sera` / `chart-remove-antigens-sera`
- [ ] `chart-keep-antigens-titrated-against-sera`
- [ ] `chart-list-antigens-without-titers`
- [ ] `chart-titers-compare` / `chart-titers-replace`
- [ ] `chart-homologous-pairs`
- [ ] `chart-distances-between-all-points`
- [ ] `chart-error-lines`
- [ ] `chart-common`
- [ ] `chart-join` / `chart-split-into-layers` / `chart-remove-layers`
- [ ] `chart-combine-projections` / `chart-remove-projections`
- [ ] `chart-projection-pca`
- [ ] `chart-relax-disconnected` / `chart-relax-grid`
- [ ] `chart-map-resolution-test`
- [ ] `chart-titer-merging-*` family
- [ ] `chart-locations` / `chart-countries` (depends on locdb)
- [ ] `chart-find-chart-with-antigens` (depends on hidb, #2)

> Caveat: a missing CLI does not always mean missing capability — the core `chart_v3`
> API may already support it. The first step for each is a quick check of the pybind
> bindings (`cc/py/chart-v3*.cc`) before writing the wrapper.

---

## Reference: current `ae_backend` surface (already ported)

Submodules exposed from [`cc/py/module.cc`](cc/py/module.cc): `chart_v3`, `chart_v2`,
`seqdb` / `raw_sequence`, `tree`, `virus`, `whocc` (+ `whocc.xlsx`), `locdb_v3`, `utils`.
No `draw`/`map_draw`, `hidb`, or `tal` submodules yet — those are the gaps above.
