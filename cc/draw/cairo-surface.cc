#include <numbers>

#include <cairo.h>
#include <cairo-pdf.h>

#include "draw/cairo-surface.hh"

// ----------------------------------------------------------------------

namespace ae::draw
{
    static inline void set_source(_cairo* cr, Color color)
    {
        cairo_set_source_rgba(cr, color.red(), color.green(), color.blue(), color.alpha());
    }

    CairoPdf::CairoPdf(const std::filesystem::path& filename, double width, double height)
        : surface_{cairo_pdf_surface_create(filename.c_str(), width, height)}, context_{cairo_create(surface_)}
    {
    }

    CairoPdf::~CairoPdf()
    {
        cairo_destroy(context_);
        cairo_surface_destroy(surface_); // finalizes and writes the PDF to disk
    }

    void CairoPdf::background(Color color)
    {
        cairo_save(context_);
        set_source(context_, color);
        cairo_paint(context_);
        cairo_restore(context_);
    }

    void CairoPdf::circle(double cx, double cy, double radius, Color outline, double outline_width, Color fill)
    {
        cairo_new_path(context_);
        cairo_arc(context_, cx, cy, radius, 0.0, 2.0 * std::numbers::pi);
        if (!fill.is_transparent()) {
            set_source(context_, fill);
            cairo_fill_preserve(context_);
        }
        set_source(context_, outline);
        cairo_set_line_width(context_, outline_width);
        cairo_stroke(context_);
    }

    void CairoPdf::square(double cx, double cy, double side, Color outline, double outline_width, Color fill)
    {
        const double half = side / 2.0;
        cairo_new_path(context_);
        cairo_rectangle(context_, cx - half, cy - half, side, side);
        if (!fill.is_transparent()) {
            set_source(context_, fill);
            cairo_fill_preserve(context_);
        }
        set_source(context_, outline);
        cairo_set_line_width(context_, outline_width);
        cairo_stroke(context_);
    }

} // namespace ae::draw

// ----------------------------------------------------------------------
