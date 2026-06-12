#include <numbers>
#include <string>

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

    void CairoPdf::text(double x, double y, std::string_view utf8, double font_size, Color color, bool center)
    {
        const std::string str{utf8};
        cairo_select_font_face(context_, "sans-serif", CAIRO_FONT_SLANT_NORMAL, CAIRO_FONT_WEIGHT_NORMAL);
        cairo_set_font_size(context_, font_size);
        cairo_text_extents_t ext;
        cairo_text_extents(context_, str.c_str(), &ext);
        // cairo_show_text places the text origin at the baseline-left; shift so the glyph
        // box lands where we want (centred on, or top-left at, (x, y)).
        const double tx = center ? (x - ext.width / 2.0 - ext.x_bearing) : (x - ext.x_bearing);
        const double ty = center ? (y - ext.height / 2.0 - ext.y_bearing) : (y - ext.y_bearing);
        set_source(context_, color);
        cairo_move_to(context_, tx, ty);
        cairo_show_text(context_, str.c_str());
    }

    std::pair<double, double> CairoPdf::text_size(std::string_view utf8, double font_size)
    {
        const std::string str{utf8};
        cairo_select_font_face(context_, "sans-serif", CAIRO_FONT_SLANT_NORMAL, CAIRO_FONT_WEIGHT_NORMAL);
        cairo_set_font_size(context_, font_size);
        cairo_text_extents_t ext;
        cairo_text_extents(context_, str.c_str(), &ext);
        return {ext.width, ext.height};
    }

} // namespace ae::draw

// ----------------------------------------------------------------------
