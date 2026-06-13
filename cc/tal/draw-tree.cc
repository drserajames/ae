#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>

#include "tal/draw-tree.hh"
#include "tal/layout.hh"
#include "tal/clades.hh"
#include "tal/time-series.hh"
#include "tree/tree.hh"
#include "draw/cairo-surface.hh"
#include "ad/color.hh"
#include "ext/date.hh"

// ======================================================================

namespace ae::tal
{
    namespace
    {
        // Distinct palette for clade colouring (cycled if there are more clades).
        Color clade_palette(std::size_t index)
        {
            static const std::array<Color, 10> palette{BLUE, RED, GREEN, ORANGE, PURPLE, Color{0x008080}, MAGENTA, Color{0x808000}, Color{0x800000}, Color{0x1f77b4}};
            return palette[index % palette.size()];
        }

        TimeSeriesInterval interval_from_string(const std::string& interval)
        {
            if (interval == "year")
                return TimeSeriesInterval::year;
            if (interval == "week")
                return TimeSeriesInterval::week;
            if (interval == "day")
                return TimeSeriesInterval::day;
            return TimeSeriesInterval::month; // default
        }

        // Format a leaf date string to canonical "YYYY-MM-DD", or "" if unparseable.
        // Canonical zero-padded ISO dates compare lexicographically == chronologically,
        // so the result can be string-compared against time-series slot bounds.
        std::string canonical_date(const std::string& source)
        {
            if (source.empty())
                return {};
            if (const auto ymd = ae::date::from_string(source, ae::date::allow_incomplete::yes, ae::date::throw_on_error::no); ymd.ok())
                return fmt::format(fmt::runtime("{:%Y-%m-%d}"), ymd);
            return {};
        }
    } // namespace
} // namespace ae::tal

// ----------------------------------------------------------------------

