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
| 1 | **Map drawing** (Cairo render engine + map-draw) | `acmacs-draw` + `acmacs-map-draw` | ~31,000 | `cc/draw/`, `cc/map-draw/` | *(map-draw agent)* | ⚪ **SHELVED** — maps already done in **kateri** (Dart, separate repo). `cc/map-draw/` is redundant; `cc/draw/cairo-surface.*` is **kept** (TAL #3 draws trees with it). See §1. |
| 2 | **hidb** (historical influenza DB) | `hidb-5` | ~4,600 | `cc/hidb/` | *(hidb agent)* | 🟢 done — reader + authoring (make/convert/stat), verified |
| 3 | **TAL** (phylo tree drawing / signature pages) | `acmacs-tal` | ~10,700 | `cc/tal/` + `tal-draw` + `py/ae/tal/` | *(tal agent)* | 🟢 feature-complete (core) — tree render; clades / time-series / **dash-bar-aa-at** columns; **leaf colouring by clade / continent / aa-at-pos** + mode-aware legend; title / **aa-transitions** (+ computation — fixed a `cc/tree` stub); **hz-sections**; node select/apply + **positioned `apply.text` labels (DrawOnTree)**; **per-clade `show:false` hiding**; **settings-v3 `.tal` reader** (`tal-signature-page --tal`); signature page = tree + **kateri** map + **WHOCC vaccine** marks. Only low-value tail left (`for-each`, ladderize, `.names`/`.html` outputs) — see [`cc/tal/PORTING.md`](cc/tal/PORTING.md) |
| 4 | **ssm-report** (seasonal report, Python+LaTeX) | `ssm-report` | ~8,900 | `py/ae/report/` (vcm engine consolidated) | *(report agent)* | 🟡 vcm **library tier** in `ae.report` (Phases 0–3 + 1b) — **verified faithful** vs a real later report's vcm (`2026-0223`): `commander`/`download`/`main_loop`/`dirs`/`modules`/`chart_modifier`/`latex` differ only by the deliberate decoupling + warning fixes. **adjust ported** — `ae.adjust` + kateri point-drag. ✅ **ASSEMBLED-REPORT RUN REPRODUCED (capstone)** — the full real `2026-0223-ssm` report builds on `ae.report` (`report.py` → **36-page `report.pdf`, visually identical** to the AD/vcm reference) after a **2-file/3-edit** per-report adaptation (`report.py` + `conference_data.py` → `from ae.report import latex`/`conference_data_base`). Capstone gaps: (a) ✅ **geographic CLOSED** — `geo-draw` + `geographic.make_geo(color_by="coloring")` consume the report's `geographic_coloring` aa/clade `apply` rules (AD `ColoringByAminoAcid` port via seqdb + packed per-antigen dots; built + verified on real H1 hidb); (b) ⚠ **tree DIFFED** vs real bvic/h3 `.tal` — report glue works; of 6 TAL-subsystem gaps, **3 now fixed + built/verified** (canvas→portrait 640×1000, black edges, clade-coloured matrix, + translator nits) and 3 still open (curated `node_id` labels — architectural, ae `.tjz` lacks AD node numbering; full legend; geo inset) — tracked under #3; (c) ✅ **per-report glue DONE**. ✅ **per-map antigenic-map export rewired to `ae.report`+kateri** — all 21 `<subtype>-<lab>/0do` library imports → `ae.report.*` + the 3 subtype modifiers mix in the concrete `ConferenceData`; verified end-to-end via kateri: **h1-cdc** `out.1.clades.pdf` pixel-identical to reference, **bvic-crick** full B clade set correct (surfaced + fixed an `ae.utils.org` ragged-row bug). ✅ **FULL FIGURE REGENERATION on ae against a current hidb** (2026-06-16; hidb refreshed to H1→2026-03/H3→2026/B→2026-04): **19/19** per-map dirs regenerated via kateri (the 2 `-vidrl` needed a `dirs.find_previous_chart` fix — return `None` when a previous report exists but lacks this dir's 2-back chart, instead of raising, matching the caller's "eliminate not found"); maps **pixel-verified vs the pristine original report** (content-identical, <1% differing pixels = anti-aliasing edges, across H1/H3/B + 6 labs); **stat** reproduced (`ae.report.stat` Python `hidb5-stat` port — structurally identical + monotonic superset of the report's, ae≥ref on all 1577 leaves); **geo** reproduced for **all three subtypes H1/H3/B** (`make_geo(color_by="coloring")` — same clade representation; extra dots = real hidb accretion; H3 large at 223–1501 loc/month); then a **fully ae-generated 36-page `report.pdf`** re-assembled from the regenerated figures (maps + trees + geo + `ae.report.latex`). No AD `hidb5-stat`/`geographic-draw`, no `vcm`. **The `ae.report` seasonal report is end-to-end reproducible.** **Remaining:** only TAL tree fidelity (#3) — not an `ae.report` blocker. See [`py/ae/report/MIGRATION.md`](py/ae/report/MIGRATION.md#from-scratch-figure-regeneration-current-hidb) |
| 5 | **webserver** (HTTPS chart serving) | `acmacs-webserver` | ~2,100 | `py/ae/webserver/` (Python rewrite) | *(webserver agent)* | 🟢 done — Python rewrite; HTTP/HTTPS + chart-data endpoints verified end-to-end |
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
8. **No real surveillance data in committed files.** Keep real strain names, titers, serum
   IDs, lab data, and sequences out of source, docs (incl. this file), comments, and test
   fixtures — use synthetic placeholders (e.g. `A(H3N2)/<CITY>/N/YYYY`, `<SERUM_ID>`) or
   clearly-synthetic test data (like `test/chart1.ace`, which uses German-city names in
   rank order). Real DB files (`acmacs-data/…`, locdb/hidb/seqdb) are read-only **inputs**,
   never copied into the repo. When verifying against real data, describe the *result*
   (counts/outcomes), don't paste the data.

---

## 1. Map drawing  *(owner: map-draw agent — antigenic maps ⚪ SHELVED (kateri); geographic `geo-draw` 🟢 done, incl. clade pies)*

> **⚠ COURSE CORRECTION (kateri audit).** Antigenic-**map** drawing is **already implemented
> in `kateri`** (`github.com/drserajames/kateri`, a Dart/Flutter app — its README: *"antigenic
> map viewer and pdf generator"*). It does the semantic-style resolution (`lib/src/plot_spec.dart`
> — the `// implement in kateri!` resolver), interactive viewing, **and headless PDF**
> (`draw_on_pdf.dart`). ae drives it over a socket (`py/ae/utils/kateri.py`: send `CHRT`,
> `set_style`, `pdf`). So the empty `cc/map-draw/` was an **architecture decision (drawing → kateri)**,
> not a porting gap — my original "biggest gap" framing was wrong.
>
> **Consequences:**
> - **`cc/map-draw/`** (`draw.cc`/`draw.hh`/`chart-draw-main.cc` + the `chart-draw` target) was
>   **redundant** with kateri → **removed from this branch** (`ad-port`). The full M1–M4 code is
>   **preserved on the `map-draw-shelved` branch** (`drserajames/map-draw-shelved`) if ever needed
>   as a headless fallback. The M1–M4 milestone notes below are kept here for history.
> - **`cc/draw/cairo-surface.*` is KEPT and is shared infrastructure.** kateri does **not** draw
>   trees, so TAL (#3) renders trees in C++ using this exact surface — `cc/tal/draw-tree.cc`
>   already `#include`s it and calls `pdf.line()/text()/background()`. The Cairo work was *not*
>   wasted; only the map-specific renderer was.
> - Other subsystems audited against kateri: **hidb / ssm-report / webserver are NOT in kateri**
>   → they remain legitimate ae-side work. Only map-draw was already done there.
> - **"Maps live in kateri" means *antigenic* maps only.** kateri has **no** geographic/world-map
>   code (zero `geograph`/`continent`/`coastline` hits in `kateri/lib`). **Geographic maps are
>   NOT a kateri job** and remain a genuine **ae-side C++ Cairo renderer still to build** — see
>   "Remaining ae-side map drawing" below. Don't over-apply the kateri framing to them.

The C++ **antigenic**-map renderer (its M1–M4 milestones and code) has been **removed from this
branch** — it lives on **`map-draw-shelved`** (`drserajames/map-draw-shelved`) if ever needed as a
headless fallback. `cc/draw/cairo-surface.*` graduated out of it into shared `cc/draw/`
infrastructure (used by TAL #3 and the geographic renderer below). What remains under map-draw on
`ad-port` is the geographic renderer:

### Remaining ae-side map drawing — **geographic time-series maps** *(map-draw agent — in progress)*

The *one* piece of "map drawing" that genuinely belongs in ae C++ (kateri does not do it).
Needed by **ssm-report #4** for its `geographic_ts` pages (`geo/<VT>-geographic-<YYYY-MM>.pdf`).
New code lives in **`cc/geo/`** + the **`geo-draw`** CLI; reuses the shared `cc/draw/cairo-surface.*`.

- [x] **Slice 1 — world base map.** Ported AD's baked equirectangular continent outline
      (`acmacs-draw/geographic-path.cc`, CC BY-SA) → [`cc/geo/geographic-path.cc`](cc/geo/geographic-path.cc)
      under `ae::geo`. Added a `path_negative_move()` primitive to `cc/draw/cairo-surface.*`
      (negative-x = move-to / positive = line-to). [`cc/geo/geographic-map.cc`](cc/geo/geographic-map.cc)
      fits the path bbox to a ~2:1 canvas and draws filled land + coastline; **`geo-draw <out.pdf>
      [width]`** CLI. **✅ Verified:** `geo-draw /tmp/world.pdf 1200` → recognizable world map
      (all continents incl. Antarctica + islands; rasterised and eyeballed).
- [x] **Slice 2 — plot located points.** `export_geographic_pdf()` now fits the full
      `geographic_map_size` rectangle (so path + points share one transform) and plots each
      `GeoPoint` via an equirectangular lon/lat→path-coord map over `geographic_map_bounds`
      (lon spans exactly 360°). `geo-draw --point lon,lat` (repeatable). **✅ Verified:** 8
      cities (Anchorage/NYC/London/Tokyo/Rio/Cape Town/Singapore/Sydney) land exactly on
      their landmasses; rasterised and eyeballed.
- [~] **Slice 3 — data integration.**
      - [x] **locdb + continent colour.** `geo-draw --location NAME` resolves via `locdb_v3`
            (`get().find()` → lat/long + `continent(country)`) and plots a continent-coloured
            dot; `ae::geo::continent_color()` ports AD's palette. **✅ Verified** (LOCDB_V2 =
            `acmacs-data/locationdb.json.xz`): London/NYC/Tokyo/Moscow/Sydney/Cairo/Buenos
            Aires/Delhi land correctly and are coloured by continent; rasterised and eyeballed.
      - [ ] seqdb/hidb per-location counts; pies for multi-category counts (deferred to Slice 4
            with the data source, since counts come from the same sequence/chart input).
- [x] **Slice 4 — time series + count sizing.** `geo-draw --data records.json --prefix <p>`
      reads `{title_prefix, periods:[{period, locations:[{name,count}]}]}` (rjson::v3), and
      writes one PDF per period named **`<prefix><period>.pdf`** (matches `make_geographic_ts`).
      Dots sized by √count, coloured by continent; per-map title. **✅ Verified:** a 2-month
      dataset renders `H3-geographic-2024-01.pdf` / `-2024-02.pdf` correctly (placement, sizes,
      continent colours, titles); rasterised and eyeballed.
- [x] **Slice 5 — clade/lineage pies.** A location can now be drawn as a **pie chart** (wedges
      sized by per-category count, coloured by category) instead of only a continent-coloured dot.
      - **Surface primitive:** added `CairoPdf::sector(cx,cy,radius,start_angle,end_angle,outline,
        outline_width,fill)` to the shared `cc/draw/cairo-surface.*` (Cairo `arc`+`line_to`-to-centre;
        angles clockwise from 12 o'clock). Additive — no existing signature changed (TAL #3 safe).
      - **Pie `GeoPoint`:** `GeoPoint` gained an optional `std::vector<GeoWedge>{count,color,label}`;
        empty ⇒ the existing single-dot path (unchanged). When present, `geographic-map.cc` draws one
        sector per wedge clockwise from 12 o'clock (angle ∝ count), total radius still √(Σcount)-scaled,
        each wedge outlined. Added `clade_color()` (stable FNV-hashed palette) + a lower-left clade
        **legend** (`LegendEntry` list, new optional arg to `export_geographic_pdf`).
      - **JSON + CLI:** the `--data` schema now accepts per-location
        `"categories":[{"name","count","color"?}]` (flat `"count"` still works → continent dot).
        Category→colour is stable across all periods of a run (first-seen order, optional per-category
        `"color"` override); legend drawn whenever any pies are present.
      - **✅ Verify:** `sh cc/geo/test/test-geo-pie.sh` (synthetic `cc/geo/test/pie-records.json`)
        renders `/tmp/geo-pie-test-2024-{01,02}.pdf` — pies sized/ordered by count, stable per-clade
        colours, forced-red `3C.3a`, SYDNEY stays a single continent dot, legend lower-left. **Built +
        eyeballed 2026-06-14** (report agent). *(One minor palette nit: the auto palette can collide
        with an explicit override colour — e.g. two reds — worth avoiding claimed-override colours.)*
- [x] **Slice 6 — report-faithful aa/clade coloring (`color_by="coloring"`).** geo-draw now also
      reproduces AD `geographic-draw -s settings.json`: one dot per antigen, packed in AD's
      concentric rings, coloured by the report's `geographic_coloring` `apply` rules. Added per-point
      `GeoPoint::outline_width`; `CairoPdf::circle()` skips the stroke on transparent/zero outline;
      `geo-draw-main.cc` parses per-location `"points":[{color,outline,outline_width,count}]` +
      top-level `point_size`/`density` + per-period `"title"`, and packs via `pack_colored_points()`
      (port of AD `GeographicMapWithPointsFromHidb::prepare`). The rule engine + seqdb match live on
      the report side (`_Coloring` in `py/ae/report/geographic.py`). **✅ Built + verified** on real
      H1 hidb (Dec 2023): clade palette correct, packed clusters, month-name title. (Closes #4 gap a.)
- **🟢 geo-draw renderer complete** for the report's needs (base map · lon/lat points · named
  locations · monthly count series · **clade/lineage pies + legend**). **Remaining is on the report
  side (#4):** the Python glue extracts per-month `{location, count}` (continent) or
  `{location, categories:[{clade,count}]}` (clade) and writes the `--data` JSON
  (`py/ae/report/geographic.py`, `make_geo(..., color_by=…)`). geo-draw is the renderer; data
  extraction is the report's job (ae-idiomatic split, mirrors tal-draw / kateri).
  The AD `-s settings.json` coloring-rule DSL is now consumed report-side via
  `make_geo(color_by="coloring", colorings={subtype: geographic_coloring(subtype)})` (Slice 6).

> **Build gotcha (affects every agent who edits `meson.build`):** any edit triggers a full
> meson regenerate, which re-runs the vendored `lexy` CMake subproject. Homebrew CMake is
> now 4.x and rejects `lexy`'s bundled `cmake_minimum_required(<3.5)`. Export
> **`CMAKE_POLICY_VERSION_MINIMUM=3.5`** before `ninja` to get past it.

> **✅ FIXED (Jun 12) — `chart_v3.Chart(<file>)` heap-corruption / SIGABRT.**
> Root cause was a two-part issue:
>
> **1. simdjson `iterate` API misuse in `cc/ext/simdjson.hh`** — the old code called
> `parser_.iterate(json_, json_.size() + SIMDJSON_PADDING)`, telling simdjson the buffer had 64
> extra readable bytes when it often didn't (XZ decompressor uses `reserve` + `resize` which
> doesn't guarantee retained extra capacity). simdjson stage1 then read 64 bytes past the valid
> data, corrupting adjacent heap allocations — specifically the `Timeit::message_` string's
> buffer pointer, causing malloc to abort in `Timeit::~Timeit()`. **Fix:** changed to
> `parser_.iterate(json_)` (the `iterate(std::string&)` overload) which calls
> `pad_with_reserve()` internally — this actually calls `json_.reserve(size + SIMDJSON_PADDING)`
> if needed, so the extra bytes are genuinely allocated before simdjson reads them.
>
> **2. simdjson 2.0.4 ARM64 NEON bug** — the ARM64 stage1 `bit_indexer::write()` always wrote
> 8 entries at a time regardless of valid count, overflowing the bit_array buffer on certain JSON
> lengths. **Fix:** updated `subprojects/simdjson.wrap` from 2.0.4 → 4.2.2 (tarball at
> `/tmp/simdjson-4.2.2.tar.gz`, SHA256
> `3efae22cb41f83299fe0b2e8a187af543d3dda93abbb910586f897df670f9eaa`).
>
> **⚠ Editable-install shadowing** — `PYTHONPATH=build` does NOT override a `pip install -e`
> of ae_backend from another checkout (`/Users/sarahjames/AC/projects/ae-backend/`). The Python
> site-packages `.pth` file wins. All `bin/` scripts that do bare `import ae_backend` will load
> the wrong module. Use `importlib.util.spec_from_file_location` (the pattern in
> `bin/_hidb_boot.py`) to load by explicit path. The standard `bin/chart-info` script is
> **still broken** for this reason until the editable install is removed or the scripts are
> updated. **Verified fix:** 6/6 `chart_v3.Chart('test/chart1.ace')` loads succeed loading the
> Jun-12 21:12 `ae_backend.so` by explicit path.

> **Note (earlier false diagnoses):** prior agents attributed the crash to a "transient build
> race" or "staleness". Those reports loaded the editable-install `.so` which appeared to work
> because it was a different (older) build that didn't trigger the bug. The crash was real.

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
- [x] [`cc/hidb/hidb-maker.{hh,cc}`](cc/hidb/hidb-maker.hh) (`ae::hidb::HidbMaker`) +
      `HiDb::save()` + a shared `ae::hidb::to_json()` serialiser; wired into `meson.build`
      (`sources_hidb`).
- [x] pybind: `hidb.make(chart_files, output, stop_on_error)` + `HidbMaker` + `HiDb.save`;
      `bin/hidb-make`, `bin/hidb-convert`.
- [x] `bin/hidb-stat`. **✅ Verified** (arm64 build): built a small hidb from several real
      charts — cross-chart **dedup** works (N charts × ~M antigens collapse to fewer unique),
      dates/lab_ids accumulate, antigen↔table links and serum **homologous** antigens are
      correct, and `reference_antigens` matches on the built DB; `hidb-convert` round-trips
      (xz→plain→reload) with identical counts and valid hidb-v5 JSON.

**Fidelity note:** like AD, a table's `a`/`s` index lists are sorted by global index while
its `t` titers stay in source-chart order (so titer rows are not aligned with the sorted
`a`/`s` — matches AD output; reader queries don't depend on titer alignment). `ae::chart::v3::Info`
has no `subset`, so the table `s`(subset) field AD overwrote with the sera array anyway is
simply omitted.

- [x] `bin/hidb-first-table-date` — per antigen: isolation date, oldest (first) hidb table
      date, AD's "Days" value, country, lab id, lineage; one CSV per subtype+lab+assay tag
      (`db.oldest_table()` + `Antigen.country()`). **Reproduces AD's `Days` logic bug-for-bug**
      (deliberately, for drop-in compatibility with downstream consumers — owner's call):
      `days = isolation.ok() ? -1 : days_between(invalid_date, first_table_date)`, displayed as
      `days>=0 ? str : ""`. So a *valid* isolation date yields a **blank** Days cell, and a
      missing/invalid one yields AD's large constant-offset number (`sys_days(first_table_date)
      − sys_days(year{0}/0/0)`, the latter == −719560 via Hinnant's `days_from_civil`, verified
      against acmacs-base `date.hh`). The only AD behaviour not copied is its *throw* on a
      literally empty date string (a crash, not a column value) — empty just takes the else
      branch here. **✅ Verified** on real H3 data: dated antigens blank, date-less antigens
      emit the AD offset numbers; constant and arithmetic checked.

- [x] **B hidb loader fix (`STRING_ERROR`).** AD-generated `hidb5.b.json.xz` encodes CJK
      location names with invalid capital-`\U` escapes (e.g. `"\U6E56\U5357"` for 湖南)
      instead of JSON `\u`; simdjson rejected the whole file with `STRING_ERROR`, so `B`
      wouldn't load while H1/H3 (no CJK names) did. `HiDb` ctor now reads + decompresses the
      file, rewrites `\U`→`\u` in-buffer (escape-aware, leaves `\\U` alone), then parses.
      Data files untouched (read-only inputs). **✅ Verified:** `hidb("B")` → 81661 antigens
      and CJK names decode (`B/湖南南县/31/2008`); H1/H3 unchanged (55497 / 95251).

All AD hidb-5 tools are now ported.

---

## 3. TAL — phylogenetic tree drawing / signature pages  *(owner: tal agent — 🟢 feature-complete (core); only low-value tail left)*

`ae` already has tree **manipulation** (Newick parse, fix-names, substitution-labels,
to-json in `cc/tree/`). Missing: the tree **drawing** / signature-page / time-aware
lineage output.

- **AD source:** `~/AC/eu/AD/sources/acmacs-tal`.
- **AD tool:** `tal`.
- **ae target:** `cc/tal/` — see [`cc/tal/PORTING.md`](cc/tal/PORTING.md) (full architecture
  map + phased port order, produced by milestone 1).
- **Depends on:** the Cairo backend from subsystem #1 (shares the draw surface). Best
  started after map-draw M1–M3 land, or coordinate on the `cc/draw/` surface API.

**✅ Blocker RESOLVED — and TAL now *owns* the C++ draw surface.** The original blocker
(TAL drawing needs a surface) is moot: TAL Phase B M1 already renders trees → PDF using
`ae::draw::CairoPdf` directly (`cc/tal/draw-tree.cc` includes `draw/cairo-surface.hh` and
calls `pdf.line()/text()/background()`). Crucially, the **map-draw subsystem #1 is shelved**
(maps live in kateri — see §1), so **`cc/draw/cairo-surface.*` is now shared infrastructure
that TAL is the primary consumer of, not a map-draw deliverable.** TAL should drive any future
surface additions it needs (Phase B M2+ wants *filled rectangle* and *rotated text* — add them
to `cc/draw/cairo-surface.*` directly; no map-draw coordination required since #1 is dormant).
The `ae::draw::Surface` abstraction remains optional/deferred. NOTE: `AntigenicMaps`
signature-page panels still need *map* rendering — get those map PDFs from **kateri**, not a
C++ renderer; TAL composes them with the tree.

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
- [x] **Phase A (remaining, headless):** aa-transition labelling — reconciled and the
      `cc/tree/aa-transitions.cc` consensus stub implemented; hz-sections — done (drawing).
- [x] **Phase B M1 — tree → PDF.** `ae::tal::export_tree_pdf` in
      [`cc/tal/draw-tree.cc`](cc/tal/draw-tree.cc) + the **`tal-draw`** CLI (port of
      acmacs-tal `DrawTree::draw`: edge segments + inode connectors, optional leaf labels).
      Reuses `compute_layout` + the `CairoPdf` surface from #1; Cairo linked only into the
      `tal-draw` target. **Verify:** `sh cc/tal/test/test-draw-tree.sh` → `OK …` (20-leaf
      tree also rasterised & eyeballed). *Used CairoPdf directly; the `ae::draw::Surface`
      abstraction is deferred (lowest-conflict while map-draw evolves CairoPdf) — see PORTING.md.*
- [x] **Phase B M2 — coloring + aligned columns.** `export_tree_pdf` takes
      `TreeDrawParameters`; draws leaf coloring by clade, a **clades column** (bars per
      section) and a **time-series dash column** (per-leaf dashes in date-bucket slots),
      all aligned to leaf rows. Reuses `compute_clade_sections` + `compute_time_series`
      (Phase A). CLI: `--color-by-clade --clades --time-series --interval=…`. Done with only
      the existing `line()`/`text()` primitives — **no `CairoPdf` change**. **Verify:**
      `sh cc/tal/test/test-draw-tree.sh`; 24-leaf 3-clade tree rasterised & eyeballed.
- [x] **Phase B M3 — title + legend + aa-transitions + rotated slot labels.** Added
      `CairoPdf::rectangle()` + `text_rotated()` to the shared surface, then drew a centred
      title (`--title=`), a clade legend (`--legend`), inode aa-transition labels
      (`--aa-transitions`, ports `DrawAATransitions`), and rotated year/month slot labels.
      **Verify:** `sh cc/tal/test/test-draw-tree.sh`; 24-leaf aa-annotated tree rendered as a
      full signature-page-style figure & eyeballed.
- [x] **Phase C M1 — declarative JSON settings.** `ae::tal::load_draw_settings()` in
      [`cc/tal/settings.cc`](cc/tal/settings.cc) + `tal-draw --settings=FILE`. Maps a JSON
      config onto `TreeDrawParameters` (parsed with `rjson::v3`), adding per-clade
      `color`/`display_name` overrides + time-series `start`/`end` that flags can't express —
      a bounded alternative to porting AD's full 71 KB settings-v3 mod pipeline. **Verify:**
      `sh cc/tal/test/test-draw-tree.sh` (settings case); override colours/names eyeballed.
- [x] **Phase C M2 — node select/apply mods.** `"nodes": [{select, apply}]` in the JSON
      config: select by `seq_id`/`cumulative_min`/`date_min`/`date_max`, apply
      `hide`/`edge_color`/`label_color`/`label_scale` (parsed in `settings.cc`, resolved via
      per-node override maps + pre-layout hide in `draw-tree.cc`). **Verify:**
      `sh cc/tal/test/test-draw-tree.sh` (node-mods case); eyeballed (hide + recolour + relabel).
- [x] **Label-collision avoidance.** Greedy top-to-bottom vertical non-overlap on the leaf-label
      column (forced labels from node mods always shown); on by default, `--labels-overlap`
      disables; `export_tree_pdf` returns the hidden count (CLI surfaces it). **Verify:**
      250-leaf tree hid 125/250 labels; eyeballed off (smear) vs on (clean).
- [x] **`AntigenicMaps` signature-page composition.** `bin/tal-signature-page` +
      `py/ae/tal/signature_page.py`: composes the TAL tree (left) + antigenic map(s) (right)
      into one signature-page PDF via `pdfjam` — the PDF the report's `signature_page` page
      embeds. Maps from `--map` (pre-rendered) or `--chart` (kateri over its socket); `--mark`
      highlights vaccine/reference strains on the tree (node-mods, the hidb hook). **Verify:**
      `sh cc/tal/test/test-signature-page.sh` (`--map` path); **and verified live end-to-end
      with kateri** — optimized `test/chart1.ace` → kateri map → tree+map signature page,
      rasterised & eyeballed. (kateri is a Flutter GUI app: launched via `open -n -a
      kateri.app --args --socket …`; the `--chart` path needs `ae_backend`, so run under
      arm64 python3.10.)
- [x] **`--mark-vaccines` (WHOCC vaccine strains) — real-data verified.** Reads
      acmacs-data's `semantic_vaccines.py` (`sData[subtype]`, the modern `vaccines.json`),
      matches against leaf seq_ids, marks them. **Verify:** `cc/tal/test/test-mark-vaccines.py`
      (synthetic); one-off on the real 38k-leaf bvic tree matched 7 BV vaccine leaves and rendered
      a signature page (vaccines red + kateri map) — eyeballed. Live kateri now also covered by
      the opt-in `cc/tal/test/test-signature-page-kateri.sh` (`TAL_TEST_KATERI=1`).
- [x] **`--mark-reference` (hidb reference antigens) — built; 0 hits on current trees.**
      `get_reference_antigen_names` (union of `HiDb.reference_antigens` over recent tables,
      `name_without_subtype`) + multi-colour mark groups (vaccines red / references blue). Honest
      finding: hidb references are older anchor strains, so on a current-season tree they match 0
      (expected — vaccines match because they're recent). Mechanism verified via the shared
      `match_leaves_by_name`.
- [x] **`hz-sections`** (left marker column: bracket + label per section, separator across the
      tree). Verified `sh cc/tal/test/test-draw-tree.sh` (hz-sections case).
- [x] **aa-transition *computation*** (`--aa-transitions-compute` + `min_leaves`). **Required
      fixing a `cc/tree` stub** — the consensus `set_transitions` in `cc/tree/aa-transitions.cc`
      was commented out (computed 0). Implemented it; `cc/tal/test/test-aa-transitions.py` →
      `T3A`.
- [x] **`DrawOnTree` positioned labels** (`apply.text` → `NodeText` at a leaf tip) **and per-clade
      `show:false` hiding** (`clade_styles[].hide` suppresses a clade's bar+label from the column/
      legend, leaves kept) — wired through `draw-tree.{hh,cc}` / `settings.cc` / settings-v3 reader;
      `sh cc/tal/test/test-draw-tree.sh` + PDF-text check.
- [x] **Continent / aa-pos leaf colouring** — `leaf_color` resolves aa-at-pos > continent > clade >
      black; continent palette ported; aa-pos by explicit colours or frequency; mode-aware legend.
      CLI `--color-by-continent` / `--color-by-pos=N`, settings `color_by_continent` / `color_by_pos`,
      settings-v3 `{"N":"tree","color-by":…}`. `sh cc/tal/test/test-draw-tree.sh` + PDF-text check.
- [x] **`if/then` conditionals + `-D` defines** — settings-v3 reader interprets
      `{"N":"if","condition":…,"then":[…],"else":[…]}` (full `eval_condition` grammar:
      `$var`/`and`/`or`/`not`/`empty`/`not-empty`/`equal`/`not-equal`); `tal-signature-page` accepts
      bare `-D name` truthy flags. `python3 cc/tal/test/test-settings-v3.py`.
- [x] **Finer signature-page layout** — `compose_grid` (pdflatex) lays the tree + an R×C grid of
      **captioned** maps with an optional page title/tree caption (`--caption` / `--page-title` /
      `--tree-caption` / `--columns`); falls back to the `pdfjam` stack without pdflatex.
      `sh cc/tal/test/test-signature-page-grid.sh`.
- [ ] **Remaining (low-value tail only):** `for-each` loops / `max-edge-length` ladderize / other
      `tal` outputs (`.names`/`.html`). **`clades-whocc` struck** — obsolete in AD (clades assigned
      upstream at tree-build, stored in the `.tjz`, which `tal-draw` reads; persisted relabelling is
      covered by `Tree::set_clades` + `export`).

- [~] **⚠ Report-tree fidelity gaps (from ssm-report #4 (b), diffed 2026-06-15) — owner: tal agent, in progress.**
      Rendering the real report `.tal` (`2026-0223-ssm/tree/{bvic.after-2021,h3.asr.after-2021}.tal`) via
      `ae.report.trees` → `tal-draw` works but the PDFs weren't faithful to the AD `tal` references.
      `tal-draw` references (AD portrait, ae square): `bvic` 631×1000 / `h3` 648×1000 vs ae 1000×1000.
      **Code changes landed AND ✅ built + verified (report agent, 2026-06-15): `tal-draw` rebuilt
      with these changes; re-rendered bvic → 640×1000 portrait (ref 631×1000), black edges,
      clade-coloured matrix, clade-section labels shown; `ae_backend` still imports.** Per-gap:**
      - **#1 canvas aspect — FIXED (code).** `TreeDrawParameters.width_to_height_ratio` + portrait page
        (`export_tree_pdf` now draws width = height × ratio; all X uses `width`/`margin`, Y uses
        `height`/`vmargin`). Translator reads `tree` `width-to-height-ratio` and adds a column allowance
        (clades +0.07, time-series +0.13, dash +0.025 each, hz +0.03, labels +0.10) → bvic≈0.64,
        h3≈0.63 (refs 0.631/0.648). `tal-draw --width-to-height-ratio=` + settings `width_to_height_ratio`.
      - **#3 clade-coloured matrix — FIXED (code, palette approximate).** `clades-whocc` now sets
        `color_by_clade` → time-series dashes + clade column coloured by clade (ae stable palette, not the
        exact WHOCC hex colours — those live in AD's builtin `tal.json`; a refinement).
      - **#6 tree edges black — FIXED (code).** Added `edge_color_for`: clade colouring colours the
        *matrix* but NOT the tree edges (edges stay black; only by-continent/by-pos recolour edges).
        Also removed the aa-transition *flood*: the report `.tal` `draw-aa-transitions` curated `per-node`
        labels were being mistranslated to consensus-`compute=True`, which labelled every inode purple;
        now compute is off and the curated labels are reported as a warning (see #2).
      - **translator robustness — FIXED.** `?`-prefixed string references (e.g. `"?dash-bars"`) skipped
        silently (were recursing into the disabled array); per-leaf name labels now default **off** (the
        trees have 38k/70k leaves; AD shows none). `?`-keyed objects (`{"?N":…}`) already skipped.
      - **#2 draw-aa-transitions positioned labels — OPEN (architectural).** The curated `per-node`
        labels select by AD's draw-time `node_id` ("vertical.horizontal"), which ae's tree does **not**
        carry (it stores a single integer id in the `.tjz`). They cannot be matched without porting AD's
        exact node-numbering; the translator now records "N curated per-node label(s) … skipped". **The
        seq_id-selected `apply.text` labels DO translate** (h3's A/DC, A/SY, A/SP vaccine labels render).
      - **#4 clade legend — PARTIAL.** Clade column draws per-clade names beside its bars; the full
        vertical colour-bar legend is not ported. **#5 geographic map inset — OPEN** (AD builtin/world-map
        legend; not ported).
      - **#7 h1 tree too narrow — OPEN** (found regenerating the real report trees, 2026-06-15). The
        column-width allowance heuristic in `settings_v3` underestimates h1: ae renders h1 **640×1000**
        vs AD **794×1000** (h3 630/648 ✓, bvic 640/631 ✓ are close). h1 carries more aa-transition / wider
        right-hand columns than the fixed per-column allowances assume, so the page comes out too narrow
        (tree is complete + faithful, just doesn't fill the width). Make the allowance reflect the actual
        column set / counts rather than fixed increments.
      - **#8 `nodes.select: {"edge >=": N}` — ✅ DONE** (2026-06-15). `edge_min` wired through
        `settings_v3` (`edge >=`→`edge_min`), `settings.cc`, and `draw-tree.{hh,cc}` (`NodeSelect.edge_min`,
        checked against the node's own edge length); AD uses it to hide long-edge/outlier nodes.
        **Verified:** `cc/tal/test/test-draw-tree.sh` (new `tree-edges.json` case — OUTLIER with edge 5.0
        hidden by `edge_min:1.0`, E1–E3 kept) + `test-settings-v3.py` (translation).
      Files: `cc/tal/draw-tree.{hh,cc}`, `cc/tal/settings.{hh,cc}`, `cc/tal/tal-draw-main.cc`,
      `py/ae/tal/settings_v3.py`. **#1/#3/#6/#8 + translator nits built + verified** (the `?`-disabled-key
      spurious-warning nit also fixed: `_select` now skips `?`-prefixed keys); **#2/#4/#5/#7 open.**
      Original gap list (priority order) retained below:
      1. **Canvas width / aspect** — `tal-draw` renders square; AD computes canvas *width* from the
         tree `width-to-height-ratio` (0.41) + accumulated column (time-series/dash/aa) widths.
         `$canvas-height`=1000 (builtin) already matches; only width is wrong.
      2. **`draw-aa-transitions` positioned labels** (biggest content gap) — `py/ae/tal/settings_v3`
         doesn't translate the `{"N":"draw-aa-transitions", per_nodes:[{name, node_id, label:{offset,…},
         show}]}` section, so the curated on-tree clade/transition labels are missing. tal-draw already
         does positioned `apply.text` (DrawOnTree), so map each entry → `nodes select{node_id}
         apply{text:{text:name, offset, …}}`.
      3. **Clade-coloured time-series / dash-bar matrix** — AD colours matrix cells by clade; ae is
         monochrome black.
      4. **Clade legend** partial vs AD's full vertical colour-bar legend.
      5. **Geographic map inset** (small world map, lower-left) absent (AD builtin/clades-whocc).
      6. **Tree edge colour** — ae draws edges purple (default/clade colouring); AD black.
      - **Translator robustness nits** (`py/ae/tal/settings_v3`): ✅ `?`-disabled keys inside `select`
        objects (e.g. `?cumulative >=`) no longer emit spurious "unsupported criterion" warnings
        (`_select` skips `?`-prefixed keys); `?`-prefixed string program items were already skipped.
        `nodes` with a string `apply` ("report") are skipped (informational; OK).
      The **report side needs no change** — `ae.report.trees` translates + invokes `tal-draw`
      correctly; all of the above is `cc/tal` (layout/rendering) + `py/ae/tal/settings_v3`
      (translation). Reproduce: `make_tree("<tree>.tjz", "<tree>.tal", "/tmp/out.pdf")` with
      `SEQDB_V4`/`AC_CLADES_JSON_V2`/`LOCDB_V2` set; compare to the `.pdf` beside the `.tal`.

---

## 4. ssm-report — seasonal report generation  *(owner: report agent — 🟡 assembly core done)*

> **⚠ Direction change — consolidate around `vcm`, not the AD port.** The team already
> builds reports on `ae` via the **`vcm`** tool (in each report working dir). The plan is to
> shelve this AD-faithful port and bring vcm's library tier into `ae` — full audit + phased
> plan in [`py/ae/report/MIGRATION.md`](py/ae/report/MIGRATION.md). Phase 0 done
> (`report-shelved` branch); `stat.py` is kept (replaces vcm's `hidb5-stat` shell).

Python + LaTeX seasonal/SSM report generation. Note: AD's `bin/ssm-report` and
`commands.py` are marked *obsolete*; the live entry is `ssm-make`/`maker.py`, but the
shared **report-assembly core** (`report.py` + `latex.py`) is what emits the final PDF.

- **AD source:** `~/AC/eu/AD/sources/ssm-report` (Python + LaTeX templates).
- **ae target:** `py/ae/report/` — see [`py/ae/report/README.md`](py/ae/report/README.md)
  (full page-type → data-input table + the dependency boundary, produced by milestone 1).
- **Figures (corrected — NOT map-draw #1):** the antigenic-map figures the report
  embeds come from **kateri** (Dart map viewer/PDF generator), driven over a socket
  via [`py/ae/utils/kateri.py`](py/ae/utils/kateri.py) — **not** the shelved C++
  map-draw #1. Trees come from **TAL** (`tal-draw`, #3). The *assembly* + *scaffolding*
  layers are ported and renderer-independent; what remains is a report-figure
  pipeline (`map.py`/`maker.py`/`geographic.py`/`signature_page.py` + `stat.json.xz`
  writer) rebuilt on kateri + `ae_backend` + TAL.
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
      and the figure-settings half of `init_settings` (part of the not-yet-ported
      figure pipeline). **✅ Verified:**
      scaffolds dirs+templates and writes substituted `report.json`/`setup.json`;
      date logic unit-checked (Northern/Southern season, teleconference, Oct year
      split); the generated 233-page `report.json` round-trips through the assembler
      (`read_json` + `LatexReport` ctor, correct `ts_dates`).
- [x] **Port the `stat.json.xz` counts writer.** `stat.py` (`make_stat_json`/`make_stat`)
      + `bin/ssm-report-stat`: antigen/sera counts by virus-type/lab/date/continent from
      `ae_backend.hidb` + `locdb_v3` (port of AD's C++ `hidb5-stat`). Uses hidb (#2 done) +
      locdb — **not** `chart_v3`, so unaffected by the import-abort bug. **✅ Verified**
      against real H1/H3 hidb: cross-product invariants hold (Σ vt = all, Σ labs = all,
      Σ months = year, `sera_unique` ≥ deduped `sera`) and the output feeds
      `StatisticsTableMaker` to render a real LaTeX table. ✅ **B now loads** — the B hidb
      `STRING_ERROR` (invalid `\U` escapes in `hidb5.b.json.xz`) is fixed in the hidb loader
      (see #2), so the stat writer no longer warn-skips B. (Also surfaced: a latent no-previous-data
      crash in the ported `StatisticsTableMaker`, `report.py` ~L635 — 1 arg to a 2-arg
      macro; only the first-report/no-previous path.)
- [ ] **Build the rest of the report-figure pipeline (kateri-based, not map-draw).** Load
      charts via `ae_backend.chart_v3`, drive **kateri** through
      [`ae.utils.kateri`](py/ae/utils/kateri.py) (`send_chart` → `set_style` → `get_pdf`) to
      emit the antigenic-map PDFs at the filenames `report.py` expects
      (`<subtype>-<assay>/clade-<lab>.pdf`, `ts-<lab>-<YYYY-MM>.pdf`, …); embed **TAL** tree
      PDFs (#3); wire in the geographic maps from the **`geo-draw`** renderer in `cc/geo/` (§1,
      all slices incl. **clade pies** done) → `geo/<VT>-geographic-<YYYY-MM>.pdf`. The Python glue
      `geographic.make_geo(..., color_by="continent"|"clade")` writes the `--data` JSON (clade resolved
      from seqdb) and embeds the per-month PDFs.
      The `chart_v3.Chart(<file>)` import-abort is **fixed** (§1, verified — load + `export()`),
      so the only remaining prerequisite is the `kateri` executable being installed. **Verify:**
      generates a full PDF report from a sample dataset.

---

## 5. webserver — HTTPS chart serving  *(owner: webserver agent — 🟢 done)*

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
      JSON + HTML pages, path-traversal protection. **✅ Verified end-to-end** (after the §1
      `chart_v3` import-abort fix) via the real `bin/chart-serve` + `curl`
      (`PYTHONPATH=build bin/chart-serve <dir>`):
      - HTTP layer: `/healthz`→ok, `/api/charts` lists the dir's charts, `/`→index HTML 200,
        `/nope`→404, missing-path→400, `../CLAUDE.md`→403; **HTTPS** with a self-signed cert
        (`https://…/healthz`→200 over TLS).
      - **Chart data (now working):** `/api/chart/info?path=chart1-relaxed.ace` → correct name,
        22 ag / 10 sr / 10 proj, projection 0 stress **66.1247** (2d, mcb none), antigen/serum
        metadata; `/api/chart/table` → full 22×10 titer matrix with encodings preserved
        (`<40` kept as string, not coerced); `/chart` HTML page → 200.
- [ ] **M3 (optional, future):** websocket/live-reload parity with AD, or FastAPI/ASGI host if a
      production deployment model is chosen. **Map figures, if ever embedded, come from `kateri`**
      (chart → kateri socket → PDF, see `py/ae/utils/kateri.py`), not the shelved C++ map-draw #1.

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
