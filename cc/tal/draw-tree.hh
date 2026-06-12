#pragma once

#include <filesystem>
#include <string>

// ======================================================================
// TAL (subsystem #3) — Phase B: render a phylogenetic tree (+ aligned columns)
// to PDF.
//
// M1 drew the tree itself (edge segments + inode connectors, optional labels).
// M2 adds, as columns aligned to the tree's leaf rows: per-leaf coloring by
// clade, a clade-sections column (bars from compute_clade_sections), and a
// time-series dash column (per-leaf dashes bucketed by compute_time_series).
//
// Reuses ae::tal::compute_layout / compute_clade_sections / compute_time_series
// (Phase A) and the ae::draw::CairoPdf surface from subsystem #1 — only its
// existing line()/text() primitives, so no surface change is needed. Cairo is
// linked only into the `tal-draw` executable, never into libae/ae_backend.
// See cc/tal/PORTING.md.
// ======================================================================

namespace ae::tree
{
    class Tree;
}

namespace ae::tal
{
    struct TreeDrawParameters
    {
        bool labels{false};          // draw each leaf's name to the right of its tip
        bool color_by_clade{false};  // colour leaf edges/labels/dashes by first clade
        bool clades{false};          // draw the clade-sections column
        bool time_series{false};     // draw the time-series dash column
        std::string time_series_interval{"month"}; // year | month | week | day
    };

    // Render `tree` to a square PDF of side `image_size` device units. Takes
    // Tree& because layout computes cumulative edges.
    void export_tree_pdf(ae::tree::Tree& tree, const std::filesystem::path& output, double image_size = 1000.0, const TreeDrawParameters& params = {});

} // namespace ae::tal

// ======================================================================
