#pragma once

#include <string>
#include <vector>

#include "tree/tree-iterator.hh" // node_index_base_t

// ======================================================================
// TAL (subsystem #3) — headless clade sections.
//
// A port of acmacs-tal Tree::make_clade_sections(): walking shown leaves in
// vertical (top-to-bottom tree) order, each clade's leaves are grouped into
// maximal runs of vertically-adjacent leaves. Each run is a "section" spanning
// [first_leaf .. last_leaf]; a gap (a leaf without the clade in between) starts
// a new section. This is the layout *data* behind the Clades drawing element;
// the drawing itself (bars/arrows/labels on a surface) is Phase B, blocked on
// subsystem #1 — see cc/tal/PORTING.md.
//
// Reuses the per-leaf clade annotations already carried by ae::tree::Leaf
// (populated by Tree::set_clades() or from the phylo-tree-v3 JSON "L" field).
// ======================================================================

namespace ae::tree
{
    class Tree;
}

namespace ae::tal
{
    struct CladeSection
    {
        ae::tree::node_index_base_t first_node{0}; // node index of the first leaf in the run
        ae::tree::node_index_base_t last_node{0};  // node index of the last leaf in the run
        std::string first_name{};                  // name of the first leaf
        std::string last_name{};                   // name of the last leaf
        std::size_t first_vertical{0};             // vertical position (0-based row) of the first leaf
        std::size_t last_vertical{0};              // vertical position of the last leaf

        std::size_t size() const { return last_vertical - first_vertical + 1; }
    };

    struct Clade
    {
        std::string name{};
        std::vector<CladeSection> sections{};

        std::size_t number_of_leaves() const; // total leaves across all sections
    };

    // Group leaves into clade sections. Clades appear in first-seen order;
    // sections within a clade are in top-to-bottom order.
    std::vector<Clade> compute_clade_sections(ae::tree::Tree& tree);

} // namespace ae::tal

// ======================================================================
