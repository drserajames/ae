#pragma once

#include <filesystem>
#include <map>
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
    // Per-clade overrides (from the settings DSL): a colour string ("#1f77b4" or a
    // name like "blue"; empty = use the default palette) and a display name shown in
    // the clade column / legend (empty = use the clade's own name).
    struct CladeStyle
    {
        std::string color{};
        std::string display_name{};
    };

    struct TreeDrawParameters
    {
        bool labels{false};          // draw each leaf's name to the right of its tip
        bool color_by_clade{false};  // colour leaf edges/labels/dashes by first clade
        bool clades{false};          // draw the clade-sections column
        bool time_series{false};     // draw the time-series dash column
        std::string time_series_interval{"month"}; // year | month | week | day
        std::string time_series_start{};            // optional "YYYY-MM-DD" range start
        std::string time_series_end{};              // optional "YYYY-MM-DD" range end
        std::string title{};         // page title (top, centred); empty = none
        bool legend{false};          // draw a clade colour legend (bottom row)
        bool aa_transitions{false};  // label inodes with their aa-substitution transitions
        std::map<std::string, CladeStyle> clade_styles{}; // clade name -> override
    };

    // Render `tree` to a square PDF of side `image_size` device units. Takes
    // Tree& because layout computes cumulative edges.
    void export_tree_pdf(ae::tree::Tree& tree, const std::filesystem::path& output, double image_size = 1000.0, const TreeDrawParameters& params = {});

} // namespace ae::tal

// ======================================================================
