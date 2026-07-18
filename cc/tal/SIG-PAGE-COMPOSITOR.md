# Single-canvas signature-page compositor (sigp)

Goal: render a report **signature page** — a phylogenetic tree paired with a column/grid
of per-clade-section antigenic maps — on **one native C++ Cairo canvas**, emitting a single
PDF page. This replaces the previous approach, which rendered the tree and each section map
as separate PDFs (tree via `tal-draw`, maps via **kateri**) and stitched them with `pdfjam`
/ `pdflatex`. Doing the maps natively also removes the last dependency of signature-page map
rendering on kateri.

## 1. How the current signature page is composed

Driver: `py/ae/tal/signature_page.py::make_section_signature_page`
(called per lab-subtype by `py/ae/report/signature_page.py` and the report's
`gen-sigpages-ae.py`). Steps today:

1. **Parse the tree settings** (`.tal`): the *shown* horizontal tree sections
   (`hz-sections`, each a contiguous leaf range `[first, last]` with a letter prefix and a
   label) and the time-series month window (`py/ae/tal/section_maps.py`).
2. **Match tree leaves to chart antigens/sera** by name (draw order taken from
   `tal-draw <tree> out.names`), assign section letters A/B/C… in tree order, and build
   **one named semantic style per shown section** in a copy of the chart (each style greys
   the whole map, then highlights that section's antigens coloured by date + its sera; title
   `"<letter>. <label> <aa>"`). This is the section↔map coupling.
3. **Render one antigenic-map PDF per section style** — currently via **kateri** over its
   socket (`render_section_maps_via_kateri`), one PDF per style.
4. **Render the tree PDF** via the `tal-draw` binary, with signature-page overrides (title
   top-left, no aa-legend, no aa colour-bar, clades column left of the time-series matrix,
   and a grey "matches-chart-antigen" dash-bar).
5. **Compose** tree + maps onto one landscape page with `compose_grid` (via `pdflatex`;
   falls back to `pdfjam`).

### Composition geometry (`compose_grid`, `auto_width=True` — the sig-page path)

All lengths in mm; the page is landscape. Inputs: `n` section maps, tree PDF aspect
`a = w/h`, `cols = ceil(n / 3)` (AD lays the maps 3 rows high), `rows = ceil(n / cols)`.

```
margin        = 2 mm  (sig-page override)
avail_h       = paper_h(210) - 2*margin - title(0) - 10
cell          = max(20, avail_h/rows - 1.5)     # square map cell side
row_gap       = 1.5 mm
grid_h        = rows*cell + (rows-1)*row_gap     # grid (and tree) height
tree_w        = a * grid_h                        # tree sized to the grid height
col_gap       = 2 mm ; panel_gap = 5 mm
grid_w        = cols*cell + (cols-1)*col_gap
paper_w       = 2*margin + tree_w + panel_gap + grid_w
paper_h       = grid_h + 2*margin + 4            # +4 = single-page spill guard
```

Layout on the page: tree occupies the left panel at its natural aspect, height = `grid_h`;
the maps fill an `rows × cols` grid on the right, each map bounded to a `cell × cell` square
(`keepaspectratio`) with a thin black frame (kateri/native maps draw no border). Maps are
filled **column-major top-to-bottom** in section (tree) order. The page title is drawn
*inside* the tree panel (step 4), not by the compositor. There are no inter-map captions
(titles live inside each map).

## 2. Single-canvas compositor design

### Constraint

`cc/map-draw/styled-draw.cc` (the native map renderer `export_styled_map`) and
`cc/draw/cairo-surface.{hh,cc}` (the shared `CairoPdf`) are owned by a parallel effort and
**must not be edited**. Both `export_styled_map` and `tal-draw`'s `export_tree_pdf` are
*self-contained*: each constructs its own full-page `CairoPdf` bound to an output file and
draws everything; neither can draw into a sub-region of a caller's surface, and `CairoPdf`
exposes no translate/offset primitive. A fully-vector single canvas would require both
renderers to accept a shared Cairo context with a translation — blocked on the map side by
the no-edit rule.

### Approach: one Cairo PDF page, painted from renderer-produced raster tiles

`CairoPdf` already selects its backend by output extension — `.png` writes a raster image.
So each renderer can emit a **high-resolution PNG tile**, and a new compositor paints those
tiles onto one Cairo PDF page at computed offsets:

- **Maps**: `ae_backend.map_draw.export_styled_maps(ace, [(style, tile.png)…], width)` —
  the existing native renderer, `.png` output, chart loaded once. **Removes kateri.**
- **Tree**: the `tal-draw` binary with a `.png` output path — existing renderer, PNG backend.
- **Compose**: a **new** C++ function `ae::tal::compose_sig_page(output_pdf, page_w, page_h,
  tiles)` where each `tile = {png, x, y, w, h, frame}` (device px). It creates ONE
  `cairo_pdf_surface` of `page_w × page_h`, and for each tile loads the PNG
  (`cairo_image_surface_create_from_png`), scales it into its rect, paints it, and strokes
  an optional 1px black frame. One `cairo_show_page`. No `pdfjam`, no `pdflatex`, no kateri.

The new file uses Cairo directly (as `cairo-surface.cc` does) — it does **not** edit the
shared surface class. It is pure layout/compositing: it reimplements neither the tree nor the
map renderer.

### Files

- `cc/tal/sig-page.hh` / `cc/tal/sig-page.cc` — `compose_sig_page` + the `SigTile` struct.
- `cc/py/sig-page.cc` — pybind11 binding `ae_backend.tal.compose_sig_page(...)`, registered
  in `cc/py/module.{cc,hh}` (appended, no reordering).
- `meson.build` — append the two `cc/tal/sig-page.cc` / `cc/py/sig-page.cc` sources to the
  Python-module list (they need only Cairo, already linked into `ae_backend`).
- `py/ae/tal/signature_page.py` — a new `make_section_signature_page_native(...)` that
  renders the map PNGs (native) + tree PNG, computes the §1 geometry in device px, and calls
  the binding. The existing kateri/pdfjam path is left intact as a fallback.

### Geometry in device pixels

The §1 mm geometry is reused verbatim, converted to device px by a fixed `px_per_mm`
(render tiles at that scale so painted tiles are 1:1 with their rects — no upscaling blur).
Tree tile is rendered at `tree_w × grid_h` px; each map tile at `cell × cell` px. The page is
`paper_w × paper_h` px.

### Trade-off (honest)

Tiles are **raster** (PNG) rather than vector, because the no-edit rule blocks a shared-context
vector path on the map side. Rendered at high `px_per_mm` the visual result is pixel-close to
the current vector composition (which is itself rasterised for on-screen/thumbnail use), and
the pixel-diff verification rasterises both sides anyway. A future fully-vector single canvas
would refactor `export_styled_map` + `export_tree_pdf` to draw into a caller-supplied Cairo
context at an offset — out of scope here by the ownership constraint.

## 3. Status

- [x] Current-composition analysis + geometry (this doc).
- [ ] `compose_sig_page` C++ + binding.
- [ ] `make_section_signature_page_native` driver.
- [ ] Build + pixel-diff verification vs the current composed page for one real signature page.