std::size_t ae::tal::export_tree_pdf(ae::tree::Tree& tree, const std::filesystem::path& output, double image_size, const TreeDrawParameters& params)
{
    using namespace ae::tree;

    // --- node select/apply mods (settings DSL): hide nodes + collect per-node style
    //     overrides (keyed by node index, consulted during drawing). Applied before the
    //     layout so that "hide" removes nodes from it. ---
    std::unordered_map<node_index_base_t, Color> edge_color_override;
    std::unordered_map<node_index_base_t, Color> label_color_override;
    std::unordered_map<node_index_base_t, double> label_scale_override;
    if (!params.node_mods.empty()) {
        tree.calculate_cumulative();
        const auto apply_mods = [&](node_index_base_t idx, Node& base, const std::string* name, const std::string* date) {
            for (const auto& mod : params.node_mods) {
                const NodeSelect& sel = mod.select;
                if (!sel.seq_id.empty() && (name == nullptr || std::find(sel.seq_id.begin(), sel.seq_id.end(), *name) == sel.seq_id.end()))
                    continue;
                if (sel.cumulative_min && base.cumulative_edge.get() < *sel.cumulative_min)
                    continue;
                if (!sel.date_min.empty()) {
                    if (name == nullptr) continue;
                    if (const std::string day = canonical_date(*date); day.empty() || day < sel.date_min) continue;
                }
                if (!sel.date_max.empty()) {
                    if (name == nullptr) continue;
                    if (const std::string day = canonical_date(*date); day.empty() || !(day < sel.date_max)) continue;
                }
                const NodeApply& ap = mod.apply;
                if (ap.hide.value_or(false))
                    base.shown = false;
                if (!ap.edge_color.empty()) {
                    try { edge_color_override[idx] = Color{ap.edge_color}; } catch (const std::exception&) { }
                }
                if (name != nullptr && !ap.label_color.empty()) {
                    try { label_color_override[idx] = Color{ap.label_color}; } catch (const std::exception&) { }
                }
                if (name != nullptr && ap.label_scale)
                    label_scale_override[idx] = *ap.label_scale;
            }
        };
        struct Frame
        {
            node_index_t index;
            std::size_t cursor;
        };
        std::vector<Frame> stack;
        stack.push_back({Tree::root_index(), 0});
        while (!stack.empty()) {
            Frame& frame = stack.back();
            const Inode& inode = tree.inode(frame.index);
            if (frame.cursor < inode.children.size()) {
                const node_index_t child = inode.children[frame.cursor++];
                if (is_leaf(child)) {
                    Leaf& leaf = tree.leaf(child);
                    apply_mods(*child, leaf, &leaf.name, &leaf.date);
                }
                else {
                    Inode& child_inode = tree.inode(child);
                    apply_mods(*child, child_inode, nullptr, nullptr);
                    stack.push_back({child, 0});
                }
            }
            else {
                stack.pop_back();
            }
        }
    }

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

    // --- clade sections + clade colour map (first-seen order) ---
    std::vector<Clade> clade_sections;
    std::unordered_map<std::string, std::size_t> clade_rank; // clade name -> palette/slot index
    if (params.clades || params.color_by_clade || params.legend) {
        clade_sections = compute_clade_sections(tree);
        for (std::size_t k = 0; k < clade_sections.size(); ++k)
            clade_rank.emplace(clade_sections[k].name, k);
    }

    // clade colour/name with optional per-clade overrides from the settings DSL
    const auto clade_color_for = [&](std::size_t rank, const std::string& name) -> Color {
        if (const auto it = params.clade_styles.find(name); it != params.clade_styles.end() && !it->second.color.empty()) {
            try {
                return Color{it->second.color};
            }
            catch (const std::exception&) { // unparseable colour -> fall back to palette
            }
        }
        return clade_palette(rank);
    };
    const auto clade_display_for = [&](const std::string& name) -> std::string {
        if (const auto it = params.clade_styles.find(name); it != params.clade_styles.end() && !it->second.display_name.empty())
            return it->second.display_name;
        return name;
    };

    // --- time series ---
    TimeSeries time_series;
    if (params.time_series)
        time_series = compute_time_series(tree, interval_from_string(params.time_series_interval), params.time_series_start, params.time_series_end);

    // leaf colour = first clade's (possibly overridden) colour when colouring, else black
    const auto leaf_color = [&](const Leaf& leaf) -> Color {
        if (params.color_by_clade && !leaf.clades.empty()) {
            const std::string name{leaf.clades[0]};
            if (const auto found = clade_rank.find(name); found != clade_rank.end())
                return clade_color_for(found->second, name);
            return GREY50;
        }
        return BLACK;
    };

    // --- horizontal layout: tree | labels | clades column | time-series column ---
    const double margin = 0.03 * image_size;
    const double drawable_w = image_size - 2.0 * margin;
    const double gap = 0.012 * image_size;
    const double label_w = params.labels ? 0.16 * drawable_w : 0.0;
    const double clade_w = params.clades && !clade_sections.empty() ? 0.09 * drawable_w : 0.0;
    const double ts_w = params.time_series && !time_series.slots.empty() ? 0.34 * drawable_w : 0.0;
    const int n_right = (label_w > 0.0) + (clade_w > 0.0) + (ts_w > 0.0);
    const double tree_w = drawable_w - label_w - clade_w - ts_w - gap * n_right;

    double cursor = margin + tree_w;
    double x_label0{0.0}, x_clade0{0.0}, x_ts0{0.0};
    if (label_w > 0.0) { cursor += gap; x_label0 = cursor; cursor += label_w; }
    if (clade_w > 0.0) { cursor += gap; x_clade0 = cursor; cursor += clade_w; }
    if (ts_w > 0.0)    { cursor += gap; x_ts0 = cursor;    cursor += ts_w; }

    // --- vertical reserves: title (top), legend + time-series slot labels (bottom) ---
    const bool want_legend = params.legend && !clade_sections.empty();
    const double top_reserve = params.title.empty() ? 0.0 : 0.05 * image_size;
    const double bottom_reserve = (want_legend || ts_w > 0.0) ? 0.07 * image_size : 0.0;

    // --- vertical (shared) + tree horizontal transforms ---
    const double height_units = layout.height > 0.0 ? layout.height : 1.0;
    const double max_cum = layout.max_cumulative > 0.0 ? layout.max_cumulative : 1.0;
    const double vstep = (image_size - 2.0 * margin - top_reserve - bottom_reserve) / height_units;
    const double hstep = tree_w / max_cum;
    const auto dev_x = [&](double cumulative) { return margin + cumulative * hstep; };
    const auto dev_y = [&](double vertical_offset) { return margin + top_reserve + (vertical_offset - 0.5) * vstep; };

    const double line_width = std::clamp(vstep * 0.5, 0.2, 3.0);
    const double font_size = std::clamp(vstep * 0.8, 3.0, 14.0);

    ae::draw::CairoPdf pdf{output, image_size, image_size};
    pdf.background(WHITE);

    // --- title (top, centred) ---
    if (!params.title.empty()) {
        const double title_fs = std::clamp(top_reserve * 0.45, 8.0, 26.0);
        pdf.text(image_size / 2.0, margin + top_reserve * 0.5, params.title, title_fs, BLACK, /*center=*/true);
    }

    // --- tree: leaf tip segments (coloured) + optional labels ---
    // Leaf labels share the fixed column at x_label0, so collisions are purely vertical:
    // a greedy top-to-bottom pass keeps a label only if it clears the last kept one.
    // Labels singled out by a node mod (label_color / label_scale) are forced on.
    std::size_t labels_hidden{0};
    double last_label_center{-1.0e18};
    for (const auto& node : layout.leaves) {
        const Leaf& leaf = tree.leaf(node_index_t{node.node});
        const double y = dev_y(node.y);
        const Color color = leaf_color(leaf);
        const auto edge_it = edge_color_override.find(node.node);
        pdf.line(dev_x(node.x - leaf.edge.get()), y, dev_x(node.x), y, edge_it != edge_color_override.end() ? edge_it->second : color, line_width);
        if (params.labels && !leaf.name.empty()) {
            const auto lcol_it = label_color_override.find(node.node);
            const auto lscale_it = label_scale_override.find(node.node);
            const Color label_color = lcol_it != label_color_override.end() ? lcol_it->second : color;
            const double label_fs = font_size * (lscale_it != label_scale_override.end() ? lscale_it->second : 1.0);
            const bool forced = lcol_it != label_color_override.end() || lscale_it != label_scale_override.end();
            if (params.labels_avoid_collisions && !forced && (y - last_label_center) < label_fs * 1.15) {
                ++labels_hidden; // would overlap the label above — skip it (edge line is still drawn)
            }
            else {
                const double lx = label_w > 0.0 ? x_label0 : dev_x(node.x) + line_width * 2.0;
                pdf.text(lx, y + label_fs * 0.3, leaf.name, label_fs, label_color, /*center=*/false);
                last_label_center = y;
            }
        }
    }

    // --- tree: inode edge segments + vertical connectors (black) ---
    for (const auto& node : layout.inodes) {
        const Inode& inode = tree.inode(node_index_t{node.node});
        const double y = dev_y(node.y);
        const auto edge_it = edge_color_override.find(node.node);
        pdf.line(dev_x(node.x - inode.edge.get()), y, dev_x(node.x), y, edge_it != edge_color_override.end() ? edge_it->second : BLACK, line_width);
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

    // --- aa-transition labels at inodes (port of DrawAATransitions) ---
    if (params.aa_transitions) {
        const double aa_fs = std::clamp(vstep * 0.7, 4.0, 11.0);
        for (const auto& node : layout.inodes) {
            const Inode& inode = tree.inode(node_index_t{node.node});
            if (inode.aa_transitions.empty())
                continue;
            const std::string label = fmt::format("{}", inode.aa_transitions);
            pdf.text(dev_x(node.x) + aa_fs * 0.3, dev_y(node.y) - aa_fs * 0.55, label, aa_fs, Color{0x9400D3}, /*center=*/false);
        }
    }

    // --- clades column: one vertical bar per section, at a per-clade slot ---
    if (clade_w > 0.0) {
        const double slot_w = clade_w / static_cast<double>(clade_sections.size());
        const double bar_w = std::clamp(slot_w * 0.30, 1.0, 8.0);
        for (std::size_t k = 0; k < clade_sections.size(); ++k) {
            const Clade& clade = clade_sections[k];
            const double cx = x_clade0 + (static_cast<double>(k) + 0.5) * slot_w;
            const Color color = clade_color_for(k, clade.name);
            const CladeSection* widest = nullptr;
            for (const auto& section : clade.sections) {
                const double y0 = dev_y(pos.at(section.first_node).second);
                const double y1 = dev_y(pos.at(section.last_node).second);
                pdf.line(cx, y0, cx, y1, color, bar_w);
                if (widest == nullptr || section.size() > widest->size())
                    widest = &section;
            }
            if (widest != nullptr) { // clade name centred on its widest section
                const double ym = (dev_y(pos.at(widest->first_node).second) + dev_y(pos.at(widest->last_node).second)) / 2.0;
                pdf.text(cx + bar_w * 0.5 + 2.0, ym + font_size * 0.3, clade_display_for(clade.name), font_size, color, /*center=*/false);
            }
        }
    }

    // --- time-series column: slot separators + per-leaf dashes ---
    if (ts_w > 0.0) {
        const std::size_t n_slots = time_series.slots.size();
        const double slot_w = ts_w / static_cast<double>(n_slots);
        const double top = dev_y(0.5);
        const double bottom = dev_y(layout.height + 0.5);
        for (std::size_t i = 0; i <= n_slots; ++i) // separators
            pdf.line(x_ts0 + static_cast<double>(i) * slot_w, top, x_ts0 + static_cast<double>(i) * slot_w, bottom, GREY, 0.3);
        const double dash_w = std::clamp(vstep * 0.5, 0.3, 2.5);
        for (const auto& node : layout.leaves) {
            const Leaf& leaf = tree.leaf(node_index_t{node.node});
            const std::string date = canonical_date(leaf.date);
            if (date.empty())
                continue;
            for (std::size_t i = 0; i < n_slots; ++i) {
                if (time_series.slots[i].first <= date && date < time_series.slots[i].after_last) {
                    const double y = dev_y(node.y);
                    pdf.line(x_ts0 + (static_cast<double>(i) + 0.2) * slot_w, y, x_ts0 + (static_cast<double>(i) + 0.8) * slot_w, y, leaf_color(leaf), dash_w);
                    break;
                }
            }
        }

        // slot labels (rotated, reading upward) below the column
        const bool yearly = params.time_series_interval == "year";
        const double slot_fs = std::clamp(slot_w * 0.7, 5.0, 10.0);
        const double label_anchor_y = bottom + bottom_reserve * 0.9;
        for (std::size_t i = 0; i < n_slots; ++i) {
            const std::string& slot_first = time_series.slots[i].first;
            const std::string label = yearly ? slot_first.substr(0, 4) : slot_first.substr(0, 7);
            pdf.text_rotated(x_ts0 + (static_cast<double>(i) + 0.5) * slot_w + slot_fs * 0.35, label_anchor_y, label, slot_fs, GREY50, -90.0);
        }
    }

    // --- legend: clade colour swatches (bottom-left row) ---
    if (want_legend) {
        const double legend_fs = std::clamp(bottom_reserve * 0.28, 7.0, 12.0);
        const double swatch_w = legend_fs * 1.4;
        const double swatch_h = legend_fs * 0.9;
        const double ly = image_size - margin - bottom_reserve * 0.35;
        double lx = margin;
        for (std::size_t k = 0; k < clade_sections.size(); ++k) {
            const Color color = clade_color_for(k, clade_sections[k].name);
            const std::string name = clade_display_for(clade_sections[k].name);
            pdf.rectangle(lx, ly - swatch_h / 2.0, swatch_w, swatch_h, color, 0.5, color);
            const double tw = pdf.text_size(name, legend_fs).first;
            pdf.text(lx + swatch_w + 4.0 + tw / 2.0, ly, name, legend_fs, BLACK, /*center=*/true);
            lx += swatch_w + 4.0 + tw + 16.0;
        }
    }

    return labels_hidden;

} // ae::tal::export_tree_pdf

// ======================================================================
