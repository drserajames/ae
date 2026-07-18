#include <stdexcept>
#include <string>

#include <cairo.h>
#include <cairo-pdf.h>

#include "ext/fmt.hh"
#include "tal/sig-page.hh"

// ======================================================================
// Single-canvas signature-page compositor (sigp). Paints renderer-produced PNG
// tiles (the tree + each section map) onto ONE cairo_pdf_surface. See sig-page.hh
// and SIG-PAGE-COMPOSITOR.md. Cairo is used directly here (as in cairo-surface.cc);
// this file does NOT modify the shared CairoPdf class.
// ======================================================================

namespace ae::tal
{
    void compose_sig_page(const std::filesystem::path& output, double page_w, double page_h, const std::vector<SigTile>& tiles)
    {
        if (page_w <= 0.0 || page_h <= 0.0)
            throw std::runtime_error{fmt::format("compose_sig_page: non-positive page size {}x{}", page_w, page_h)};

        cairo_surface_t* surface = cairo_pdf_surface_create(output.c_str(), page_w, page_h);
        if (cairo_surface_status(surface) != CAIRO_STATUS_SUCCESS) {
            const std::string err = cairo_status_to_string(cairo_surface_status(surface));
            cairo_surface_destroy(surface);
            throw std::runtime_error{fmt::format("compose_sig_page: cannot create PDF surface {}: {}", output.string(), err)};
        }
        cairo_t* cr = cairo_create(surface);

        // white page background
        cairo_save(cr);
        cairo_set_source_rgb(cr, 1.0, 1.0, 1.0);
        cairo_paint(cr);
        cairo_restore(cr);

        for (const SigTile& tile : tiles) {
            cairo_surface_t* img = cairo_image_surface_create_from_png(tile.png.c_str());
            if (cairo_surface_status(img) != CAIRO_STATUS_SUCCESS) {
                const std::string err = cairo_status_to_string(cairo_surface_status(img));
                cairo_surface_destroy(img);
                cairo_destroy(cr);
                cairo_surface_destroy(surface);
                throw std::runtime_error{fmt::format("compose_sig_page: cannot load tile PNG {}: {}", tile.png.string(), err)};
            }
            const double img_w = static_cast<double>(cairo_image_surface_get_width(img));
            const double img_h = static_cast<double>(cairo_image_surface_get_height(img));
            if (img_w > 0.0 && img_h > 0.0 && tile.w > 0.0 && tile.h > 0.0) {
                cairo_save(cr);
                // Map the tile's pixel box onto its device-pixel rectangle (x, y, w, h),
                // clipped so a slightly-oversized tile can't bleed into a neighbour cell.
                cairo_rectangle(cr, tile.x, tile.y, tile.w, tile.h);
                cairo_clip(cr);
                cairo_translate(cr, tile.x, tile.y);
                cairo_scale(cr, tile.w / img_w, tile.h / img_h);
                cairo_set_source_surface(cr, img, 0.0, 0.0);
                cairo_paint(cr);
                cairo_restore(cr);
            }
            cairo_surface_destroy(img);

            if (tile.frame && tile.w > 0.0 && tile.h > 0.0) {
                cairo_save(cr);
                cairo_set_source_rgb(cr, 0.0, 0.0, 0.0);
                cairo_set_line_width(cr, 1.0);
                // stroke centred on the rect edge (0.5px inset keeps a crisp 1px line)
                cairo_rectangle(cr, tile.x + 0.5, tile.y + 0.5, tile.w - 1.0, tile.h - 1.0);
                cairo_stroke(cr);
                cairo_restore(cr);
            }
        }

        cairo_show_page(cr);
        cairo_destroy(cr);
        cairo_surface_destroy(surface); // finalises + writes the PDF
    }

} // namespace ae::tal

// ======================================================================
