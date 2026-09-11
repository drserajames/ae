#pragma once

#include <filesystem>
#include <string>
#include <string_view>
#include <utility>

#include "ad/color.hh"

// Forward declarations of the opaque Cairo types keep the Cairo headers
// confined to cairo-surface.cc (they are `typedef struct _cairo cairo_t;` etc).
struct _cairo;
struct _cairo_surface;

// ----------------------------------------------------------------------

namespace ae::draw
{
    // Minimal Cairo drawing surface — the first slice of the acmacs-draw
    // port (see TODO.md subsystem #1). All coordinates and sizes are in device
    // units (PDF points); the caller maps chart coordinates to device coordinates.
    // The output backend is selected by the filename extension: ".png" writes a
    // raster image (finalised on destruction), any other extension writes a vector
    // PDF. (The class name is historical; it drives both backends.)
    class CairoPdf
    {
      public:
        CairoPdf(const std::filesystem::path& filename, double width, double height);
        // Borrowed-context constructor (single-canvas compositor): draw into a sub-rectangle of a
        // caller-supplied cairo_t (a shared page surface) instead of creating an owned surface. The
        // drawing coordinate space is [0, logical_w] x [0, logical_h]; it is mapped (device-space
        // translate + scale) onto the device rectangle (dst_x, dst_y, dst_w, dst_h) of `context` and
        // clipped to it, so every existing draw primitive lands inside that rect. The context and its
        // surface are NOT owned: the destructor restores the saved graphics state and leaves them
        // intact (the caller finalises/writes the page). All other methods are unchanged. Used by the
        // fully-vector signature-page compositor to place the tree + each section map onto one page.
        CairoPdf(_cairo* context, double dst_x, double dst_y, double dst_w, double dst_h, double logical_w, double logical_h);
        ~CairoPdf();
        CairoPdf(const CairoPdf&) = delete;
        CairoPdf(CairoPdf&&) = delete;
        CairoPdf& operator=(const CairoPdf&) = delete;
        CairoPdf& operator=(CairoPdf&&) = delete;

        void background(Color color);
        // For the shapes below, a transparent fill (Color::is_transparent()) is not painted,
        // giving an outline-only shape.
        void circle(double cx, double cy, double radius, Color outline, double outline_width, Color fill);
        // Filled circular sector (pie wedge): the slice of the disc of `radius` centred at
        // (cx, cy) between `start_angle` and `end_angle` (radians, measured clockwise from
        // 12 o'clock in the PDF coordinate system where y grows downward). The path runs
        // centre -> arc -> centre, so the wedge is closed. Transparent fill = outline only;
        // non-positive outline width / transparent outline skips the stroke.
        void sector(double cx, double cy, double radius, double start_angle, double end_angle, Color outline, double outline_width, Color fill);
        // Open circular arc stroke (no fill, no radius lines to centre): the arc of the circle
        // of `radius` centred at (cx, cy) from `start_angle` to `end_angle` (same clockwise-from-
        // 12-o'clock convention as sector()). Used to build kateri's dashed serum circles, whose
        // outline is a set of short arcs (unlike sector(), which closes the path to the centre).
        void arc(double cx, double cy, double radius, double start_angle, double end_angle, Color outline, double outline_width);
        void square(double cx, double cy, double side, Color outline, double outline_width, Color fill);
        void triangle(double cx, double cy, double radius, Color outline, double outline_width, Color fill); // equilateral, point up
        // Egg (kateri PointShape.egg): a closed two-bezier egg of the given `size` (bounding
        // diameter) centred at (cx, cy), reproducing kateri _drawShape's control points so a
        // native render matches the kateri golden exactly. Transparent fill = outline only.
        void egg(double cx, double cy, double size, Color outline, double outline_width, Color fill);
        void filled_triangle(double x0, double y0, double x1, double y1, double x2, double y2, Color fill); // arbitrary filled triangle
        // Axis-aligned rectangle with its top-left corner at (x, y). Transparent fill = outline only.
        void rectangle(double x, double y, double width, double height, Color outline, double outline_width, Color fill);
        void line(double x1, double y1, double x2, double y2, Color color, double width);
        // Draw a multi-subpath path in the "negative-move" convention: [first, last) is a flat
        // double array (stride 2 = {x, y}); a pair with x < 0 starts a new subpath (move-to at
        // {|x|, y}), x >= 0 is a line-to. Transparent fill / non-positive outline width are skipped.
        void path_negative_move(const double* first, const double* last, Color outline, double outline_width, Color fill);
        // Single-subpath polygon/polyline: [first, last) is a flat double array (stride 2 =
        // {x, y}), every pair a vertex. `close` closes the outline back to the first vertex.
        // Unlike path_negative_move() no coordinate is overloaded as a subpath marker, so a
        // vertex at x == 0 (a legal device coordinate) is drawn rather than read as a move-to.
        // Transparent fill / non-positive outline width are skipped; a fill is always taken
        // over the implicitly-closed path, as Cairo does.
        void polygon(const double* first, const double* last, bool close, Color outline, double outline_width, Color fill);
        // Draw UTF-8 text via Cairo's built-in font API. When center is true the text's
        // bounding box is centred on (x, y); otherwise (x, y) is the box's top-left.
        // halo_width > 0 strokes a halo (default white) behind the glyphs so an underlying
        // line/bracket is masked and the text stands out (halo_width = stroke radius in device units).
        void text(double x, double y, std::string_view utf8, double font_size, Color color, bool center = true, bool monospace = false,
                  double halo_width = 0.0, Color halo_color = WHITE);
        // Draw UTF-8 text rotated by angle_degrees (positive = clockwise; -90 reads upward)
        // about (x, y), with (x, y) as the baseline-left anchor of the first glyph. halo_width > 0
        // strokes a halo (default white) behind the glyphs (see text()).
        void text_rotated(double x, double y, std::string_view utf8, double font_size, Color color, double angle_degrees,
                          double halo_width = 0.0, Color halo_color = WHITE);
        // Like text(center=false) but with selectable weight/slant (for the semantic-style
        // title/legend, which carry helvetica bold/italic). (x, y) is the glyph-box top-left.
        // halo_width > 0 strokes a halo (default white) behind the glyphs, so point labels stay
        // legible over the point cloud (kateri's default point-label halo). halo_width is the full
        // stroke width in font-size units (scaled internally to match the glyph), not a radius.
        void text_font(double x, double y, std::string_view utf8, double font_size, Color color, bool bold, bool italic,
                       double halo_width = 0.0, Color halo_color = WHITE);
        // Measure a string at the given font size: returns {width, height} in device units.
        // `helvetica` selects the Helvetica face (matching text_font) so callers that draw with
        // text_font size their boxes/rows from the same metrics; default keeps the sans-serif face.
        std::pair<double, double> text_size(std::string_view utf8, double font_size, bool helvetica = false);
        // Where this particular string's INK sits about its baseline: {above, below}, both >= 0.
        // text_size's height is the em (kateri's convention), which for the usual all-caps/digit
        // strings is a good deal taller than the glyphs; a caller that has to fit text into a tight
        // shape (the map renderer's `inside` point labels) needs the real extent instead.
        std::pair<double, double> text_ink_height(std::string_view utf8, double font_size, bool helvetica = false);

      private:
        _cairo_surface* surface_{nullptr};
        _cairo* context_{nullptr};
        std::string png_filename_{}; // non-empty => PNG backend; written on destruction
        bool borrowed_{false};       // true => context_ is caller-owned (sub-rect draw); dtor only restores, never destroys
    };

} // namespace ae::draw

// ----------------------------------------------------------------------
