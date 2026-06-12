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

    void CairoPdf::triangle(double cx, double cy, double radius, Color outline, double outline_width, Color fill)
    {
        constexpr double sin60 = 0.86602540378443864676; // sqrt(3)/2
        cairo_new_path(context_);
        cairo_move_to(context_, cx, cy - radius);                       // apex (up; PDF y grows downward)
        cairo_line_to(context_, cx + sin60 * radius, cy + radius / 2.0); // bottom-right
        cairo_line_to(context_, cx - sin60 * radius, cy + radius / 2.0); // bottom-left
        cairo_close_path(context_);
        if (!fill.is_transparent()) {
            set_source(context_, fill);
            cairo_fill_preserve(context_);
        }
        set_source(context_, outline);
        cairo_set_line_width(context_, outline_width);
        cairo_stroke(context_);
    }

    void CairoPdf::line(double x1, double y1, double x2, double y2, Color color, double width)
    {
        cairo_new_path(context_);
        cairo_move_to(context_, x1, y1);
        cairo_line_to(context_, x2, y2);
        set_source(context_, color);
        cairo_set_line_width(context_, width);
        cairo_stroke(context_);
    }

} // namespace ae::draw

// ----------------------------------------------------------------------
