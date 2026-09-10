# Fully-vector single-canvas signature-page compositor (sigp-vector)

Goal: render a report **signature page** — a phylogenetic tree paired with a grid of
per-hz-section antigenic maps — on **one native C++ Cairo canvas**, with BOTH halves drawn
as **vectors** into one shared `cairo_pdf_surface`. This replaces (a) the original approach,
which rendered the tree (`tal-draw`) and each section map (**kateri**) as separate PDFs and
stitched them with `pdfjam`/`pdflatex`, and (b) a prior PNG-tile prototype that painted
per-renderer raster tiles onto one page. Here nothing is rasterised and nothing is stitched:
the map renderer and the tree renderer draw straight into sub-rectangles of one page.

## 1. Composition geometry (`py/ae/tal/signature_page.py::_sig_page_layout`)

A device-space port of AD's `compose_grid` `auto_width` path. All lengths in mm; the page is
landscape. Inputs: `n` section maps, tree page aspect `a = w/h`, `cols = ceil(n / 3)` (AD lays
the maps 3 rows high), `rows = ceil(n / cols)`.

```
margin        = 2 mm
avail_h       = paper_h(210) - 2*margin - 10
cell          = max(20, avail_h/rows - 1.5)        # square map cell side
row_gap 1.5 ; col_gap 2 ; panel_gap 5 (mm)
grid_h        = rows*cell + (rows-1)*row_gap        # grid (and tree) height
tree_w        = a * grid_h                          # tree sized to the grid height
grid_w        = cols*cell + (cols-1)*col_gap
page_w        = 2*margin + tree_w + panel_gap + grid_w
page_h        = grid_h + 2*margin + 4               # +4 = single-page spill guard
```

