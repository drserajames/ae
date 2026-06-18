#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <optional>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>

#include "tal/draw-tree.hh"
#include "tal/continent-map.hh"
#include "tal/layout.hh"
#include "tal/clades.hh"
#include "tal/time-series.hh"
#include "tree/tree.hh"
#include "tree/aa-transitions.hh"
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

        // Continent colour, ported from AD acmacs-base/color-continent.cc (primary palette).
        Color continent_color(std::string_view continent)
        {
            static const std::array<std::pair<std::string_view, std::uint32_t>, 14> colors{{
                {"EUROPE", 0x00FF00}, {"CENTRAL-AMERICA", 0xAAF9FF}, {"MIDDLE-EAST", 0x8000FF}, {"NORTH-AMERICA", 0x00008B},
                {"AFRICA", 0xFF8000}, {"ASIA", 0xFF0000}, {"RUSSIA", 0xB03060}, {"AUSTRALIA-OCEANIA", 0xFF69B4},
                {"SOUTH-AMERICA", 0x40E0D0}, {"ANTARCTICA", 0x808080}, {"CHINA-SOUTH", 0xFF0000}, {"CHINA-NORTH", 0x6495ED},
                {"CHINA-UNKNOWN", 0x808080}, {"UNKNOWN", 0x808080}}};
            for (const auto& [name, value] : colors)
                if (name == continent)
                    return Color{value};
            return GREY50; // unknown / empty continent
        }

        // Frequency palette shared by colour-by-pos and the dash-bar columns
        // (most common aa -> grey, variants pop).
        Color frequency_palette(std::size_t rank)
        {
            static const std::array<Color, 8> palette{GREY, RED, BLUE, GREEN, ORANGE, PURPLE, Color{0x008080}, MAGENTA};
            return palette[std::min(rank, palette.size() - 1)];
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

    // --- compute aa-substitution transitions (consensus) when requested, instead of
    //     using the transitions already stored on the tree's inodes (the `A` field). ---
    if (params.aa_transitions_compute)
        set_aa_nuc_transition_labels(tree, AANucTransitionSettings{.set_aa_labels = true, .set_nuc_labels = false, .non_common_tolerance = params.aa_transitions_tolerance});

    // --- node select/apply mods (settings DSL): hide nodes + collect per-node style
    //     overrides (keyed by node index, consulted during drawing). Applied before the
    //     layout so that "hide" removes nodes from it. ---
    std::unordered_map<node_index_base_t, Color> edge_color_override;
    std::unordered_map<node_index_base_t, Color> label_color_override;
    std::unordered_map<node_index_base_t, double> label_scale_override;
    std::unordered_map<node_index_base_t, NodeText> text_override; // positioned labels (DrawOnTree)
    if (!params.node_mods.empty()) {
        tree.calculate_cumulative();
        const auto apply_mods = [&](node_index_base_t idx, Node& base, const std::string* name, const std::string* date) {
            for (const auto& mod : params.node_mods) {
                const NodeSelect& sel = mod.select;
                if (!sel.seq_id.empty() && (name == nullptr || std::find(sel.seq_id.begin(), sel.seq_id.end(), *name) == sel.seq_id.end()))
                    continue;
                if (sel.cumulative_min && base.cumulative_edge.get() < *sel.cumulative_min)
                    continue;
                if (sel.edge_min && base.edge.get() < *sel.edge_min)
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
                if (name != nullptr && ap.text && !ap.text->text.empty())
                    text_override[idx] = *ap.text;
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

    // --- ladderize (reorder children before layout). "none"/"" keep the .tjz order. ---
    if (params.ladderize == "number-of-leaves")
        tree.ladderize(Tree::ladderize_method::number_of_leaves);
    else if (params.ladderize == "max-edge-length")
        tree.ladderize(Tree::ladderize_method::max_edge_length);

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
    std::unordered_map<std::string, std::size_t> clade_rank; // clade name -> palette/slot index (all clades; colours stay stable)
    std::vector<std::size_t> visible_clades;                 // ranks of clades shown in the column/legend (per-clade hide removes them)
    if (params.clades || params.color_by_clade || params.legend) {
        clade_sections = compute_clade_sections(tree);
        for (std::size_t k = 0; k < clade_sections.size(); ++k) {
            clade_rank.emplace(clade_sections[k].name, k);
            const auto style = params.clade_styles.find(clade_sections[k].name);
            if (style == params.clade_styles.end() || !style->second.hide)
                visible_clades.push_back(k);
        }
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

    // --- colour-by-pos: amino-acid-at-position colour map (explicit or by frequency) ---
    const sequences::pos0_t color_pos0{params.color_by_pos > 0 ? static_cast<std::size_t>(params.color_by_pos - 1) : std::size_t{0}};
    std::vector<std::pair<char, Color>> pos_aa_colors; // aa -> colour, ordered (most common first / as given)
    if (params.color_by_pos > 0) {
        for (const auto& [aa, color_string] : params.color_by_pos_colors) {
            try { pos_aa_colors.emplace_back(aa, Color{color_string}); } catch (const std::exception&) { }
        }
        if (pos_aa_colors.empty()) { // colour by frequency over the shown leaves
            std::unordered_map<char, int> counts;
            for (const auto& node : layout.leaves) {
                const Leaf& leaf = tree.leaf(node_index_t{node.node});
                if (leaf.aa.size() > color_pos0)
                    ++counts[leaf.aa[color_pos0]];
            }
            std::vector<std::pair<char, int>> ranked(counts.begin(), counts.end());
            std::sort(ranked.begin(), ranked.end(), [](const auto& l, const auto& r) { return l.second > r.second; });
            for (std::size_t r = 0; r < ranked.size(); ++r)
                pos_aa_colors.emplace_back(ranked[r].first, frequency_palette(r));
        }
    }
    const auto pos_color_for = [&](char aa) -> Color {
        for (const auto& [a, c] : pos_aa_colors)
            if (a == aa)
                return c;
        return GREY50;
    };

    // matrix colour (time-series dashes / dash-bar cells): by aa-at-pos > by continent
    // > by first clade > black. This is what the WHOCC report colours by clade.
    const auto leaf_color = [&](const Leaf& leaf) -> Color {
        if (params.color_by_pos > 0)
            return leaf.aa.size() > color_pos0 ? pos_color_for(leaf.aa[color_pos0]) : GREY50;
        if (params.color_by_continent)
            return continent_color(leaf.continent);
        if (params.color_by_clade && !leaf.clades.empty()) {
            const std::string name{leaf.clades[0]};
            if (const auto found = clade_rank.find(name); found != clade_rank.end())
                return clade_color_for(found->second, name);
            return GREY50;
        }
        return BLACK;
    };

    // tree-edge colour. The WHOCC report draws tree edges BLACK while colouring the
    // right-hand matrix by clade — so clade colouring does NOT recolour edges (only the
    // explicit by-continent / by-aa-pos colourings do, matching acmacs-tal which recolours
    // edges only for those modes). Keeps the tree black under clades-whocc.
    const auto edge_color_for = [&](const Leaf& leaf) -> Color {
        if (params.color_by_pos > 0)
            return leaf.aa.size() > color_pos0 ? pos_color_for(leaf.aa[color_pos0]) : GREY50;
        if (params.color_by_continent)
            return continent_color(leaf.continent);
        return BLACK;
    };

    // --- page geometry: height is image_size; width is portrait when a tree
    //     width-to-height ratio is set (acmacs-tal canvas sizing), else square. ---
    const double height = image_size;
    const double width = params.width_to_height_ratio > 0.0 ? image_size * params.width_to_height_ratio : image_size;

    // --- horizontal layout: hz-marker column | tree | labels | time-series column | dash bars | clades column ---
    //     The clade column is the RIGHTMOST (acmacs-tal draws it past the time-series, flipped to
    //     the page's right edge), so the bracket/label staircase sits in the right margin like AD. ---
    const double margin = 0.03 * width;
    const double drawable_w = width - 2.0 * margin;
    const double gap = 0.012 * width;
    const double hz_w = params.hz_sections.empty() ? 0.0 : 0.045 * drawable_w; // left marker column
    const double label_w = params.labels ? 0.16 * drawable_w : 0.0;
    const double clade_w = params.clades && !visible_clades.empty() ? 0.09 * drawable_w : 0.0;
    const double ts_w = params.time_series && !time_series.slots.empty() ? 0.34 * drawable_w : 0.0;
    const double dash_col_w = 0.022 * drawable_w;                       // width of one dash-bar column
    const double dash_w = static_cast<double>(params.dash_bars.size()) * dash_col_w;
    const int n_right = (label_w > 0.0) + (clade_w > 0.0) + (ts_w > 0.0) + (dash_w > 0.0);
    const double tree_w = drawable_w - hz_w - label_w - clade_w - ts_w - dash_w - gap * n_right;

    double cursor = margin + tree_w;
    double x_label0{0.0}, x_clade0{0.0}, x_ts0{0.0}, x_dash0{0.0};
    if (label_w > 0.0) { cursor += gap; x_label0 = cursor; cursor += label_w; }
    if (ts_w > 0.0)    { cursor += gap; x_ts0 = cursor;    cursor += ts_w; }
    if (dash_w > 0.0)  { cursor += gap; x_dash0 = cursor;  cursor += dash_w; }
    if (clade_w > 0.0) { cursor += gap; x_clade0 = cursor; cursor += clade_w; } // clade column rightmost

    // --- legend items for the active colouring mode (aa-at-pos > continent > clade) ---
    std::vector<std::pair<std::string, Color>> legend_items;
    if (params.legend) {
        if (params.color_by_pos > 0) {
            for (const auto& [aa, color] : pos_aa_colors)
                legend_items.emplace_back(fmt::format("{}{}", params.color_by_pos, aa), color);
        }
        else if (params.color_by_continent) {
            std::vector<std::string> seen; // first-seen order among shown leaves
            for (const auto& node : layout.leaves) {
                const std::string& cont = tree.leaf(node_index_t{node.node}).continent;
                if (!cont.empty() && std::find(seen.begin(), seen.end(), cont) == seen.end())
                    seen.push_back(cont);
            }
            for (const auto& cont : seen)
                legend_items.emplace_back(cont, continent_color(cont));
        }
        else {
            for (const std::size_t k : visible_clades)
                legend_items.emplace_back(clade_display_for(clade_sections[k].name), clade_color_for(k, clade_sections[k].name));
        }
    }

    // --- vertical reserves: title (top); time-series / dash slot labels (bottom). The
    //     colour legend sits in the top-right corner (acmacs-tal), so it needs no bottom reserve. ---
    const double vmargin = 0.03 * height;
    const bool want_legend = !legend_items.empty();
    const double top_reserve = params.title.empty() ? 0.0 : 0.05 * height;
    const double bottom_reserve = (ts_w > 0.0 || dash_w > 0.0) ? 0.07 * height : 0.0;

    // --- vertical (shared) + tree horizontal transforms ---
    const double height_units = layout.height > 0.0 ? layout.height : 1.0;
    const double max_cum = layout.max_cumulative > 0.0 ? layout.max_cumulative : 1.0;
    const double vstep = (height - 2.0 * vmargin - top_reserve - bottom_reserve) / height_units;
    const double hstep = tree_w / max_cum;
    const auto dev_x = [&](double cumulative) { return margin + hz_w + cumulative * hstep; };
    const auto dev_y = [&](double vertical_offset) { return vmargin + top_reserve + (vertical_offset - 0.5) * vstep; };

    const double line_width = std::clamp(vstep * 0.5, 0.2, 3.0);
    const double font_size = std::clamp(vstep * 0.8, 3.0, 14.0);

    ae::draw::CairoPdf pdf{output, width, height};
    pdf.background(WHITE);

    // --- title (top, centred) ---
    if (!params.title.empty()) {
        const double title_fs = std::clamp(top_reserve * 0.45, 8.0, 26.0);
        pdf.text(width / 2.0, vmargin + top_reserve * 0.5, params.title, title_fs, BLACK, /*center=*/true);
    }

    // --- hz-sections: left marker column (bracket + rotated label) + separator across the tree ---
    if (hz_w > 0.0) {
        std::unordered_map<std::string, double> name_y; // leaf seq_id -> vertical offset
        name_y.reserve(layout.leaves.size());
        for (const auto& leaf_node : layout.leaves)
            name_y.emplace(leaf_node.name, leaf_node.y);
        const double bracket_x = margin + hz_w * 0.62;
        const double sep_x_end = margin + hz_w + tree_w; // separator spans the tree
        const double hz_label_fs = std::clamp(vstep * 1.2, 6.0, 12.0);
        for (const auto& section : params.hz_sections) {
            const auto first_it = name_y.find(section.first);
            const auto last_it = name_y.find(section.last);
            if (first_it == name_y.end() || last_it == name_y.end())
                continue; // unknown seq_id — skip the section
            double y0 = first_it->second, y1 = last_it->second;
            if (y0 > y1)
                std::swap(y0, y1);
            const double dy0 = dev_y(y0), dy1 = dev_y(y1);
            pdf.line(bracket_x, dy0, bracket_x, dy1, BLACK, 0.8);                         // bracket spine
            pdf.line(bracket_x, dy0, bracket_x + hz_w * 0.14, dy0, BLACK, 0.8);           // top tick
            pdf.line(bracket_x, dy1, bracket_x + hz_w * 0.14, dy1, BLACK, 0.8);           // bottom tick
            if (!section.label.empty())                                                  // label, rotated, centred
                pdf.text_rotated(margin + hz_w * 0.42, (dy0 + dy1) / 2.0 + section.label.size() * hz_label_fs * 0.28, section.label, hz_label_fs, BLACK, -90.0);
            pdf.line(bracket_x, dev_y(y0 - 0.5), sep_x_end, dev_y(y0 - 0.5), GREY, 0.3);  // top-boundary separator
        }
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
        const Color color = leaf_color(leaf);        // matrix / label colour (may be clade)
        const Color edge_col = edge_color_for(leaf); // tree edge colour (black under clades-whocc)
        const auto edge_it = edge_color_override.find(node.node);
        pdf.line(dev_x(node.x - leaf.edge.get()), y, dev_x(node.x), y, edge_it != edge_color_override.end() ? edge_it->second : edge_col, line_width);
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
    if (params.aa_transitions || params.aa_transitions_compute) {
        const double aa_fs = std::clamp(vstep * 0.7, 4.0, 11.0);
        if (params.aa_transitions_min_leaves > 1)
            tree.update_number_of_leaves_in_subtree();
        for (const auto& node : layout.inodes) {
            const Inode& inode = tree.inode(node_index_t{node.node});
            if (inode.aa_transitions.empty())
                continue;
            if (params.aa_transitions_min_leaves > 1 && inode.number_of_leaves() < static_cast<std::size_t>(params.aa_transitions_min_leaves))
                continue;
            const std::string label = fmt::format("{}", inode.aa_transitions);
            pdf.text(dev_x(node.x) + aa_fs * 0.3, dev_y(node.y) - aa_fs * 0.55, label, aa_fs, Color{0x9400D3}, /*center=*/false);
        }
    }

    // --- clades column (acmacs-tal Clades): each shown clade is a vertical double-arrow
    //     bracket spanning its leaf run, in a slot, with a rotated name label. Nested clades
    //     are pushed to inner slots (set_slots): the widest, outermost clade sits at the right
    //     edge (slot 0) and sub-clades stack leftwards, giving AD's right-hand bracket staircase.
    if (clade_w > 0.0 && !visible_clades.empty()) {
        // ae's compute_clade_sections has no section tolerance (unlike acmacs-tal's
        // section-inclusion/exclusion-tolerance), so a clade that is interrupted by a few
        // interspersed leaves fragments into dozens of tiny sections. Approximate the AD
        // tolerances at draw time: drop sections below a leaf-count floor (speckle), then
        // merge survivors separated by a small vertical gap into one band — so each clade
        // renders as one (or a few) clean brackets, not a cloud of one-leaf ticks.
        const double min_section = std::max(5.0, 0.001 * height_units); // drop sections smaller than this
        const double merge_gap = 0.04 * height_units;                   // bridge gaps up to this many leaves

        struct Band { double y0; double y1; std::size_t size; }; // one merged bracket
        struct CladeDraw { std::size_t rank; std::vector<Band> bands; double y0; double y1; int slot; };
        std::vector<CladeDraw> draws;
        draws.reserve(visible_clades.size());
        for (const std::size_t k : visible_clades) {
            const Clade& clade = clade_sections[k];
            if (clade.sections.empty())
                continue;
            // keep sections above the floor; if none clear it, keep just the largest so the clade still shows
            std::vector<const CladeSection*> kept;
            for (const auto& section : clade.sections)
                if (static_cast<double>(section.size()) >= min_section)
                    kept.push_back(&section);
            if (kept.empty()) {
                const CladeSection* largest = &clade.sections.front();
                for (const auto& section : clade.sections)
                    if (section.size() > largest->size())
                        largest = &section;
                kept.push_back(largest);
            }
            // merge kept sections (already top-to-bottom) separated by <= merge_gap into bands
            std::vector<Band> bands;
            double cur_first_v = kept.front()->first_vertical, cur_last_v = kept.front()->last_vertical;
            std::size_t cur_size = kept.front()->size();
            for (std::size_t i = 1; i < kept.size(); ++i) {
                if (static_cast<double>(kept[i]->first_vertical) - cur_last_v <= merge_gap) {
                    cur_last_v = kept[i]->last_vertical;
                    cur_size += kept[i]->size();
                }
                else {
                    bands.push_back({dev_y(cur_first_v), dev_y(cur_last_v), cur_size});
                    cur_first_v = kept[i]->first_vertical;
                    cur_last_v = kept[i]->last_vertical;
                    cur_size = kept[i]->size();
                }
            }
            bands.push_back({dev_y(cur_first_v), dev_y(cur_last_v), cur_size});
            double y0 = bands.front().y0, y1 = bands.back().y1;
            draws.push_back({k, std::move(bands), y0, y1, 0});
        }

        // slot assignment (acmacs-tal set_slots): widest extent first -> slot 0 (right edge);
        // a clade overlapping an already-placed clade in a slot is bumped left, so sub-clades
        // stack inward of their parent — AD's right-hand bracket staircase.
        std::sort(draws.begin(), draws.end(), [](const CladeDraw& a, const CladeDraw& b) { return (a.y1 - a.y0) > (b.y1 - b.y0); });
        std::vector<std::vector<std::pair<double, double>>> occupied; // per slot: occupied [y0,y1] extents
        for (auto& draw : draws) {
            int slot = 0;
            for (;; ++slot) {
                if (slot >= static_cast<int>(occupied.size()))
                    occupied.emplace_back();
                bool clash = false;
                for (const auto& span : occupied[slot])
                    if (draw.y0 < span.second && span.first < draw.y1) { clash = true; break; }
                if (!clash) { occupied[slot].emplace_back(draw.y0, draw.y1); draw.slot = slot; break; }
            }
        }
        const int n_slots = std::max<int>(1, static_cast<int>(occupied.size()));
        const double slot_w = clade_w / static_cast<double>(n_slots);
        const double cap = std::clamp(slot_w * 0.16, 1.0, 4.0); // arrowhead half-width
        const double clade_fs = std::clamp(vstep * 1.1, 5.0, 11.0);
        for (const auto& draw : draws) {
            const Clade& clade = clade_sections[draw.rank];
            const double cx = x_clade0 + clade_w - (static_cast<double>(draw.slot) + 0.5) * slot_w; // slot 0 = right edge
            const Band* widest = nullptr;
            for (const auto& band : draw.bands) {
                pdf.line(cx, band.y0, cx, band.y1, BLACK, 0.7);             // spine
                pdf.line(cx - cap, band.y0 + cap, cx, band.y0, BLACK, 0.7); // top arrowhead (two strokes)
                pdf.line(cx + cap, band.y0 + cap, cx, band.y0, BLACK, 0.7);
                pdf.line(cx - cap, band.y1 - cap, cx, band.y1, BLACK, 0.7); // bottom arrowhead
                pdf.line(cx + cap, band.y1 - cap, cx, band.y1, BLACK, 0.7);
                if (widest == nullptr || band.size > widest->size)
                    widest = &band;
            }
            if (widest != nullptr) { // name label, rotated to read upward, just left of the spine
                const std::string name = clade_display_for(clade.name);
                const double ym = (widest->y0 + widest->y1) / 2.0;
                pdf.text_rotated(cx - cap - clade_fs * 0.35, ym + name.size() * clade_fs * 0.28, name, clade_fs, BLACK, -90.0);
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

    // --- dash-bar-aa-at columns: per-leaf dash coloured by the amino acid at a position ---
    if (dash_w > 0.0) {
        static const std::array<Color, 8> freq_palette{GREY, RED, BLUE, GREEN, ORANGE, PURPLE, Color{0x008080}, MAGENTA};
        const double dash_len = dash_col_w * 0.6;
        const double dash_lw = std::clamp(vstep * 0.6, 0.3, 2.5);
        const double pos_fs = std::clamp(dash_col_w * 0.5, 6.0, 11.0);
        const double bottom = dev_y(layout.height + 0.5);
        for (std::size_t b = 0; b < params.dash_bars.size(); ++b) {
            const DashBarAAAt& bar = params.dash_bars[b];
            if (bar.pos < 1)
                continue;
            const sequences::pos0_t pos0{static_cast<std::size_t>(bar.pos - 1)};
            const double col_x = x_dash0 + (static_cast<double>(b) + 0.5) * dash_col_w;
            // colours: explicit colors_by_aa, else by aa frequency (most common -> grey, variants pop)
            std::unordered_map<char, Color> aa_color;
            for (const auto& [aa, color_string] : bar.colors_by_aa) {
                try { aa_color.emplace(aa, Color{color_string}); } catch (const std::exception&) { }
            }
            if (aa_color.empty()) {
                std::unordered_map<char, int> counts;
                for (const auto& node : layout.leaves) {
                    const Leaf& leaf = tree.leaf(node_index_t{node.node});
                    if (leaf.aa.size() > pos0)
                        ++counts[leaf.aa[pos0]];
                }
                std::vector<std::pair<char, int>> ranked(counts.begin(), counts.end());
                std::sort(ranked.begin(), ranked.end(), [](const auto& l, const auto& r) { return l.second > r.second; });
                for (std::size_t r = 0; r < ranked.size(); ++r)
                    aa_color.emplace(ranked[r].first, freq_palette[std::min(r, freq_palette.size() - 1)]);
            }
            for (const auto& node : layout.leaves) {
                const Leaf& leaf = tree.leaf(node_index_t{node.node});
                if (leaf.aa.size() <= pos0)
                    continue;
                const auto found = aa_color.find(leaf.aa[pos0]);
                const double y = dev_y(node.y);
                pdf.line(col_x - dash_len / 2.0, y, col_x + dash_len / 2.0, y, found != aa_color.end() ? found->second : GREY, dash_lw);
            }
            pdf.text_rotated(col_x + pos_fs * 0.35, bottom + bottom_reserve * 0.9, fmt::format("{}", bar.pos), pos_fs, BLACK, -90.0);
        }
    }

    // --- legend: colour swatches + names for the active mode (continent / aa-at-pos / clade),
    //     stacked top-right (acmacs-tal draws the coloured-by legend near the top-right corner). ---
    if (want_legend) {
        const double legend_fs = std::clamp(0.014 * height, 7.0, 12.0);
        const double swatch = legend_fs * 1.1;
        const double line_h = legend_fs * 1.55;
        double max_tw = 0.0;
        for (const auto& [name, color] : legend_items)
            max_tw = std::max(max_tw, pdf.text_size(name, legend_fs).first);
        const double block_w = swatch + 5.0 + max_tw;
        const double lx = width - margin - block_w; // right-aligned block
        double ly = vmargin + legend_fs;
        for (const auto& [name, color] : legend_items) {
            pdf.rectangle(lx, ly - swatch * 0.85, swatch, swatch, color, 0.4, color);
            pdf.text(lx + swatch + 5.0, ly, name, legend_fs, BLACK, /*center=*/false);
            ly += line_h;
        }
    }

    // --- geographic inset: continent-coloured world map in the lower-left (acmacs-tal
    //     LegendContinentMap). Sized to ~18% of the page width, with the continent map's
    //     aspect, sitting just above the bottom margin. ---
    if (params.geo_inset) {
        const double box_w = 0.18 * width;
        const double box_h = box_w / continent_map_aspect();
        const double box_x = margin;
        const double box_y = height - vmargin - box_h;
        draw_continent_inset(pdf, box_x, box_y, box_w, box_h);
    }

    // --- positioned text labels at leaf tips (port of DrawOnTree / nodes apply.text) ---
    for (const auto& [idx, label] : text_override) {
        const auto found = pos.find(idx);
        if (found == pos.end())
            continue; // node hidden / not in layout
        const double label_fs = label.size > 0.0 ? label.size * height : font_size;
        Color color = BLACK;
        if (!label.color.empty()) {
            try { color = Color{label.color}; } catch (const std::exception&) { }
        }
        // offset_x is a fraction of page width, offset_y a fraction of page height (acmacs-tal DrawOnTree)
        const double tx = dev_x(found->second.first) + label.offset_x * width;
        const double ty = dev_y(found->second.second) + label.offset_y * height + label_fs * 0.3;
        pdf.text(tx, ty, label.text, label_fs, color, /*center=*/false);
    }

    // --- curated on-tree labels at MRCA(first,last) internal nodes (acmacs-tal draw-aa-transitions
    //     per-node). AD selects by draw-time node_id; ae instead finds the node as the MRCA of the
    //     entry's first/last leaf seq_ids (MRCA(first,last) IS that node) and labels its position. ---
    if (!params.mrca_labels.empty()) {
        std::unordered_map<std::string, node_index_base_t> leaf_by_name; // shown leaves only
        leaf_by_name.reserve(layout.leaves.size());
        for (const auto& ln : layout.leaves)
            leaf_by_name.emplace(ln.name, ln.node);
        const auto root = *Tree::root_index();
        const auto mrca = [&tree, root](node_index_base_t a, node_index_base_t b) -> std::optional<node_index_base_t> {
            std::unordered_set<node_index_base_t> ancestors;
            for (node_index_t n{a};;) { ancestors.insert(*n); if (*n == root) break; n = tree.parent(n); }
            for (node_index_t m{b};;) {
                if (ancestors.find(*m) != ancestors.end()) return *m;
                if (*m == root) return std::nullopt;
                m = tree.parent(m);
            }
        };
        const double mrca_fs = std::clamp(vstep * 0.9, 4.0, 11.0);
        for (const auto& label : params.mrca_labels) {
            const auto fi = leaf_by_name.find(label.first);
            const auto li = leaf_by_name.find(label.last);
            if (fi == leaf_by_name.end() || li == leaf_by_name.end())
                continue; // first/last leaf not shown
            const auto node = mrca(fi->second, li->second);
            if (!node)
                continue;
            const auto found = pos.find(*node);
            if (found == pos.end())
                continue;
            const double fs = label.size > 0.0 ? label.size * height : mrca_fs;
            Color color = BLACK;
            if (!label.color.empty()) {
                try { color = Color{label.color}; } catch (const std::exception&) { }
            }
            const double tx = dev_x(found->second.first) + label.offset_x * width;
            const double ty = dev_y(found->second.second) + label.offset_y * height + fs * 0.3;
            pdf.text(tx, ty, label.text, fs, color, /*center=*/false);
        }
    }

    return labels_hidden;

} // ae::tal::export_tree_pdf

// ======================================================================
