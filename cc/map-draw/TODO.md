# map-draw revival — headless C++ antigenic-map renderer (fidelity port of AD ChartDraw)

## Goal

Give `ae` a **headless, Linux-capable C++ Cairo renderer** for antigenic maps whose output is
**visually identical to AD's `acmacs.ChartDraw`** as used by the WHO-CC incremental-chain web app
(`chains-202105`). This is "Option A": the chains workflow runs on a **Linux server** where kateri
(macOS-only — it has only `macos`/`web` Flutter targets, and its `--headless` is a macOS-Swift window
trick) cannot run, so ae needs its own in-process renderer. It reuses the live
`cc/draw/cairo-surface.*`, which already builds/runs on Linux for TAL (`tal-draw`) and geo (`geo-draw`).

**Success** = for a chain-step `.ace` + coloring key + size, ae's renderer reproduces the
corresponding **cached AD PNG**, verified **at high zoom, side-by-side**.

## Where everything is

- **Worktree/branch:** this dir (`/Users/sarahjames/AC/eu/ae-map-draw`, branch `map-draw-revive`).
  **Edit ONLY files inside this worktree.** Everything else below is read-only reference.
- **Starting code (M1 scaffold):**
  `git show drserajames/map-draw-shelved:cc/map-draw/{draw.hh,draw.cc,chart-draw-main.cc}`.
  It is only the **M1 slice** (bbox → square viewport + Y-flip transform, unit grid + border,
  plot-spec point styles, opt-in serum circles — no coloring/legend/title/marks/procrustes).
  `main` has moved on since it was cut (cairo-surface API changed; geo/tal evolved), so **port it
  forward** onto current main rather than merging the branch.
- **Live drawing surface:** `cc/draw/cairo-surface.hh` — `background, circle, sector, square,
  triangle, filled_triangle, rectangle, line, path_negative_move, text, text_rotated, text_size`.
  Add primitives here if needed (e.g. an `arrow`), additively — TAL/geo also use this file.
- **Fidelity reference (AD C++ source):** `~/AC/eu/AD/sources/acmacs-map-draw/cc/` — especially
  `draw.cc`, `point-style-draw.cc`, `map-elements*.{cc,hh}`, `labels.*`, `map-procrustes.cc`,
  legend code, and the viewport calculation.
- **The exact behaviours to match (the chains app):**
  `~/AC/eu/AD/sources/acmacs-whocc/web/chains-202105/py/chart.py` —
  `make_map` (reset styles, clade `chart_draw_modify(mapi_key=coloring)`, `mark_recent_layer`,
  `mark_vaccines`, `drw.title(["{stress}"])`, `drw.legend(...)`, `calculate_viewport`) and
  `make_pc` (`procrustes_arrows(..., threshold=0.3)`, title `RMS: {rms:.4f}`). Point defaults there:
  grey `#D0D0D0`, `sTestAntigenSize=10`, `sReferenceAntigenSize=15`, `sSerumSize=15`.
- **Coloring DSL data:** `~/AC/eu/ac/results/chains-202105/clades.mapi` — the mapi settings that map
  clade → fill/outline for coloring keys `clades-A(H3N2)-v1/-v2/-v3` (and the other subtypes).
- **GOLDEN references:** cached AD PNGs in `~/AC/eu/ac/results/chains-202105/**/png/` (~34k files).
  Naming: `<step>.<daterange>.<type>.<coloring>.<size>.png`, e.g.
  `001.20200122-20200203.incremental.clades-A-H3N2--v1.800.png`. The source chart is the sibling
  `<step>.<daterange>.<type>.ace` in the parent dir. **AD's module here is a Linux `.so` and will not
  load on this Mac — do NOT try to re-run AD; compare against these frozen PNGs.**
- **Test/output dir (create it; do NOT edit any existing `.py` there):**
  `~/AC/eu/ac/results/map-draw-revive-test/`.

## Build & run

- Build: `./build.sh` (arm64 / Apple clang 21 / py3.14); `./build.sh check` = preflight only.
  If a fresh reconfigure trips lexy/CMake, `export CMAKE_POLICY_VERSION_MINIMUM=3.5` (build.sh does).
