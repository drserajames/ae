#pragma once

#include <filesystem>
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
    // Minimal Cairo PDF drawing surface — the first slice of the acmacs-draw
    // port (see TODO.md subsystem #1). All coordinates and sizes are in device
    // units (PDF points); the caller maps chart coordinates to device coordinates.
    class CairoPdf
    {
      public:
        CairoPdf(const std::filesystem::path& filename, double width, double height);
        ~CairoPdf();
        CairoPdf(const CairoPdf&) = delete;
        CairoPdf(CairoPdf&&) = delete;
        CairoPdf& operator=(const CairoPdf&) = delete;
        CairoPdf& operator=(CairoPdf&&) = delete;

        void background(Color color);
        // For the shapes below, a transparent fill (Color::is_transparent()) is not painted,
        // giving an outline-only shape.
        void circle(double cx, double cy, double radius, Color outline, double outline_width, Color fill);
        void square(double cx, double cy, double side, Color outline, double outline_width, Color fill);
        void triangle(double cx, double cy, double radius, Color outline, double outline_width, Color fill); // equilateral, point up
        // Axis-aligned rectangle with its top-left corner at (x, y). Transparent fill = outline only.
        void rectangle(double x, double y, double width, double height, Color outline, double outline_width, Color fill);
        void line(double x1, double y1, double x2, double y2, Color color, double width);
        // Draw a multi-subpath path in the "negative-move" convention: [first, last) is a flat
        // double array (stride 2 = {x, y}); a pair with x < 0 starts a new subpath (move-to at
        // {|x|, y}), x >= 0 is a line-to. Transparent fill / non-positive outline width are skipped.
        void path_negative_move(const double* first, const double* last, Color outline, double outline_width, Color fill);
        // Draw UTF-8 text via Cairo's built-in font API. When center is true the text's
        // bounding box is centred on (x, y); otherwise (x, y) is the box's top-left.
        void text(double x, double y, std::string_view utf8, double font_size, Color color, bool center = true);
        // Draw UTF-8 text rotated by angle_degrees (positive = clockwise; -90 reads upward)
        // about (x, y), with (x, y) as the baseline-left anchor of the first glyph.
        void text_rotated(double x, double y, std::string_view utf8, double font_size, Color color, double angle_degrees);
        // Measure a string at the given font size: returns {width, height} in device units.
        std::pair<double, double> text_size(std::string_view utf8, double font_size);

      private:
        _cairo_surface* surface_{nullptr};
        _cairo* context_{nullptr};
    };

} // namespace ae::draw

// ----------------------------------------------------------------------
