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
