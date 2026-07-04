# P2 rendering spike — can `map-draw` become the canonical `ae.report` figure engine?

**Spike goal.** Decide whether the headless C++ `map-draw` renderer (subsystem #1, revived
for the Linux whocc-chains batch path) can replace **kateri** (a Dart/Flutter macOS app,
driven over a Unix socket) as the engine that renders antigenic-map figures for
`ae.report`. The original author's intended architecture is a *single fast C++ engine that
reads JSON → image/PDF*, driven from Python and a thin GUI; kateri was a GUI experiment.

**Status:** spike complete. Gap characterised; one representative figure prototyped and
pixel-diffed against its kateri golden. Recommendation below is **conditional GO, staged**.

---

## 1. The two input paths

### 1a. What `ae.report` sends to kateri (today's report figure path)

The report never hands kateri a "plot spec" describing *how to draw*. It hands kateri a
**fully self-describing chart** and a **style name**:

- `ChartModifier` (`py/ae/report/chart_modifier.py`) writes onto the chart:
  1. **Semantic attributes** on antigens/sera — clade, reference, passage, continent/country,
     older-than, new-compared-to-previous, vaccine, serology (`ae.semantic.*`).
  2. **Named styles** in the chart's `c["R"]` block (`ae_backend` `SemanticStyles`), e.g.
     `-reset`, `-clades`, `-vaccines`, `clades`, `clades-6m/-12m`, `info-clades`, `serology`,
     `-o6m-grey`, `-continent`, `-pale`, `ts-YYYY-MM`, serum-circle / serum-coverage styles.
     A **front style** (e.g. `clades`) *composes* background styles by reference
     (`A: [{R:"-reset"}, {R:"-clades"}, {R:"-new-1"}, {R:"-vaccines"}]`) and carries a
     **title** (box origin/offset + text font/weight/slant/size/colour/interline), a
     **legend** flag block, and a **viewport/zoom** reset (`L`). A background style
     (e.g. `-clades`) is a **list of selector→point-style rules**: `{T: selector, F: fill,
     O: outline, D: drawing-order, A: alpha, L: {p: legend-priority, t: legend-text}}`.
- Transport (`py/ae/utils/kateri.py`): `send_chart(chart)` → `set_style(name)` →
  `get_pdf(style=name)`. kateri resolves the named style, applies the per-selector point-style
  modifications, draws title/legend/serum-circles/grid, frames by the stored viewport, and
  returns PDF bytes.

The C++ structs for this style model **already exist in ae** at `cc/chart/v3/styles.hh`
(`Title`, `Legend`, `box_t`, `text_t`, `point_style_fow_t`, `serum_circle_style_t`,
`serum_coverage_style_t`, `Selector`) — but only kateri (Dart) currently *interprets* them.

### 1b. What `map-draw` consumes

`ae_backend.map_draw.export_map(ace, output, projection_no, size, reorient_master, mapi,
coloring, marks, title, legend, labels, serum_circles)` / the `map-draw` CLI. It is a
**fixed-pipeline reproduction of AD's chains-202105 `make_map`**, *not* a style interpreter:

- Grey base points with **AD-chains hardcoded** shapes/sizes (`outline #D0D0D0`, test d10 /
  reference d15 (open circle) / serum d15 (open box)) — set in `draw.cc`, not read from the chart.
- Clade colour re-derived from an **external `clades.mapi` DSL file** + `coloring_key`, after
  **populating clades from seqdb** — *not* from the chart's baked semantic attributes/styles.
- `mark_recent_layer`, `mark_vaccines` (vaccine strains read at runtime from
  `acmacs-data/semantic_vaccines.py`), a **stress-value** title, a mapi-derived clade legend,
  a **self-computed bounding-ball** viewport (or `reorient-master` alignment), opt-in
  hardcoded 2-fold serum circles.

