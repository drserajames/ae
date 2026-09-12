#include <algorithm>
#include <unordered_map>

#include "tal/clades.hh"
#include "tree/tree.hh"

// ======================================================================

std::size_t ae::tal::Clade::number_of_leaves() const
{
    std::size_t total{0};
    for (const auto& section : sections)
        total += section.size();
    return total;

} // ae::tal::Clade::number_of_leaves

// ----------------------------------------------------------------------

std::vector<ae::tal::Clade> ae::tal::compute_clade_sections(ae::tree::Tree& tree)
{
    using namespace ae::tree;

    std::vector<Clade> result;
    std::unordered_map<std::string, std::size_t> clade_index; // clade name -> index in result

    // Iterative pre-order over node_index_t, visiting shown leaves in vertical
    // (top-to-bottom) order — same traversal/ordering as ae::tal::compute_layout.
    struct Frame
    {
        node_index_t index;
        std::size_t cursor;
    };
    std::vector<Frame> stack;
    stack.push_back({Tree::root_index(), 0});
    std::size_t vertical{0};

    while (!stack.empty()) {
        Frame& frame = stack.back();
        const Inode& inode = tree.inode(frame.index);
        if (frame.cursor < inode.children.size()) {
            const node_index_t child = inode.children[frame.cursor++];
            if (is_leaf(child)) {
                const Leaf& leaf = tree.leaf(child);
                if (leaf.shown) {
                    const std::size_t v{vertical++};
                    for (const std::string& clade_name : leaf.clades) {
                        const auto [it, inserted] = clade_index.try_emplace(clade_name, result.size());
                        if (inserted)
                            result.push_back(Clade{.name = clade_name});
                        Clade& clade = result[it->second];
                        if (!clade.sections.empty() && (clade.sections.back().last_vertical + 1) == v) {
                            CladeSection& section = clade.sections.back(); // vertically adjacent -> extend
                            section.last_node = *child;
                            section.last_name = leaf.name;
                            section.last_vertical = v;
                        }
                        else {
                            clade.sections.push_back(CladeSection{.first_node = *child,
                                                                  .last_node = *child,
                                                                  .first_name = leaf.name,
                                                                  .last_name = leaf.name,
                                                                  .first_vertical = v,
                                                                  .last_vertical = v});
                        }
                    }
                }
            }
            else if (tree.inode(child).shown) {
                stack.push_back({child, 0}); // descend; hidden subtrees skipped entirely
            }
        }
        else {
            stack.pop_back();
        }
    }

    return result;

} // ae::tal::compute_clade_sections

// ======================================================================

// ======================================================================
// Section tolerance — port of acmacs-tal Clades::make_sections()
// (AD sources/acmacs-tal/cc/clades.cc). Two steps, in AD's order:
//
//   1. merge: walk the runs top-to-bottom and absorb the next run into the
//      current one when the vertical gap (next.first - current.last) is
//      within `section-inclusion-tolerance`. A merged section's size() is the
//      span of the merged range — it counts the bridged gap, exactly as AD's
//      clade_section_t::size() (last - first + 1) does.
//   2. remove small: drop sections whose size() <= `section-exclusion-tolerance`,
//      BUT only when not every section is small — AD keeps them all in that case
//      (`num_small_sections < clade.sections.size()`), so a clade is never emptied
//      by the exclusion tolerance alone.
//
// A clade whose parameters are not shown is dropped before any of this (AD
// CladeParameters::any_shown()), and a clade left with no sections is erased.
// ======================================================================

