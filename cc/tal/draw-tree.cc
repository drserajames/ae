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

    // --- clade placement (port of acmacs-tal Clades::make_sections + set_slots) ---
    // For each visible clade: merge its sections with the per-clade section-inclusion-tolerance
    // (bridge gaps) and drop sections <= section-exclusion-tolerance (both in leaf-index units);
    // then assign a horizontal slot — the explicit per-clade slot when given, else set_slots
    // (smallest clade -> slot 0 nearest the matrix, larger/parent clades bumped rightward).
    struct CladeBand { long first_v; long last_v; std::size_t size; };
    struct CladePlan { std::size_t rank; std::vector<CladeBand> bands; int slot; long first_v; long last_v; std::size_t longest; double label_scale; int rotation; double offset_x; double offset_y; };
    std::vector<CladePlan> clade_plan;
    int clade_max_slot = 0;
    {
        for (const std::size_t k : visible_clades) {
            const Clade& clade = clade_sections[k];
            if (clade.sections.empty())
                continue;
            const auto* style = params.clade_styles.count(clade.name) ? &params.clade_styles.at(clade.name) : nullptr;
            const double incl = style ? style->section_inclusion_tolerance : 0.0;
            const double excl = style ? style->section_exclusion_tolerance : 0.0;
            // merge adjacent sections whose gap <= inclusion tolerance
            std::vector<CladeBand> bands;
            for (const auto& section : clade.sections) {
                const long fv = static_cast<long>(section.first_vertical), lv = static_cast<long>(section.last_vertical);
                if (!bands.empty() && static_cast<double>(fv - bands.back().last_v) <= incl) {
                    bands.back().last_v = lv;
                    bands.back().size += section.size();
                }
                else
                    bands.push_back({fv, lv, section.size()});
            }
            // drop bands whose size <= exclusion tolerance; if all drop, keep the largest
            std::vector<CladeBand> kept;
            for (const auto& b : bands)
                if (static_cast<double>(b.size) > excl)
                    kept.push_back(b);
            if (kept.empty()) {
                const CladeBand* big = &bands.front();
                for (const auto& b : bands) if (b.size > big->size) big = &b;
                kept.push_back(*big);
            }
            std::size_t longest = 0;
            for (const auto& b : kept) longest = std::max(longest, b.size);
            const int slot = style ? style->slot : -1;
            const double lscale = (style && style->label_scale > 0.0) ? style->label_scale
                                    : (params.clades_label_scale > 0.0 ? params.clades_label_scale : 1.0);
            const int rot = style ? style->rotation_degrees : 90;
            const double offx = style ? style->label_offset_x : 0.002;
            const double offy = style ? style->label_offset_y : 0.0;
            clade_plan.push_back({k, std::move(kept), slot, 0, 0, longest, lscale, rot, offx, offy});
            clade_plan.back().first_v = clade_plan.back().bands.front().first_v;
            clade_plan.back().last_v = clade_plan.back().bands.back().last_v;
        }
        // set_slots for clades without an explicit slot: smallest first; bump to the first slot
        // not clashing (vertical overlap) with an already-placed clade at that slot.
        std::vector<CladePlan*> refs;
        for (auto& p : clade_plan) refs.push_back(&p);
        std::sort(refs.begin(), refs.end(), [](const CladePlan* a, const CladePlan* b) {
            return a->longest != b->longest ? a->longest < b->longest : (a->last_v - a->first_v) < (b->last_v - b->first_v);
        });
        std::vector<std::vector<std::pair<long, long>>> occupied;
        const auto place = [&](CladePlan* p, int slot) {
            if (slot >= static_cast<int>(occupied.size())) occupied.resize(slot + 1);
            occupied[slot].emplace_back(p->first_v, p->last_v);
            p->slot = slot;
            clade_max_slot = std::max(clade_max_slot, slot);
        };
        for (auto* p : refs) if (p->slot >= 0) place(p, p->slot);     // explicit slots first
        for (auto* p : refs) {
            if (p->slot >= 0) continue;
            int slot = 0;
            for (;; ++slot) {
                if (slot >= static_cast<int>(occupied.size())) { occupied.emplace_back(); break; }
                bool clash = false;
                for (const auto& sp : occupied[slot])
                    if (p->first_v < sp.second && sp.first < p->last_v) { clash = true; break; }
                if (!clash) break;
            }
            place(p, slot);
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
        if (!params.color_edges)             // WHOCC report: matrix is continent-coloured, edges stay black
            return BLACK;
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
    const double hz_w = params.hz_sections.empty() ? 0.0 : 0.005 * drawable_w; // AD hz-section-marker reserve (no left label column)
    const double label_w = params.labels ? 0.16 * drawable_w : 0.0;
    // AD clade column width = (max_slot + 2) * slot.width (a fraction of height). Honour it so
    // brackets land at slot.width*(slot+1); fall back to the old fraction when no slot.width given.
    const double clade_slot_px = params.clades_slot_width > 0.0 ? params.clades_slot_width * height : 0.0;
    const double clade_w = (params.clades && !visible_clades.empty())
        ? (clade_slot_px > 0.0 ? static_cast<double>(clade_max_slot + 2) * clade_slot_px
           : (params.clades_width_ratio > 0.0 ? params.clades_width_ratio * height : 0.09 * drawable_w))
        : 0.0;
    // AD sizes the time-series column as n_slots * slot.width (slot.width a fraction of
    // height); honour it so the column is AD's narrow width, falling back to 0.34·drawable.
    const double ts_w = (params.time_series && !time_series.slots.empty())
        ? (params.time_series_slot_width > 0.0
               ? static_cast<double>(time_series.slots.size()) * params.time_series_slot_width * height
               : 0.34 * drawable_w)
        : 0.0;
    const double dash_col_w = 0.022 * drawable_w;                       // width of one dash-bar column
    const double dash_w = static_cast<double>(params.dash_bars.size()) * dash_col_w;
    const int n_right = (label_w > 0.0) + (clade_w > 0.0) + (ts_w > 0.0) + (dash_w > 0.0);
    const double tree_w = drawable_w - hz_w - label_w - clade_w - ts_w - dash_w - gap * n_right;

    double cursor = margin + tree_w;
    double x_label0{0.0}, x_clade0{0.0}, x_ts0{0.0}, x_dash0{0.0};
    // AD column order (left→right past the tree): labels, time-series matrix, clades, then the
    // aa dash-bars (rightmost). The clades column's horizontal arms extend to its own right edge,
    // just left of the dash-bars.
    if (label_w > 0.0) { cursor += gap; x_label0 = cursor; cursor += label_w; }
    if (ts_w > 0.0)    { cursor += gap; x_ts0 = cursor;    cursor += ts_w; }
    if (clade_w > 0.0) { cursor += gap; x_clade0 = cursor; cursor += clade_w; }
    if (dash_w > 0.0)  { cursor += gap; x_dash0 = cursor;  cursor += dash_w; } // aa dash-bars rightmost

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
    const double vmargin = 0.015 * height; // AD uses a small vertical margin so the tree fills the height
    // AD draws the continent legend as the lower-left world map (LegendContinentMap),
    // not as a coloured-square legend — so when the geo inset is present it IS the legend
    // and the top-right square legend is suppressed (otherwise it duplicates the inset).
    const bool want_legend = !legend_items.empty() && !params.geo_inset;
    // AD draws time-series date labels at BOTH the top and bottom of the matrix, so the row
    // range is inset by a date-label band top and bottom (the tree fills that full range, the
    // title sits top-left within the top band). When there's no matrix, only the title needs
    // a small top band.
    const double bottom_reserve = (ts_w > 0.0 || dash_w > 0.0) ? 0.045 * height : 0.0; // shallow band: AD's date pair is compact
    const double top_reserve = bottom_reserve > 0.0 ? bottom_reserve : (params.title.empty() ? 0.0 : 0.035 * height);

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

    // --- title (top-left, near the very top; acmacs-tal Title draws at offset [5,5]) ---
    if (!params.title.empty()) {
        const double title_fs = std::clamp(0.015 * height, 8.0, 26.0);
        pdf.text(margin, title_fs * 0.95, params.title, title_fs, BLACK, /*center=*/false); // near the very top (AD offset [5,5])
    }

    // hz-section separators are no longer drawn here: AD draws the faint grey top/bottom rules
    // per *clade* (from the matrix start to the bracket arrow), rendered with the clades column
    // below — so a separate hz-section separator would duplicate / over-draw them.

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
        // AD tip names: every shown leaf's seq_id at its tip, ~row height (vertical_step*0.8,
        // UNCLAMPED so one fits per row), no column / no collision — faint at page scale,
        // readable on zoom. Drawn in the leaf's matrix colour (AD coloring().color(leaf)).
        if (params.tip_names && !leaf.name.empty()) {
            const double tip_fs = vstep * 0.8;
            pdf.text(dev_x(node.x) + tip_fs * 0.5, y + tip_fs * 0.3, leaf.name, tip_fs, color, /*center=*/false);
        }
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

    // --- clades column (port of acmacs-tal Clades::draw): each shown clade's bands are vertical
    //     double-arrow brackets at slot.width*(slot+1) from the matrix edge (slot 0 nearest the
    //     matrix, deeper clades stepping right), with horizontal arms to the matrix side and a
    //     name label rotated clockwise (top-to-bottom), sized slot.width * per-clade scale. ---
    if (clade_w > 0.0 && !clade_plan.empty()) {
        const double slot_px = clade_slot_px > 0.0 ? clade_slot_px : clade_w / static_cast<double>(clade_max_slot + 2);
        // Arrowhead: an ABSOLUTE size tied to page height, not slot_px, so every subtype gets the
        // same head (H1's wide clade slot otherwise produced oversized heads vs H3). ~1.4px @1000.
        const double ahw = std::clamp(0.0014 * height, 1.0, 2.2);  // arrowhead half-width
        const double ahl = ahw * 3.5;                             // arrowhead length (sharp)
        const double line_to = ts_w > 0.0 ? x_ts0 : x_clade0;    // grey lines start at the matrix (AD horizontal_line)
        for (const auto& plan : clade_plan) {
            const Clade& clade = clade_sections[plan.rank];
            const double cx = x_clade0 + slot_px * (static_cast<double>(plan.slot) + 1.0); // AD pos_x
            const double clade_fs = std::clamp(slot_px * plan.label_scale, 3.0, 14.0);      // label_size = slot.width * scale (AD), capped smaller
            // ONE arrow per clade, spanning its LARGEST contiguous band (the AD reference brackets
            // only the main block — not the whole first..last extent, which a stray distant
            // section would over-stretch, e.g. H1 B(5a.1)). Collapses the tiny-section clutter too.
            const CladeBand* main_band = &plan.bands.front();
            for (const auto& b : plan.bands) if (b.size > main_band->size) main_band = &b;
            const long ext_first = main_band->first_v, ext_last = main_band->last_v;
            {
                const double y0 = dev_y(static_cast<double>(ext_first)), y1 = dev_y(static_cast<double>(ext_last));
                // two faint GREY horizontal lines at the clade's top & bottom, from the matrix
                // start across to the bracket arrow (AD horizontal_line, terminates at pos_x).
                pdf.line(line_to, y0, cx, y0, GREY, 0.4);
                pdf.line(line_to, y1, cx, y1, GREY, 0.4);
                // vertical double-arrow spine with FILLED triangular heads (AD double_arrow)
                pdf.line(cx, y0, cx, y1, BLACK, 0.6);
                pdf.filled_triangle(cx, y0, cx - ahw, y0 + ahl, cx + ahw, y0 + ahl, BLACK); // top head (up)
                pdf.filled_triangle(cx, y1, cx - ahw, y1 - ahl, cx + ahw, y1 - ahl, BLACK); // bottom head (down)
            }
            {
                const std::string name = clade_display_for(clade.name);
                // label centred on the clade's whole vertical extent (AD vpos=middle), shifted by
                // the per-clade offset (fractions of height); rotation 90 = clockwise (top->bottom),
                // 0 = horizontal. Placed just right of the arrow.
                const double center_y = dev_y(static_cast<double>(ext_first + ext_last) / 2.0) + plan.offset_y * height;
                const double tx = cx + ahw + clade_fs * 0.2 + plan.offset_x * height; // just right of the arrow, not crossing the spine/rules
                if (plan.rotation == 0) {
                    pdf.text(tx, center_y + clade_fs * 0.32, name, clade_fs, BLACK, /*center=*/false); // horizontal
                }
                else {
                    const double tw = pdf.text_size(name, clade_fs).first;
                    pdf.text_rotated(tx, center_y - tw / 2.0, name, clade_fs, BLACK, 90.0); // clockwise, vertically centred
                }
            }
        }
    }

    // --- time-series column: slot separators + per-leaf dashes ---
    if (ts_w > 0.0) {
        const std::size_t n_slots = time_series.slots.size();
        const double slot_w = ts_w / static_cast<double>(n_slots);
        const double top = dev_y(0.5);
        const double bottom = dev_y(layout.height + 0.5);
        for (std::size_t i = 0; i <= n_slots; ++i) // separators (AD draws these a medium grey)
            pdf.line(x_ts0 + static_cast<double>(i) * slot_w, top, x_ts0 + static_cast<double>(i) * slot_w, bottom, GREY50, 0.35);
        // hz-section separators across the matrix (AD HzSections::add_separators_to_time_series:
        // a grey rule above each section's first leaf and below its last leaf). Drawn behind the
        // dashes, spanning the time-series matrix only.
        if (!params.hz_sections.empty()) {
            std::unordered_map<std::string, double> name_y;
            name_y.reserve(layout.leaves.size());
            for (const auto& ln : layout.leaves)
                name_y.emplace(ln.name, ln.y);
            const double hz_x1 = x_ts0 + ts_w;
            for (const auto& section : params.hz_sections) {
                if (const auto it = name_y.find(section.first); it != name_y.end())
                    pdf.line(x_ts0, dev_y(it->second - 0.5), hz_x1, dev_y(it->second - 0.5), GREY, 0.4);
                if (const auto it = name_y.find(section.last); it != name_y.end())
                    pdf.line(x_ts0, dev_y(it->second + 0.5), hz_x1, dev_y(it->second + 0.5), GREY, 0.4);
            }
        }
        const double dash_w = std::clamp(vstep * 0.5, 0.15, 2.5); // thin marks (AD line_width 0.1) -> more white space
        for (const auto& node : layout.leaves) {
            const Leaf& leaf = tree.leaf(node_index_t{node.node});
            const std::string date = canonical_date(leaf.date);
            if (date.empty())
                continue;
            for (std::size_t i = 0; i < n_slots; ++i) {
                if (time_series.slots[i].first <= date && date < time_series.slots[i].after_last) {
                    const double y = dev_y(node.y);
                    pdf.line(x_ts0 + (static_cast<double>(i) + 0.25) * slot_w, y, x_ts0 + (static_cast<double>(i) + 0.75) * slot_w, y, leaf_color(leaf), dash_w);
                    break;
                }
            }
        }

        // slot labels (rotated). AD's TimeSeries::labels formats month slots as "%b" + "%y"
        // (e.g. "Mar 24", black), year slots as "%y". The report's slot.label sets a small
        // scale (size = slot.width * scale * height) and rotation "clockwise" (dates read
        // top-to-bottom). Drawn at BOTH the top and bottom of the matrix.
        static const char* const kMonth3[12] = {"Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                                 "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"};
        const bool yearly = params.time_series_interval == "year";
        const double slot_fs = (params.time_series_label_scale > 0.0 && params.time_series_slot_width > 0.0)
            ? std::max(params.time_series_slot_width * params.time_series_label_scale * height, 2.5)
            : std::clamp(slot_w * 0.7, 5.0, 10.0);
        const bool clockwise = params.time_series_label_rotation == "clockwise";
        const double angle = clockwise ? 90.0 : -90.0;
        // perpendicular offset to centre the text band in the slot; the sign flips with rotation
        const double xoff = clockwise ? -slot_fs * 0.35 : slot_fs * 0.35;
        const double sample_len = pdf.text_size("May 24", slot_fs).first;
        const double bottom_anchor_y = clockwise ? bottom + slot_fs * 0.6 : bottom + bottom_reserve * 0.9;
        const double top_anchor_y = clockwise ? top - sample_len - 2.0 : top - 2.0;
        // AD draws month and year as a COMPACT PAIR near the matrix: the year token sits adjacent
        // to the matrix edge and the month token one token-length + a small inter-line gap further
        // out (month directly above year in the top band, below year in the bottom band). The
        // years thus line up in a row by the matrix, the months a row just outside it. Clockwise
        // text reads downward from its anchor (token occupies [anchor, anchor + text_width]).
        const double month_w = pdf.text_size("Sep", slot_fs).first;
        const double year_w = pdf.text_size("24", slot_fs).first;
        const double pair_gap = slot_fs * 0.35;                  // normal inter-line gap
        for (std::size_t i = 0; i < n_slots; ++i) {
            const std::string& slot_first = time_series.slots[i].first;     // "YYYY-MM-DD"
            const double lx = x_ts0 + (static_cast<double>(i) + 0.5) * slot_w + xoff;
            if (yearly) {
                const std::string yy4 = slot_first.substr(0, 4);
                pdf.text_rotated(lx, bottom_anchor_y, yy4, slot_fs, BLACK, angle);
                pdf.text_rotated(lx, top_anchor_y, yy4, slot_fs, BLACK, angle);
                continue;
            }
            const std::string yy = slot_first.size() >= 4 ? slot_first.substr(2, 2) : std::string{};
            int mm = 0;
            if (slot_first.size() >= 7) { try { mm = std::stoi(slot_first.substr(5, 2)); } catch (...) { mm = 0; } }
            const std::string mon = (mm >= 1 && mm <= 12) ? kMonth3[mm - 1] : slot_first.substr(5, 2);
            if (clockwise) {
                // top band: year ends just above the matrix; month directly above year (tight pair)
                pdf.text_rotated(lx, top - 2.0 - year_w, yy, slot_fs, BLACK, 90.0);
                pdf.text_rotated(lx, top - 2.0 - year_w - pair_gap - month_w, mon, slot_fs, BLACK, 90.0);
                // bottom band: year just below the matrix; month directly below year (tight pair)
                pdf.text_rotated(lx, bottom + 2.0, yy, slot_fs, BLACK, 90.0);
                pdf.text_rotated(lx, bottom + 2.0 + year_w + pair_gap, mon, slot_fs, BLACK, 90.0);
            }
            else { // anticlockwise fallback: combined token
                const std::string label = fmt::format("{} {}", mon, yy);
                pdf.text_rotated(lx, bottom_anchor_y, label, slot_fs, BLACK, angle);
                pdf.text_rotated(lx, top_anchor_y, label, slot_fs, BLACK, angle);
            }
        }
    }

    // --- dash-bar-aa-at columns: per-leaf dash coloured by the amino acid at a position ---
    if (dash_w > 0.0) {
        // AD's "Ana" distinct palette (acmacs-base color-distinct.cc): the frequency-order
        // fallback colours (most common aa -> #03569b dark blue, then dark red, yellow, …).
        static const std::array<Color, 16> freq_palette{
            Color{0x03569b}, Color{0xe72f27}, Color{0xffc808}, Color{0xa2b324}, Color{0xa5b8c7},
            Color{0x049457}, Color{0xf1b066}, Color{0x742f32}, Color{0x9e806e}, Color{0x75ada9},
            Color{0x675b2c}, Color{0xa020f0}, Color{0x8b8989}, Color{0xe9a390}, Color{0xdde8cf}, Color{0x00939f}};
        const double dash_len = dash_col_w * 0.6;
        const double dash_lw = std::clamp(vstep * 0.6, 0.15, 2.5); // thin marks, AD-like white space
        const double pos_fs = std::clamp(dash_col_w * 0.5, 6.0, 11.0);
        for (std::size_t b = 0; b < params.dash_bars.size(); ++b) {
            const DashBarAAAt& bar = params.dash_bars[b];
            const double col_x = x_dash0 + (static_cast<double>(b) + 0.5) * dash_col_w;
            std::unordered_map<char, Color> aa_color; // resolved aa -> colour (for the legend swatches)
            if (bar.pos >= 1) {
                // pos-based (dash-bar-aa-at): colour each leaf by its aa at pos. AD assigns EVERY
                // aa a colour — frequency-order palette by default (colors.get_or), then overridden
                // per-aa by the explicit `colors` map; "transparent" means that aa is not drawn.
                const sequences::pos0_t pos0{static_cast<std::size_t>(bar.pos - 1)};
                std::unordered_set<char> hide_aa;
                std::unordered_map<char, int> counts;
                for (const auto& node : layout.leaves) {
                    const Leaf& leaf = tree.leaf(node_index_t{node.node});
                    if (leaf.aa.size() > pos0)
                        ++counts[leaf.aa[pos0]];
                }
                std::vector<std::pair<char, int>> ranked(counts.begin(), counts.end());
                std::sort(ranked.begin(), ranked.end(), [](const auto& l, const auto& r) { return l.second > r.second; });
                for (std::size_t r = 0; r < ranked.size(); ++r)
                    aa_color[ranked[r].first] = freq_palette[std::min(r, freq_palette.size() - 1)]; // frequency fallback
                for (const auto& [aa, color_string] : bar.colors_by_aa) {                          // explicit override
                    if (color_string == "transparent" || color_string == "TRANSPARENT") { hide_aa.insert(aa); aa_color.erase(aa); continue; }
                    try { aa_color[aa] = Color{color_string}; } catch (const std::exception&) {}
                }
                aa_color['X'] = GREY;                                                               // AD: X -> grey
                for (const auto& node : layout.leaves) {
                    const Leaf& leaf = tree.leaf(node_index_t{node.node});
                    if (leaf.aa.size() <= pos0)
                        continue;
                    const char a = leaf.aa[pos0];
                    if (hide_aa.count(a))
                        continue;                      // "transparent" aa — not drawn (AD)
                    const auto found = aa_color.find(a);
                    const double y = dev_y(node.y);
                    pdf.line(col_x - dash_len / 2.0, y, col_x + dash_len / 2.0, y, found != aa_color.end() ? found->second : GREY, dash_lw);
                }
            }
            else if (!bar.selects.empty()) {
                // select-based (dash-bar): colour each leaf by the first matching select (all
                // its <pos><aa> conditions hold); leaves matching none are not drawn.
                std::vector<Color> sel_colors;
                for (const auto& [conds, cstr] : bar.selects) {
                    Color c = GREY; try { c = Color{cstr}; } catch (const std::exception&) {}
                    sel_colors.push_back(c);
                }
                for (const auto& node : layout.leaves) {
                    const Leaf& leaf = tree.leaf(node_index_t{node.node});
                    for (std::size_t s = 0; s < bar.selects.size(); ++s) {
                        bool all = true;
                        for (const auto& cond : bar.selects[s].first) {
                            const sequences::pos0_t p0{static_cast<std::size_t>(cond.pos - 1)};
                            if (leaf.aa.size() <= p0 || leaf.aa[p0] != cond.aa) { all = false; break; }
                        }
                        if (all) {
                            const double y = dev_y(node.y);
                            pdf.line(col_x - dash_len / 2.0, y, col_x + dash_len / 2.0, y, sel_colors[s], dash_lw);
                            break;
                        }
                    }
                }
            }
            // legend at the TOP of each dash-bar column (in the top-reserve band, above the
            // matrix) and HORIZONTAL: each position+aa label stacked, in its resolved aa colour
            // (AD draws each label in colors.get(aa); h3_aabar_legend_top). Fall back to the .tal
            // label colour, or a bare position number when no legend is present.
            const double leg_fs = std::clamp(dash_col_w * 0.42, 5.0, 9.0);
            if (!bar.legend.empty()) {
                double ly = vmargin + leg_fs;                                       // top of the band, read downward
                for (const auto& item : bar.legend) {
                    Color c = BLACK;
                    const auto resolved = item.aa ? aa_color.find(item.aa) : aa_color.end();
                    if (resolved != aa_color.end())
                        c = resolved->second;                                       // actual draw colour (AD)
                    else { try { if (!item.color.empty()) c = Color{item.color}; } catch (const std::exception&) {} }
                    pdf.text(col_x, ly, item.text, leg_fs, c, /*center=*/true);
                    ly += leg_fs * 1.25;
                }
            }
            else if (bar.pos >= 1) {
                pdf.text(col_x, vmargin + pos_fs, fmt::format("{}", bar.pos), pos_fs, BLACK, /*center=*/true);
            }
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
        const double label_fs = label.size > 0.0 ? label.size * height * 0.85 : font_size; // ~0.85x to match AD vaccine-label size
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
        // AD draws these small, grey (all-nodes label colour grey30) and MONOSPACE, with a
        // tether (leader line) to the branch. Slightly smaller than before to match AD.
        const double mrca_fs = 0.0095 * height; // AD draw-aa-transitions default label scale ~0.01
        struct Placed { double nx, ny, tx, ty, fs, x0, x1, y0, y1; std::string text; Color color; };
        std::vector<Placed> placed;
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
            Color color = GREY50;
            if (!label.color.empty()) {
                try { color = Color{label.color}; } catch (const std::exception&) { }
            }
            const double nx = dev_x(found->second.first), ny = dev_y(found->second.second); // branch point
            const double tx = nx + label.offset_x * width;
            const double ty = ny + label.offset_y * height + fs * 0.3;
            const double tw = pdf.text_size(label.text, fs).first;
            placed.push_back({nx, ny, tx, ty, fs, tx, tx + tw, ty - fs, ty, label.text, color});
        }
        // vertical collision avoidance (AD shifts overlapping label boxes apart): process
        // top-to-bottom; if a label's box overlaps an already-placed one in x, nudge it down.
        std::sort(placed.begin(), placed.end(), [](const Placed& a, const Placed& b) { return a.y0 < b.y0; });
        std::vector<Placed> done;
        done.reserve(placed.size());
        for (auto& p : placed) {
            for (bool moved = true; moved;) {
                moved = false;
                for (const auto& q : done) {
                    if (p.x0 < q.x1 && q.x0 < p.x1 && p.y0 < q.y1 && q.y0 < p.y1) {
                        const double dy = q.y1 - p.y0 + p.fs * 0.15;
                        p.y0 += dy; p.y1 += dy; p.ty += dy;
                        moved = true;
                    }
                }
            }
            done.push_back(p);
        }
        for (const auto& p : done) {
            // tether: thin line from the branch to the label's near edge (AD LabelTether),
            // drawn only when the label sits off the branch (incl. after a collision nudge).
            const double anchor_x = p.tx < p.nx ? p.x1 : p.tx;
            if (std::abs(anchor_x - p.nx) > p.fs * 0.5 || std::abs(p.ty - p.ny) > p.fs * 0.5)
                pdf.line(p.nx, p.ny, anchor_x, p.ty - p.fs * 0.3, GREY, 0.3);
            pdf.text(p.tx, p.ty, p.text, p.fs, p.color, /*center=*/false, /*monospace=*/true);
        }
    }

    return labels_hidden;

} // ae::tal::export_tree_pdf

// ======================================================================
