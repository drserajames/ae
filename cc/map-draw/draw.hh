#pragma once

#include <filesystem>

#include "chart/v3/index.hh"

// ----------------------------------------------------------------------

namespace ae::chart::v3
{
    class Chart;
}

namespace ae::map_draw
{
    // Minimal antigenic-map renderer — M1 vertical slice of the acmacs-map-draw
    // port (see TODO.md subsystem #1). Draws one projection's antigen points
    // (filled circle = test, open circle = reference) and serum points (open
    // square) to a PDF. No labels, legend, serum circles or the mapi settings
    // DSL yet — those are later milestones.
    void export_pdf(const ae::chart::v3::Chart& chart, ae::projection_index projection_no,
                    const std::filesystem::path& output, double image_size = 800.0, bool label_points = false,
                    bool draw_serum_circles = false);

} // namespace ae::map_draw

// ----------------------------------------------------------------------