void ae::tal::apply_section_tolerance(std::vector<Clade>& clades, const per_clade_parameters_t& per_clade, const CladeSectionParameters& all_clades)
{
    const auto parameters_for = [&per_clade, &all_clades](const std::string& name) -> const CladeSectionParameters& {
        if (const auto found = per_clade.find(name); found != per_clade.end())
            return found->second;
        else
            return all_clades;
    };

    std::vector<Clade> result;
    result.reserve(clades.size());
    for (Clade& clade : clades) {
        const CladeSectionParameters& param = parameters_for(clade.name);
        if (!param.shown || clade.sections.empty())
            continue;

        // 1. merge runs separated by no more than the inclusion tolerance
        std::vector<CladeSection> merged;
        merged.reserve(clade.sections.size());
        for (const CladeSection& section : clade.sections) {
            if (!merged.empty() && (static_cast<long>(section.first_vertical) - static_cast<long>(merged.back().last_vertical)) <= param.inclusion_tolerance) {
                CladeSection& into = merged.back();
                into.last_node = section.last_node;
                into.last_name = section.last_name;
                into.last_vertical = section.last_vertical;
            }
            else
                merged.push_back(section);
        }

        // 2. drop small sections, unless every section is small
        std::size_t num_small{0};
        for (const CladeSection& section : merged) {
            if (static_cast<long>(section.size()) <= param.exclusion_tolerance)
                ++num_small;
        }
        if (num_small < merged.size()) {
            std::erase_if(merged, [tol = param.exclusion_tolerance](const CladeSection& section) { return static_cast<long>(section.size()) <= tol; });
        }

        if (!merged.empty()) {
            clade.sections = std::move(merged);
            result.push_back(std::move(clade));
        }
    }
    clades = std::move(result);

} // ae::tal::apply_section_tolerance

// ======================================================================

namespace ae::tal
{
    // One inode's subtree extent over shown leaves, in the same vertical (row)
    // units compute_clade_sections uses, plus its pre-order visit rank. AD keeps
    // the equivalent on the node itself as first_prev_leaf / last_next_leaf
    // (Tree::set_first_last_next_node_id).
    struct InodeSpan
    {
        std::size_t first_vertical{0};
        std::size_t last_vertical{0};
        const ae::tree::transitions_t* aa_transitions{nullptr};
    };
} // namespace ae::tal

