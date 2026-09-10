#include <algorithm>
#include <numbers>
#include <string>

#include <cairo.h>
#include <cairo-pdf.h>

#include "draw/cairo-surface.hh"

// ----------------------------------------------------------------------

namespace ae::draw
{
    // kateri renders map text 2% larger than the nominal size (PdfGraphics.fontScaleToMatchCanvas,
    // draw_on_pdf.dart) so its PDF text matches its on-screen canvas. The report's golden PDFs carry
    // that factor, so the semantic-style text primitives (text_font / helvetica text_size) apply it
    // too — both the drawn glyphs and the metrics the callers size their boxes from — to land on the
    // golden's glyph pixels rather than ~2% short.
    static constexpr double kFontScaleToMatchCanvas = 1.02;

    static inline void set_source(_cairo* cr, Color color)
    {
        cairo_set_source_rgba(cr, color.red(), color.green(), color.blue(), color.alpha());
    }

    // The backend is chosen by the output extension: ".png" -> raster image surface
    // (finalised with cairo_surface_write_to_png in the destructor); anything else ->
    // vector PDF surface (as before — tal-draw / geo-draw are unaffected). Device
    // coordinates are identical for both backends.
    CairoPdf::CairoPdf(const std::filesystem::path& filename, double width, double height)
    {
        if (filename.extension() == ".png") {
            png_filename_ = filename.string();
            surface_ = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, static_cast<int>(width), static_cast<int>(height));
        }
        else {
            surface_ = cairo_pdf_surface_create(filename.c_str(), width, height);
        }
        context_ = cairo_create(surface_);
    }

    // Borrowed-context constructor (single-canvas compositor). context_ is the caller's cairo_t
    // (a shared page surface); we neither create nor destroy it. We save its graphics state and
    // set a device-space transform (translate to the sub-rect origin, then scale so the logical
    // [0,logical_w]x[0,logical_h] box fills the (dst_w, dst_h) rect) plus a clip to that rect, so
    // every draw primitive below lands inside (dst_x, dst_y, dst_w, dst_h). The destructor
    // restores the saved state, leaving the caller's context/surface untouched.
    CairoPdf::CairoPdf(_cairo* context, double dst_x, double dst_y, double dst_w, double dst_h, double logical_w, double logical_h)
        : borrowed_{true}
    {
        surface_ = nullptr; // not owned; never destroyed
        context_ = context;
        cairo_save(context_);
        cairo_translate(context_, dst_x, dst_y);
        if (logical_w > 0.0 && logical_h > 0.0)
            cairo_scale(context_, dst_w / logical_w, dst_h / logical_h);
        cairo_rectangle(context_, 0.0, 0.0, logical_w, logical_h);
        cairo_clip(context_);
        cairo_new_path(context_);
    }

    CairoPdf::~CairoPdf()
    {
        if (borrowed_) {
            cairo_restore(context_); // caller owns context_ + its surface; only undo our save/transform/clip
            return;
        }
        if (!png_filename_.empty()) {
            cairo_surface_flush(surface_);
            cairo_surface_write_to_png(surface_, png_filename_.c_str());
        }
        cairo_destroy(context_);
        cairo_surface_destroy(surface_); // finalizes and writes the PDF to disk (for the PDF backend)
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
        if (fill.alpha() > 0.0) { // draw translucent fills too; skip only fully-transparent
            set_source(context_, fill);
            cairo_fill_preserve(context_);
        }
        if (outline_width > 0.0 && !outline.is_transparent()) {
            set_source(context_, outline);
            cairo_set_line_width(context_, outline_width);
            cairo_stroke(context_);
        }
        else
            cairo_new_path(context_); // discard the preserved path if we didn't stroke
    }

    void CairoPdf::sector(double cx, double cy, double radius, double start_angle, double end_angle, Color outline, double outline_width, Color fill)
    {
        // The caller's angles are measured clockwise from 12 o'clock. In Cairo, angle 0 is
        // the +x axis (3 o'clock) and cairo_arc sweeps in the direction of increasing angle,
        // which is clockwise in the PDF device space (y grows downward). So 12 o'clock is at
        // Cairo angle -pi/2 and a clockwise sweep maps directly onto cairo_arc.
        constexpr double twelve_oclock = -std::numbers::pi / 2.0;
        const double a0 = twelve_oclock + start_angle;
        const double a1 = twelve_oclock + end_angle;
        cairo_new_path(context_);
        cairo_move_to(context_, cx, cy);
        cairo_arc(context_, cx, cy, radius, a0, a1);
        cairo_close_path(context_);
        if (fill.alpha() > 0.0) { // draw translucent fills too; skip only fully-transparent
            set_source(context_, fill);
            cairo_fill_preserve(context_);
        }
        if (outline_width > 0.0 && !outline.is_transparent()) {
            set_source(context_, outline);
            cairo_set_line_width(context_, outline_width);
            cairo_stroke(context_);
        }
        else
            cairo_new_path(context_); // discard the preserved path if we didn't stroke
    }

    void CairoPdf::arc(double cx, double cy, double radius, double start_angle, double end_angle, Color outline, double outline_width)
    {
        if (outline_width <= 0.0 || outline.is_transparent())
            return;
        constexpr double twelve_oclock = -std::numbers::pi / 2.0;
        cairo_new_path(context_);
        cairo_arc(context_, cx, cy, radius, twelve_oclock + start_angle, twelve_oclock + end_angle);
        set_source(context_, outline);
        cairo_set_line_width(context_, outline_width);
        cairo_stroke(context_);
    }

    void CairoPdf::square(double cx, double cy, double side, Color outline, double outline_width, Color fill)
    {
        const double half = side / 2.0;
        cairo_new_path(context_);
        cairo_rectangle(context_, cx - half, cy - half, side, side);
        if (fill.alpha() > 0.0) { // draw translucent fills too; skip only fully-transparent
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
        if (fill.alpha() > 0.0) { // draw translucent fills too; skip only fully-transparent
            set_source(context_, fill);
            cairo_fill_preserve(context_);
        }
        set_source(context_, outline);
        cairo_set_line_width(context_, outline_width);
        cairo_stroke(context_);
    }

    void CairoPdf::egg(double cx, double cy, double size, Color outline, double outline_width, Color fill)
    {
        // Reproduces kateri's _drawShape egg (draw_on_pdf.dart): two cubic beziers between the
        // top (0, -r) and bottom (0, +r) apexes, y growing downward (matches our device space,
        // no Y-flip). r = size/2.
        const double r = size / 2.0;
        cairo_new_path(context_);
        cairo_move_to(context_, cx + 0.0, cy + r);
        cairo_curve_to(context_, cx + r * 1.4, cy + r * 0.95, cx + r * 0.8, cy - r * 0.98, cx + 0.0, cy - r);
        cairo_curve_to(context_, cx - r * 0.8, cy - r * 0.98, cx - r * 1.4, cy + r * 0.95, cx + 0.0, cy + r);
        cairo_close_path(context_);
        if (fill.alpha() > 0.0) { // draw translucent fills too; skip only fully-transparent
            set_source(context_, fill);
            cairo_fill_preserve(context_);
        }
        if (outline_width > 0.0 && !outline.is_transparent()) {
            set_source(context_, outline);
            cairo_set_line_width(context_, outline_width);
            cairo_stroke(context_);
        }
        else
            cairo_new_path(context_);
    }

    void CairoPdf::filled_triangle(double x0, double y0, double x1, double y1, double x2, double y2, Color fill)
    {
        cairo_new_path(context_);
        cairo_move_to(context_, x0, y0);
        cairo_line_to(context_, x1, y1);
        cairo_line_to(context_, x2, y2);
        cairo_close_path(context_);
        set_source(context_, fill);
        cairo_fill(context_);
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

    void CairoPdf::path_negative_move(const double* first, const double* last, Color outline, double outline_width, Color fill)
    {
        cairo_new_path(context_);
        for (const double* p = first; p + 1 < last; p += 2) {
            if (p[0] < 0.0)
                cairo_move_to(context_, -p[0], p[1]);
            else
                cairo_line_to(context_, p[0], p[1]);
        }
        if (fill.alpha() > 0.0) { // draw translucent fills too; skip only fully-transparent
            set_source(context_, fill);
            cairo_fill_preserve(context_);
        }
        if (outline_width > 0.0 && !outline.is_transparent()) {
            set_source(context_, outline);
            cairo_set_line_width(context_, outline_width);
            cairo_stroke(context_);
        }
    }

    void CairoPdf::rectangle(double x, double y, double width, double height, Color outline, double outline_width, Color fill)
    {
        cairo_new_path(context_);
        cairo_rectangle(context_, x, y, width, height);
        const bool stroke = outline_width > 0.0 && !outline.is_transparent();
        if (fill.alpha() > 0.0) { // draw translucent fills too; skip only fully-transparent
            set_source(context_, fill);
            if (stroke)
                cairo_fill_preserve(context_);
            else
                cairo_fill(context_);
        }
        if (stroke) {
            set_source(context_, outline);
            cairo_set_line_width(context_, outline_width);
            cairo_stroke(context_);
        }
    }

    void CairoPdf::text_rotated(double x, double y, std::string_view utf8, double font_size, Color color, double angle_degrees,
                                double halo_width, Color halo_color)
    {
        const std::string str{utf8};
        cairo_save(context_);
        cairo_select_font_face(context_, "sans-serif", CAIRO_FONT_SLANT_NORMAL, CAIRO_FONT_WEIGHT_NORMAL);
        cairo_set_font_size(context_, font_size);
        cairo_translate(context_, x, y);
        cairo_rotate(context_, angle_degrees * std::numbers::pi / 180.0);
        cairo_move_to(context_, 0.0, 0.0);
        if (halo_width > 0.0) {
            // stroke the glyph outlines in the halo colour first (rounded joins so the halo is a
            // smooth band), then fill the glyphs on top — masks any line/bracket behind the text.
            cairo_text_path(context_, str.c_str());
            set_source(context_, halo_color);
            cairo_set_line_width(context_, halo_width * 2.0);
            cairo_set_line_join(context_, CAIRO_LINE_JOIN_ROUND);
            cairo_stroke_preserve(context_);
            set_source(context_, color);
            cairo_fill(context_);
        }
        else {
            set_source(context_, color);
            cairo_show_text(context_, str.c_str());
        }
        cairo_restore(context_);
    }

    void CairoPdf::text(double x, double y, std::string_view utf8, double font_size, Color color, bool center, bool monospace,
                        double halo_width, Color halo_color)
    {
        const std::string str{utf8};
        cairo_select_font_face(context_, monospace ? "monospace" : "sans-serif", CAIRO_FONT_SLANT_NORMAL, CAIRO_FONT_WEIGHT_NORMAL);
        cairo_set_font_size(context_, font_size);
        cairo_text_extents_t ext;
        cairo_text_extents(context_, str.c_str(), &ext);
        // cairo_show_text places the text origin at the baseline-left; shift so the glyph
        // box lands where we want (centred on, or top-left at, (x, y)).
        const double tx = center ? (x - ext.width / 2.0 - ext.x_bearing) : (x - ext.x_bearing);
        const double ty = center ? (y - ext.height / 2.0 - ext.y_bearing) : (y - ext.y_bearing);
        cairo_move_to(context_, tx, ty);
        if (halo_width > 0.0) {
            cairo_text_path(context_, str.c_str());
            set_source(context_, halo_color);
            cairo_set_line_width(context_, halo_width * 2.0);
            cairo_set_line_join(context_, CAIRO_LINE_JOIN_ROUND);
            cairo_stroke_preserve(context_);
            set_source(context_, color);
            cairo_fill(context_);
        }
        else {
            set_source(context_, color);
            cairo_move_to(context_, tx, ty);
            cairo_show_text(context_, str.c_str());
        }
    }

    void CairoPdf::text_font(double x, double y, std::string_view utf8, double font_size, Color color, bool bold, bool italic,
                             double halo_width, Color halo_color)
    {
        // Baseline-origin anchor (matches kateri drawString at (origin.dx, origin.dy)): (x, y) is
        // the pen origin — baseline at y, first glyph's pen position at x (ink starts at
        // x + left-side-bearing, exactly as the golden's drawString does).
        const std::string str{utf8};
        // kateri renders Latin1 text in Helvetica (Type1); use the same face so the native
        // render's title/legend/labels match the golden's glyph shapes/metrics. On this
        // toolchain cairo's toy "Helvetica" resolves (via fontconfig) to the same face poppler
        // substitutes for the golden PDF's non-embedded base-14 Helvetica, so an embedded
        // subset rasterises pixel-identically — the remaining tail is glyph *placement*.
        cairo_select_font_face(context_, "Helvetica", italic ? CAIRO_FONT_SLANT_ITALIC : CAIRO_FONT_SLANT_NORMAL, bold ? CAIRO_FONT_WEIGHT_BOLD : CAIRO_FONT_WEIGHT_NORMAL);
        cairo_set_font_size(context_, font_size * kFontScaleToMatchCanvas);
        // kateri's PdfGraphics.drawString anchors the glyph *pen origin* (baseline-left) at the
        // supplied point — it does NOT shift by the first glyph's left side-bearing. Match that
        // (a prior x_bearing subtraction pushed every string ~1px left of the golden).
        cairo_move_to(context_, x, y);
        if (halo_width > 0.0) {
            // kateri addPointLabel halo: stroke the glyph outlines in the halo colour first (round
            // joins for a smooth band, scaled with the glyph), then fill the glyphs on top so the
            // label reads over the point cloud (drawString stroke pass under the fill).
            cairo_text_path(context_, str.c_str());
            set_source(context_, halo_color);
            cairo_set_line_width(context_, halo_width * kFontScaleToMatchCanvas);
            cairo_set_line_join(context_, CAIRO_LINE_JOIN_MITER); // match kateri PDF default halo join
            cairo_stroke_preserve(context_);
            set_source(context_, color);
            cairo_fill(context_);
        }
        else {
            set_source(context_, color);
            cairo_show_text(context_, str.c_str());
        }
    }

    std::pair<double, double> CairoPdf::text_size(std::string_view utf8, double font_size, bool helvetica)
    {
        const std::string str{utf8};
        if (helvetica) {
            // Match kateri's PdfGraphics.textSize so callers (title box, legend rows) lay text out
            // exactly where the golden has it: width = the font's *advance* width (kateri uses the
            // base-14 AFM metrics.width, i.e. the pen advance, not the ink extent), height = the
            // em size itself (kateri hard-codes textSize height to 1.0*fontSize, not the 1.156 line
            // height nor the ink height). Both scaled by fontScaleToMatchCanvas, as kateri does.
            cairo_select_font_face(context_, "Helvetica", CAIRO_FONT_SLANT_NORMAL, CAIRO_FONT_WEIGHT_NORMAL);
            const double scaled = font_size * kFontScaleToMatchCanvas;
            cairo_set_font_size(context_, scaled);
            cairo_text_extents_t ext;
            cairo_text_extents(context_, str.c_str(), &ext);
            return {ext.x_advance, scaled};
        }
        cairo_select_font_face(context_, "sans-serif", CAIRO_FONT_SLANT_NORMAL, CAIRO_FONT_WEIGHT_NORMAL);
        cairo_set_font_size(context_, font_size);
        cairo_text_extents_t ext;
        cairo_text_extents(context_, str.c_str(), &ext);
        return {ext.width, ext.height};
    }

    std::pair<double, double> CairoPdf::text_ink_height(std::string_view utf8, double font_size, bool helvetica)
    {
        const std::string str{utf8};
        // Same face and same fontScaleToMatchCanvas as text_size/text_font, so the extents describe
        // the glyphs those two would lay down. cairo's y_bearing is the ink top measured from the
        // baseline with y growing DOWN, i.e. negative for anything above it.
        const double scaled = helvetica ? font_size * kFontScaleToMatchCanvas : font_size;
        cairo_select_font_face(context_, helvetica ? "Helvetica" : "sans-serif", CAIRO_FONT_SLANT_NORMAL, CAIRO_FONT_WEIGHT_NORMAL);
        cairo_set_font_size(context_, scaled);
        cairo_text_extents_t ext;
        cairo_text_extents(context_, str.c_str(), &ext);
        return {std::max(0.0, -ext.y_bearing), std::max(0.0, ext.y_bearing + ext.height)};
    }

} // namespace ae::draw

// ----------------------------------------------------------------------
