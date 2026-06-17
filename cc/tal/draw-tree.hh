#pragma once

#include <cstddef>
#include <filesystem>
#include <map>
#include <optional>
#include <string>
#include <vector>

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
        bool hide{false}; // suppress this clade's bar + label from the clades column / legend (acmacs-tal per-clade show:false)
    };

    // A node-select / node-apply mod — the core of the acmacs-tal settings pipeline.
    // A node matches when every set criterion holds (empty criteria match anything).
    struct NodeSelect
    {
        std::vector<std::string> seq_id{};      // leaf-name is one of these (leaves only)
        std::optional<double> cumulative_min{}; // node cumulative edge length >= this
        std::optional<double> edge_min{};       // node's own edge length >= this (hide long-edge outliers)
        std::string date_min{};                 // leaf date >= this "YYYY-MM-DD" (leaves only)
        std::string date_max{};                 // leaf date <  this "YYYY-MM-DD" (leaves only)
    };

    // A positioned text label drawn at a leaf's tip (acmacs-tal DrawOnTree / nodes apply.text).
    // Offsets and size are fractions of image_size; offset is relative to the leaf tip
    // (default places the text just to its right).
    struct NodeText
    {
        std::string text{};         // the label string
        double offset_x{0.01};      // x offset from the leaf tip, fraction of image_size
        double offset_y{0.0};       // y offset, fraction of image_size (down is positive)
        std::string color{};        // "" -> black
        double size{0.0};           // font size as fraction of image_size; 0 -> default leaf font
    };

    struct NodeApply
    {
        std::optional<bool> hide{};       // hide the node (and its subtree) from the layout
        std::string edge_color{};         // recolour the node's edge line ("#rrggbb"/name)
        std::string label_color{};        // recolour the leaf label (leaves only)
        std::optional<double> label_scale{}; // scale the leaf-label font (leaves only)
        std::optional<NodeText> text{};   // positioned text label at the leaf tip (leaves only)
    };

    struct NodeMod
    {
        NodeSelect select{};
        NodeApply apply{};
    };

    // A per-leaf dash column keyed by the amino acid at a position (acmacs-tal
    // dash-bar-aa-at). Each shown leaf gets a dash coloured by its aa at `pos` (1-based):
    // by `colors_by_aa` when given, else by frequency (most common = grey, variants pop).
    struct DashBarAAAt
    {
        int pos{0};
        std::map<char, std::string> colors_by_aa{}; // aa char -> colour string ("#rrggbb"/name)
    };

    // A horizontal section of the tree (acmacs-tal hz-sections): the contiguous run of
    // leaves from `first` to `last` (by seq_id), labelled with `label` in a left marker
    // column, with a separator line across the tree at the section's top boundary.
    struct HzSection
    {
        std::string first{};
        std::string last{};
        std::string label{};
    };

    struct TreeDrawParameters
    {
        // Overall page aspect (width / height). When > 0 the canvas is drawn portrait —
        // width = height * width_to_height_ratio — instead of square (acmacs-tal sizes the
        // canvas width from the tree's width-to-height-ratio plus the right-hand columns;
        // the report .tal's give the tree ratio ~0.4, columns push the page to ~0.63).
        // 0 (default) keeps the historical square canvas.
        double width_to_height_ratio{0.0};
        bool labels{false};                  // draw each leaf's name to the right of its tip
        bool labels_avoid_collisions{true};  // suppress leaf labels that would overlap the one above
        bool color_by_clade{false};  // colour leaf edges/labels/dashes by first clade
        bool color_by_continent{false}; // colour leaves by geographic continent (acmacs-tal color-by continent)
        int color_by_pos{0};         // colour leaves by amino acid at this 1-based position (0 = off)
        std::map<char, std::string> color_by_pos_colors{}; // aa char -> colour for color_by_pos; empty = colour by frequency
        bool clades{false};          // draw the clade-sections column
        bool time_series{false};     // draw the time-series dash column
        std::string time_series_interval{"month"}; // year | month | week | day
        std::string time_series_start{};            // optional "YYYY-MM-DD" range start
        std::string time_series_end{};              // optional "YYYY-MM-DD" range end
        std::string title{};         // page title (top, centred); empty = none
        bool legend{false};          // draw a clade colour legend (bottom row)
        bool geo_inset{false};       // draw the continent-coloured world-map inset (lower-left); doubles as the continent legend (acmacs-tal LegendContinentMap)
        bool aa_transitions{false};  // label inodes with their aa-substitution transitions
        bool aa_transitions_compute{false}; // compute the transitions first (consensus) instead of using the tree's stored ones
        double aa_transitions_tolerance{0.6}; // consensus non-common tolerance (when computing)
        int aa_transitions_min_leaves{1};   // only label an inode's transitions if its subtree has >= this many leaves
        std::map<std::string, CladeStyle> clade_styles{}; // clade name -> override
        std::vector<NodeMod> node_mods{};                 // select/apply mods, applied in order
        std::vector<HzSection> hz_sections{};             // horizontal section bands (left marker column)
        std::vector<DashBarAAAt> dash_bars{};             // per-leaf aa-at-position dash columns
    };

    // Render `tree` to a PDF whose height is `image_size` device units. The width is
    // `image_size` (square) unless params.width_to_height_ratio > 0, in which case the
    // page is portrait (width = image_size * width_to_height_ratio). Takes Tree& because
    // layout computes cumulative edges. Returns the number of leaf labels suppressed by
    // collision avoidance (0 when disabled or none overlap).
    std::size_t export_tree_pdf(ae::tree::Tree& tree, const std::filesystem::path& output, double image_size = 1000.0, const TreeDrawParameters& params = {});

} // namespace ae::tal

// ======================================================================
