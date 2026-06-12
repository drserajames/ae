#pragma once

#include <string>
#include <vector>

#include "tree/tree-iterator.hh" // node_index_base_t

// ======================================================================
// TAL (subsystem #3) — headless tree layout.
//
// Computes per-node drawing positions from the tree topology, with no
// dependency on the (not-yet-ported) Cairo Surface backend. This is the
// "tree layout (node positions)" milestone of the Phase A headless port
// described in cc/tal/PORTING.md.
//
//   y (vertical)   — cumulative vertical offset: shown leaves are stacked one
//                    per `default_vertical_offset`; an inode sits at the
//                    midpoint of its first and last shown children. This is a
//                    port of acmacs-tal Tree::compute_cumulative_vertical_offsets().
//   x (horizontal) — cumulative edge length from the root (reuses
//                    ae::tree::Tree::calculate_cumulative()).
//
// The drawing step that turns these positions into lines/labels on a surface
// is Phase B and is blocked on subsystem #1 — see cc/tal/PORTING.md.
// ======================================================================

namespace ae::tree
{
    class Tree;
}

namespace ae::tal
{
    // Default per-leaf vertical spacing (matches acmacs-tal default_vertical_offset).
    constexpr double default_vertical_offset{1.0};

    struct NodeLayout
    {
        ae::tree::node_index_base_t node{0}; // tree node index (positive: leaf, <=0: inode)
        std::string name{};                  // leaf name; empty for inodes
        double x{0.0};                       // horizontal: cumulative edge length from root
        double y{0.0};                       // vertical: cumulative vertical offset (leaf row)
    };

    struct TreeLayout
    {
        double height{0.0};         // vertical extent = sum of shown-leaf vertical offsets
        double max_cumulative{0.0}; // horizontal extent = max cumulative edge among shown leaves
        std::vector<NodeLayout> leaves{}; // shown leaves, in tree (top-to-bottom) order
        std::vector<NodeLayout> inodes{}; // shown inodes, in post-order (children before parent)
    };

    // Compute node positions for drawing. Does not modify the tree topology
    // (it does populate cumulative edge lengths via calculate_cumulative()).
    TreeLayout compute_layout(ae::tree::Tree& tree);

} // namespace ae::tal

// ======================================================================
