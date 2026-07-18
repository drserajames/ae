#pragma once

#include <filesystem>
#include <vector>

// ======================================================================
// Single-canvas signature-page compositor (subsystem #3 — sigp).
//
// A signature page pairs a phylogenetic tree with a grid of per-clade-section
// antigenic maps. Historically ae rendered the tree (tal-draw) and each section
// map (kateri) as separate PDFs and stitched them with pdfjam/pdflatex. This
// composes them onto ONE Cairo PDF page instead: each renderer emits a high-res
// PNG tile, and compose_sig_page paints the tiles onto a single cairo_pdf_surface
// at the caller-computed layout offsets. No pdfjam, no pdflatex, no kateri.
//
// This is pure layout/compositing — it neither reimplements the tree renderer
// (cc/tal/draw-tree) nor the map renderer (cc/map-draw/styled-draw); it consumes
// their PNG output. It uses Cairo directly (like cc/draw/cairo-surface.cc) and
// does NOT touch the shared CairoPdf surface class. See SIG-PAGE-COMPOSITOR.md.
// ======================================================================

namespace ae::tal
{
    // One image tile placed on the signature page. `png` is a raster tile produced
    // by a renderer (the tree, or one section map); it is painted scaled to fit the
    // device-pixel rectangle (x, y, w, h) with the top-left corner at (x, y). When
    // `frame` is true a 1px black border is stroked around the rectangle (matching
    // AD's per-map border, which the native/kateri maps don't draw themselves).
    struct SigTile
    {
        std::filesystem::path png{};
        double x{0.0};
        double y{0.0};
        double w{0.0};
        double h{0.0};
        bool frame{false};
    };

    // Paint `tiles` onto a single Cairo PDF page of `page_w` x `page_h` device
    // units, written to `output`. The page background is white. Tiles are painted
    // in list order (later tiles overpaint earlier ones). Throws std::runtime_error
    // if the surface can't be created or a tile PNG can't be loaded.
    void compose_sig_page(const std::filesystem::path& output, double page_w, double page_h, const std::vector<SigTile>& tiles);

} // namespace ae::tal

// ======================================================================