**Confirmed by inspection:** `cc/map-draw/draw.cc` has **zero** references to `chart.styles()`
(`c["R"]`) or the legacy plot-spec (`c["p"]`). It ignores the entire report styling system.

### 1c. The gap (enumerated)

| # | Report figure needs (kateri does it) | `map-draw` today |
|---|---|---|
| 1 | Resolve named front styles + background-style composition + priority (`c["R"]`) | **missing entirely** |
| 2 | Per-point styles from the legacy plot-spec (`c["p"]`) | **ignored** (AD-chains hardcoded defaults) |
| 3 | Per-selector fill/outline/outline-width/size/shape/alpha/drawing-order | wrong (fixed greys + fixed sizes) |
| 4 | Arbitrary title: text + box origin/offset + font face/weight/slant/size/colour/interline | only a stress number, top-left |
| 5 | Semantic legend: rows (priority+text), counter, box, point-size, zero-count rows | only a mapi-derived clade legend |
| 6 | Selectors beyond clade: reference, passage, continent, older-than, new-compared-to, serology, vaccine | only clade + reference + serum |
| 7 | Stored/zoom viewport from the style (`L`) → exact report framing | self-computed bbox → **framing/zoom mismatch** |
| 8 | Serum circles from style: fold, theoretical/empirical, dash, angles, radius outline | hardcoded 2-fold empirical only |
| 9 | Serum-coverage (within/outside) styling | missing |
| 10 | Time-series / pale / continent / serology composed styles | missing |
| 11 | Vaccine marks driven by the chart's semantic vaccine attribute + style | different source (runtime `semantic_vaccines.py`) |
| 12 | Font matching to kateri (Helvetica, weights/slants) + PDF page geometry | partial / not matched |

**Root characterisation:** `map-draw` is a *fixed AD-chains pipeline*; the report needs a
*semantic-style interpreter*. Closing the gap = porting kateri's rendering logic (Dart) into
C++ on top of `map-draw`'s existing cairo/viewport/point scaffolding.

---

## 2. Prototype (what was actually validated)

One representative report figure: the `clades` main map of a small H1 report chart
(8 antigens × 7 sera). Rendered through `map-draw` (`--no-populate --no-marks --no-vaccines`)
and pixel-compared to the **existing kateri golden** `out.1.clades.pdf` for the same chart.
(No kateri re-run needed — the golden was already on disk. Real chart + renders kept in the
scratchpad, never in the repo.)

- **RMSE = 0.155 (15.5%).**
- **Visual (montage):** kateri shows the report title, clade-coloured antigens, green
  vaccine dots with strain labels, and a full clade legend with counts, framed by the stored
  zoom viewport. `map-draw` shows an all-grey map (reference = open circles, sera = open
  boxes) with a stress-number title, **no** colour / vaccines / legend / report title, at a
  **different zoom/framing**. Point *positions* correspond (same optimisation), but scale
  differs because the viewports differ.
- **Effective report-figure parity of `map-draw` as-is: ~0%.** The 15.5% RMSE understates it
  because most of the canvas is white background; every foreground element differs.

This is the expected result and confirms the gap is architectural, not cosmetic:
`map-draw` cannot approximate a report figure by tweaking flags — it lacks the style engine.

Repro: `tools/p2-render-spike/compare.sh <styled.ace> <kateri-golden.pdf>`.

---

## 3. Parity + effort plan

Realistic path: add a **semantic-style interpreter** to `map-draw` — read `c["R"]` + `c["p"]`,
resolve/compose front styles, apply per-selector point styles, and draw title/legend/viewport/
serum-circles from the style. Reuse what already exists:

- `cc/chart/v3/styles.hh` already **models** the style structs (big head-start — the schema is
  done; it needs a JSON reader + an interpreter, not a new data model).
- `cc/chart/v3` selection (`SelectedAntigens`/`SelectedSera`) already matches semantic
  attributes — reuse for selectors.