The tree occupies the left panel (`tree_w × grid_h`); the maps fill a `rows × cols` grid on
the right, each bounded to a `cell × cell` square with a thin black frame, filled **row-major**
in section (tree) order (matching the pdfjam baseline's `compose_grid` fill order). Rects are
converted to PDF points (`_MM2PT = 72/25.4`) and handed to the C++ compositor.

The **tree page aspect `a`** is read directly from the tree settings'
`width_to_height_ratio` (draw-tree.cc sizes the page `width = image_size * ratio`), so no probe
render is needed to measure it.

## 2. Shared-surface render path (the core refactor)

`ae::map_draw::export_styled_map` and `ae::tal::export_tree_pdf` each historically built their
own full-page `CairoPdf` bound to an output file. They were refactored so each can also draw
into a **caller-supplied Cairo context** at an offset:

- **`cc/draw/cairo-surface.{hh,cc}`** — a second `CairoPdf` constructor takes a borrowed
  `cairo_t*` plus a device rect `(dst_x, dst_y, dst_w, dst_h)` and a logical size
  `(logical_w, logical_h)`. It `cairo_save`s, applies a device-space translate+scale mapping the
  logical box onto the rect, and clips to it; the destructor `cairo_restore`s and never destroys
  the borrowed context/surface. Every existing draw primitive then lands inside the rect. The
  file-bound constructor is unchanged.
- **`cc/map-draw/styled-draw.cc`** — the per-map compute+draw body was factored behind a surface
  factory (`render_styled_map(..., make_surface)`). `export_styled_map(..., output)` supplies a
  file surface (byte-identical output as before); `export_styled_map_into(..., context, rect)`
  supplies a borrowed surface, letterboxing the map (aspect-preserving) into the rect.
- **`cc/tal/draw-tree.cc`** — same factoring (`render_tree_core(..., make_surface)`), with
  `export_tree_pdf` (file) and `export_tree_into` (borrowed rect) wrappers.

Because only the *surface* differs, the standalone file renderers are **pixel-identical** to
before the refactor (verified: `export_styled_map`, `tal-draw`, `geo-draw` all AE = 0).

## 3. Compositor (`cc/tal/sig-page.{hh,cc}` + `cc/py/sig-page.cc`)

`ae::tal::SigPageCanvas` owns ONE `cairo_pdf_surface` of `page_w × page_h` (white background) and
exposes:

- `render_maps(ace, projection_no, width, jobs)` — loads the chart **once** and draws each
  job's named style into its device rect via `export_styled_map_into` (+ optional 1px frame).
- `render_tree(tree, settings, image_size, x, y, w, h)` — loads the tal-draw settings + tree and
  draws via `export_tree_into` into the tree rect.
- `finish()` — `cairo_show_page` + finalise the PDF.

Exposed to Python as `ae_backend.tal.SigPageCanvas`. The tree renderer + geographic-continent
sources (`draw-tree.cc`, `settings.cc`, `continent-map.cc`, `geo/*`) are linked into
`ae_backend` alongside Cairo so the binding can reach both renderers (they were previously only
in the `tal-draw` binary).

## 4. Driver + default wiring (`py/ae/tal/signature_page.py`)

`make_section_signature_page_native(...)` builds the section↔map coupling (the same
`section_maps.build_section_styles` used by the kateri path — greyed base map, per-section
antigens coloured by date + sera, AD `A/B/C…` section prefixes), writes the styled chart once,
computes the §1 geometry, then drives one `SigPageCanvas`. `make_section_signature_page(...)`
now defaults to this native vector path (`native=True`); `native=False` falls back to the
legacy kateri section-maps + `pdflatex`/`pdfjam` grid.

## 5. Text-size / page-size fidelity (why the tree renders at 1000, not the panel height)

Two driver-side geometry rules make the composited text land at the SAME size as the LaTeX
(`compose_grid`) baseline the report was built from, verified against the live path and against
`report/addendum-4.pdf` (bvic-niid) at the aa-transition-label glyph level:

1. **Render the tree at the baseline's internal `image_size` (`size or tal_size or 1000`), then
   letterbox it into the panel** — *not* at the panel height in points. `draw-tree.cc` clamps
   fonts/line-widths to ABSOLUTE device bounds (`font_size` [3,14], `line_width` [0.2,3],
   `title_fs` [8,26], legend/arrowhead …), so the tree does NOT scale linearly with `image_size`:
   rendering at the small panel height and placing it 1:1 makes those clamped glyphs/lines
   proportionally LARGER (a bolder tree, drifted label spacing) than the baseline, which renders
   at 1000 and optically scales DOWN. `export_tree_into` scales vector content losslessly, and
   because the tree page aspect == `width_to_height_ratio` == the panel aspect, the fit scale is
   `panel_h/image_size` in both axes → the tree still fills the panel exactly.
2. **Round the composed page to whole mm** (`_sig_page_layout`), exactly as `compose_grid` emits
   the LaTeX paper (`paperwidth={:.0f}mm`). This makes the page ASPECT — hence the scale
   `pdfpages` applies when it fits the sig page onto the report's A4 pages — identical to the
   baseline, so text lands at the same absolute size in the assembled report.

Measured (bvic-niid, 8 sections): page **926.929 × 572.598 pt = the live LaTeX path exactly**;
aa-label glyph height **5.23 pt vs 5.22 pt** for the baseline (0.2 %); tree vertical span within
0.2 % of the live `compose_grid` fit.

## 6. Status / residuals

- Composition: a real ~8-section signature page renders on ONE Cairo page as vectors (no kateri,
  no pdfjam/pdflatex). Page size + text size now match the live `compose_grid` baseline (see §5).
- Residuals (all expected, not compositor error): **map content** differs by the known
  native↔kateri delta (that swap is the point). The composited content sits ~10 pt higher within
  the page than the LaTeX baseline — a uniform `minipage[t]`/`\topskip` top offset that shifts the
  tree AND the maps together (tree↔map registration is preserved), and that `pdfpages` re-centres
  away when the page is embedded in the A4 report, so it does not affect the assembled report.
  The `report/addendum-4.pdf` sig pages were built from an older tree render whose tree is ~1.85 %
  shorter than the current pipeline (live `compose_grid` and this compositor agree to 0.2 %); that
  is stale-baseline drift, not a compositor error. The native maps render crisply (no raster tile
  softness).
