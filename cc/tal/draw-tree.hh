#pragma once

#include <filesystem>

// ======================================================================
// TAL (subsystem #3) — Phase B M1: render a phylogenetic tree to PDF.
//
// The first drawing slice of the TAL port. Reuses ae::tal::compute_layout for
// node positions (Phase A) and the ae::draw::CairoPdf surface from subsystem #1
// (the same surface chart-draw uses). Draws each node's horizontal edge segment
// plus the vertical connector under each inode (a port of the leaf/inode loop in
// acmacs-tal DrawTree::draw), optionally with leaf-name labels.
//
// Cairo is linked only into the `tal-draw` executable target, never into libae
// or ae_backend — see meson.build and cc/tal/PORTING.md.
// ======================================================================

namespace ae::tree
{
    class Tree;
}

namespace ae::tal
{
    // Render `tree` to a square PDF of side `image_size` device units. With
    // `labels`, draws each leaf's name to the right of its tip (no collision
    // avoidance yet). Takes Tree& because layout computes cumulative edges.
    void export_tree_pdf(ae::tree::Tree& tree, const std::filesystem::path& output, double image_size = 1000.0, bool labels = false);

} // namespace ae::tal

// ======================================================================
