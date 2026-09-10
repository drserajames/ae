# P2 — Headless native map renderer for `ae.report`: design + work-breakdown

**Goal (Eu, 2026-07-08).** Render the seasonal report's antigenic maps **without launching
kateri per map** (faster reports), **improve AD fidelity**, and stay **kateri-compatible** —
consume the *same on-chart styling* the report already feeds kateri, so the renderer is a
drop-in for the report's map step. kateri stays available (interactive drag/relax).

This document is the Phase-1 spike output: it (a) writes down the *rendering contract*, (b)
records what the POC proved, (c) proposes the architecture, and (d) gives an **independent,
parallelisable** work-breakdown for the full build. It supersedes and extends
`P2-RENDER-SPIKE-PLAN.md` (A7's paper analysis) with a working headless POC and the key
de-risking findings.

---

## 0. Executive summary

- **The styling can be consumed headlessly — proven.** A ~230-line headless POC
  (`tools/p2-render-spike/poc_render.py`) reads a real report chart's on-chart styles
  (`c["R"]` named styles + `c["p"]` base plot-spec), resolves the selected front style,
  applies per-point fill/outline/size/shape/order, draws the title, vaccine labels, and
  viewport, and produces a map **recognisably identical in content** to both the kateri
  golden and the AD reference for the same map (same two clusters, full clade palette, same
  vaccine labels). This is the core unknown A7 left open (A7 only showed the *current*
  `map-draw` pipeline ignores styles → ~0% content parity).
- **The C++ head-start is larger than A7 stated.** `cc/chart/v3/chart-import.cc` **already
  fully parses `c["R"]`** into `cc/chart/v3/styles.hh`'s `semantic::Styles`
  (modifiers, selectors, title, legend, serum circle, serum coverage). The data model *and*
  the JSON reader exist and round-trip through Python (`chart.styles()`). Only the
  **style resolver + drawing application** are missing from `cc/map-draw/draw.cc`.
- **Fidelity (normalised RMSE, one representative map, coarse):** headless-vs-kateri 0.29,
  headless-vs-AD 0.28, **kateri-vs-AD 0.23**. The kateri-vs-AD 0.23 is a *framing/legend/scale
  floor* between differently-exported maps — the POC sits just above it, and the excess is the
  known, bounded tail (exact viewport, legend box, grid, fonts/AA). Pixel-RMSE is **not** a
  clean metric until viewport + page geometry are matched; the visual montage is the honest
  evidence at this stage.
- **Recommendation: GO, staged, multi-phase (multi-agent).** The spine is proven and the data
  model + reader + drawing primitives already exist. Gate the commitment on milestone **A**
  (one plain by-clade map < ~2% pixel-diff vs the kateri golden once the viewport convention
  is matched). The sub-features below are largely independent and can be parallelised.

---

## 1. The rendering contract (the spec the renderer implements)

### 1.1 What the report feeds kateri

The report never sends a "how to draw" plot spec. `ChartModifier`
(`py/ae/report/chart_modifier.py`) bakes onto the chart:

1. **Semantic attributes** on antigens/sera (`ae.semantic.*`): clade list (`C`), reference
   (`R`), passage (`p`), continent/country (`C9`/`c9`), older-than (`o6m`/`o12m`),
   new-compared-to-previous (`new`), vaccine (`V`), serology, sequenced.
2. **Named styles** in the chart's `c["R"]` block (C++ `semantic::Styles`).

`py/ae/utils/kateri.py` then transports over a length-prefixed Unix socket (4-byte code +
4-byte length + 4-byte-padded payload): `send_chart` (`CHRT`), `set_style(name)` (`COMD`),
`get_pdf(style,width,square,viewportSize)` (`COMD` → `PDFB` bytes). kateri resolves the
named style, applies it, draws title/legend/grid/serum-circles, frames by the viewport, and
returns PDF bytes. The report's map step is exactly: **pick a style name → get a PDF**. That
is the whole surface the headless renderer must replace.

### 1.2 On-chart representation (verified against a real styled chart)

`c["R"]` is an object: `name → style`. Two kinds of style:

**Front (composite) style** — the thing a map is rendered as. Carries:
- `z` : integer priority (inter-style draw order).
- `A` : ordered list; each entry `{ "R": <name> }` is a **reference** that composes a
  background style (resolved by following the reference).
- `L` : legend flags `{ "-": shown(bool), "C": add_counter(bool) }`.
- `T` : title `{ "B": box{ "o": origin, "O": [dx,dy], padding/border/bg }, "T": text{
  "t": text, "f": face, "W": weight, "S": slant, "s": size, "c": colour, "i": interline } }`.

**Background style** — a list of selector→point-style rules, plus optional viewport:
- `z` : priority.
- `V` : `[x, y, w, h]` viewport (present on the `-reset` family).
- `A` : ordered modifier list. Each modifier:
  - `T` : **selector** object — `{C: clade}` (matches if clade ∈ antigen's `C` list),
    `{R: true}` reference, `{V: true}` vaccine, `{p: passage}`, `{"!i": index}` by point
    index; empty ⇒ all candidates.
  - `A` : select — `1`/truthy = antigens only, `0`/false = sera only, absent = both.
  - point-style fields (shared with `c["p"]`): `F` fill, `O` outline, `o` outline-width,
    `S` shape (`C`ircle/`B`ox/`T`riangle/`E`gg/`U`glyegg), `s` size, `r` rotation,
    `a` aspect, `-` hidden (`false` ⇒ shown), `l` label `{p:[dx,dy], t:text, s:size}`.
  - `D` : drawing order — `"r"` raise, `"l"` lower.
  - `L` : legend row `{ p: priority, t: text }`.
  - `CI` : serum-circle spec; `SC` : serum-coverage spec (see `styles.hh`).

**Base plot-spec `c["p"]`** (kateri's starting point before named-style modifiers):
`P` = list of point styles, `p` = per-point index into `P`, `d` = draw order. Same field
letters. This supplies the default appearance (base greys, shapes, sizes) that the named
style then overrides.

**Resolution algorithm** (kateri's, reproduced in the POC): start from `c["p"]` per-point
styles; resolve the selected front style by walking its `A` list, recursively expanding each
`{R:name}` reference into that background style's modifiers (picking up its `V` viewport),
producing a **flat, ordered modifier list**; apply each modifier to the points its selector
matches (later modifiers win; `D:"r"` moves matched points to the end of the draw order);
collect legend rows; apply the front style's own `T`/`L`. Undefined references are tolerated
(e.g. a `-new-*` ref absent on a chart with no previous). Draw in draw order; then title;
then legend; frame by the viewport.

The C++ structs for all of this already exist (`styles.hh`) and the reader already
populates them (`chart-import.cc` `read_semantic_plot_specification` → `…_style` →
`…_style_modifier`). **The resolver above is the missing piece** (currently only kateri/Dart
implements it).

### 1.3 AD heritage (fidelity target)

Where kateri diverges from AD, match **AD**. AD's renderer is
`~/AC/eu/AD/sources/acmacs-draw` + `acmacs-map-draw` (`draw.cc`, `point-style-draw.cc`,
`map-elements*.{cc,hh}`, `labels.*`, legend + viewport code). The revived `cc/map-draw`
already reproduced AD *chain* maps to <1% px-diff, so the cairo/viewport/point-shape layer is
AD-calibrated. The POC confirmed the report's kateri golden and the AD reference for the same
map are near-identical in content (same clades/counts/labels), so for the by-clade maps
"match kateri" and "match AD" coincide; the fidelity strategy only needs an explicit AD tie-
breaker for details where they differ (grid style, legend metrics, label auto-placement).

---

## 2. POC — what was actually built and proven

`tools/p2-render-spike/poc_render.py` (Python + Pillow, stdlib elsewhere), run headlessly:

```
python3.14 poc_render.py <styled.ace> <style-name> <out.png>
```

It implements §1.2 end-to-end: colour parsing (hex/#AARRGGBB/named/`gray80`/`:bright`),
base plot-spec extraction, selector matching against semantic attributes, recursive front-
style resolution, per-point application, draw-order raising, title, vaccine labels, legend-
row collection, and a Pillow rasteriser (circle/box/triangle/egg-approx). Reads the chart
**read-only** from a private report dir; no WHO data enters the repo (images stay in the
scratchpad).

**Result.** For the representative `clades` main map it draws the correct two clusters, the
**full clade palette matching kateri and AD**, base grey cloud, open-box sera, open-circle
references, the title, and all vaccine labels. See the 3-way montage (POC | kateri | AD) in
the scratchpad. This validates the whole spine: style read → selector → point-style →
title → legend → viewport, headless, on a real report chart.

**What the POC did NOT do (⇒ the fidelity tail):** exact viewport/aspect match to kateri
(it auto-frames to the data bbox), the legend *box* with per-row counts, the background
unit grid + border, exact fonts/anti-aliasing/PDF page geometry, serum circles/coverage,
time-series / continent / serology / info-map style families, label auto-placement (overlap
avoidance). These are the §4 tasks.

### 2.1 Vertical-mirror resolution

The first POC pass applied a Y-flip (`device_y = H - (y-vy)/vh*H`) and came out vertically
mirrored vs kateri. **Fix: apply no Y-flip** — `device_y = (y - vy)/vh * H`. The projection
layout `c["P"][0]["l"]`, after the stored 2×2 transform `t` is applied
(`x' = t0·x + t1·y`, `y' = t2·x + t3·y`), is already in a **y-increases-downward screen
coordinate system**; kateri maps world→device directly with no inversion. With the flip
removed the POC matches kateri's orientation exactly (diverse cluster top, blue cluster
bottom). The native renderer must likewise treat post-transform layout Y as screen-down.

### 2.2 Viewport convention (open item, must be nailed in milestone A)

The stored `-reset` viewport `V=[x,y,w,h]` did **not** frame the post-transform layout in the
POC (data y-range fell outside the viewport y-range), so the POC auto-frames instead. kateri
frames correctly, so kateri applies an additional **recenter** between the transform and the
viewport (cf. `export_mapi_for_signature_pages` in `chart_modifier.py`, which combines
kateri's `native`, `used`, and `native_center` to recover an absolute viewport — evidence
kateri carries a native-center offset). Milestone A must reproduce this exact transform +
recenter + viewport chain so the native frame equals kateri's; it is the single most
important fidelity step (everything keys off it) and the biggest residual in the POC numbers.

---

## 3. Architecture — native renderer as a kateri-compatible drop-in

### 3.1 Component

Add a **semantic-style interpreter** layer to `cc/map-draw` on top of its existing cairo /
viewport / point-shape scaffolding, plus a new entry point that takes a **chart + style
name** (mirroring `set_style` + `get_pdf`) rather than the chains `DrawSettings`:

```
export_styled_map(chart, projection_no, style_name, width, output)   // C++ + pybind
```

Pipeline inside: `resolve_style(chart.styles(), c["p"], style_name)` → flat modifier list +
viewport + title + legend (the §1.2 algorithm, in C++, reusing `semantic::Styles` already
parsed by the importer and `SelectedAntigens/Sera` for selector matching) → apply to a
per-point render model → draw via `cc/draw/cairo-surface` (points, grid/border, title,
legend, serum circles) → PDF/PNG. The chains `export_map` stays as-is (fixed AD-chains
pipeline); the new path is additive.

### 3.2 Where it plugs into `ae.report`

The report's map step is "select style → get PDF" via `kateri.communicator`
(`set_style`/`get_pdf`) in the `style`/`export` path (`ae.report.commander`). Introduce a
small **renderer seam** — a `MapRenderer` interface with two implementations:

- `KateriRenderer` — current behaviour (launch kateri, socket, `set_style`/`get_pdf`).
- `NativeRenderer` — call `ae_backend.map_draw.export_styled_map(chart, style, width)`
  in-process; no subprocess, no socket, Linux-capable.

Select via a config flag / env (`AE_REPORT_MAP_RENDERER=native|kateri`, default `kateri`
until milestone D proves parity, then flip). This keeps kateri as a **fallback** and as the
**interactive** tool (drag-adjust / relax — `handle_relax`, `get_moved_points`), which the
native batch renderer deliberately does not replace.

### 3.3 AD-fidelity strategy

1. Match **viewport/transform/recenter** first (§2.2) — the frame must equal kateri's.
2. Point shapes/sizes/outlines/greys from `c["p"]` + modifiers (POC already correct in
   content) — calibrate pixel size against the AD/kateri golden.
3. Grid + border, legend box metrics, title box metrics, fonts (Helvetica weights/slants),
   PDF page geometry: take AD (`acmacs-draw`/`acmacs-map-draw`) as the tie-breaker where it
   differs from kateri; the chains `map-draw` revival already matched AD here.
4. Per-map-family details (serum circles theoretical/empirical, coverage within/outside,
   time-series sizing) from the modifier specs in `styles.hh`.

Fidelity harness: rasterise native + kateri golden with `pdftoppm` at equal size and
`magick compare -metric RMSE/AE` + a high-zoom montage, over the figure matrix (subtypes ×
labs × style families). Reuse the chains map-draw pixel-diff helpers.

---

## 4. Work-breakdown (independent sub-features — parallelisable)

Milestone **A** is the go/no-go spine and must land first. After A, the rest are largely
independent and can be handed to separate agents in parallel; dependencies noted.

| ID | Sub-feature | Depends on | Size | Hard parts |
|----|-------------|-----------|------|-----------|
| **A** | **Spine + go/no-go.** C++ `export_styled_map`: style resolver (front→background composition, flat modifier list), selector engine (reuse `SelectedAntigens/Sera`), per-point fill/outline/width/size/shape/order, **transform+recenter+viewport exact match** (§2.2), title, plain legend. Target: one plain by-clade map < ~2% px-diff vs kateri golden. | reader (done) | **M** | **Viewport recenter convention** (the key risk); flat-resolution order vs kateri; colour model (`:bright`, `#AARRGGBB`, `gray80`). |
| **B** | Legend box | A | S–M | Per-row counts (`legend_counter` ⇒ count matched points), zero-count rows, box origin/padding, row point-size/text-size metrics matching kateri/AD. |
| **C** | Title + fonts + PDF page geometry | A | S–M | Helvetica face/weight/slant, interline, box origin/offset, multi-line titles; PDF point size = width; AA parity. |
| **D** | Background grid + border | A | S | AD `BackgroundBorderGrid` spacing/colour; cheap, isolate early for fidelity. |
| **E** | Remaining selectors + composed styles | A | M | reference/passage/continent/older-than/new/serology/vaccine selectors; `-reset`/`-new`/`-vaccines`/`-pale`/`-o6m/12m` composition; **info-** maps (blank title, no legend). Mostly selector coverage — low risk once A's engine exists. |
| **F** | Serum circles | A | M | Empirical vs theoretical radius, fold, dash, angle radius-lines, per-passage outline/fill, fallback radius. Geometry-heavy; AD `map-procrustes`/serum-circle code is the reference. |
| **G** | Serum coverage | F | M | within/outside point restyle by fold; `-sco-*`/`sc-*` front styles; per-serum map matrix. |
| **H** | Time-series / continent / serology / pale families | E | M | Composed multi-reference styles; per-month `ts-*`; old/new sizing. Volume, not novelty. |
| **I** | Label auto-placement | A,C | **M–L** | Vaccine/serology labels currently carry explicit offsets (`l.p`) so baseline is easy; **overlap-avoidance / leader lines** to match AD is the genuinely hard, iterative part. |
| **J** | `ae.report` renderer seam + flag | A | S | `MapRenderer` interface, `NativeRenderer`, `AE_REPORT_MAP_RENDERER`; keep kateri default + fallback. Wire producer **and** consumer (a feature isn't done until end-to-end). |
| **K** | Fidelity harness + figure-matrix sign-off | B–J | **M–L**, iterative | The long tail: per-family px-diff to <~1–2%, document irreducible AA diffs, flag any map that can't match and why. |

> **K status (2026-09-10): partially signed off** — see
> [`tools/p2-fidelity/FIGURE-MATRIX-RESULTS.md`](tools/p2-fidelity/FIGURE-MATRIX-RESULTS.md).
> 219 maps (18 lab dirs × 3 subtypes) across the five reference-backed families —
> by-clade, by-clade −6m/−12m, serology, time-series — ran clean: **214/219 (97.7 %) under
> the 2 % fuzz30 target**, mean 0.93 %, and the residual is shown to be irreducible
> anti-aliasing (the same-content rasteriser floor is 0.98 % fuzz30 / 6.11 % strict).
> Viewport/recenter (§2.2, the milestone-A risk) is confirmed pixel-exact — best raster
> shift is always (0,0). **Four families are NOT signed off** for want of a reference:
> info maps, serum circles/coverage (F/G), multiple-serum-circles, signature-page section
> maps. Tracked as **K′**.

**Stays on kateri (do not port):** interactive drag-adjust + live relax animation
(`RLAX`/`LAYT`/`get_moved_points`/`handle_relax`) and the operator GUI. The native renderer
is the **batch** map engine only.

**Downstream (out of P2 scope, enabled by it):** single-canvas signature pages — draw the
`tal-draw` tree and the per-section `map-draw` maps on one `CairoSurface` (today composed via
`pdfjam`/`pdflatex` in `signature_page.py`/`section_maps.py`). Defer until A–E land.

---

## 5. Recommendation

**GO, staged, multi-phase (multi-agent).** The architecture matches the author's stated
intent (one fast C++ JSON→image/PDF engine, kateri as thin/interactive client), the data
model + JSON reader + AD-calibrated drawing layer already exist, and the POC proves the
styling is consumable headlessly with content parity to both kateri and AD.

- **Next step:** milestone **A** as a single focused agent-session. Success = the plain
  by-clade map frames and colours like the kateri golden (< ~2% px-diff), which requires
  cracking the viewport recenter convention (§2.2) — the one real risk. **If A cannot reach
  parity within ~2 sessions, that is the no-go signal**: keep kateri for report maps and
  `map-draw` chains-only.
- **After A:** fan out B–J to parallel agents (independent per the table), then converge on
  the K harness. Total ≈ a multi-week C++ effort comparable to the chains `map-draw` revival,
  but front-loaded risk is small because the reader/model/primitives are done — the cost is
  the fidelity long tail (viewport, legend/title metrics, fonts, label placement), not new
  architecture.

**Honesty on the POC:** it is a Python/Pillow *content* proof, not a pixel-faithful renderer.
It does not match kateri's viewport, legend box, grid, or fonts, and its RMSE numbers are
dominated by those gaps (the kateri-vs-AD 0.23 floor shows RMSE is uninformative until
framing is matched). What it *does* prove — the previously-open question — is that the report's
on-chart styling can be parsed and applied headlessly to reproduce the report map's content.
