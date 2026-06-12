#pragma once

#include <filesystem>

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
        void line(double x1, double y1, double x2, double y2, Color color, double width);

      private:
        _cairo_surface* surface_{nullptr};
        _cairo* context_{nullptr};
    };

} // namespace ae::draw

// ----------------------------------------------------------------------
