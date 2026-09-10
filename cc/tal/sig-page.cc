#include <stdexcept>
#include <string>
#include <string_view>

#include <cairo.h>
#include <cairo-pdf.h>

#include "ext/fmt.hh"
#include "tal/sig-page.hh"
#include "tal/draw-tree.hh"
#include "tal/settings.hh"
#include "tree/tree.hh"
#include "map-draw/draw.hh"
#include "chart/v3/chart.hh"

// ======================================================================
// Fully-vector single-canvas signature-page compositor (sigp-vector). Creates ONE
// cairo_pdf_surface for the whole page and draws the section maps + tree into their
// sub-rectangles as vectors, via ae::map_draw::export_styled_map_into and
// ae::tal::export_tree_into (both target a caller-supplied cairo_t + rect). No PNG
// tiles, no pdfjam/pdflatex, no kateri. See sig-page.hh and SIG-PAGE-COMPOSITOR.md.
// ======================================================================

namespace ae::tal
{
    SigPageCanvas::SigPageCanvas(const std::filesystem::path& output, double page_w, double page_h)
    {
        if (page_w <= 0.0 || page_h <= 0.0)
            throw std::runtime_error{fmt::format("SigPageCanvas: non-positive page size {}x{}", page_w, page_h)};
        surface_ = cairo_pdf_surface_create(output.c_str(), page_w, page_h);
        if (cairo_surface_status(surface_) != CAIRO_STATUS_SUCCESS) {
            const std::string err = cairo_status_to_string(cairo_surface_status(surface_));
            cairo_surface_destroy(surface_);
            surface_ = nullptr;
            throw std::runtime_error{fmt::format("SigPageCanvas: cannot create PDF surface {}: {}", output.string(), err)};
        }
        context_ = cairo_create(surface_);
        // white page background
        cairo_save(context_);
        cairo_set_source_rgb(context_, 1.0, 1.0, 1.0);
        cairo_paint(context_);
        cairo_restore(context_);
    }

    SigPageCanvas::~SigPageCanvas()
    {
        try {
            finish(); // no-op when the caller already finished; a destructor must not throw
        }
        catch (const std::exception& err) {
            fmt::print(stderr, "  [sig-page] WARNING: {}\n", err.what());
        }
        if (context_ != nullptr)
            cairo_destroy(context_);
        if (surface_ != nullptr)
            cairo_surface_destroy(surface_);
    }

    // Cairo latches the first failure into the context/surface and then silently no-ops EVERY
    // subsequent operation, so one bad draw would blank the rest of the page and still leave a
    // plausible-looking PDF. Nothing watches the output on the headless whocc-chains batch path,
    // so turn the latched status into a real error at each step instead.
    void SigPageCanvas::check_status(std::string_view stage) const
    {
        if (const auto status = cairo_status(context_); status != CAIRO_STATUS_SUCCESS)
            throw std::runtime_error{fmt::format("SigPageCanvas: cairo error {}: {}", stage, cairo_status_to_string(status))};
        if (const auto status = cairo_surface_status(surface_); status != CAIRO_STATUS_SUCCESS)
            throw std::runtime_error{fmt::format("SigPageCanvas: cairo surface error {}: {}", stage, cairo_status_to_string(status))};
    }

    void SigPageCanvas::render_maps(const std::filesystem::path& ace, unsigned projection_no, double width, const std::vector<SigMapJob>& jobs)
    {
        const ae::chart::v3::Chart chart{ace}; // loaded ONCE, reused for every style (as export_styled_maps)
        for (const SigMapJob& job : jobs) {
            // Draw the styled map into its rect as a vector (letterboxed inside the cell by
            // export_styled_map_into). A missing/undefined style would draw nothing but must not
            // abort the whole page, so tolerate a per-map failure.
            try {
                ae::map_draw::export_styled_map_into(chart, ae::projection_index{projection_no}, job.style, width, context_, job.x, job.y, job.w, job.h);
            }
            catch (const std::exception& err) {
                fmt::print(stderr, "  [sig-page] WARNING: map style '{}' failed: {}\n", job.style, err.what());
            }
            if (job.frame && job.w > 0.0 && job.h > 0.0) {
                cairo_save(context_);
                cairo_set_source_rgb(context_, 0.0, 0.0, 0.0);
                cairo_set_line_width(context_, 1.0);
                cairo_rectangle(context_, job.x + 0.5, job.y + 0.5, job.w - 1.0, job.h - 1.0); // 0.5px inset = crisp 1px line
                cairo_stroke(context_);
                cairo_restore(context_);
            }
            // Outside the try: a C++ failure in one style is tolerated (above), but a cairo error is
            // not — it would silently swallow every map after this one.
            check_status(fmt::format("rendering map style '{}'", job.style));
        }
    }

    void SigPageCanvas::render_tree(const std::filesystem::path& tree, const std::filesystem::path& settings, double image_size, double x, double y, double w, double h)
    {
        double settings_size = image_size;
        ae::tal::TreeDrawParameters params = ae::tal::load_draw_settings(settings, &settings_size);
        // The caller's image_size is the render height (as the tal-draw positional size overrides the
        // settings' image_size); fall back to the settings value only when the caller passed <= 0.
        const double use_size = image_size > 0.0 ? image_size : settings_size;
        const auto loaded = ae::tree::load(tree);
        ae::tal::export_tree_into(*loaded, context_, x, y, w, h, use_size, params);
        check_status("rendering tree");
    }

    void SigPageCanvas::draw_caption(std::string_view utf8, double x, double y, double w, double h, double font_size)
    {
        if (utf8.empty() || font_size <= 0.0)
            return;
        const std::string str{utf8};
        cairo_save(context_);
        // Helvetica: compose_grid typesets the signature page with sans=True (\usepackage{helvet}).
        cairo_select_font_face(context_, "Helvetica", CAIRO_FONT_SLANT_NORMAL, CAIRO_FONT_WEIGHT_NORMAL);
        cairo_set_font_size(context_, font_size);
        cairo_text_extents_t extents;
        cairo_text_extents(context_, str.c_str(), &extents);
        // cairo_show_text draws from the baseline-left pen origin; shift so the ink box is centred
        // in the rect (LaTeX's \centering under the tree image).
        cairo_move_to(context_, x + (w - extents.width) / 2.0 - extents.x_bearing, y + (h - extents.height) / 2.0 - extents.y_bearing);
        cairo_set_source_rgb(context_, 0.0, 0.0, 0.0);
        cairo_show_text(context_, str.c_str());
        cairo_restore(context_);
        check_status("drawing the tree caption");
    }

    void SigPageCanvas::finish()
    {
        if (finished_ || context_ == nullptr)
            return;
        finished_ = true; // set first: on a throw below the page is still done, do not retry from ~SigPageCanvas
        cairo_show_page(context_);
        cairo_surface_flush(surface_);
        // cairo_surface_finish (not just flush) emits the PDF trailer, so the file is complete when
        // we return rather than only when the surface is destroyed — a caller that keeps the canvas
        // alive (a retained traceback frame, a reference cycle) used to get a truncated PDF. It is
        // idempotent, so the destructor's cairo_surface_destroy remains correct.
        cairo_surface_finish(surface_);
        check_status("finishing the page");
    }

} // namespace ae::tal

// ======================================================================