std::vector<ae::tal::ComputedHzSection> ae::tal::compute_hz_sections(ae::tree::Tree& tree, const per_clade_parameters_t& per_clade, const CladeSectionParameters& all_clades)
{
    using namespace ae::tree;

    std::vector<Clade> clades = compute_clade_sections(tree);
    apply_section_tolerance(clades, per_clade, all_clades);

    // --- sections, AD Clades::make_clades() -> HzSections::add_section ---
    // Every section of every shown clade becomes an hz-section, id "{clade}-{section no}",
    // label = the per-clade display name (falling back to the clade name).
    std::vector<ComputedHzSection> sections;
    for (const Clade& clade : clades) {
        std::string label{clade.name};
        if (const auto found = per_clade.find(clade.name); found != per_clade.end() && !found->second.display_name.empty())
            label = found->second.display_name;
        else if (found == per_clade.end() && !all_clades.display_name.empty())
            label = all_clades.display_name;
        for (std::size_t section_no{0}; section_no < clade.sections.size(); ++section_no) {
            const CladeSection& section = clade.sections[section_no];
            sections.push_back(ComputedHzSection{.id = fmt::format("{}-{}", clade.name, section_no),
                                         .label = label,
                                         .first_name = section.first_name,
                                         .last_name = section.last_name,
                                         .first_vertical = section.first_vertical,
                                         .last_vertical = section.last_vertical});
        }
    }

    // --- HzSections::sort() : top-to-bottom by the first leaf ---
    std::sort(std::begin(sections), std::end(sections), [](const ComputedHzSection& s1, const ComputedHzSection& s2) { return s1.first_vertical < s2.first_vertical; });

    // --- HzSections::detect_intersect() ---
    for (auto sect = std::begin(sections); sect != std::end(sections); ++sect) {
        for (auto other = std::next(sect); other != std::end(sections); ++other) {
            if (sect->first_vertical <= other->last_vertical && other->first_vertical <= sect->last_vertical)
                sect->intersect = other->intersect = true;
        }
    }

    // --- HzSections::set_prefix() : A, B, C … in that order ---
    for (std::size_t no{0}; no < sections.size(); ++no)
        sections[no].prefix.assign(1, static_cast<char>('A' + no));

    // --- HzSections::set_aa_transitions() ---
    // Pre-order over the tree: an inode contributes its transitions to every section its
    // subtree fully contains (AD: section.first >= node.first_prev_leaf &&
    // section.last <= node.last_next_leaf). add_or_replace semantics — a later (deeper)
    // transition at the same position replaces the earlier one AND moves to the end.
    {
        // Post-order pass for each inode's shown-leaf span, then a pre-order pass to apply
        // them in AD's order. Both run off one iterative walk over node_index_t.
        struct Frame
        {
            node_index_t index;
            std::size_t cursor;
            std::size_t first_vertical;
            bool any_leaf;
            std::size_t span_slot;
        };
        std::vector<InodeSpan> spans;   // in pre-order
        std::vector<Frame> stack;
        std::size_t vertical{0};
        spans.push_back(InodeSpan{.aa_transitions = &tree.inode(Tree::root_index()).aa_transitions});
        stack.push_back({Tree::root_index(), 0, 0, false, 0});
        while (!stack.empty()) {
            Frame& frame = stack.back();
            const Inode& inode = tree.inode(frame.index);
            if (frame.cursor < inode.children.size()) {
                const node_index_t child = inode.children[frame.cursor++];
                if (is_leaf(child)) {
                    if (tree.leaf(child).shown) {
                        for (Frame& fr : stack) {
                            if (!fr.any_leaf) {
                                fr.any_leaf = true;
                                fr.first_vertical = vertical;
                            }
                            spans[fr.span_slot].first_vertical = fr.first_vertical;
                            spans[fr.span_slot].last_vertical = vertical;
                        }
                        ++vertical;
                    }
                }
                else if (tree.inode(child).shown) {
                    spans.push_back(InodeSpan{.aa_transitions = &tree.inode(child).aa_transitions});
                    stack.push_back({child, 0, 0, false, spans.size() - 1});
                }
            }
            else {
                stack.pop_back();
            }
        }

        // accumulate as transitions (AD AA_Transitions), format once at the end
        std::vector<std::vector<ae::tree::transition_t>> accumulated(sections.size());
        for (const InodeSpan& span : spans) { // spans is in pre-order
            if (span.aa_transitions == nullptr || span.aa_transitions->empty())
                continue;
            for (std::size_t sno{0}; sno < sections.size(); ++sno) {
                const ComputedHzSection& section = sections[sno];
                if (span.first_vertical <= section.first_vertical && section.last_vertical <= span.last_vertical) {
                    for (const auto& transition : span.aa_transitions->transitions) {
                        // AD AA_Transitions::add_or_replace: drop any entry at the same position, append
                        std::erase_if(accumulated[sno], [&transition](const auto& have) { return have.pos == transition.pos; });
                        accumulated[sno].push_back(transition);
                    }
                }
            }
        }
        // AD formats a section's label with AA_Transitions::display_most_important(0), which
        // drops any entry with an empty left or right residue — a label whose ancestral residue
        // was never resolved is not printed. Mirror that here.
        for (std::size_t sno{0}; sno < sections.size(); ++sno) {
            fmt::memory_buffer out;
            bool first{true};
            for (const auto& transition : accumulated[sno]) {
                if (transition.left == ' ' || transition.right == ' ')
                    continue;
                fmt::format_to(std::back_inserter(out), "{}{}", first ? "" : " ", transition);
                first = false;
            }
            sections[sno].aa_transitions = fmt::to_string(out);
        }
    }

    return sections;

} // ae::tal::compute_hz_sections

// ======================================================================
