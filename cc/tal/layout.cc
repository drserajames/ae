#include <cmath>
#include <limits>
#include <unordered_map>

#include "tal/layout.hh"
#include "tree/tree.hh"

// ======================================================================

ae::tal::TreeLayout ae::tal::compute_layout(ae::tree::Tree& tree)
{
    using namespace ae::tree;

    tree.calculate_cumulative(); // fills Node::cumulative_edge for every node

    TreeLayout layout;
    std::unordered_map<node_index_base_t, double> y_of; // node index -> assigned vertical offset
    double height{0.0};

    // Iterative post-order over node_index_t so that ladderized (deep, caterpillar)
    // trees do not overflow the stack — children are positioned before their parent.
    struct Frame
    {
        node_index_t index;
        size_t cursor;
    };
    std::vector<Frame> stack;
    stack.push_back({Tree::root_index(), 0});

    while (!stack.empty()) {
        Frame& frame = stack.back();
        const Inode& inode = tree.inode(frame.index);
        if (frame.cursor < inode.children.size()) {
            const node_index_t child = inode.children[frame.cursor++];
            if (is_leaf(child)) {
                const Leaf& leaf = tree.leaf(child);
                if (leaf.shown) {
                    height += default_vertical_offset;
                    y_of[*child] = height;
                    const double x = leaf.cumulative_edge.get();
                    layout.leaves.push_back(NodeLayout{.node = *child, .name = leaf.name, .x = x, .y = height});
                    layout.max_cumulative = std::max(layout.max_cumulative, x);
                }
            }
            else if (tree.inode(child).shown) {
                stack.push_back({child, 0}); // descend; hidden subtrees are skipped entirely
            }
        }
        else {
            // post-visit: inode vertical offset = midpoint of first and last shown child
            double first_y{std::numeric_limits<double>::quiet_NaN()};
            double last_y{first_y};
            for (const node_index_t child : inode.children) {
                if (const auto found = y_of.find(*child); found != y_of.end()) {
                    if (std::isnan(first_y))
                        first_y = found->second;
                    last_y = found->second;
                }
            }
            if (!std::isnan(first_y)) {
                const double mid = (first_y + last_y) / 2.0;
                y_of[*frame.index] = mid;
                layout.inodes.push_back(NodeLayout{.node = *frame.index, .name = {}, .x = inode.cumulative_edge.get(), .y = mid});
            }
            stack.pop_back();
        }
    }

    layout.height = height;
    return layout;

} // ae::tal::compute_layout

// ======================================================================
