#pragma once

#include <filesystem>
#include <string>
#include <vector>

// ======================================================================
// Fully-vector single-canvas signature-page compositor (subsystem #3 — sigp-vector).
//
// A signature page pairs a phylogenetic tree (left) with a grid of per-hz-section antigenic
// maps (right). Historically ae rendered the tree (tal-draw) and each section map (kateri)
// as separate PDFs and stitched them with pdfjam/pdflatex; a prior prototype instead painted
// per-renderer PNG tiles onto one Cairo page. This compositor draws BOTH halves as VECTORS
// onto ONE shared cairo_pdf_surface: the section maps via ae::map_draw::export_styled_map_into
// and the tree via ae::tal::export_tree_into, each targeting a computed device sub-rectangle of
// the shared context. No PNG tiles, no pdfjam/pdflatex, no kateri.
//
// Geometry (page size + tree/cell rects) is computed by the Python driver
// (py/ae/tal/signature_page.py::_sig_page_layout, a port of AD's compose_grid auto_width path)
// and passed in as device-point rectangles. See cc/tal/SIG-PAGE-COMPOSITOR.md.
// ======================================================================

struct _cairo;
struct _cairo_surface;

namespace ae::tal
{
    // One section-map job: render the chart's named style `style` into the device rectangle
    // (x, y, w, h) (top-left origin, PDF points); `frame` strokes a 1px black border around the
    // rect (AD's per-map border, which the native map does not draw itself).
    struct SigMapJob
    {
        std::string style{};
        double x{0.0};
        double y{0.0};
        double w{0.0};
        double h{0.0};
        bool frame{false};
    };

    // A single Cairo PDF page onto which the tree + section maps are drawn as vectors. Construct
    // with the page size (device points), render the maps (chart loaded once) and the tree into
    // their sub-rects, then finish() to finalise/write the PDF. The class owns its surface+context.
    class SigPageCanvas
    {
      public:
        SigPageCanvas(const std::filesystem::path& output, double page_w, double page_h);
        ~SigPageCanvas();
        SigPageCanvas(const SigPageCanvas&) = delete;
        SigPageCanvas& operator=(const SigPageCanvas&) = delete;

        // Render each job's styled map into its rect (vector), loading `ace` exactly once (a report
        // section page renders ~8 styles from the same chart). `width` is the map render width in
        // device px (as ae::map_draw::export_styled_map).
        void render_maps(const std::filesystem::path& ace, unsigned projection_no, double width, const std::vector<SigMapJob>& jobs);

        // Render `tree` (tal-draw settings file `settings`, page height `image_size`) into the device
        // rectangle (x, y, w, h). Loads the settings + tree and draws via ae::tal::export_tree_into.
        void render_tree(const std::filesystem::path& tree, const std::filesystem::path& settings, double image_size, double x, double y, double w, double h);

        // Finalise the page (cairo_show_page) and write the PDF. Called by the destructor if not
        // already invoked; idempotent.
        void finish();

      private:
        _cairo_surface* surface_{nullptr};
        _cairo* context_{nullptr};
        bool finished_{false};
    };

} // namespace ae::tal

// ======================================================================