- `source ae-env.sh` to set `AE_ROOT`/`PYTHONPATH`/`SEQDB_V4`/`LOCDB_V2`/etc.
- New meson: add a `# --- map-draw ---` block, a `map-draw` binary target linking Cairo (mirror the
  `tal-draw`/`geo-draw` targets). Python binding: `cc/py/map-draw.cc` registered in
  `cc/py/module.{hh,cc}` **without reordering** existing registrations.
- `.ace` are XZ-compressed JSON; inspect with `decat file.ace | python3 -m json.tool` or `xz -dc`.

## Fidelity strategy (get these in order — each depends on the last)

1. **Transform / viewport FIRST.** Everything keys off it. AD calls `calculate_viewport()`, but a
   chart often carries a **stored viewport** in its plot-spec — prefer that if present so ae frames
   the map exactly like AD. Match: square canvas, Y-flip, padding, coords→device mapping, and the
   background **unit grid + border** (AD `BackgroundBorderGrid`). Nail point POSITIONS before styling.
2. **Point styles** — match AD `point-style-draw.cc`: shapes (test = filled circle, reference = open
   circle, serum = open box; egg passage = egg outline; reassortant = rotated), sizes, outline widths,
   default greys. An uncoloured map should be pixel-close before adding colour.
3. **Clade colouring** — reproduce `chart_draw_modify(mapi_key)` from `clades.mapi` for v1/v2/v3:
   select antigens by clade, apply fill/outline/raise-order. **Decide the clade source that matches
   the frozen PNGs:** prefer clade **semantic attributes already in the `.ace`** (AD baked them in)
   over re-populating from a possibly-drifted seqdb — verify which reproduces the reference colours.
4. **Marks** — `mark_recent_layer` (points from the last layer: outline width 3, raised; last-layer
   sera get black outline too) and `mark_vaccines` (blue fill, size 24, label
   `{location_abbreviated}/{year2}`, raised).
5. **Map elements** — title line `{stress}` (match AD's stress value + precision) and the clade
   **legend** (offsets/label sizes per `drw.legend(offset=[-10,-10], label_size=-1, point_size=-1)`).
6. **Procrustes** (`make_pc`) — ae_backend already has procrustes (`chart-procrustes` /
   `CommonAntigensSera`); compute arrows (threshold 0.3), draw them (add an `arrow` primitive to
   cairo-surface if needed), title `RMS: {rms:.4f}`.

## Milestones

- **M1** Port-forward scaffold → `map-draw` CLI + `ae_backend` binding build; render a step `.ace` →
  PDF+PNG; **viewport/positions match AD framing**.
- **M2** Point shapes/sizes/outlines/greys match AD (uncoloured map identical).
- **M3** Clade colouring (v1/v2/v3) matches cached-PNG colours.
- **M4** `mark_recent_layer` + `mark_vaccines`.
- **M5** Title (stress) + legend + grid/border polish.
- **M6** Procrustes `make_pc`.
- **M7** Fidelity harness + side-by-side high-zoom comparisons over a representative matrix; iterate
  to a match; deliver comparison images for review.

## Verification / deliverable (the point of the exercise)

- Comparison harness in the test dir: for each case, render the ae PNG at the reference **size 800**,
  then produce (a) an ImageMagick `compare` RMSE / %-different-pixels number, (b) a **high-zoom**
  side-by-side montage (crop a region + nearest-neighbour upscale ~400–800% so individual points and
  outlines are inspectable), and (c) a difference heatmap.
- **Representative matrix:** ≥ H3 / H1 / B; ≥ 2 labs; colouring v1 + v2 + v3; step types
  incremental / scratch / mcb / individual; plus ≥ 1 **procrustes** pair (consecutive steps).
- **Acceptance:** visually identical; document residual anti-aliasing diffs (target < 1 % differing
  pixels, as the ssm-report kateri port achieved). Note any case that can't match and why.
- **Return:** the side-by-side comparison images + a short per-case fidelity report (RMSE / %diff,
  the montages, known gaps), saved under the test dir with paths listed.
- **No WHO surveillance data** in committed ae files/comments (real strain names/titers/serum IDs
  stay out of the repo — keep them only in the test dir).
