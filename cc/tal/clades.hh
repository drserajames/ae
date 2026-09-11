#pragma once

#include <map>
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

    // ------------------------------------------------------------------
    // Section tolerance — port of acmacs-tal Clades::make_sections()
    // (AD cc/clades.cc). The raw runs above fragment a clade wherever a
    // single interspersed leaf of another clade falls inside it; AD bridges
    // those gaps with `section-inclusion-tolerance` and then drops the
    // leftover specks with `section-exclusion-tolerance`.
    // ------------------------------------------------------------------

    struct CladeSectionParameters
    {
        // AD defaults, acmacs-tal cc/clades.hh:74-75.
        long inclusion_tolerance{10}; // merge two runs when (next.first - prev.last) <= this
        long exclusion_tolerance{5};  // drop a section whose size() <= this
        bool shown{true};             // AD CladeParameters::any_shown() — a clade with "show": false is skipped entirely
        std::string display_name{};   // section label; empty -> the clade name
    };

    using per_clade_parameters_t = std::map<std::string, CladeSectionParameters>;

    // Apply AD's merge + small-section removal to `clades` in place. Clades whose
    // parameters say not shown, and clades left with no sections, are erased.
    // `all_clades` supplies the defaults for clades absent from `per_clade`.
    void apply_section_tolerance(std::vector<Clade>& clades, const per_clade_parameters_t& per_clade, const CladeSectionParameters& all_clades = {});

    // ------------------------------------------------------------------
    // hz-sections — port of acmacs-tal Clades::make_clades() handing its
    // sections to HzSections, plus HzSections::sort / detect_intersect /
    // set_prefix / set_aa_transitions (AD cc/hz-sections.cc).
    // ------------------------------------------------------------------

    struct HzSection
    {
        std::string id{};             // AD "{clade name}-{section no}"
        std::string prefix{};         // A, B, C … in top-to-bottom order
        std::string label{};          // section display name
        std::string first_name{};     // first leaf name (AD seq_id)
        std::string last_name{};      // last leaf name
        std::size_t first_vertical{0};
        std::size_t last_vertical{0};
        std::string aa_transitions{}; // space-joined, accumulated from the enclosing inodes
        bool intersect{false};        // overlaps another section (AD reports this)

        std::size_t size() const { return last_vertical - first_vertical + 1; }
    };

    // Derive the signature-page hz-sections from the tree's clade annotations the way AD
    // does when the `hz` sub-program is absent from the `tal` program: clade sections with
    // tolerance applied, sorted top-to-bottom, lettered A.., with each section's
    // aa-transitions accumulated from every inode whose subtree contains it (AD
    // HzSections::set_aa_transitions). Transitions are read from `Inode::aa_transitions`,
    // so populate them first (ae::tree::set_aa_nuc_transition_labels) if the tree carries none.
    std::vector<HzSection> compute_hz_sections(ae::tree::Tree& tree, const per_clade_parameters_t& per_clade, const CladeSectionParameters& all_clades = {});

} // namespace ae::tal

// ======================================================================