- `map-draw` already has cairo primitives, the viewport/transform, point shapes, and
  title/legend/serum-circle drawing code — the *drawing* layer is largely there; the
  *style-interpretation* layer is ~0%.
- whocc-chains proved `map-draw` can reach **<1% pixel diff** vs an AD golden — the fidelity
  bar is achievable.

Staged milestones (each ends with a pixel-diff vs a kateri golden across the report set):

| Stage | Scope | Est. (agent-pace) |
|---|---|---|
| P2-A | Style reader for `c["R"]`/`c["p"]` + front-style resolver + selector engine; apply per-point fill/outline/size/shape/order; draw title (arbitrary text/box/font) + semantic legend + **viewport from style**. Target: `clades` main map < 1% vs kateri golden. | **M** (1–2 sessions) |
| P2-B | Remaining selectors (reference/passage/continent/older-than/new/serology/vaccine) + `-vaccines`/`-reset`/`-new` composition + info-/6m/12m variants. | **M** |
| P2-C | Serum circles + serum coverage from style (fold/theoretical/empirical/dash/angles/radius); time-series / pale / continent / serology styles. | **M** |
| P2-D | Font + PDF-geometry parity with kateri; fidelity harness over the full figure matrix (subtypes × labs × styles); iterate to < 1%. | **M–L**, iterative |

**Total ≈ a multi-week C++ effort (several agent-sessions)** — comparable to or somewhat larger
than the whocc-chains `map-draw` revival, because the target is *arbitrary report styling*
parity, not one fixed pipeline. The `styles.hh` head-start and existing drawing layer are the
main risk-reducers; the long tail (exact fonts, legend/title box metrics, viewport rounding,
per-style-family quirks) is where iteration time goes.

**What is validated vs estimated:** the gap analysis and the ~0% as-is parity are
**validated** (inspection + prototype). The stage effort is **estimated** by analogy to the
chains revival and by the fact that the data model already exists.

---

## 4. Recommendation

### P2 (report figure engine): **conditional GO — staged.**

The architecture case is strong and matches the author's intent: one fast, Linux-capable C++
engine reading JSON → PDF, no Dart/macOS/socket dependency, no separate GUI process in the
batch path. The work is substantial but **bounded and well-scaffolded** (`styles.hh` models
the styles; the drawing layer exists; chains proved <1% fidelity is reachable).

De-risk by gating on **P2-A**: build the style interpreter far enough to reproduce the plain
`clades` main map **< 1% pixel-diff vs the kateri golden**. That single milestone exercises the
whole spine (style read → selector → point-style → title → legend → viewport). If P2-A lands
cleanly, commit to P2-B..D and retire kateri from the report figure path. **If P2-A cannot
reach < 1% within ~2 sessions, that is the no-go signal** — kateri stays the report renderer
and `map-draw` remains the chains-only tool.

### sigp (AD-faithful maps + tree on one C++ canvas): **feasible, but downstream of P2.**

`map-draw` and `tal-draw` both build on the shared `cc/draw/cairo-surface` primitives, and AD
historically drew the tree and the section maps on a **single canvas**. Today ae composes a
`tal-draw` tree PDF with **kateri** map PDFs via `pdfjam`/`pdflatex`
(`py/ae/tal/signature_page.py` + `section_maps.py`; the latter's own docstring notes "ae has no
single-canvas renderer"). Once P2 gives `map-draw` a report-grade map renderer, a true
single-canvas sig page becomes achievable: draw the tree (tal-draw code) and the per-section
maps (map-draw code) onto one `CairoSurface`, positioned by the sig-page layout, with
per-section colouring that `section_maps.py` already computes.

**Verdict:** sigp single-canvas is a clean architectural win but is **contingent on P2** (needs
the map renderer first) **plus a compositor** (shared coordinate space, section→map viewport,
page layout). Recommend: **defer sigp until P2-A/B prove the map engine**, then scope it as a
follow-on. It should not gate the P2 decision.
