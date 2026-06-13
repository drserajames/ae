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

void ae::tal::export_tree_pdf(ae::tree::Tree& tree, const std::filesystem::path& output, double image_size, const TreeDrawParameters& params)
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

    // --- clade sections + clade colour map (first-seen order) ---
    std::vector<Clade> clade_sections;
    std::unordered_map<std::string, std::size_t> clade_rank; // clade name -> palette/slot index
    if (params.clades || params.color_by_clade || params.legend) {
        clade_sections = compute_clade_sections(tree);
        for (std::size_t k = 0; k < clade_sections.size(); ++k)
            clade_rank.emplace(clade_sections[k].name, k);
    }

    // --- time series ---
    TimeSeries time_series;
    if (params.time_series)
        time_series = compute_time_series(tree, interval_from_string(params.time_series_interval));

    // leaf colour = first clade's palette colour (when colouring), else black
    const auto leaf_color = [&](const Leaf& leaf) -> Color {
        if (params.color_by_clade && !leaf.clades.empty()) {
            if (const auto found = clade_rank.find(std::string{leaf.clades[0]}); found != clade_rank.end())
                return clade_palette(found->second);
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
    for (const auto& node : layout.leaves) {
        const Leaf& leaf = tree.leaf(node_index_t{node.node});
        const double y = dev_y(node.y);
        const Color color = leaf_color(leaf);
        pdf.line(dev_x(node.x - leaf.edge.get()), y, dev_x(node.x), y, color, line_width);
        if (params.labels && !leaf.name.empty()) {
            const double lx = label_w > 0.0 ? x_label0 : dev_x(node.x) + line_width * 2.0;
            pdf.text(lx, y + font_size * 0.3, leaf.name, font_size, color, /*center=*/false);
        }
    }

    // --- tree: inode edge segments + vertical connectors (black) ---
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
            const Color color = clade_palette(k);
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
                pdf.text(cx + bar_w * 0.5 + 2.0, ym + font_size * 0.3, clade.name, font_size, color, /*center=*/false);
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
            const Color color = clade_palette(k);
            pdf.rectangle(lx, ly - swatch_h / 2.0, swatch_w, swatch_h, color, 0.5, color);
            const double tw = pdf.text_size(clade_sections[k].name, legend_fs).first;
            pdf.text(lx + swatch_w + 4.0 + tw / 2.0, ly, clade_sections[k].name, legend_fs, BLACK, /*center=*/true);
            lx += swatch_w + 4.0 + tw + 16.0;
        }
    }

} // ae::tal::export_tree_pdf

// ======================================================================
