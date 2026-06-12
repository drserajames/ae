#include <algorithm>
#include <cmath>
#include <limits>
#include <unordered_map>
#include <utility>

#include "tal/draw-tree.hh"
#include "tal/layout.hh"
#include "tree/tree.hh"
#include "draw/cairo-surface.hh"
#include "ad/color.hh"

// ======================================================================

void ae::tal::export_tree_pdf(ae::tree::Tree& tree, const std::filesystem::path& output, double image_size, bool labels)
{
    using namespace ae::tree;

    const TreeLayout layout = compute_layout(tree);
    if (layout.leaves.empty())
        throw std::runtime_error{"cannot draw tree: no shown leaves"};

    // node index -> (x = cumulative edge, y = vertical offset)
    std::unordered_map<node_index_base_t, std::pair<double, double>> pos;
    pos.reserve(layout.leaves.size() + layout.inodes.size());
    for (const auto& node : layout.leaves)
        pos.emplace(node.node, std::pair{node.x, node.y});
    for (const auto& node : layout.inodes)
        pos.emplace(node.node, std::pair{node.x, node.y});

    // --- device-coordinate transform ---
    const double margin = 0.03 * image_size;
    const double height_units = layout.height > 0.0 ? layout.height : 1.0;
    const double max_cum = layout.max_cumulative > 0.0 ? layout.max_cumulative : 1.0; // guard cladograms (no branch lengths)
    const double label_reserve = labels ? 0.30 : 0.02;                               // fraction of width kept free on the right
    const double vstep = (image_size - 2.0 * margin) / height_units;
    const double hstep = (image_size - 2.0 * margin) * (1.0 - label_reserve) / max_cum;

    const auto dev_x = [&](double cumulative) { return margin + cumulative * hstep; };
    const auto dev_y = [&](double vertical_offset) { return margin + (vertical_offset - 0.5) * vstep; };

    const double line_width = std::clamp(vstep * 0.5, 0.2, 3.0);
    const double font_size = std::clamp(vstep * 0.8, 3.0, 14.0);

    ae::draw::CairoPdf pdf{output, image_size, image_size};
    pdf.background(WHITE);

    // Leaves: horizontal tip segment [parent_x .. x] at the leaf row, optional label.
    for (const auto& node : layout.leaves) {
        const Leaf& leaf = tree.leaf(node_index_t{node.node});
        const double y = dev_y(node.y);
        pdf.line(dev_x(node.x - leaf.edge.get()), y, dev_x(node.x), y, BLACK, line_width);
        if (labels && !leaf.name.empty())
            pdf.text(dev_x(node.x) + line_width * 2.0, y + font_size * 0.3, leaf.name, font_size, BLACK, /*center=*/false);
    }

    // Inodes: horizontal edge segment + vertical connector spanning first..last shown child.
    for (const auto& node : layout.inodes) {
        const Inode& inode = tree.inode(node_index_t{node.node});
        const double y = dev_y(node.y);
        pdf.line(dev_x(node.x - inode.edge.get()), y, dev_x(node.x), y, BLACK, line_width);

        double first_child_y{std::numeric_limits<double>::quiet_NaN()};
        double last_child_y{first_child_y};
        for (const node_index_t child : inode.children) {
            if (const auto found = pos.find(*child); found != pos.end()) {
                if (std::isnan(first_child_y))
                    first_child_y = found->second.second;
                last_child_y = found->second.second;
            }
        }
        if (!std::isnan(first_child_y))
            pdf.line(dev_x(node.x), dev_y(first_child_y), dev_x(node.x), dev_y(last_child_y), BLACK, line_width);
    }

} // ae::tal::export_tree_pdf

// ======================================================================
