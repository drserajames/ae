#include <algorithm>
#include <array>
#include <cmath>
#include <fstream>
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
    // Reserve extra WHITESPACE to the left of the tree for the auto-placed aa-transition labels
    // (they need room to sit beside their — mostly backbone — branches with short, non-crossing
    // leaders). Sized to the widest single substitution (labels stack one per line) + breathing
    // room. The tree is shifted right by this; labels are NOT confined to a rigid column.
    double aa_left = 0.0;
    if (params.mrca_labels_auto_place && !params.mrca_labels.empty()) {
        std::size_t maxlen = 0;
        for (const auto& l : params.mrca_labels) {
            std::size_t cur = 0, best = 0;
            for (char c : l.text) { if (c == ' ') { best = std::max(best, cur); cur = 0; } else ++cur; }
            maxlen = std::max(maxlen, std::max(best, cur));
        }
        const double fs = 0.0095 * height;
        aa_left = static_cast<double>(maxlen) * fs * 0.62 + fs * 3.0; // estimate + generous breathing room
    }
    // hz-section marker: the AD sig page draws the section letters (A/B/C) + brackets in a
    // column on the RIGHT, adjacent to the maps (hz_section_labels). The old left reserve
    // (used only to inset the matrix separators) stays when no right marker is drawn.
    const double hz_marker_w = params.hz_section_labels ? 0.028 * drawable_w : 0.0;
    const double hz_w = (params.hz_sections.empty() || params.hz_section_labels) ? 0.0 : 0.005 * drawable_w;
    // grey "matches-chart-antigen" dash column (AD): a thin column of grey dashes.
    const double grey_dash_w = params.matches_chart_seq_ids.empty() ? 0.0 : 0.016 * drawable_w;
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
    const int n_right = (label_w > 0.0) + (clade_w > 0.0) + (ts_w > 0.0) + (dash_w > 0.0)
                        + (grey_dash_w > 0.0) + (hz_marker_w > 0.0);
    const double tree_w = drawable_w - aa_left - hz_w - label_w - clade_w - ts_w - dash_w - grey_dash_w - hz_marker_w - gap * n_right;

    double cursor = margin + aa_left + tree_w;
    double x_label0{0.0}, x_clade0{0.0}, x_ts0{0.0}, x_dash0{0.0}, x_grey0{0.0}, x_hzmark0{0.0};
    if (params.clades_before_time_series) {
        // AD layout-with-maps order (left→right past the tree): labels, clades, time-series
        // matrix, grey matches-chart dash, hz-section markers (rightmost, next to the maps).
        if (label_w > 0.0)     { cursor += gap; x_label0 = cursor;  cursor += label_w; }
        if (clade_w > 0.0)     { cursor += gap; x_clade0 = cursor;  cursor += clade_w; }
        if (ts_w > 0.0)        { cursor += gap; x_ts0 = cursor;     cursor += ts_w; }
        if (grey_dash_w > 0.0) { cursor += gap; x_grey0 = cursor;   cursor += grey_dash_w; }
        // hz-section markers on the RIGHT of the time series (AD), hugging the grey-dash/matrix
        // (small gap) so the brackets sit close to the time series rather than out by the maps.
        if (hz_marker_w > 0.0) { cursor += gap * 0.25; x_hzmark0 = cursor; cursor += hz_marker_w; }
    }
    else {
        // AD layout-tree-only order: labels, time-series matrix, clades, then aa dash-bars.
        if (label_w > 0.0) { cursor += gap; x_label0 = cursor; cursor += label_w; }
        if (ts_w > 0.0)    { cursor += gap; x_ts0 = cursor;    cursor += ts_w; }
        if (clade_w > 0.0) { cursor += gap; x_clade0 = cursor; cursor += clade_w; }
        if (dash_w > 0.0)  { cursor += gap; x_dash0 = cursor;  cursor += dash_w; }
    }

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
    const double vmargin = 0.008 * height; // small vertical margin so the tree fills more of the height (AD)
    // AD draws the continent legend as the lower-left world map (LegendContinentMap),
    // not as a coloured-square legend — so when the geo inset is present it IS the legend
    // and the top-right square legend is suppressed (otherwise it duplicates the inset).
    const bool want_legend = !legend_items.empty() && !params.geo_inset;
    // AD draws time-series date labels at BOTH the top and bottom of the matrix, so the row
    // range is inset by a date-label band top and bottom (the tree fills that full range, the
    // title sits top-left within the top band). When there's no matrix, only the title needs
    // a small top band.
    // Signature pages (hz_section_labels) extend the matrix UP toward the maps (small top band)
    // and reserve a deeper BOTTOM band for the date-colour key (#4) under the matrix; standalone
    // trees keep the symmetric date-label bands.
    const double bottom_reserve = (ts_w > 0.0 || dash_w > 0.0)
        ? (params.hz_section_labels ? 0.075 * height : 0.045 * height)
        : 0.0;
    const double top_reserve = (ts_w > 0.0 || dash_w > 0.0)
        ? (params.hz_section_labels ? 0.022 * height : 0.045 * height)
        : (params.title.empty() ? 0.0 : 0.035 * height);

    // --- vertical (shared) + tree horizontal transforms ---
    const double height_units = layout.height > 0.0 ? layout.height : 1.0;
    const double max_cum = layout.max_cumulative > 0.0 ? layout.max_cumulative : 1.0;
    const double vstep = (height - 2.0 * vmargin - top_reserve - bottom_reserve) / height_units;
    const double hstep = tree_w / max_cum;
    const auto dev_x = [&](double cumulative) { return margin + aa_left + hz_w + cumulative * hstep; };
    const auto dev_y = [&](double vertical_offset) { return vmargin + top_reserve + (vertical_offset - 0.5) * vstep; };

    const double line_width = std::clamp(vstep * 0.5, 0.2, 3.0);
    // AD draws tree branches at vertical_step()*0.5 with NO lower floor, so a branch is always
    // half the row pitch and white gaps remain between adjacent leaves. A fixed floor (e.g. 0.1)
    // is fatal here: for these dense report trees vstep is ~0.01pt, so a floor forces the line
    // ~10x the row pitch and adjacent leaf edges merge into solid black blocks (burying the tip
    // names). Match AD: half the pitch, capped only at the top, no meaningful floor. Used for the
    // three tree-edge draws only (leaf edge, inode edge, vertical connector); clade arrows/spines,
    // time-series separators, hz-lines and dash marks keep their own widths.
    const double tree_line_width = std::min(vstep * 0.5, 1.0);
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
        pdf.line(dev_x(node.x - leaf.edge.get()), y, dev_x(node.x), y, edge_it != edge_color_override.end() ? edge_it->second : edge_col, tree_line_width);
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
        pdf.line(dev_x(node.x - inode.edge.get()), y, dev_x(node.x), y, edge_it != edge_color_override.end() ? edge_it->second : BLACK, tree_line_width);
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
            pdf.line(dev_x(node.x), dev_y(first_child_y), dev_x(node.x), dev_y(last_child_y), BLACK, tree_line_width);
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
        const double ahw = std::clamp(0.0012 * height, 0.8, 1.8);  // arrowhead half-width (narrower -> sharper)
        const double ahl = ahw * 4.8;                             // arrowhead length (long, crisp apex; AD double_arrow)
        const double line_to = ts_w > 0.0 ? x_ts0 : x_clade0;    // grey lines start at the matrix (AD horizontal_line)
        // When the clades column sits LEFT of the matrix (AD sig page), slot 0 (shallow) hugs the
        // matrix edge and deeper clades step toward the tree (left); arms still run right to the
        // matrix and the name label sits to the LEFT of the bracket.
        const bool clades_left = params.clades_before_time_series;
        const double clade_right_edge = x_clade0 + clade_w;
        for (const auto& plan : clade_plan) {
            const Clade& clade = clade_sections[plan.rank];
            const double cx = clades_left
                ? clade_right_edge - slot_px * (static_cast<double>(plan.slot) + 1.0)
                : x_clade0 + slot_px * (static_cast<double>(plan.slot) + 1.0); // AD pos_x
            const double clade_fs = std::clamp(slot_px * plan.label_scale, 3.0, 11.0);      // label_size = slot.width * scale (AD); 11 cap bites only H1's wide derived slot, leaving H3/BVic (7.0/9.8px) untouched
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
                // vertical double-arrow spine with FILLED triangular heads (AD double_arrow).
                // The spine runs only between the two arrowhead BASES, so the tips are pure
                // triangle apexes with no line poking through to the point. For a band shorter
                // than two full heads the head length is capped to half the band so the two heads
                // meet base-to-base at the centre (points still at the extremes), instead of
                // overlapping into an inward-pointing bowtie; no spine is drawn in that case.
                const double head_len = std::min(ahl, (y1 - y0) * 0.5);
                if (y1 - head_len > y0 + head_len)
                    pdf.line(cx, y0 + head_len, cx, y1 - head_len, BLACK, 0.6);
                pdf.filled_triangle(cx, y0, cx - ahw, y0 + head_len, cx + ahw, y0 + head_len, BLACK); // top head (up)
                pdf.filled_triangle(cx, y1, cx - ahw, y1 - head_len, cx + ahw, y1 - head_len, BLACK); // bottom head (down)
            }
            {
                const std::string name = clade_display_for(clade.name);
                // label centred on the clade's whole vertical extent (AD vpos=middle), shifted by
                // the per-clade offset (fractions of height); rotation 90 = clockwise (top->bottom),
                // 0 = horizontal. Placed just right of the arrow.
                const double center_y = dev_y(static_cast<double>(ext_first + ext_last) / 2.0) + plan.offset_y * height;
                if (plan.rotation == 0) {
                    const double tw0 = pdf.text_size(name, clade_fs).first;
                    // horizontal: right of the arrow normally, left of it when clades sit left of the matrix
                    const double tx = clades_left ? (cx - ahw - clade_fs * 0.1 - tw0 + plan.offset_x * height)
                                                  : (cx + ahw + clade_fs * 0.1 + plan.offset_x * height);
                    pdf.text(tx, center_y + clade_fs * 0.32, name, clade_fs, BLACK, /*center=*/false);
                }
                else {
                    // clockwise (top→bottom), vertically centred; just left of the spine when clades_left
                    const double tx = clades_left ? (cx - ahw - clade_fs * 1.05 + plan.offset_x * height)
                                                  : (cx + ahw + clade_fs * 0.1 + plan.offset_x * height);
                    const double tw = pdf.text_size(name, clade_fs).first;
                    pdf.text_rotated(tx, center_y - tw / 2.0, name, clade_fs, BLACK, 90.0);
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
        // Grey horizontal rules must sit BEHIND the vertical slot separators (AD draws the
        // verticals on top). So emit the hz-section separators FIRST, then the verticals over
        // them. (The per-clade top/bottom grey rules are already emitted earlier, in the clades
        // block above, so they too render behind these verticals.)
        // hz-section separators across the matrix (AD HzSections::add_separators_to_time_series:
        // a grey rule above each section's first leaf and below its last leaf), spanning the
        // time-series matrix only.
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
        for (std::size_t i = 0; i <= n_slots; ++i) // vertical separators, drawn OVER the horizontals (AD medium grey)
            pdf.line(x_ts0 + static_cast<double>(i) * slot_w, top, x_ts0 + static_cast<double>(i) * slot_w, bottom, GREY50, 0.35);
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
            const std::string mon = (mm >= 1 && mm <= 12) ? kMonth3[mm - 1]
                                     : (slot_first.size() >= 7 ? slot_first.substr(5, 2) : std::string{});
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

        // --- date-colour key (#4, AD): a horizontal viridis gradient under the matrix, keying the
        //     date→colour scale used to colour antigens in the section maps. Sig pages only. ---
        if (params.hz_section_labels) {
            // viridis quadratic-bezier gradient (anchors #440154, #40ffff, #fde725), per-term trunc
            const auto viridis = [](double t) -> Color {
                const double u = 1.0 - t;
                const auto ch = [&](int a, int b, int c) { return static_cast<int>(u * u * a + 2.0 * u * t * b + t * t * c); };
                return Color{static_cast<unsigned>((ch(0x44, 0x40, 0xfd) << 16) | (ch(0x01, 0xff, 0xe7) << 8) | ch(0x54, 0xff, 0x25))};
            };
            const double key_y = height - 0.040 * height;   // below the bottom date labels
            const double key_h = 0.013 * height;
            const int nseg = 72;
            for (int i = 0; i < nseg; ++i) {
                const Color col = viridis((i + 0.5) / nseg);
                pdf.rectangle(x_ts0 + (static_cast<double>(i) / nseg) * ts_w, key_y, ts_w / nseg + 0.6, key_h, col, 0.0, col);
            }
            // AD draws just the gradient bar — no bounding box, no date labels under it.
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
                aa_color['X'] = GREY;                                                               // AD: X -> grey (default, before explicit overrides)
                for (const auto& [aa, color_string] : bar.colors_by_aa) {                          // explicit override (wins over the X default)
                    if (color_string == "transparent" || color_string == "TRANSPARENT") { hide_aa.insert(aa); aa_color.erase(aa); continue; }
                    try { aa_color[aa] = Color{color_string}; } catch (const std::exception&) {}
                }
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
            // The legend sits just ABOVE the bar top (AD), not at the very top of the page — the
            // old vmargin anchor left a big gap (the date-label band). Anchor the block so its last
            // label ends a small gap above the bar top (= dev_y(0.5)), then draw downward as before.
            const double bar_top = dev_y(0.5);
            const double leg_gap = leg_fs * 0.6;
            if (!bar.legend.empty()) {
                const double block_height = static_cast<double>(bar.legend.size()) * leg_fs * 1.25;
                double ly = std::max(vmargin + leg_fs, bar_top - block_height - leg_gap); // clamp so it never runs off the top
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
                pdf.text(col_x, bar_top - leg_gap - pos_fs * 0.5, fmt::format("{}", bar.pos), pos_fs, BLACK, /*center=*/true);
            }
        }
    }

    // --- grey "matches-chart-antigen" dash column (AD layout-with-maps): a grey (#808080) dash
    //     for each leaf whose antigen is in the chart, in a thin column right of the matrix. ---
    if (grey_dash_w > 0.0) {
        const std::unordered_set<std::string> matched(params.matches_chart_seq_ids.begin(), params.matches_chart_seq_ids.end());
        const double col_x = x_grey0 + grey_dash_w * 0.5;
        const double dlen = grey_dash_w * 0.7;
        const double dlw = std::clamp(vstep * 0.6, 0.15, 2.5);
        for (const auto& node : layout.leaves) {
            if (matched.count(node.name)) {
                const double y = dev_y(node.y);
                pdf.line(col_x - dlen / 2.0, y, col_x + dlen / 2.0, y, Color{0x808080}, dlw);
            }
        }
    }

    // --- hz-section marker column (AD hz-section-marker): a bracket + section letter (A/B/C)
    //     per shown section, in a column on the right (adjacent to the maps); the letters match
    //     the per-map titles. ---
    if (hz_marker_w > 0.0 && !params.hz_sections.empty()) {
        std::unordered_map<std::string, double> name_y;
        name_y.reserve(layout.leaves.size());
        for (const auto& ln : layout.leaves)
            name_y.emplace(ln.name, ln.y);
        // AD section marker: a vertical line (with short top/bottom arms, like a double-arrow)
        // spanning the section, the section LETTER at the TOP just to the RIGHT of the line,
        // overlapping it. The line sits near the tree (left) side of the column.
        const double spine_x = x_hzmark0 + hz_marker_w * 0.18;  // line near the LEFT (tree side)
        const double arm = hz_marker_w * 0.10;                  // short arms (arrowhead-ish)
        const double label_fs = std::clamp(hz_marker_w * 0.62, 7.0, 16.0);
        for (const auto& section : params.hz_sections) {
            const auto itf = name_y.find(section.first), itl = name_y.find(section.last);
            if (itf == name_y.end() || itl == name_y.end())
                continue;
            double y0 = dev_y(itf->second - 0.5), y1 = dev_y(itl->second + 0.5);
            if (y0 > y1)
                std::swap(y0, y1);
            pdf.line(spine_x, y0, spine_x, y1, BLACK, 0.6);            // section line
            pdf.line(spine_x - arm, y0, spine_x + arm, y0, BLACK, 0.6); // top arm
            pdf.line(spine_x - arm, y1, spine_x + arm, y1, BLACK, 0.6); // bottom arm
            if (!section.prefix.empty()) {
                // letter hard at the TOP of the line, overlapping it (sits over the line, with a
                // tight white background so the line doesn't cut through it) — AD style.
                const auto [tw, th] = pdf.text_size(section.prefix, label_fs);
                const double lx = spine_x - label_fs * 0.06;  // overlaps the line
                const double ly = y0 + th * 0.92;             // hard at the top
                pdf.rectangle(lx - label_fs * 0.08, ly - th * 1.0, tw + label_fs * 0.16, th * 1.16, WHITE, 0.0, WHITE);
                pdf.text(lx, ly, section.prefix, label_fs, BLACK, /*center=*/false);
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

    // Unified geometry-sidecar rows for the WYSIWYG drag editor — BOTH the NodeText vaccine/strain
    // labels (below) AND the curated MRCA labels (further down). Written once, after both are placed,
    // when params.mrca_label_sidecar is set. `ax,ay` is the offset origin (box_top_left = anchor +
    // offset*page); for NodeText `ay` is shifted up 0.7*fs so that same clean inverse holds there too.
    struct SideRow { std::string kind, first, last, seq_id, text; double ax, ay, tx, ty, bx0, by0, bx1, by1, fs; int nlines; bool pinned; std::uint32_t color; };
    std::vector<SideRow> side_rows;

    // --- positioned text labels at leaf tips (port of DrawOnTree / nodes apply.text) ---
    std::vector<std::array<double, 4>> text_label_boxes; // device boxes {x0,y0,x1,y1}; kept clear of auto-placed aa-labels
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
        const double ntw = pdf.text_size(label.text, label_fs).first;
        text_label_boxes.push_back({tx, ty - label_fs, tx + ntw, ty});
        if (!params.mrca_label_sidecar.empty()) {
            // identity = leaf seq_id; box top-left (tx, ty-fs); anchor.y = tip_y - 0.7*fs so the editor's
            // clean inverse off = (box_top_left - anchor)/page reproduces this label's .tal offset exactly.
            const double tipx = dev_x(found->second.first), tipy = dev_y(found->second.second);
            side_rows.push_back({"nodetext", "", "", tree.leaf(node_index_t{idx}).name, label.text,
                                 tipx, tipy - label_fs * 0.7, tipx, tipy,
                                 tx, ty - label_fs, tx + ntw, ty, label_fs, 1, true, color.rgbI()});
        }
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
        struct Placed { double nx, ny, tx, ty, fs, x0, x1, y0, y1, cx, cy; int nlines; std::string text; Color color; int aidx{-1}; };
        // split an aa-transition label into its substitutions (one per line) so doubles/triples
        // stack vertically (AD style); the box is then max-token-wide and nlines tall.
        const auto split_ws = [](const std::string& s) { std::vector<std::string> out; std::string cur; for (char c : s) { if (c == ' ') { if (!cur.empty()) { out.push_back(cur); cur.clear(); } } else cur += c; } if (!cur.empty()) out.push_back(cur); if (out.empty()) out.push_back(s); return out; };
        // resolve each curated label to its anchor (the MRCA branch point) + text metrics
        struct Anchor { double nx, ny, mid_x, fs, tw, off_x, off_y; int nlines; std::string text; Color color; bool pinned; std::string first, last; };
        std::vector<Anchor> anchors;
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
            const double nx = dev_x(found->second.first), ny = dev_y(found->second.second); // branch (node) point
            double mid_x = nx; // tether target = the MIDDLE of the node's horizontal edge (AD)
            { node_index_t self{*node}; if (*self != root) { const auto pp = pos.find(*tree.parent(self)); if (pp != pos.end()) mid_x = 0.5 * (dev_x(pp->second.first) + nx); } }
            const auto toks = split_ws(label.text);
            double tw = 0.0;
            for (const auto& t : toks) tw = std::max(tw, pdf.text_size(t, fs).first);
            anchors.push_back({nx, ny, mid_x, fs, tw, label.offset_x, label.offset_y, static_cast<int>(toks.size()), label.text, color, label.pinned, label.first, label.last});
        }

        std::vector<Placed> done;
        done.reserve(anchors.size());

        if (params.mrca_labels_auto_place && !anchors.empty()) {
            // --- automatic whitespace placement ---
            // Rasterise the tree's ink into a coarse occupancy grid, then for each label search
            // outward from its anchor for the nearest free rectangle (preferring the AD-style
            // left side and a short tether), reserving each placed box so labels never overlap.
            const double gx0 = margin, gx1 = dev_x(max_cum);                 // tree band (left of the matrix)
            const double gy0 = vmargin + top_reserve, gy1 = height - vmargin - bottom_reserve;
            const double cell = std::max(mrca_fs * 0.33, 0.6); // fine grid: find the small inter-clade whitespace pockets near branches
            const int GX = std::clamp(static_cast<int>((gx1 - gx0) / cell), 1, 2600);
            const int GY = std::clamp(static_cast<int>((gy1 - gy0) / cell), 1, 3400);
            std::vector<unsigned char> occ(static_cast<std::size_t>(GX) * static_cast<std::size_t>(GY), 0);
            const auto col = [&](double x) { return std::clamp(static_cast<int>((x - gx0) / (gx1 - gx0) * GX), 0, GX - 1); };
            const auto row = [&](double y) { return std::clamp(static_cast<int>((y - gy0) / (gy1 - gy0) * GY), 0, GY - 1); };
            const auto mark_h = [&](double xa, double xb, double y) { const int r = row(y); const int c0 = col(std::min(xa, xb)), c1 = col(std::max(xa, xb)); for (int c = c0; c <= c1; ++c) occ[static_cast<std::size_t>(r) * GX + c] = 1; };
            const auto mark_v = [&](double x, double ya, double yb) { const int c = col(x); const int r0 = row(std::min(ya, yb)), r1 = row(std::max(ya, yb)); for (int r = r0; r <= r1; ++r) occ[static_cast<std::size_t>(r) * GX + c] = 1; };
            const auto mark_box = [&](double rx, double ry, double rw, double rh) { const int c0 = col(rx), c1 = col(rx + rw), r0 = row(ry), r1 = row(ry + rh); for (int r = r0; r <= r1; ++r) for (int c = c0; c <= c1; ++c) occ[static_cast<std::size_t>(r) * GX + c] = 1; };
            const auto box_free = [&](double rx, double ry, double rw, double rh) -> bool {
                if (rx < gx0 || rx + rw > gx1 || ry < gy0 || ry + rh > gy1) return false;
                const int c0 = col(rx), c1 = col(rx + rw), r0 = row(ry), r1 = row(ry + rh);
                for (int r = r0; r <= r1; ++r) for (int c = c0; c <= c1; ++c) if (occ[static_cast<std::size_t>(r) * GX + c]) return false;
                return true;
            };
            // tree ink: every node's horizontal edge (parent.x -> node.x) + inode vertical connectors
            for (const auto& ln : layout.leaves) {
                node_index_t self{ln.node};
                if (*self == root) continue;
                const auto p = pos.find(*tree.parent(self));
                mark_h(p != pos.end() ? dev_x(p->second.first) : dev_x(ln.x), dev_x(ln.x), dev_y(ln.y));
            }
            for (const auto& in : layout.inodes) {
                node_index_t self{in.node};
                if (*self != root) {
                    const auto p = pos.find(*tree.parent(self));
                    mark_h(p != pos.end() ? dev_x(p->second.first) : dev_x(in.x), dev_x(in.x), dev_y(in.y));
                }
                double ymin = 1e18, ymax = -1e18;
                for (const node_index_t ch : tree.inode(node_index_t{in.node}).children) {
                    const auto f = pos.find(*ch);
                    if (f != pos.end()) { const double cy = dev_y(f->second.second); ymin = std::min(ymin, cy); ymax = std::max(ymax, cy); }
                }
                if (ymax >= ymin) mark_v(dev_x(in.x), ymin, ymax);
            }
            // keep labels clear of the top-left title and the positioned strain-name labels
            if (!params.title.empty()) mark_box(gx0, gy0, 0.18 * width, mrca_fs * 1.6);
            for (const auto& b : text_label_boxes) mark_box(b[0], b[1], b[2] - b[0], b[3] - b[1]);

            // --- candidate search + conflict-minimising local search (finds a near-branch,
            // crossing-free layout when one exists, as AD's hand layout proves it does) ---
            const double PI = 3.14159265358979323846;
            // The leader always meets the label at the MID-HEIGHT of its RIGHT edge (consistent;
            // for a stacked double that is the middle of BOTH lines). Labels are kept left of the
            // branch (below), so this right-edge attach also makes every leader run rightward.
            const auto attach_pt = [](double, double, double, double y0, double x1, double y1, double& cx, double& cy) {
                cx = x1; cy = (y0 + y1) * 0.5;
            };
            const auto segs_cross = [](double ax, double ay, double bx, double by, double cx, double cy, double dx, double dy) {
                const auto o = [](double px, double py, double qx, double qy, double rx, double ry) { const double v = (qy - py) * (rx - qx) - (qx - px) * (ry - qy); return v < 0.0 ? -1 : (v > 0.0 ? 1 : 0); };
                return o(ax, ay, bx, by, cx, cy) != o(ax, ay, bx, by, dx, dy) && o(cx, cy, dx, dy, ax, ay) != o(cx, cy, dx, dy, bx, by);
            };
            const auto seg_box = [&](double x0, double y0, double x1, double y1, double bx0, double by0, double bx1, double by1) {
                const auto inside = [&](double x, double y) { return x >= bx0 && x <= bx1 && y >= by0 && y <= by1; };
                if (inside(x0, y0) || inside(x1, y1)) return true;
                return segs_cross(x0, y0, x1, y1, bx0, by0, bx1, by0) || segs_cross(x0, y0, x1, y1, bx1, by0, bx1, by1)
                    || segs_cross(x0, y0, x1, y1, bx1, by1, bx0, by1) || segs_cross(x0, y0, x1, y1, bx0, by1, bx0, by0);
            };
            // --- continuous geometry, for the SOFT cost (gives the search a gradient toward feasibility) ---
            const auto pt_seg_d = [](double px, double py, double ax, double ay, double bx, double by) -> double {
                const double dx = bx - ax, dy = by - ay, l2 = dx * dx + dy * dy;
                double t = l2 > 0.0 ? ((px - ax) * dx + (py - ay) * dy) / l2 : 0.0; t = std::clamp(t, 0.0, 1.0);
                return std::hypot(px - (ax + t * dx), py - (ay + t * dy));
            };
            const auto seg_seg_d = [&](double ax, double ay, double bx, double by, double cx, double cy, double dx, double dy) -> double {
                if (segs_cross(ax, ay, bx, by, cx, cy, dx, dy)) return 0.0; // crossing => zero distance
                return std::min({pt_seg_d(ax, ay, cx, cy, dx, dy), pt_seg_d(bx, by, cx, cy, dx, dy), pt_seg_d(cx, cy, ax, ay, bx, by), pt_seg_d(dx, dy, ax, ay, bx, by)});
            };
            const auto seg_box_len = [](double ax, double ay, double bx, double by, double bx0, double by0, double bx1, double by1) -> double {
                double t0 = 0.0, t1 = 1.0; const double dx = bx - ax, dy = by - ay;       // Liang-Barsky clip: length of AB inside the box
                const double p[4] = {-dx, dx, -dy, dy}, q[4] = {ax - bx0, bx1 - ax, ay - by0, by1 - ay};
                for (int e = 0; e < 4; ++e) {
                    if (p[e] == 0.0) { if (q[e] < 0.0) return 0.0; }
                    else { const double r = q[e] / p[e]; if (p[e] < 0.0) { if (r > t1) return 0.0; if (r > t0) t0 = r; } else { if (r < t0) return 0.0; if (r < t1) t1 = r; } }
                }
                return t1 > t0 ? std::hypot(dx, dy) * (t1 - t0) : 0.0;
            };
            struct Cand { double x0, y0, x1, y1, cx, cy, base; };
            std::vector<std::vector<Cand>> cands(anchors.size());
            const double rmax = 0.35 * height;
            const double gapL = mrca_fs * 0.45; // min gap between the label's right edge and the branch
            const double pad = mrca_fs * 0.3;   // clearance kept clear of tree ink around each label
            // PINNED labels (user dragged them in the WYSIWYG editor) are NOT auto-placed: each sits at
            // its authored offset (box top-left = node point + offset*page — the editor's exact inverse)
            // and is RESERVED in the occupancy grid up-front, so the auto search for the remaining labels
            // routes around it (and the pairwise conflict terms keep their leaders/boxes off it too).
            for (std::size_t i = 0; i < anchors.size(); ++i) {
                if (!anchors[i].pinned) continue;
                const double lineh = anchors[i].fs * 1.18, th = anchors[i].nlines * lineh, tw = anchors[i].tw;
                const double x0 = anchors[i].nx + anchors[i].off_x * width, y0 = anchors[i].ny + anchors[i].off_y * height;
                mark_box(x0 - pad, y0 - pad, tw + 2.0 * pad, th + 2.0 * pad);
            }
            for (std::size_t i = 0; i < anchors.size(); ++i) {
                const double fs = anchors[i].fs, lineh = fs * 1.18, th = anchors[i].nlines * lineh, tw = anchors[i].tw;
                if (anchors[i].pinned) {
                    // one fixed candidate at the authored offset; mid-right attach (same as the auto attach).
                    const double x0 = anchors[i].nx + anchors[i].off_x * width, y0 = anchors[i].ny + anchors[i].off_y * height;
                    cands[i].push_back({x0, y0, x0 + tw, y0 + th, x0 + tw, (2.0 * y0 + th) * 0.5, 0.0});
                    continue;
                }
                const double ax = anchors[i].mid_x, ay = anchors[i].ny;
                for (double r = mrca_fs * 0.7; r <= rmax; r += mrca_fs * 0.5) {
                    const int na = 28;
                    for (int k = 0; k < na; ++k) {
                        const double ang = -PI + (2.0 * PI) * k / na;
                        const double cxr = ax + r * std::cos(ang), cyr = ay + r * std::sin(ang);
                        const double x0 = cxr - tw * 0.5, y0 = cyr - th * 0.5;
                        if (x0 + tw > ax - gapL) continue;                                       // box must sit LEFT of the branch (#3,#5)
                        if (!box_free(x0 - pad, y0 - pad, tw + 2.0 * pad, th + 2.0 * pad)) continue; // clear of tree ink, with margin (#6)
                        double cx, cy; attach_pt(ax, ay, x0, y0, x0 + tw, y0 + th, cx, cy);       // mid-right attach (#4,#5)
                        double base = std::hypot(ax - cx, ay - cy) * 1.8;                        // leader length, weighted: prefer SHORT leaders (#3) and, by keeping labels near their branch, branch-y order (#5)
                        const double dyl = std::abs(ay - cy);
                        if (dyl < fs * 1.6) base += (fs * 1.6 - dyl) * 4.5;                       // avoid near-HORIZONTAL leaders (#4)
                        if (cy < ay) base += (ay - cy) * 0.8;                                     // prefer the label BELOW the branch -> leader slopes up-right, bottom-left to top-right (#4)
                        cands[i].push_back({x0, y0, x0 + tw, y0 + th, cx, cy, base});
                    }
                }
                if (cands[i].empty()) { // far-left whitespace fallback (always clear, left of the branch)
                    const double x0 = gx0, y0 = std::clamp(ay - th * 0.5, gy0, gy1 - th);
                    double cx, cy; attach_pt(ax, ay, x0, y0, x0 + tw, y0 + th, cx, cy);
                    cands[i].push_back({x0, y0, x0 + tw, y0 + th, cx, cy, 1.0e5});
                }
                std::sort(cands[i].begin(), cands[i].end(), [](const Cand& a, const Cand& b) { return a.base < b.base; });
                if (cands[i].size() > 56) cands[i].resize(56);
            }
            const std::size_t n = anchors.size();
            const double m = mrca_fs * 0.08;  // min separation between label boxes (#7)
            const double mt = mrca_fs * 0.05; // small clearance leaders keep from other text (#1,#2) — kept tiny so dense trees stay feasible
            const auto pconf = [&](std::size_t i, int ci, std::size_t j, int cj) -> int {
                const Cand& a = cands[i][ci]; const Cand& b = cands[j][cj]; int c = 0;
                if (a.x0 - m < b.x1 && b.x0 - m < a.x1 && a.y0 - m < b.y1 && b.y0 - m < a.y1) ++c;                          // box overlap (+ margin)
                if (segs_cross(anchors[i].mid_x, anchors[i].ny, a.cx, a.cy, anchors[j].mid_x, anchors[j].ny, b.cx, b.cy)) ++c; // leader crossing
                if (seg_box(anchors[i].mid_x, anchors[i].ny, a.cx, a.cy, b.x0 - mt, b.y0 - mt, b.x1 + mt, b.y1 + mt)) ++c;  // i's leader over (or grazing) j's text (#1,#2)
                if (seg_box(anchors[j].mid_x, anchors[j].ny, b.cx, b.cy, a.x0 - mt, a.y0 - mt, a.x1 + mt, a.y1 + mt)) ++c;  // j's leader over (or grazing) i's text (#1,#2)
                return c;
            };
            const auto inv = [&](std::size_t i, int ci, std::size_t j, int cj) -> int { // labels out of branch-y order? (#2)
                const double cyi = (cands[i][ci].y0 + cands[i][ci].y1) * 0.5, cyj = (cands[j][cj].y0 + cands[j][cj].y1) * 0.5;
                return ((anchors[i].ny < anchors[j].ny) != (cyi < cyj)) ? 1 : 0;
            };
            // SOFT pair penalty — a CONTINUOUS measure of how badly two labels interfere (penetration
            // depth, not yes/no). This is what lets the search "see" that one placement is closer to
            // feasible than another, and thus take the position of other leaders/labels into account.
            const double leadthr = mrca_fs * 0.5; // leaders nearer than this are pushed apart (0 distance == crossing)
            const auto psoft = [&](std::size_t i, int ci, std::size_t j, int cj) -> double {
                const Cand& a = cands[i][ci]; const Cand& b = cands[j][cj]; double pen = 0.0;
                const double ox = std::min(a.x1, b.x1) - std::max(a.x0, b.x0) + m; // box-overlap depth (+margin)
                const double oy = std::min(a.y1, b.y1) - std::max(a.y0, b.y0) + m;
                if (ox > 0.0 && oy > 0.0) pen += 6.0 * (ox / mrca_fs) * (oy / mrca_fs);                                                       // penetration AREA
                pen += 5.0 * seg_box_len(anchors[i].mid_x, anchors[i].ny, a.cx, a.cy, b.x0 - mt, b.y0 - mt, b.x1 + mt, b.y1 + mt) / mrca_fs;  // i's leader length inside j's text
                pen += 5.0 * seg_box_len(anchors[j].mid_x, anchors[j].ny, b.cx, b.cy, a.x0 - mt, a.y0 - mt, a.x1 + mt, a.y1 + mt) / mrca_fs;  // j's leader inside i's text
                const double d = seg_seg_d(anchors[i].mid_x, anchors[i].ny, a.cx, a.cy, anchors[j].mid_x, anchors[j].ny, b.cx, b.cy);
                if (d < leadthr) pen += 4.0 * (leadthr - d) / mrca_fs;                                                                        // leaders crossing / too close
                return pen;
            };
            // label order down the tree (by branch-y), for the "adjacent leaders near-parallel" term (#3)
            std::vector<std::size_t> ordA(n);
            for (std::size_t i = 0; i < n; ++i) ordA[i] = i;
            std::sort(ordA.begin(), ordA.end(), [&](std::size_t a, std::size_t b) { return anchors[a].ny < anchors[b].ny; });
            std::vector<int> rankA(n);
            for (int k = 0; k < static_cast<int>(n); ++k) rankA[ordA[k]] = k;
            const auto ang = [&](std::size_t i, int ci) { const Cand& a = cands[i][ci]; return std::atan2(anchors[i].ny - a.cy, anchors[i].mid_x - a.cx); };
            const long WC = 1000000L, WO = 1100L, WA = 130L; // conflicts >> vertical order > adjacent-angle ~ leader length
            std::vector<int> choice(n, 0), best(n, 0);
            const auto icost = [&](std::size_t i, int ci) -> long {
                long c = static_cast<long>(cands[i][ci].base);
                for (std::size_t j = 0; j < n; ++j) if (j != i) c += static_cast<long>(pconf(i, ci, j, choice[j])) * WC + static_cast<long>(inv(i, ci, j, choice[j])) * WO;
                const int r = rankA[i]; // angle similarity with the labels immediately above/below in branch order
                if (r > 0) { const std::size_t nb = ordA[r - 1]; c += static_cast<long>(WA * std::abs(ang(i, ci) - ang(nb, choice[nb]))); }
                if (r + 1 < static_cast<int>(n)) { const std::size_t nb = ordA[r + 1]; c += static_cast<long>(WA * std::abs(ang(i, ci) - ang(nb, choice[nb]))); }
                return c;
            };
            std::uint32_t rng = 2463534242u;
            const auto rnd = [&](int mm) { rng ^= rng << 13; rng ^= rng >> 17; rng ^= rng << 5; return static_cast<int>(rng % static_cast<std::uint32_t>(mm)); };
            const auto conf_i = [&](std::size_t i, int ci) { int c = 0; for (std::size_t j = 0; j < n; ++j) if (j != i) c += pconf(i, ci, j, choice[j]); return c; };
            const auto conf_total = [&]() { int c = 0; for (std::size_t i = 0; i < n; ++i) for (std::size_t j = i + 1; j < n; ++j) c += pconf(i, choice[i], j, choice[j]); return c; };
            const auto inv_i = [&](std::size_t i, int ci) { int c = 0; for (std::size_t j = 0; j < n; ++j) if (j != i) c += inv(i, ci, j, choice[j]); return c; };
            const auto inv_total = [&]() { int c = 0; for (std::size_t i = 0; i < n; ++i) for (std::size_t j = i + 1; j < n; ++j) c += inv(i, choice[i], j, choice[j]); return c; };
            const auto soft_i = [&](std::size_t i, int ci) { double s = 0.0; for (std::size_t j = 0; j < n; ++j) if (j != i) s += psoft(i, ci, j, choice[j]); return s; };
            const auto soft_total = [&]() { double s = 0.0; for (std::size_t i = 0; i < n; ++i) for (std::size_t j = i + 1; j < n; ++j) s += psoft(i, choice[i], j, choice[j]); return s; };
            const auto base_total = [&]() { double b = 0.0; for (std::size_t i = 0; i < n; ++i) b += cands[i][choice[i]].base; return b; };
            // Phase-A objective (double): hard conflicts dominate, then the SOFT penetration gradient
            // (this is the key change — it lets a move that merely *reduces* interference win, so the
            // search flows toward feasibility instead of stalling on a flat all-or-nothing landscape),
            // then branch-y order, then leader length. Note: each candidate eval here is O(n) (conf_i +
            // soft_i scan all labels), so Phase A is ~O(restarts · iters · n² · candidates) — fine for
            // the few-dozen labels a signature page carries, but quadratic in label count.
            const double WSOFT = 5000.0;
            const auto acost_i = [&](std::size_t i, int ci) -> double { return static_cast<double>(conf_i(i, ci)) * 1.0e6 + soft_i(i, ci) * WSOFT + static_cast<double>(inv_i(i, ci)) * static_cast<double>(WO) + static_cast<double>(cands[i][ci].base); };
            // scoreA tracks which restart to keep; it carries the same terms as acost_i (including the
            // leader-length base) so the best-layout tracker and the per-label descent agree.
            const auto scoreA = [&]() -> double { return static_cast<double>(conf_total()) * 1.0e6 + soft_total() * WSOFT + static_cast<double>(inv_total()) * static_cast<double>(WO) + base_total(); };
            // PHASE A — find a CONFLICT-FREE layout, and among those prefer one in branch-y ORDER
            // (ordered labels over ordered branches cannot cross, so order both fixes #5 and removes
            // the otherwise-stubborn crossings). Score = conflicts >> inversions >> leader length;
            // random restarts escape local minima. This reliably reaches zero on dense trees.
            best = choice;
            double best_scoreA = scoreA();
            int stale = 0;
            for (int restart = 0; restart <= 400; ++restart) {
                if (restart > 0) for (std::size_t i = 0; i < n; ++i) choice[i] = rnd(std::min<int>(28, static_cast<int>(cands[i].size())));
                bool restart_improved = false;
                for (int iter = 0; iter < 60; ++iter) {
                    bool improved = false;
                    for (std::size_t i = 0; i < n; ++i) {
                        int bc = choice[i]; double bv = acost_i(i, bc);
                        for (int ci = 0; ci < static_cast<int>(cands[i].size()); ++ci) { const double v = acost_i(i, ci); if (v < bv) { bv = v; bc = ci; } }
                        if (bc != choice[i]) { choice[i] = bc; improved = true; }
                    }
                    const double s = scoreA();
                    if (s < best_scoreA) { best_scoreA = s; best = choice; restart_improved = true; }
                    if (!improved) break;
                }
                // Once a conflict-free layout exists, stop after 120 consecutive restarts find nothing
                // better (a true stall counter — reset whenever a restart improves the best layout).
                if (best_scoreA < 1.0e6) { stale = restart_improved ? 0 : stale + 1; if (stale >= 120) break; }
            }
            choice = best; // fewest conflicts (zero if feasible), then least interference, then order
            // PHASE A2 — pairwise (2-opt) repair. A pair that conflicts only with each other can't be
            // fixed by single-label moves (moving one re-conflicts the other); try moving BOTH together
            // to a combination that leaves each conflict-free against everyone.
            const auto conf_excl = [&](std::size_t i, int ci, std::size_t excl) { int c = 0; for (std::size_t k = 0; k < n; ++k) if (k != i && k != excl) c += pconf(i, ci, k, choice[k]); return c; };
            for (int pass = 0; pass < 12; ++pass) {
                bool any = false;
                for (std::size_t i = 0; i < n; ++i) for (std::size_t j = i + 1; j < n; ++j) {
                    if (pconf(i, choice[i], j, choice[j]) == 0) continue; // only repair conflicting pairs
                    long bestv = -1; int bci = choice[i], bcj = choice[j];
                    for (int ci = 0; ci < static_cast<int>(cands[i].size()); ++ci) {
                        if (conf_excl(i, ci, j) > 0) continue;            // i clean vs everyone but j
                        for (int cj = 0; cj < static_cast<int>(cands[j].size()); ++cj) {
                            if (pconf(i, ci, j, cj) > 0 || conf_excl(j, cj, i) > 0) continue; // pair clean, and j clean vs everyone but i
                            const long v = static_cast<long>(cands[i][ci].base) + static_cast<long>(cands[j][cj].base);
                            if (bestv < 0 || v < bestv) { bestv = v; bci = ci; bcj = cj; }
                        }
                    }
                    if (bestv >= 0) { choice[i] = bci; choice[j] = bcj; any = true; }
                }
                if (!any) break;
            }
            // PHASE A3 — focused-window repair. A pair can stay in conflict because the whole local
            // cluster is congested: relieving it needs the labels ABOVE/BELOW to lift and open a gap,
            // which no single/pairwise move tries (lifting an innocent neighbour only raises its own
            // cost). So re-optimise a small branch-y WINDOW around the conflict — the conflicting pair
            // plus their neighbours — all together, with random restarts. This finds that coordinated
            // shift. (No-op on trees already conflict-free.)
            for (int pass = 0; pass < 8; ++pass) {
                const int before = conf_total();
                if (before == 0) break;
                std::size_t pi = n, pj = n; // first remaining conflicting pair
                for (std::size_t i = 0; i < n && pi == n; ++i) for (std::size_t j = i + 1; j < n; ++j) if (pconf(i, choice[i], j, choice[j]) > 0) { pi = i; pj = j; break; }
                if (pi == n) break;
                const int W = 6; // branch-order neighbours each side to free up
                const int lo = std::max(0, std::min(rankA[pi], rankA[pj]) - W), hi = std::min(static_cast<int>(n) - 1, std::max(rankA[pi], rankA[pj]) + W);
                std::vector<std::size_t> win; for (int r = lo; r <= hi; ++r) win.push_back(ordA[r]);
                std::vector<int> bestwin; for (std::size_t w : win) bestwin.push_back(choice[w]);
                int bestwc = conf_total(); // pure feasibility during repair (order is restored by Phase B)
                for (int rs = 0; rs <= 250 && bestwc > 0; ++rs) {
                    if (rs > 0) for (std::size_t w : win) choice[w] = rnd(static_cast<int>(cands[w].size()));
                    for (int it = 0; it < 40; ++it) {
                        bool imp = false;
                        for (std::size_t w : win) {
                            int bc = choice[w]; long bv = static_cast<long>(conf_i(w, bc)) * 1000000L + static_cast<long>(cands[w][bc].base);
                            for (int c = 0; c < static_cast<int>(cands[w].size()); ++c) { const long v = static_cast<long>(conf_i(w, c)) * 1000000L + static_cast<long>(cands[w][c].base); if (v < bv) { bv = v; bc = c; } }
                            if (bc != choice[w]) { choice[w] = bc; imp = true; }
                        }
                        const int s = conf_total();
                        if (s < bestwc) { bestwc = s; bestwin.clear(); for (std::size_t w : win) bestwin.push_back(choice[w]); }
                        if (bestwc == 0 || !imp) break;
                    }
                }
                for (std::size_t k = 0; k < win.size(); ++k) choice[win[k]] = bestwin[k];
                if (conf_total() >= before) break; // window couldn't improve -> give up
            }
            // PHASE B — refine aesthetics (vertical order, up-right slope, short & near-parallel leaders)
            // WITHOUT ever reintroducing a conflict: a label may only move to a candidate that has no
            // more conflicts (vs the others' current positions) than it has now, so global conflicts
            // never increase. Iterate to a local optimum of the full cost.
            for (int iter = 0; iter < 200; ++iter) {
                bool improved = false;
                for (std::size_t i = 0; i < n; ++i) {
                    const int cur = choice[i], cur_cf = conf_i(i, cur);
                    int bc = cur; long bv = icost(i, cur);
                    for (int ci = 0; ci < static_cast<int>(cands[i].size()); ++ci) {
                        if (conf_i(i, ci) > cur_cf) continue; // never increase this label's conflicts
                        const long v = icost(i, ci);
                        if (v < bv) { bv = v; bc = ci; }
                    }
                    if (bc != cur) { choice[i] = bc; improved = true; }
                }
                if (!improved) break;
            }
            for (std::size_t i = 0; i < n; ++i) {
                const Cand& c = cands[i][choice[i]];
                done.push_back({anchors[i].mid_x, anchors[i].ny, c.x0, c.y1, anchors[i].fs, c.x0, c.x1, c.y0, c.y1, c.cx, c.cy, anchors[i].nlines, anchors[i].text, anchors[i].color, static_cast<int>(i)});
            }
            { int cc = 0;
              for (std::size_t i = 0; i < n; ++i) for (std::size_t j = i + 1; j < n; ++j) {
                  const int c = pconf(i, choice[i], j, choice[j]);
                  if (c > 0) { cc += c; fmt::print(stderr, ">>> aa-label placement: residual conflict — '{}' (y={:.0f}%) vs '{}' (y={:.0f}%)\n", anchors[i].text, 100.0 * (cands[i][choice[i]].y0 + cands[i][choice[i]].y1) * 0.5 / height, anchors[j].text, 100.0 * (cands[j][choice[j]].y0 + cands[j][choice[j]].y1) * 0.5 / height); } }
              if (cc > 0) fmt::print(stderr, ">>> aa-label placement: WARNING — {} residual conflict(s) (overlaps/crossings) could not be removed\n", cc); }
        }
        else {
            // legacy: honour each label's manual offset, then nudge overlaps downward
            std::vector<Placed> placed;
            for (std::size_t i = 0; i < anchors.size(); ++i) {
                const auto& a = anchors[i];
                const double tx = a.nx + a.off_x * width;
                const double ty = a.ny + a.off_y * height + a.fs * 0.3;
                placed.push_back({a.nx, a.ny, tx, ty, a.fs, tx, tx + a.tw, ty - a.fs, ty, tx, ty - a.fs * 0.5, a.nlines, a.text, a.color, static_cast<int>(i)});
            }
            std::sort(placed.begin(), placed.end(), [](const Placed& a, const Placed& b) { return a.y0 < b.y0; });
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
        }
        // collect curated MRCA label rows for the unified geometry sidecar (written after this block)
        if (!params.mrca_label_sidecar.empty()) {
            for (const auto& p : done) {
                const Anchor& a = anchors[p.aidx];
                side_rows.push_back({"mrca", a.first, a.last, "", a.text,
                                     a.nx, a.ny, a.mid_x, a.ny, p.x0, p.y0, p.x1, p.y1, a.fs, a.nlines, a.pinned, a.color.rgbI()});
            }
        }

        for (const auto& p : done) {
            // leader to the branch midpoint (p.nx,p.ny); attach point (p.cx,p.cy) chosen above.
            if (std::abs(p.cx - p.nx) > p.fs * 0.4 || std::abs(p.cy - p.ny) > p.fs * 0.4)
                pdf.line(p.nx, p.ny, p.cx, p.cy, GREY, 0.3);
            // stacked text: one substitution per line, each vertically CENTRED in its row so the
            // glyphs fill the collision box (pdf.text anchors the glyph top at y; a cap is ~0.72*fs
            // tall, so top = row-centre - 0.36*fs). This makes the box match the rendered text, so
            // the mid-right attach (p.cx,p.cy = box centre) meets the text mid-height, and overlap
            // tests are computed where the text actually is.
            const double lineh = p.fs * 1.18;
            const auto toks = split_ws(p.text);
            for (std::size_t i = 0; i < toks.size(); ++i)
                pdf.text(p.x0, p.y0 + (static_cast<double>(i) + 0.5) * lineh - p.fs * 0.36, toks[i], p.fs, p.color, /*center=*/false, /*monospace=*/true);
        }
    }

    // --- write the unified geometry sidecar (NodeText vaccine labels + curated MRCA labels) ---
    // Schema "tal-mrca-labels/1": page size (device units, +y DOWN) + per label its kind, identity
    // (mrca -> {first,last}; nodetext -> seq_id), anchor (offset origin), tether, current box, and the
    // offset that reproduces the box (box_top_left = anchor + offset*page). The editor drags a box and
    // writes the inverted offset back to the .tal (mrca -> per-node label.offset+pinned; nodetext ->
    // nodes apply.text.offset). Emitted even with no MRCA labels (so vaccine-only trees still drive it).
    if (!params.mrca_label_sidecar.empty()) {
        const auto jstr = [](const std::string& s) {
            std::string o; o.reserve(s.size() + 2);
            for (char c : s) {
                switch (c) {
                    case '"': o += "\\\""; break;
                    case '\\': o += "\\\\"; break;
                    case '\n': o += "\\n"; break;
                    case '\r': o += "\\r"; break;
                    case '\t': o += "\\t"; break;
                    default: if (static_cast<unsigned char>(c) < 0x20) fmt::format_to(std::back_inserter(o), "\\u{:04x}", static_cast<unsigned>(static_cast<unsigned char>(c))); else o += c;
                }
            }
            return o;
        };
        std::string j;
        fmt::format_to(std::back_inserter(j),
                       "{{\n  \"schema\": \"tal-mrca-labels/1\",\n  \"pdf\": \"{}\",\n  \"image_size\": {},\n"
                       "  \"page\": {{ \"width\": {:.4f}, \"height\": {:.4f} }},\n  \"auto_place\": {},\n  \"labels\": [\n",
                       jstr(output.filename().string()), image_size, width, height,
                       params.mrca_labels_auto_place ? "true" : "false");
        for (std::size_t k = 0; k < side_rows.size(); ++k) {
            const SideRow& r = side_rows[k];
            const double off_x = (r.bx0 - r.ax) / width, off_y = (r.by0 - r.ay) / height;
            fmt::format_to(std::back_inserter(j),
                           "    {{ \"id\": {}, \"kind\": \"{}\", \"first\": \"{}\", \"last\": \"{}\", \"seq_id\": \"{}\", \"text\": \"{}\", \"nlines\": {}, \"pinned\": {},\n"
                           "      \"anchor\": {{ \"x\": {:.4f}, \"y\": {:.4f} }}, \"tether\": {{ \"x\": {:.4f}, \"y\": {:.4f} }},\n"
                           "      \"box\": {{ \"x0\": {:.4f}, \"y0\": {:.4f}, \"x1\": {:.4f}, \"y1\": {:.4f} }},\n"
                           "      \"offset\": {{ \"x\": {:.6f}, \"y\": {:.6f} }}, \"color\": \"#{:06x}\", \"fs\": {:.4f} }}",
                           k, r.kind, jstr(r.first), jstr(r.last), jstr(r.seq_id), jstr(r.text), r.nlines, r.pinned ? "true" : "false",
                           r.ax, r.ay, r.tx, r.ty, r.bx0, r.by0, r.bx1, r.by1, off_x, off_y, r.color, r.fs);
            j += (k + 1 < side_rows.size()) ? ",\n" : "\n";
        }
        j += "  ]\n}\n";
        std::ofstream out{params.mrca_label_sidecar};
        out << j;
    }

    return labels_hidden;

} // ae::tal::export_tree_pdf

// ======================================================================
