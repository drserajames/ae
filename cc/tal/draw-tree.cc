#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <array>
#include <cmath>
#include <fstream>
#include <functional>
#include <limits>
#include <map>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
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

namespace ae::tal
{
    namespace
    {
        // The ECMAScript special characters. A `seq_id` with none of them is a plain literal,
        // and an unanchored regex search for a literal is exactly a substring search — so we can
        // skip std::regex entirely, which matters at ~1000 selectors x ~100k leaves per render.
        constexpr std::string_view seq_id_regex_metacharacters{"\\^$.|?*+()[]{}"};

        char ascii_lower(char c) { return static_cast<char>(std::tolower(static_cast<unsigned char>(c))); }

        std::string ascii_lowered(std::string_view src)
        {
            std::string res;
            res.reserve(src.size());
            std::transform(src.begin(), src.end(), std::back_inserter(res), ascii_lower);
            return res;
        }
    } // namespace

    bool SeqIdMatcher::matches(std::string_view name) const
    {
        if (re)
            return std::regex_search(name.begin(), name.end(), *re);
        // literal fast path: case-insensitive substring, i.e. unanchored — AD's semantics
        return std::search(name.begin(), name.end(), lowered.begin(), lowered.end(),
                           [](char in_name, char in_pattern) { return ascii_lower(in_name) == in_pattern; }) != name.end();
    }

    bool SeqIdMatcher::equals(std::string_view name) const { return ascii_lowered(name) == ascii_lowered(pattern); }

    SeqIdMatcher make_seq_id_matcher(std::string_view pattern)
    {
        SeqIdMatcher matcher{.pattern = std::string{pattern}, .lowered = ascii_lowered(pattern)};
        if (pattern.find_first_of(seq_id_regex_metacharacters) != std::string_view::npos) {
            try {
                matcher.re = std::make_shared<const std::regex>(pattern.begin(), pattern.end(),
                                                                std::regex_constants::ECMAScript | std::regex_constants::icase | std::regex_constants::optimize);
            }
            catch (const std::regex_error& err) {
                // AD would throw out of the whole render here; a single bad selector is not worth
                // losing the tree over, so fall back to treating it as a literal and say so.
                AD_WARNING("seq_id selector \"{}\" is not a valid regex ({}) — matched as a literal string instead", pattern, err.what());
            }
        }
        return matcher;
    }

    // Does a node-mod's selector match this node? Extracted so the drawing path (which
    // applies hide + the style overrides) and `apply_node_hide_mods` (which the `.names`
    // dump uses, and which needs hide only) cannot drift apart.
    static bool node_mod_selects(const NodeSelect& sel, const ae::tree::Node& base, const std::string* name, const std::string* date)
    {
        if (!sel.seq_id.empty() &&
            (name == nullptr || std::none_of(sel.seq_id.begin(), sel.seq_id.end(), [name](const SeqIdMatcher& matcher) { return matcher.matches(*name); })))
            return false;
        if (sel.cumulative_min && base.cumulative_edge.get() < *sel.cumulative_min)
            return false;
        if (sel.edge_min && base.edge.get() < *sel.edge_min)
            return false;
        if (!sel.date_min.empty()) {
            if (name == nullptr)
                return false;
            if (const std::string day = canonical_date(*date); day.empty() || day < sel.date_min)
                return false;
        }
        if (!sel.date_max.empty()) {
            if (name == nullptr)
                return false;
            if (const std::string day = canonical_date(*date); day.empty() || !(day < sel.date_max))
                return false;
        }
        return true;
    }

    // Walk every leaf once and report `seq_id` selectors whose outcome is suspicious. Run once
    // per render, before the mods are applied, so it sees the whole tree.
    //
    // Two findings, deliberately separated because their signal-to-noise differs by two orders
    // of magnitude. Measured on the 2026-0921 round (bvic + h1 + h3, 1088 active selectors):
    //   - "matched only as a substring": 1 hit — and that one hit is a real, report-visible bug
    //     that sat unnoticed for years (a seq_id one character short of the leaf's sequence hash,
    //     hiding a different strain than the author named). Worth a warning each.
    //   - "matched nothing": 205 hits, 203 of them stale ids left over from previous cycles.
    //     Genuinely worth cleaning out of the `.tal`, but not worth 205 warnings on every
    //     render — summarised on one line, with a bounded sample.
    void report_node_mod_selectors(const ae::tree::Tree& tree, const TreeDrawParameters& params)
    {
        if (params.node_mods.empty())
            return;
        struct Stat
        {
            const SeqIdMatcher* matcher{nullptr};
            std::size_t matched{0};
            std::size_t exact{0};
            const std::string* first_inexact{nullptr};
        };
        std::vector<Stat> stats;
        for (const NodeMod& mod : params.node_mods)
            for (const SeqIdMatcher& matcher : mod.select.seq_id)
                stats.push_back(Stat{.matcher = &matcher});
        if (stats.empty())
            return;
        // Same stack walk as apply_node_hide_mods below — the tree exposes no whole-leaf-range
        // accessor, and this runs before anything is hidden, so it sees every leaf.
        struct Frame
        {
            ae::tree::node_index_t index;
            std::size_t cursor;
        };
        std::vector<Frame> stack;
        stack.push_back({ae::tree::Tree::root_index(), 0});
        while (!stack.empty()) {
            Frame& frame = stack.back();
            const ae::tree::Inode& inode = tree.inode(frame.index);
            if (frame.cursor < inode.children.size()) {
                const ae::tree::node_index_t child = inode.children[frame.cursor++];
                if (ae::tree::is_leaf(child)) {
                    const std::string& name = tree.leaf(child).name;
                    for (Stat& stat : stats) {
                        if (stat.matcher->matches(name)) {
                            ++stat.matched;
                            if (stat.matcher->equals(name))
                                ++stat.exact;
                            else if (stat.first_inexact == nullptr)
                                stat.first_inexact = &name;
                        }
                    }
                }
                else
                    stack.push_back({child, 0});
            }
            else
                stack.pop_back();
        }
        std::vector<const Stat*> unmatched;
        for (const Stat& stat : stats) {
            if (stat.matched == 0)
                unmatched.push_back(&stat);
            else if (stat.exact == 0 && stat.matcher->is_literal())
                AD_WARNING("seq_id selector \"{}\" carries no regex metacharacters but equals none of the {} leaf/leaves it selected — the match is unanchored, so a truncated or mistyped id silently selects a longer one (first: \"{}\")",
                           stat.matcher->pattern, stat.matched, *stat.first_inexact);
        }
        if (!unmatched.empty()) {
            std::string sample;
            constexpr std::size_t max_listed{8};
            constexpr std::size_t max_pattern_shown{90}; // a 70-way alternation is 2.5k characters
            for (std::size_t no{0}; no < std::min(max_listed, unmatched.size()); ++no) {
                const std::string& pattern = unmatched[no]->matcher->pattern;
                if (pattern.size() <= max_pattern_shown)
                    fmt::format_to(std::back_inserter(sample), "\n    {}", pattern);
                else
                    fmt::format_to(std::back_inserter(sample), "\n    {}… ({} characters)", std::string_view{pattern}.substr(0, max_pattern_shown), pattern.size());
            }
            if (unmatched.size() > max_listed)
                fmt::format_to(std::back_inserter(sample), "\n    … and {} more", unmatched.size() - max_listed);
            AD_WARNING("{} seq_id selector(s) selected no leaf at all (stale ids do nothing, silently):{}", unmatched.size(), sample);
        }
    }

    // AD `Node::hide()` (acmacs-tal cc/tree.cc:567) hides a matched node AND ITS WHOLE SUBTREE,
    // and `Tree::hide()` (cc/tree.cc:594-599) then hides every inode left with no shown child.
    // ae used to set `shown = false` on the matched node only. The layout and the clade sections
    // never noticed (both stop descending at a hidden inode, so the vertical numbering is the
    // same either way), but the aa-transition consensus DID: `children_with_common_aa`
    // (cc/tree/aa-transitions.cc, AD `number_of_children_with_the_same_common_aa`) reads a
    // child inode's counter WITHOUT a hidden check, exactly as AD does. In AD a hidden inode's
    // counter is empty, because `update_common_aa` skipped all of its (also hidden) children;
    // in ae it was fully populated from descendants that were still marked shown. So a hidden
    // outlier subtree could still "agree" with its parent's consensus, flipping
    // `is_common_with_tolerance` / `is_common_with_tolerance_for_child` and moving labels.
    // On this round's H1 config 4 inodes are hidden by an `edge >= 0.01` mod, covering 12 leaves.
    static void propagate_hide(ae::tree::Tree& tree)
    {
        using namespace ae::tree;
        // down: everything under a hidden node is hidden (AD Node::hide)
        struct Frame { node_index_t index; std::size_t cursor; bool hidden; };
        std::vector<Frame> stack;
        stack.push_back({Tree::root_index(), 0, !tree.root().shown});
        while (!stack.empty()) {
            Frame& frame = stack.back();
            const Inode& inode = tree.inode(frame.index);
            if (frame.cursor < inode.children.size()) {
                const node_index_t child = inode.children[frame.cursor++];
                const bool hidden = frame.hidden;
                if (is_leaf(child)) {
                    if (hidden)
                        tree.leaf(child).shown = false;
                }
                else {
                    Inode& child_inode = tree.inode(child);
                    if (hidden)
                        child_inode.shown = false;
                    stack.push_back({child, 0, !child_inode.shown});
                }
            }
            else {
                stack.pop_back();
            }
        }
        // up: an inode with no shown child is hidden (AD Tree::hide)
        for (auto ref : tree.visit(tree_visiting::inodes_post)) {
            Inode& inode = *ref.inode();
            bool any{false};
            for (const auto child : inode.children)
                any = any || tree.node(child).visit([](const auto* node) { return node->shown; });
            if (!any)
                inode.shown = false;
        }
    }

    // Apply ONLY the `hide` part of the settings' node mods, marking hidden nodes
    // `shown = false` exactly as the drawing path does before it computes the layout.
    //
    // This exists for the `.names` dump, which computes a layout directly and so used to
    // report every leaf in the tree regardless of the settings — 70002 instead of the shown
    // subset on a report tree with 547 hide mods. Callers that match chart antigens against
    // "the leaves on the tree" (the signature page's in-tree grey, its section leaf ranges)
    // were therefore matching against hidden leaves too.
    void apply_node_hide_mods(ae::tree::Tree& tree, const TreeDrawParameters& params)
    {
        using namespace ae::tree;
        if (params.node_mods.empty())
            return;
        report_node_mod_selectors(tree, params);
        tree.calculate_cumulative();
        const auto apply_hide = [&](Node& base, const std::string* name, const std::string* date) {
            for (const auto& mod : params.node_mods) {
                if (node_mod_selects(mod.select, base, name, date) && mod.apply.hide.value_or(false))
                    base.shown = false;
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
                    apply_hide(leaf, &leaf.name, &leaf.date);
                }
                else {
                    Inode& child_inode = tree.inode(child);
                    apply_hide(child_inode, nullptr, nullptr);
                    stack.push_back({child, 0});
                }
            }
            else {
                stack.pop_back();
            }
        }
        propagate_hide(tree);
    }

// Per-inode aa-transition dump for differential verification against AD's
// `tal --first-last-leaves 1` (acmacs-tal `Tree::report_first_last_leaves`, cc/tree.cc:775).
// One TAB-separated line per inode in pre-order:
//     <first descendant leaf name> <last descendant leaf name> <shown leaves> <labels>
// `labels` is AD's `AA_Transitions::display()`: space-joined "{left}{pos}{right}", entries with
// an empty left or right omitted. The (first, last) pair keys the diff, since AD's node ids
// ("vertical.horizontal") have no ae equivalent. Leaf counts are the SHOWN ones, as AD's
// `Node::number_leaves` is (acmacs-tal `Tree::set_first_last_next_node_id`, cc/tree.cc:755-763).
static void write_transitions_report(const ae::tree::Tree& tree, const std::filesystem::path& filename)
{
    using namespace ae::tree;
    const auto last_leaf = [&tree](node_index_t index) {
        while (!is_leaf(index))
            index = tree.inode(index).children.back();
        return index;
    };
    const auto display = [](const transitions_t& transitions) {
        fmt::memory_buffer out;
        bool first{true};
        for (const auto& tr : transitions.transitions) {
            if (tr.left == ' ' || tr.right == ' ')
                continue;
            fmt::format_to(std::back_inserter(out), "{}{}{}{}", first ? "" : " ", tr.left, tr.pos, tr.right);
            first = false;
        }
        return fmt::to_string(out);
    };
    // shown-leaf counts, computed here so the dump does not depend on when number_of_leaves_ was last set
    std::unordered_map<node_index_base_t, std::size_t> shown_leaves;
    const std::function<std::size_t(node_index_t)> count = [&](node_index_t index) -> std::size_t {
        if (is_leaf(index))
            return tree.leaf(index).shown ? 1u : 0u;
        std::size_t num{0};
        for (const auto child : tree.inode(index).children)
            num += count(child);
        shown_leaves[*index] = num;
        return num;
    };
    count(Tree::root_index());

    std::ofstream out{filename};
    const std::function<void(node_index_t)> walk = [&](node_index_t index) {
        const Inode& node = tree.inode(index);
        out << tree.leaf(tree.first_leaf(index)).name << '\t' << tree.leaf(last_leaf(index)).name << '\t' << shown_leaves[*index] << '\t' << display(node.aa_transitions) << '\n';
        for (const auto child : node.children) {
            if (!is_leaf(child))
                walk(child);
        }
    };
    walk(Tree::root_index());
    fmt::print(stderr, ">>> transitions-report: {}\n", filename.string());
}

// Shared tree-render core: compute the page geometry, then draw the whole tree through a surface
// obtained from make_surface(width, height). The two public entry points differ ONLY in the surface
// they supply — a file-bound CairoPdf (export_tree_pdf) or a borrowed sub-rectangle of a shared page
// context (export_tree_into) — so standalone tal-draw file output is unchanged. `output` is used only
// for the (optional) mrca sidecar filename; the shared-surface path passes an empty path.
static std::size_t render_tree_core(ae::tree::Tree& tree, const std::filesystem::path& output, double image_size, const TreeDrawParameters& params,
                                    const std::function<std::unique_ptr<ae::draw::CairoPdf>(double, double)>& make_surface)
{
    using namespace ae::tree;

    // --- compute aa-substitution transitions when requested, instead of using the
    //     transitions already stored on the tree's inodes (the `A` field). The method comes
    //     from the .tal's `draw-aa-transitions` `method` (acmacs-tal names it). ---
    //     Computed BELOW, after the node `hide` mods: AD applies its whole settings stack
    //     (hiding included) before any element's prepare() runs, and both its consensus
    //     counters (update_common_aa: `if (!child.hidden)`) and ae's (aa-transitions.cc:107,
    //     160, 360: `if (… .shown)`) skip hidden children, so computing first would consense
    //     over leaves AD has already removed.

    // --- node select/apply mods (settings DSL): hide nodes + collect per-node style
    //     overrides (keyed by node index, consulted during drawing). Applied before the
    //     layout so that "hide" removes nodes from it. ---
    std::unordered_map<node_index_base_t, Color> edge_color_override;
    std::unordered_map<node_index_base_t, Color> label_color_override;
    std::unordered_map<node_index_base_t, double> label_scale_override;
    std::unordered_map<node_index_base_t, NodeText> text_override; // positioned labels (DrawOnTree)
    if (!params.node_mods.empty()) {
        report_node_mod_selectors(tree, params);
        tree.calculate_cumulative();
        const auto apply_mods = [&](node_index_base_t idx, Node& base, const std::string* name, const std::string* date) {
            for (const auto& mod : params.node_mods) {
                if (!node_mod_selects(mod.select, base, name, date))
                    continue;
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
        propagate_hide(tree);
    }

    // --- compute aa-substitution transitions when requested, instead of using the
    //     transitions already stored on the tree's inodes (the `A` field). The method comes
    //     from the .tal's `draw-aa-transitions` `method` (acmacs-tal names it).
    //     `reset_labels = false`: acmacs-tal's `tal` never clears the labels an `.asr` tjz
    //     already carries (Tal::reset() runs only in its interactive loop), so the method adds
    //     to them and they take part in the ancestor chain — clearing them changes the
    //     computed labels' `left` residue. ---
    if (params.aa_transitions_compute) {
        auto method{aa_nuc_transition_method::consensus};
        if (params.aa_transitions_method == "eu-20200915" || params.aa_transitions_method == "eu_20200915" || params.aa_transitions_method == "eu-20200915-low-mem")
            method = aa_nuc_transition_method::eu_20200915;
        else if (params.aa_transitions_method != "consensus")
            AD_WARNING("draw-aa-transitions: unsupported method \"{}\" — using consensus", params.aa_transitions_method);
        set_aa_nuc_transition_labels(tree, AANucTransitionSettings{.set_aa_labels = true,
                                                                   .set_nuc_labels = false,
                                                                   .method = method,
                                                                   .reset_labels = false,
                                                                   .non_common_tolerance = params.aa_transitions_tolerance});
    }

    // --- --transitions-report=FILE: per-inode label dump for differential verification against
    //     AD's `tal --first-last-leaves 1`, keyed on the (first leaf, last leaf) pair. Written
    //     here, i.e. after the node `hide` mods and the computation, and nothing is drawn. ---
    if (!params.transitions_report_file.empty()) {
        write_transitions_report(tree, params.transitions_report_file);
        return 0;
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
    struct CladeBand { long first_v; long last_v; std::size_t size; std::string first_name; std::string last_name; };
    // `slot` is a double so a `.tal` can ask for a fractional or slightly negative slot (see
    // CladeStyle::slot); `slot_explicit` replaces the old "slot < 0 means auto" sentinel.
    struct CladePlan { std::size_t rank; std::vector<CladeBand> bands; double slot; bool slot_explicit; long first_v; long last_v; std::size_t longest; double label_scale; int rotation; double offset_x; double offset_y;
                       // the rest is carried purely for the clade-section diagnostic below:
                       double incl; double excl;      // the tolerances actually applied
                       std::vector<CladeBand> dropped; }; // post-merge bands the exclusion tolerance removed
    std::vector<CladePlan> clade_plan;
    double clade_max_slot = 0.0;
    {
        for (const std::size_t k : visible_clades) {
            const Clade& clade = clade_sections[k];
            if (clade.sections.empty())
                continue;
            const auto* style = params.clade_styles.count(clade.name) ? &params.clade_styles.at(clade.name) : nullptr;
            // AD defaults (acmacs-tal clades.hh:74-75): section_inclusion_tolerance{10}, section_exclusion_tolerance{5}.
            // ae's CladeStyle struct (draw-tree.hh:44-45) + the settings.cc:115-116 reader default these to 0 when
            // the .tal omits them — and H1's C.1.7 / C.1.7.1 / C.1.7.2 / D.4 set ONLY section-exclusion-tolerance,
            // never inclusion. With incl=0 no runs merge, so C.1.7's 14 contiguous runs (interior gaps == 2 leaves:
            // a single interspersed non-C.1.7 leaf between runs) stayed fragmented and the draw below picked only the
            // LARGEST run — [10776..11096], a stub ~21% of the true [10118..11646] extent, with real C.1.7 leaves
            // both above and below it (FINDINGS-TREE r8 FIX 1: a MEMBERSHIP bug, not a pos_y bug — proved by dumping
            // compute_clade_sections). Restore AD's defaults: treat a missing/0 tolerance as AD's 10 / 5, so nearby
            // runs merge into one full-extent band exactly like AD's Clades::make_sections. Verified across
            // H1/H3/BVic: every SHOWN clade then collapses to exactly ONE kept band whose largest == full span; only
            // C.1.7-family + D.4 change (each toward AD's full extent), H3/BVic are byte-unchanged. Explicit per-clade
            // tolerances (B(5a.1)=20, C(5a.2)=300, D=50/100, …) still win — B(5a.1)'s stray distant runs stay excluded.
            const double incl = (style && style->section_inclusion_tolerance > 0.0) ? style->section_inclusion_tolerance : 10.0;
            const double excl = (style && style->section_exclusion_tolerance > 0.0) ? style->section_exclusion_tolerance : 5.0;
            // merge adjacent sections whose gap <= inclusion tolerance
            std::vector<CladeBand> bands;
            for (const auto& section : clade.sections) {
                const long fv = static_cast<long>(section.first_vertical), lv = static_cast<long>(section.last_vertical);
                if (!bands.empty() && static_cast<double>(fv - bands.back().last_v) <= incl) {
                    bands.back().last_v = lv;
                    bands.back().last_name = section.last_name; // the merged band now ends at this run's last leaf
                    // A merged band's size is its SPAN, not the sum of the runs it bridged — AD
                    // clade_section_t::size() is last->node_id.vertical - first->node_id.vertical + 1,
                    // recomputed from the merged first/last (acmacs-tal clades.hh:40-47), and ae's own
                    // clades.cc CladeSection::size() is span-based too. Accumulating run sizes instead
                    // made merged bands look far smaller than they are, so section-exclusion-tolerance
                    // dropped bands AD keeps and draws: on this round's h1, C.1.9's band 98235..98289 is
                    // span 55 (AD keeps it, excl=20) but summed only 2 (ae dropped it).
                    bands.back().size = static_cast<std::size_t>(bands.back().last_v - bands.back().first_v + 1);
                }
                else
                    bands.push_back({fv, lv, section.size(), section.first_name, section.last_name});
            }
            // drop bands whose size <= exclusion tolerance; if all drop, keep the largest
            std::vector<CladeBand> kept, dropped;
            for (const auto& b : bands) {
                if (static_cast<double>(b.size) > excl)
                    kept.push_back(b);
                else
                    dropped.push_back(b); // reported by the clade-section diagnostic, so a `(1)` that is
            }                             // really "several runs, the strays dropped" is not mistaken for monophyly
            // AD clades.cc:118-120 drops the small sections only when at least one survives; when EVERY
            // section is small nothing is dropped and the clade keeps them all. ae used to keep only the
            // LARGEST here, which silently hid the rest — now matched to AD (and to clades.cc's
            // apply_section_tolerance, so the drawing and signature-page paths agree).
            if (kept.empty()) {
                kept = bands;
                dropped.clear();
            }
            std::size_t longest = 0;
            for (const auto& b : kept) longest = std::max(longest, b.size);
            const std::optional<double> slot = style ? style->slot : std::optional<double>{};
            // Default all-clades label scale when neither a per-clade nor an all-clades `label.scale`
            // is given (H1's report .tal sets neither for C.1.7 / D / C.1.9 — their `?scale` keys are
            // disabled). AD's real struct default is 0.7 (acmacs-tal clades.hh:36 parameters::Label
            // scale{0.7}); label_size = slot.width * 0.7. The r6 fallback of 0.88 rendered every
            // default-scaled clade (D and the clades to its right, C.1.9, …) ~26% too big vs AD (r7
            // item #1). Restore AD's 0.7. Clades with an explicit `scale` (D.1-D.5/D.3.1.1 → 0.5,
            // C.1.7.1/.2 & C.1.9.x → 0.3) read it via style->label_scale and are unaffected.
            // H3/BVic set clades_label_scale (1.4) so they take that branch, not this fallback.
            const double lscale = (style && style->label_scale > 0.0) ? style->label_scale
                                    : (params.clades_label_scale > 0.0 ? params.clades_label_scale : 0.7);
            const int rot = style ? style->rotation_degrees : 90;
            const double offx = style ? style->label_offset_x : 0.002;
            const double offy = style ? style->label_offset_y : 0.0;
            clade_plan.push_back({k, std::move(kept), slot.value_or(0.0), slot.has_value(), 0, 0, longest, lscale, rot, offx, offy, incl, excl, std::move(dropped)});
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
        // Occupancy is tracked per WHOLE column: an explicit slot of 2.2 or 1.75 still shares its
        // staircase step with the integer slot it rounds to, so an auto-placed clade must treat
        // that column as taken. Only the drawing uses the exact (possibly fractional) value.
        std::vector<std::vector<std::pair<long, long>>> occupied;
        const auto column_of = [](double slot) { return std::max(0, static_cast<int>(std::lround(slot))); };
        const auto reserve = [&](const CladePlan* p, int column) {
            if (column >= static_cast<int>(occupied.size())) occupied.resize(static_cast<std::size_t>(column) + 1);
            occupied[static_cast<std::size_t>(column)].emplace_back(p->first_v, p->last_v);
        };
        for (auto* p : refs) {                                        // explicit slots first
            if (!p->slot_explicit) continue;
            reserve(p, column_of(p->slot));
            clade_max_slot = std::max(clade_max_slot, p->slot);
        }
        for (auto* p : refs) {
            if (p->slot_explicit) continue;
            int column = 0;
            for (;; ++column) {
                if (column >= static_cast<int>(occupied.size())) { occupied.emplace_back(); break; }
                bool clash = false;
                for (const auto& sp : occupied[static_cast<std::size_t>(column)])
                    if (p->first_v < sp.second && sp.first < p->last_v) { clash = true; break; }
                if (!clash) break;
            }
            reserve(p, column);
            p->slot = static_cast<double>(column);
            clade_max_slot = std::max(clade_max_slot, p->slot);
        }
    }

    // --- hz sections: the computed clade bands with the `.tal`'s CURATED `hz-sections` entries
    //     merged in. Port of AD HzSections::update_from_parameters / sort / detect_intersect /
    //     set_prefix (acmacs-tal cc/hz-sections.cc:44 / :93 / :112 / :136).
    //
    // AD keeps ONE section list. Clades::make_clades fills it from the computed clade bands
    // (HzSections::add_section), then update_from_parameters walks the `.tal`'s static `sections`
    // array and, for each entry, does find_add_section BY ID: an entry whose id is already there
    // overrides that section's extents, and an entry whose id is NOT there ADDS a section. That
    // second half is how a hand-split clade survives — the curator writes `<clade>-1`, `<clade>-2`
    // beside the computed `<clade>-0` and AD draws three bands where the tree yields one run.
    //
    // ae had no equivalent: the section set was built from `clade_plan` alone and the static block
    // reached only `params.hz_sections`, where it drove the marker column and the time-series
    // separators but never the sections themselves. The two therefore disagreed with each other,
    // and with AD, on any tree whose `.tal` curates splits. Measured on 2026-0223 (whose `.tal`s
    // RUN the `hz` sub-program; 2026-0921's define it and never invoke it, which is why only the
    // older round exposes this): ae reported 14/20/11 sections against AD's 14/21/15.
    struct HzSectionResolved
    {
        std::string id, prefix, label, first_name, last_name, aa_transitions;
        std::optional<std::string> curated_aa_transitions; // AD label_aa_transitions; dump text only
        long first_v{0}, last_v{0};
        bool shown{true}, intersect{false};
        std::size_t size{0};
    };
    std::vector<HzSectionResolved> hz_set;
    for (const CladePlan& plan : clade_plan) {
        const Clade& clade = clade_sections[plan.rank];
        const auto style_it = params.clade_styles.find(clade.name);
        const CladeStyle* style = style_it != params.clade_styles.end() ? &style_it->second : nullptr;
        const std::string display = (style && !style->display_name.empty()) ? style->display_name : clade.name;
        for (std::size_t bno{0}; bno < plan.bands.size(); ++bno) {
            const CladeBand& band = plan.bands[bno];
            hz_set.push_back(HzSectionResolved{.id = fmt::format("{}-{}", clade.name, bno),
                                               .label = display,
                                               .first_name = band.first_name,
                                               .last_name = band.last_name,
                                               .first_v = band.first_v,
                                               .last_v = band.last_v,
                                               .size = band.size});
        }
    }

    // Two callers supply `params.hz_sections`, and they mean different things by it:
    //   * settings_v3, translating a `.tal` that RUNS an `hz-sections` command — a CURATED list,
    //     every entry carrying AD's `id`, to be merged into the computed set the way AD does.
    //   * py/ae/tal/signature_page.py, handing over the sections the page is actually built from
    //     (`SM.sections_for`), already lettered in tree order and with NO ids. That list is
    //     authoritative for the page and must be drawn as given, not merged into anything.
    // The presence of an id is the discriminator, so the signature-page column is untouched.
    const bool hz_curated_by_id =
        std::any_of(std::begin(params.hz_sections), std::end(params.hz_sections), [](const HzSection& section) { return !section.id.empty(); });

    if (hz_curated_by_id) {
        // seq_id -> vertical, the same numbering cc/tal/clades.cc uses: a counter over SHOWN
        // leaves in tree order, which is exactly the index into layout.leaves.
        std::unordered_map<std::string_view, long> vertical;
        vertical.reserve(layout.leaves.size());
        for (std::size_t i{0}; i < layout.leaves.size(); ++i)
            vertical.emplace(layout.leaves[i].name, static_cast<long>(i));

        // AD Tree::leaf_position::first (cc/tree.cc:734-741): a node that is its parent's FIRST
        // child, where the parent has more than one child. Taken from the RAW child order, hidden
        // children included, as AD's pre-order lambda does.
        std::unordered_set<std::string_view> leaf_pos_first;
        const std::function<void(node_index_t)> mark_first = [&](node_index_t index) {
            const Inode& in = tree.inode(index);
            for (std::size_t ch{0}; ch < in.children.size(); ++ch) {
                const node_index_t child = in.children[ch];
                if (ch == 0 && in.children.size() > 1 && is_leaf(child))
                    leaf_pos_first.emplace(tree.leaf(child).name);
                if (!is_leaf(child))
                    mark_first(child);
            }
        };
        mark_first(Tree::root_index());

        for (const HzSection& curated : params.hz_sections) {
            if (curated.id.empty())
                continue; // AD merges on the id; an entry without one addresses nothing
            auto found = std::find_if(std::begin(hz_set), std::end(hz_set), [&curated](const HzSectionResolved& s) { return s.id == curated.id; });
            if (found == std::end(hz_set)) {
                hz_set.push_back(HzSectionResolved{.id = curated.id});
                found = std::prev(std::end(hz_set));
            }
            if (!curated.first.empty()) {
                if (const auto it = vertical.find(curated.first); it != vertical.end()) {
                    found->first_name = curated.first;
                    found->first_v = it->second;
                }
                // else: the named leaf is hidden or absent. AD leaves node_id.vertical at the
                // node_id_t::NotSet sentinel and prints 4294967295; ae keeps the computed extent
                // instead of propagating a sentinel into a coordinate. See PORTING.md.
            }
            if (!curated.last.empty()) {
                if (const auto it = vertical.find(curated.last); it != vertical.end()) {
                    long last_v = it->second;
                    std::string last_name = curated.last;
                    // AD hz-sections.cc:62 — when the curated `last` lands on a leaf_position::first
                    // node, step back to the previous shown leaf. That is what lets a curator close
                    // a section by naming the FIRST leaf of the section below it.
                    if (last_v > 0 && leaf_pos_first.contains(curated.last)) {
                        --last_v;
                        last_name = layout.leaves[static_cast<std::size_t>(last_v)].name;
                    }
                    found->last_name = last_name;
                    found->last_v = last_v;
                }
            }
            found->shown = curated.shown;
            if (!curated.label.empty())
                found->label = curated.label;
            found->curated_aa_transitions = curated.aa_transitions; // AD update_from_parameters: assigned, not copy-if-set
            if (found->last_v >= found->first_v)
                found->size = static_cast<std::size_t>(found->last_v - found->first_v + 1);
        }
    }

    // AD HzSections::sort() — top-to-bottom by the first leaf.
    std::sort(std::begin(hz_set), std::end(hz_set), [](const HzSectionResolved& s1, const HzSectionResolved& s2) { return s1.first_v < s2.first_v; });
    // AD HzSections::detect_intersect() — SHOWN sections only (a hidden section overlapping a
    // shown one is not a conflict: it is not drawn).
    std::vector<std::pair<std::string, std::string>> hz_intersects;
    for (auto sect = std::begin(hz_set); sect != std::end(hz_set); ++sect) {
        if (!sect->shown)
            continue;
        for (auto other = std::next(sect); other != std::end(hz_set); ++other) {
            if (other->shown && sect->first_v <= other->last_v && other->first_v <= sect->last_v) {
                hz_intersects.emplace_back(sect->id, other->id);
                sect->intersect = other->intersect = true;
            }
        }
    }
    // AD HzSections::set_prefix() — A, B, C… over the SHOWN sections in order; a hidden section
    // takes no letter and does not consume one. ae previously took the letter from the `.tal`'s
    // own "L" field, which AD never reads back, so a `.tal` whose letters counted hidden sections
    // put the wrong letter on every bracket (2026-0223 bvic: first shown section lettered "C"
    // where AD draws "A").
    {
        char letter{0};
        for (HzSectionResolved& section : hz_set) {
            if (section.shown)
                section.prefix.assign(1, static_cast<char>('A' + (letter++ % 26)));
            else
                section.prefix.clear();
        }
    }
    {
        std::vector<std::pair<std::size_t, std::size_t>> spans;
        spans.reserve(hz_set.size());
        for (const HzSectionResolved& section : hz_set)
            spans.emplace_back(static_cast<std::size_t>(std::max(0L, section.first_v)), static_cast<std::size_t>(std::max(0L, section.last_v)));
        const std::vector<std::string> transitions = section_aa_transitions(tree, spans);
        for (std::size_t no{0}; no < hz_set.size(); ++no)
            hz_set[no].aa_transitions = transitions[no];
    }

    // What the marker column and the time-series separators actually draw. With a curated,
    // id-bearing list this is the MERGED set (so a hand-split clade draws its own brackets and
    // rules, and a `show: false` section draws none); with the signature page's authoritative
    // list it is that list verbatim, prefixes and all, exactly as before this merge existed.
    struct HzDrawn
    {
        // `id` carries AD's warn_if_present rule into the matrix-rule registry (an auto-split id
        // like "C.1-1" expects to share a line with its clade); it is not drawn.
        std::string id, first_name, last_name, prefix;
        bool shown{true};
    };
    std::vector<HzDrawn> hz_drawn;
    if (hz_curated_by_id) {
        for (const HzSectionResolved& section : hz_set)
            hz_drawn.push_back(HzDrawn{.id = section.id, .first_name = section.first_name, .last_name = section.last_name, .prefix = section.prefix, .shown = section.shown});
    }
    else {
        for (const HzSection& section : params.hz_sections)
            hz_drawn.push_back(HzDrawn{.id = section.id, .first_name = section.first, .last_name = section.last, .prefix = section.prefix, .shown = section.shown});
    }

    // --- clade-section diagnostic: AD Clades::report_clades + HzSections::report/detect_intersect ---
    //
    // Ported from acmacs-tal cc/clades.cc:221 and cc/hz-sections.cc:112/196. Reported from the
    // `clade_plan` built immediately above — i.e. from the bands THIS renderer actually draws, not
    // from cc/tal/clades.cc's compute_hz_sections (the signature-page path). The two agree on the
    // merge rule but NOT on two points, so reporting the sig-page numbers here would mislead:
    //   * exclusion: AD (and compute_hz_sections) drop small sections only when at least one
    //     section survives, otherwise they keep them ALL; the loop above keeps only the LARGEST.
    //   * all-clades tolerances: compute_hz_sections inherits `all-clades`
    //     section-inclusion/exclusion-tolerance as the per-clade default, the loop above reads
    //     only the per-clade style (a missing/0 value falls back to AD's 10/5).
    // Both are noted in cc/tal/PORTING.md; this block deliberately mirrors the drawing path.
    //
    // Printed BEFORE the drawing below so the RUNNING-THE-REPORT.md §10.5 tuning loop can read it
    // without waiting out a full render, and also written to `<output>.taleg`.
    //
    // `.taleg` is ONE diagnostic file per tree, shared by every diagnostic block: the clade-section
    // report here and the aa-transition label-position dump further down (which can only be produced
    // after the labels are placed). `clades.report_file` overrides the path; "-" writes no file; the
    // shared-surface entry point (signature pages) passes an empty `output`, which also means no file
    // — stderr only. The first block to emit truncates, later ones append, so the order in the file is
    // the order the render produced them.
    std::filesystem::path taleg_path{params.clades_report_file};
    if (taleg_path.empty() && !output.empty())
        taleg_path = std::filesystem::path{output}.replace_extension(".taleg");
    if (taleg_path == std::filesystem::path{"-"})
        taleg_path.clear();
    bool taleg_started{false};
    // AD splits every one of these blocks across the two streams: the `vvvv`/`^^^^` banners and the
    // intersect warnings are AD_INFO/AD_WARNING (stderr), while the pasteable rows and their
    // enclosing `[`/`]` are fmt::print (stdout) — see AD/sources/acmacs-tal/cc/clades.cc:224 and
    // draw-aa-transitions.cc:757. That is what makes `./0do <page> > labels.txt` capture the block
    // and nothing else, which matters most on the signature-page path: it passes an empty `output`,
    // so no `.taleg` is written and stdout is the only clean capture there.
    // `>>`-prefixed lines are the banner/warning shape; blank lines separate blocks, so both go to
    // stderr and stdout carries only the pasteable JSON. The `.taleg` file keeps the whole block.
    //
    // The HZ block is the exception, and it is AD's exception, not ours: AD splits its clade and
    // aa-transition reports but prints the hz block WHOLLY to stderr, brackets included
    // (AD/sources/acmacs-tal/cc/hz-sections.cc:212 and :228-230 are all `fmt::print(stderr, …)`,
    // where clades.cc:224 and draw-aa-transitions.cc:759 use AD_INFO for the banner only). Sarah
    // ruled on 2026-09-15 that ae matches AD here rather than applying the split uniformly, so
    // `stderr_only` is passed for that block and nothing else.
    enum class diag_stream { split, stderr_only };
    const auto emit_diag = [&taleg_path, &taleg_started](const std::string& report, diag_stream mode = diag_stream::split) {
        if (mode == diag_stream::stderr_only) {
            fmt::print(stderr, "{}", report);
        }
        else {
            for (std::size_t pos{0}; pos < report.size();) {
                const auto eol = report.find('\n', pos);
                const auto end = eol == std::string::npos ? report.size() : eol + 1;
                const std::string_view line{report.data() + pos, end - pos};
                fmt::print(line.starts_with(">>") || line == "\n" ? stderr : stdout, "{}", line);
                pos = end;
            }
            std::fflush(stdout);
        }
        if (taleg_path.empty())
            return;
        if (std::ofstream out{taleg_path, taleg_started ? std::ios::app : std::ios::trunc}; out) {
            out << report;
            taleg_started = true;
        }
        else
            AD_WARNING("cannot write tal diagnostic to {}", taleg_path.string());
    };

    if (params.clades_report && !clade_plan.empty()) {
        fmt::memory_buffer rep;
        const auto app = std::back_inserter(rep);
        // The HZ block goes to its own buffer so it can be emitted stderr-only, as AD does.
        fmt::memory_buffer hz_rep;
        const auto hz_app = std::back_inserter(hz_rep);

        // ---- AD Clades::report_clades ----
        fmt::format_to(app, ">>> Clades ({}) vvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvv\n", clade_plan.size());
        for (const CladePlan& plan : clade_plan) {
            const Clade& clade = clade_sections[plan.rank];
            const auto style_it = params.clade_styles.find(clade.name);
            const CladeStyle* style = style_it != params.clade_styles.end() ? &style_it->second : nullptr;
            std::string display = (style && !style->display_name.empty()) ? style->display_name : clade.name;
            for (auto nl = display.find('\n'); nl != std::string::npos; nl = display.find('\n', nl + 2))
                display.replace(nl, 1, "\\n"); // keep the line as the .tal would write it
            fmt::format_to(app, "Clade {} ({})    {{\"name\": \"{}\", \"display_name\": \"{}\", \"section-inclusion-tolerance\": {:.0f}, \"section-exclusion-tolerance\": {:.0f}, \"show\": {}}}\n",
                           clade.name, plan.bands.size(), clade.name, display, plan.incl, plan.excl, !(style && style->hide));
            for (std::size_t bno{0}; bno < plan.bands.size(); ++bno) {
                const CladeBand& band = plan.bands[bno];
                fmt::format_to(app, "  ({}) \"{}\" [{}] slot:{} {} \"{}\" .. {} \"{}\"\n", bno, display, band.size, plan.slot, band.first_v, band.first_name, band.last_v,
                               band.last_name);
                if (bno + 1 < plan.bands.size()) {
                    // AD reports the COUNT OF INTERVENING LEAVES (next.first - this.last - 1) while the
                    // merge test compares (next.first - this.last) against the tolerance — so merging this
                    // pair needs a tolerance of gap+1. Spell that out: it is the number §10.5 asks for.
                    const long gap = plan.bands[bno + 1].first_v - band.last_v - 1;
                    fmt::format_to(app, "   gap {}  (to merge: \"section-inclusion-tolerance\" >= {})\n", gap, gap + 1);
                }
            }
            // Bands the exclusion tolerance removed. Without these a clade reported `(1)` is
            // ambiguous: genuinely one run, or several runs with the strays silently dropped —
            // and §10.5's "usually resembles the previous report" cross-check needs to tell them apart.
            if (!plan.dropped.empty()) {
                fmt::format_to(app, "   dropped {} band(s) by \"section-exclusion-tolerance\" {:.0f} (NOT drawn):", plan.dropped.size(), plan.excl);
                for (const CladeBand& band : plan.dropped)
                    fmt::format_to(app, " [{}] {}..{}", band.size, band.first_v, band.last_v);
                fmt::format_to(app, "\n");
            }
        }
        fmt::format_to(app, ">>> ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n\n");

        // ---- AD HzSections::report over the merged section set built above ----
        // AD_WARNING in AD; a parent clade containing a child is expected, siblings overlapping is not.
        for (const auto& [one, other] : hz_intersects)
            fmt::format_to(hz_app, ">> WARNING: HZ Sections \"{}\" and \"{}\" intersect\n", one, other);
        const std::vector<HzSectionResolved>& sections = hz_set;

        // AD HzSections::report: a `[ … ]` block in the `.tal`'s own `hz` "sections" array shape,
        // column-aligned, so it can be pasted straight back into a `.tal`.
        // AD HzSection::aa_transitions_format (cc/hz-sections.cc:12): the "aa_transitions" column
        // prints the curated value when the settings carried one — "" included — else the computed
        // list, so a dump pasted back into a `.tal` echoes curated values unchanged. "All
        // transitions" is always the computed list.
        const auto aa_transitions_format = [](const HzSectionResolved& section) -> const std::string& {
            return section.curated_aa_transitions ? *section.curated_aa_transitions : section.aa_transitions;
        };
        std::size_t w_id{0}, w_first{0}, w_last{0}, w_label{0}, w_label_aa{0};
        for (const HzSectionResolved& section : sections) {
            w_id = std::max(w_id, section.id.size());
            w_first = std::max(w_first, section.first_name.size());
            w_last = std::max(w_last, section.last_name.size());
            w_label = std::max(w_label, section.label.size());
            w_label_aa = std::max(w_label_aa, aa_transitions_format(section).size()); // AD hz-sections.cc:206
        }
        const bool any_intersect = std::any_of(std::begin(sections), std::end(sections), [](const HzSectionResolved& section) { return section.intersect; });
        fmt::format_to(hz_app, ">>> HZ sections ({})\n[\n", sections.size());
        for (const HzSectionResolved& section : sections)
            fmt::format_to(hz_app, "    {{\"show\": {:6s} \"id\": {:{}s} \"L\": \"{:1s}\", \"V\": [{:5d}, {:5d}], \"N\": {:5d}, {}\"first\": {:{}s} \"last\": {:{}s} \"label\": {:{}s} \"aa_transitions\": {:{}s} \"All transitions\": \"{}\"}},\n",
                           fmt::format("{},", section.shown), fmt::format("\"{}\",", section.id), w_id + 3, section.prefix, section.first_v, section.last_v, section.size,
                           section.intersect ? "\"INTRSCT\":1, " : (any_intersect ? "             " : ""), fmt::format("\"{}\",", section.first_name), w_first + 3,
                           fmt::format("\"{}\",", section.last_name), w_last + 3, fmt::format("\"{}\",", section.label), w_label + 3,
                           fmt::format("\"{}\",", aa_transitions_format(section)), w_label_aa + 3, section.aa_transitions);
        fmt::format_to(hz_app, "]\n\n");

        // …and to <output>.taleg, which RUNNING-THE-REPORT.md §10.5 documents reading instead of
        // watching the terminal.
        emit_diag(fmt::to_string(rep));
        emit_diag(fmt::to_string(hz_rep), diag_stream::stderr_only);
    }

    // --clades-report: the diagnostic above is all the caller wanted. Return before make_surface,
    // so no PDF is created and the minutes of drawing below are skipped entirely.
    if (params.clades_report_only)
        return 0;

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
    // A display name may hold "\n" to stack a clade label over several lines (Feb slide style:
    // the new name with the old nomenclature on the line below, never "new (old)"). Only the horizontal clade-column
    // label stacks; everywhere else the lines are joined back with a space.
    const auto clade_label_lines = [](const std::string& text) -> std::vector<std::string> {
        std::vector<std::string> lines;
        std::string::size_type start{0};
        for (auto nl = text.find('\n'); nl != std::string::npos; start = nl + 1, nl = text.find('\n', start))
            lines.push_back(text.substr(start, nl - start));
        lines.push_back(text.substr(start));
        return lines;
    };
    const auto clade_label_one_line = [&](const std::string& text) -> std::string {
        std::string joined{text};
        std::replace(joined.begin(), joined.end(), '\n', ' ');
        return joined;
    };
    constexpr double clade_label_line_spacing = 1.15; // baseline-to-baseline, in font sizes

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
    const double width_base = params.width_to_height_ratio > 0.0 ? image_size * params.width_to_height_ratio : image_size;
    // --- left band for the automatically-placed aa-transition labels ---------------------------
    // A tree page has no whitespace on its left: the root sits on the page margin and the canopy
    // opens to the right, so a label on a basal branch has nowhere to go on the near side and the
    // placer is forced to park it right of its own branch, on a long shallow leader across the
    // canopy. A band on the left is what makes a left-hand placement possible for those labels.
    // 0.05 of the page width. Swept 0.00 -> 0.16 against both the overlap metrics and the dead
    // space actually left over: 0.16 was far too generous (77pt of the h3 band and 58pt of the
    // B/Vic band went unused), while 0.00 costs real quality — measured on the three 2026-0223
    // report trees, dropping the band to 0 gives B/Vic 3 residual leader/leader conflicts and h3
    // 1 leader-over-text, and pushes the worst leader from 9.9%/12.1% of the page to 15.3%/14.7%
    // and the worst tree-ink crossing from 33/30 cells to 95/94. 0.05 keeps all three trees
    // conflict-free with short leaders.
    const double aa_band = (!output.empty() && !params.mrca_labels.empty()) ? 0.05 * width_base : 0.0;
    // The band is taken OUT of the page, not added to it. `width_to_height_ratio` is the page
    // aspect acmacs-tal computes from the `.tal` (cc/draw.cc Draw::set_width_to_height_ratio),
    // and AD then draws a page of exactly height*ratio (cc/draw.cc:43) — so adding anything here
    // makes every ae tree page wider than AD's for the same input, which it was by exactly
    // 1 + 0.05 until this was fixed. The page is height*ratio; the band comes out of the tree.
    const double width = width_base;

    // --- horizontal layout: hz-marker column | tree | labels | time-series column | dash bars | clades column ---
    //     The clade column is the RIGHTMOST (acmacs-tal draws it past the time-series, flipped to
    //     the page's right edge), so the bracket/label staircase sits in the right margin like AD. ---
    const double margin = 0.03 * width;
    // The RIGHT margin is separately settable. On a signature page the tree panel butts up
    // against the map grid, so AD's rightmost column (the AA colour bars) has to reach the
    // panel edge; a symmetric 3% margin parks ~4mm of blank paper between the bars and the
    // maps that no composition gap can take back.
    const double margin_r = (params.right_margin_ratio > 0.0 ? params.right_margin_ratio : 0.03) * width;
    const double drawable_w = width - margin - margin_r;
    const double gap = 0.012 * width;
    // The gap immediately before the clades column is separately settable (`clades.gap_ratio`),
    // because it is half of the distance between the time-series matrix and the first clade
    // bracket — the other half being one whole clade slot. AD spells it as an explicit `gap`
    // element in the `.tal` program; ae positions the columns itself, so it reads a ratio.
    const double clade_gap = params.clades_gap_ratio >= 0.0 ? params.clades_gap_ratio * width : gap;
    // The band computed above, inset from the left of the drawable area (so the root sits at
    // margin + aa_left and the tree loses that width). It was briefly ADDED to the page width
    // instead, to keep the tree at its full width; that is what made every ae tree page exactly
    // 5% wider than AD's, so the page is now AD's and the band is taken from the tree. The two
    // costs that had an earlier carved-out reserve rejected (r5 items #1/#2) do not apply: the
    // title is drawn at the root, not at the page margin (see the title block below), and the
    // label metrics improved rather than regressed — see the sweep note at `aa_band`.
    // Standalone tree PDFs only — the signature-page path (export_tree_into, empty `output`)
    // letterboxes the tree into someone else's rectangle.
    const double aa_left = aa_band;
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
    // AD (clades.cc:34) sets width_to_height_ratio = (number_of_slots+2)*slot.width and IGNORES any
    // configured width-to-height-ratio for the clade column; slot.width defaults to 0.02 (fraction of
    // height). The report .tal gives only a width-to-height-ratio (0.092 for H1) and NO slot.width, so
    // ae used to honour 0.092 -> a 92px column that COMPRESSED the slot pitch (15.3px) and the labels
    // below AD's true 0.02*height (~19px) -> labels too small (r6 #1) AND the deepest label spilled
    // past the narrow column into the dash bar (r6 #2). Match AD: derive the column width from the AD
    // slot.width (0.02*height) when no explicit slot.width is given, leaving AD's 2-slot right margin
    // for the deepest rotated label. (number_of_slots = clade_max_slot+1, so width = (clade_max_slot+3).)
    // clade_max_slot may be fractional (an explicit `"slot": 2.2`); round the column up to whole
    // slots so the width is unchanged for the integer case and never narrower than the deepest
    // bracket for the fractional one.
    const double clade_max_slot_w = std::ceil(clade_max_slot);
    const double clade_w = (params.clades && !visible_clades.empty())
        ? (clade_slot_px > 0.0 ? (clade_max_slot_w + 2.0) * clade_slot_px
           : (clade_max_slot_w + 3.0) * 0.02 * height)
        : 0.0;
    // AD sizes the time-series column as n_slots * slot.width (slot.width a fraction of
    // height); honour it so the column is AD's narrow width, falling back to 0.34·drawable.
    const double ts_w = (params.time_series && !time_series.slots.empty())
        ? (params.time_series_slot_width > 0.0
               ? static_cast<double>(time_series.slots.size()) * params.time_series_slot_width * height
               : 0.34 * drawable_w)
        : 0.0;
    const double dash_col_w_ref = 0.022 * drawable_w;                  // DEFAULT dash-bar column pitch (legend/label fonts scale off this, so narrower columns don't shrink the text)
    const double dash_col_w = (params.dash_column_width_ratio > 0.0 ? params.dash_column_width_ratio : 0.022) * drawable_w; // width of one dash-bar column
    const double dash_w = static_cast<double>(params.dash_bars.size()) * dash_col_w;
    const int n_right = (label_w > 0.0) + (clade_w > 0.0) + (ts_w > 0.0) + (dash_w > 0.0)
                        + (grey_dash_w > 0.0) + (hz_marker_w > 0.0);
    // AD (conf/tal.json:93-105) sets the grey matches-chart-antigen dash-bar just 0.005·treeH to the
    // RIGHT of the time-series — a thin gap, not a full inter-column gap. treeH = the tree band height
    // (same formula as vmargin/top_reserve/bottom_reserve below; those vars aren't declared yet here).
    // r7 item #6 — sig-page (hz_section_labels) tree band extended top+bottom to fill more of the
    // strip like AD (measured AD sig tree [0.035, 0.932] of the composed page vs ae [0.047, 0.925]):
    // top reserve 0.022 → 0.012 (title still fits just above the tree), bottom reserve 0.075 → 0.066
    // (still clears the rotated date labels + viridis date-key). Keep these two literals in sync with
    // the top_reserve / bottom_reserve block below (marker_treeH must equal the tree band height).
    const double marker_treeH = height - 2.0 * (0.008 * height)
        - ((ts_w > 0.0 || dash_w > 0.0) ? (params.hz_section_labels ? 0.012 * height : 0.017 * height)
                                        : (params.title.empty() ? 0.0 : 0.035 * height))
        - ((ts_w > 0.0 || dash_w > 0.0) ? (params.hz_section_labels ? 0.012 * height : 0.017 * height) : 0.0);
    const double grey_gap = 0.005 * marker_treeH;   // AD time-series → grey-bar gap (was the full 0.012·width)

    // The gaps actually consumed on the right differ from `gap * n_right`: the grey dash bar
    // takes the narrow `grey_gap`, and the hz-marker column takes a NEGATIVE quarter-gap so its
    // bracket arms overlap the dash table like AD's. Charging the tree a full gap for each of
    // those anyway left ~2.25 gaps of dead paper at the panel's right edge — which on a
    // signature page is exactly the space the maps want. Subtract what is really spent.
    const double gaps_right = params.clades_before_time_series
        ? gap * static_cast<double>((label_w > 0.0) + (ts_w > 0.0) + (dash_w > 0.0))
              + (clade_w > 0.0 ? clade_gap : 0.0)
              + (grey_dash_w > 0.0 ? grey_gap : 0.0)
              - (hz_marker_w > 0.0 ? gap * 0.25 : 0.0)
        : gap * static_cast<double>(n_right - (clade_w > 0.0 ? 1 : 0)) + (clade_w > 0.0 ? clade_gap : 0.0);
    const double tree_w = drawable_w - aa_left - hz_w - label_w - clade_w - ts_w - dash_w - grey_dash_w - hz_marker_w - gaps_right;


    double cursor = margin + aa_left + tree_w;
    double x_label0{0.0}, x_clade0{0.0}, x_ts0{0.0}, x_dash0{0.0}, x_grey0{0.0}, x_hzmark0{0.0};
    if (params.clades_before_time_series) {
        // AD layout-with-maps order (left→right past the tree): labels, clades, time-series
        // matrix, grey matches-chart dash, hz-section markers, then the AA dash-bar colour
        // columns nearest the maps.
        if (label_w > 0.0)     { cursor += gap; x_label0 = cursor;  cursor += label_w; }
        if (clade_w > 0.0)     { cursor += clade_gap; x_clade0 = cursor;  cursor += clade_w; }
        if (ts_w > 0.0)        { cursor += gap; x_ts0 = cursor;     cursor += ts_w; }
        if (grey_dash_w > 0.0) { cursor += grey_gap; x_grey0 = cursor;   cursor += grey_dash_w; }
        // hz-section markers on the RIGHT of the time series (AD), hugging the grey-dash/matrix.
        // AD runs the bracket's top/bottom arms right up to (and the section-letter halo slightly
        // INTO) the grey-dash table edge, so start the marker column with a small NEGATIVE offset:
        // x_hzmark0 sits just inside the grey column's right edge, the arm-left-end overlapping the
        // table dashes like AD rather than floating a gap to its right (Sarah r6 sig section item #5a).
        if (hz_marker_w > 0.0) { cursor -= gap * 0.25; x_hzmark0 = cursor; cursor += hz_marker_w; }
        // AA dash-bar colour columns go OUTSIDE the hz-section markers, i.e. between the
        // section brackets/letters and the maps — that is AD's order (matrix, grey dashes,
        // bracket+letter column, colour bars, maps). Placing them before the markers, as a
        // first pass at this did, leaves the section letters sitting inboard of the bars
        // instead of wrapping around them.
        if (dash_w > 0.0)      { cursor += gap; x_dash0 = cursor;   cursor += dash_w; }
    }
    else {
        // AD layout-tree-only order: labels, time-series matrix, clades, then aa dash-bars.
        if (label_w > 0.0) { cursor += gap; x_label0 = cursor; cursor += label_w; }
        if (ts_w > 0.0)    { cursor += gap; x_ts0 = cursor;    cursor += ts_w; }
        if (clade_w > 0.0) { cursor += clade_gap; x_clade0 = cursor; cursor += clade_w; }
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
                legend_items.emplace_back(clade_label_one_line(clade_display_for(clade_sections[k].name)), clade_color_for(k, clade_sections[k].name));
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
    // AD insets the matrix by just the rotated date-label band (~0.017·height) top and bottom, so the
    // tree fills almost the whole canvas (measured AD matrix band = [0.025,0.975] of height once the
    // 0.008 vmargin is added). A larger reserve here shrinks the tree and leaves blank space at the
    // bottom. Sig pages (hz_section_labels) keep their own deeper bands (out of scope here).
    // r7 item #6: sig-page bottom reserve 0.075 → 0.066, top reserve 0.022 → 0.012 so the tree +
    // time-series fill more of the strip vertically like AD (kept in sync with marker_treeH above).
    // r8: 0.066 was still ~2.5x what AD leaves — measured, AD's matrix ink ends at 97.5% of page
    // height (its grid bottom is 98.9%, i.e. flush) while ae stopped at 90.1%, ~40pt short on
    // every page. The band only has to clear the date-colour key strip under the matrix.
    const double bottom_reserve = (ts_w > 0.0 || dash_w > 0.0)
        ? (params.hz_section_labels ? 0.012 * height : 0.017 * height)
        : 0.0;
    const double top_reserve = (ts_w > 0.0 || dash_w > 0.0)
        ? (params.hz_section_labels ? 0.012 * height : 0.017 * height)
        : (params.title.empty() ? 0.0 : 0.035 * height);

    // --- vertical (shared) + tree horizontal transforms ---
    const double height_units = layout.height > 0.0 ? layout.height : 1.0;
    const double max_cum = layout.max_cumulative > 0.0 ? layout.max_cumulative : 1.0;
    const double vstep = (height - 2.0 * vmargin - top_reserve - bottom_reserve) / height_units;
    const double hstep = tree_w / max_cum;
    const auto dev_x = [&](double cumulative) { return margin + aa_left + hz_w + cumulative * hstep; };
    const auto dev_y = [&](double vertical_offset) { return vmargin + top_reserve + (vertical_offset - 0.5) * vstep; };
    // TOP EDGE of the row of `layout.leaves[leaf_index]` = AD LayoutElement::pos_y_above
    // (acmacs-tal cc/layout.cc:253, vertical_step * (cumulative_vertical_offset - vertical_offset/2)).
    // The +1 is the index→offset conversion: layout.cc assigns the FIRST leaf y = 1
    // (`height += default_vertical_offset` BEFORE the push_back), so leaves[i].y == i + 1 while
    // every clade/hz section carries 0-based leaf INDICES (cc/tal/clades.cc's `vertical` counter
    // starts at 0). Feeding an index straight to dev_y — as the clades block did — puts the line
    // a whole row too high. `leaf_index == leaves.size()` is the bottom edge of the last row.
    const auto row_top = [&](double leaf_index) { return dev_y(leaf_index + 1.0 - 0.5); };

    const double line_width = std::clamp(vstep * 0.5, 0.2, 3.0);
    // AD draws tree branches at vertical_step()*0.5 with NO lower floor, so a branch is always
    // half the row pitch and white gaps remain between adjacent leaves. A fixed floor (e.g. 0.1)
    // is fatal here: for these dense report trees vstep is ~0.01pt, so a floor forces the line
    // ~10x the row pitch and adjacent leaf edges merge into solid black blocks (burying the tip
    // names). Match AD: half the pitch, capped only at the top, no meaningful floor. Used for the
    // three tree-edge draws only (leaf edge, inode edge, vertical connector); clade arrows/spines,
    // time-series separators, hz-lines and dash marks keep their own widths.
    // params.edge_line_width_scale is AD's per-node edge_line_width_scale applied globally
    // (the info trees' `nodes {select:{all-and-intermediate}, apply:{tree-edge-line-width:N}}`
    // heavy-edge diagnostic; 1.0 = default). min(vstep*0.5,1.0) keeps the default render
    // unchanged at scale 1; for the dense info trees vstep*0.5 is well under the cap, so
    // vstep*0.5*scale matches AD's branch width exactly.
    const double tree_line_width = std::min(vstep * 0.5, 1.0) * params.edge_line_width_scale;
    const double font_size = std::clamp(vstep * 0.8, 3.0, 14.0);

    std::unique_ptr<ae::draw::CairoPdf> pdf_holder = make_surface(width, height);
    ae::draw::CairoPdf& pdf = *pdf_holder;
    pdf.background(WHITE);
    // AD's line widths are ABSOLUTE points at final page scale (acmacs-tal `Pixels` through
    // context::convert). A standalone tal-draw PDF is drawn 1:1, so they land as written — but the
    // signature page composes this tree into a sub-rectangle (export_tree_into -> the borrowed-context
    // CairoPdf), and cairo then multiplies every stroke width by that rectangle's scale. Measured on
    // 2026-0223-ssm h1-cdc: the composed tree's geometry is the SAME physical size as AD's (matrix
    // 112.47pt vs AD 109.11pt) while every constant stroke came out at 0.5513x AD's — the slot
    // separators 0.2757 vs 0.5, the clade spine 0.5513 vs 1.0, the clade arms 0.2757 vs 0.5. So the
    // page was right and only the ink was thin (Sarah, 19 Sep).
    // `devw` converts an absolute AD width into this surface's user space; it is exactly 1.0 for a
    // standalone render, so report trees are untouched. Apply it ONLY to AD's constant widths —
    // NEVER to a width derived from the geometry (tree_line_width is half the row pitch and is
    // supposed to shrink with the tree).
    const double devw = pdf.stroke_scale() > 0.0 ? 1.0 / pdf.stroke_scale() : 1.0;

    // --- title (top-left, near the very top; acmacs-tal Title draws at offset [5,5]) ---
    if (!params.title.empty()) {
        const double title_fs = std::clamp(0.015 * height, 8.0, 26.0);
        // Sit the title ABOVE the tree (Sarah r5 item #2): AD places it so its bottom meets the
        // tree top (matrix/leaf band starts at vmargin+top_reserve). ae had y=0.95*fs, which put the
        // glyph-box bottom (y is the box TOP here) ~4pt below the tree top, so it overlapped/occluded
        // the root backbone and read as "beside" the tree. Raise it so the box clears the tree top.
        const double title_y = std::min(title_fs * 0.6, vmargin + top_reserve - title_fs);
        // At the ROOT (margin + aa_left), not the page margin: with a label band the root is inset,
        // and a title left at the margin would sit out in the band beside the tree instead of above
        // it. With no band (aa_left == 0) this is exactly the old position.
        pdf.text(margin + aa_left, std::max(title_y, 1.0), params.title, title_fs, BLACK, /*center=*/false);
    }

    // No horizontal rules are drawn here. Every rule that crosses the time-series matrix — whether
    // a clade's or an hz section's — goes through `matrix_rules` below and is emitted once, in the
    // time-series block, so the two producers cannot over-draw each other. (The comment that used
    // to sit here claimed hz separators were not drawn at all; they were, at the bottom of the
    // time-series block, on top of the clade rules.)

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
    // `show` alone decides whether the blanket per-inode labels are DRAWN. Computing the
    // transitions is a separate question (`compute`), exactly as in AD, where
    // Settings::add_draw_aa_transitions sets `aa_transitions.calculate = true` for every
    // `draw-aa-transitions` command while DrawAATransitions::draw decides what is painted.
    // A `.tal` whose block carries curated `per-node` labels asks for the computation but
    // not the blanket labels; gating the drawing on `compute` too would flood the tree.
    if (params.aa_transitions) {
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

    // --- the time-series matrix's horizontal rules, in ONE registry (port of acmacs-tal
    //     TimeSeries::add_horizontal_line_above, cc/time-series.cc:138) ---
    //
    // AD keeps every rule that crosses the matrix in a single `horizontal_lines_` collection keyed
    // by THE NODE THE RULE SITS ABOVE, and a second registration for the same node adds nothing —
    // it only warns. Two producers call it:
    //   * Clades::add_separators_to_time_series  (cc/clades.cc:200)   — GREY 0.5 (clades.hh:79)
    //   * HzSections::add_separators_to_time_series (cc/hz-sections.cc:168) — GREY 1.0 (hz-sections.hh:60)
    // so where an hz-section boundary lands on a leaf that already carries a clade rule, AD draws
    // ONE line, with the clade's parameters. ae had no registry and drew both, which is only
    // invisible while the report trees never run their `hz` sub-program.
    //
    // REGISTRATION ORDER — clades first. Not from ae's draw order (which proves nothing) but from
    // AD's preparation stages: Layout::prepare (cc/layout.cc:67) runs stages 1→3 over every
    // element, Clades::prepare (cc/clades.cc:26) registers on its FIRST call (`if (!prepared_)`,
    // i.e. stage 1) while HzSections::prepare (cc/hz-sections.cc:23) is guarded by
    // `stage == 2`. So the clade line always wins a shared boundary regardless of the elements'
    // order in the layout. The two blocks below register in that same order.
    //
    // The key is the INDEX of the leaf below the rule, which is how AD addresses both ends of a
    // section: the top rule is registered above `section.first`, the bottom rule above
    // `section.last->last_next_leaf` — the leaf AFTER the section. Two consequences ae did not
    // have: a section's bottom rule and the next section's top rule are ONE rule, and the last
    // leaf in the tree has no `last_next_leaf`, so the bottom-most section registers no rule
    // (`leaf_below == leaves.size()` is rejected below).
    struct MatrixRule { Color color{GREY}; double width{0.5}; };
    std::map<long, MatrixRule> matrix_rules;
    const auto n_leaves = static_cast<long>(layout.leaves.size());
    const auto register_matrix_rule = [&matrix_rules, n_leaves](long leaf_below, Color color, double width, bool warn_if_present, std::string_view producer) {
        if (leaf_below < 0 || leaf_below >= n_leaves)
            return; // AD: no node to key on (past the last leaf) -> no line at all
        const auto [it, inserted] = matrix_rules.try_emplace(leaf_below, MatrixRule{.color = color, .width = width});
        // AD_WARNING fires only when the DISCARDED line differs from the kept one, and only when
        // the caller asked for it — HzSections suppresses it for auto-split ids like "C.1-1", where
        // a coincident line is expected rather than a mistake (cc/hz-sections.cc:172).
        if (!inserted && warn_if_present && (it->second.color != color || it->second.width != width))
            fmt::print(stderr, ">>> WARNING: matrix horizontal line above leaf {} already added with different parameters ({} discarded)\n", leaf_below, producer);
    };

    // --- clades column (port of acmacs-tal Clades::draw): each shown clade's bands are vertical
    //     double-arrow brackets at slot.width*(slot+1) from the matrix edge (slot 0 nearest the
    //     matrix, deeper clades stepping right), with horizontal arms to the matrix side and a
    //     name label rotated clockwise (top-to-bottom), sized slot.width * per-clade scale. ---
    if (clade_w > 0.0 && !clade_plan.empty()) {
        // Slot spacing: AD uses a FIXED slot.width = 0.02 * clades-area-height (acmacs-tal
        // clades.hh:66 SlotParameters width{0.02}; clades.cc:269 pos_x = viewport.left() +
        // slot.width*(slot+1)) — NOT ae's old clade_w/(max_slot+2), which bunched the brackets
        // tighter than AD (measured 0.016w vs AD 0.024w). Adopt AD's value; clamp to
        // clade_w/(max_slot+1) so the deepest bracket can never overrun the clade column into the
        // dash-bar column (keeps clade/dash alignment intact — the stated risk).
        const double clades_area_h = height - 2.0 * vmargin - top_reserve - bottom_reserve;
        // AD slot.width = 0.02 (fraction of the clades area height); the bracket staircase steps at
        // slot.width*(slot+1) and the label size = slot.width*scale. Do NOT compress to fit a narrow
        // column (the old min(..., clade_w/(max_slot+1)) shrank pitch+font below AD) — clade_w is now
        // sized to AD's (max_slot+3)*0.02*height so the full-pitch staircase + 2-slot label margin fit.
        const double slot_px = clade_slot_px > 0.0 ? clade_slot_px : 0.02 * clades_area_h;
        // Arrowhead: an ABSOLUTE size tied to page height, not slot_px, so every subtype gets the
        // same head (H1's wide clade slot otherwise produced oversized heads vs H3). ~1.4px @1000.
        // AD double_arrow (acmacs-draw Surface::arrow): arrow_width{3.0px} = head FULL width, and
        // ARROW_WIDTH_TO_LENGTH_RATIO=2.0 => head length = 2*full = 4*half. Rendered half-width ~1.44pt
        // @1000. Match it: half-width 0.00144*height, length 4*half.
        const double ahw = std::clamp(0.00144 * height, 0.9, 2.0);  // arrowhead half-width (= AD arrow_width/2)
        const double ahl = ahw * 4.0;                              // arrowhead length (AD 2.0 ratio on full width)
        // Fallback arm end for a tree with NO time-series column: there is no matrix to run to,
        // and no registry entry either, so the arm simply spans the clades column. With a matrix
        // the arm stops at the column edge instead and the matrix part is a registered rule.
        const double line_to = ts_w > 0.0 ? x_ts0 : x_clade0;
        // When the clades column sits LEFT of the matrix (AD sig page), slot 0 (shallow) hugs the
        // matrix edge and deeper clades step toward the tree (left); arms still run right to the
        // matrix and the name label sits to the LEFT of the bracket.
        const bool clades_left = params.clades_before_time_series;
        const double clade_right_edge = x_clade0 + clade_w;
        // --- pre-pass: declutter clade LABELS that share a slot and would overlap along the leaf
        //     axis. AD's sub-clade labels (C.1.7.1/.2, C.1.9.1/.4/.2, …) sit at well-separated band
        //     centres; ae's ported sections place some adjacent tips close together, so two rotated
        //     labels centred on their bands overprint into garbled text ("C.1.C1.7.2"). Spread each
        //     overlapping cluster apart with a small gap, centred on the cluster's mean, so the labels
        //     read cleanly like AD. Only the TEXT moves — the brackets stay on their true bands. ---
        // One bracket + label per BAND (AD Clades::draw draws the arrow, the arms and the label per
        // SECTION, all sections of a clade sharing the clade's slot — acmacs-tal clades.cc:248-... ).
        // A clade left fragmented by its tolerances therefore SHOWS as several brackets, which is the
        // signal the `.tal` needs tuning; it is the user's job to bring it back to one via
        // section-inclusion/exclusion-tolerance (RUNNING-THE-REPORT.md §10.5).
        struct BandLabel { std::size_t plan_index; std::size_t band_index; };
        std::vector<BandLabel> band_labels;
        for (std::size_t i = 0; i < clade_plan.size(); ++i)
            for (std::size_t b = 0; b < clade_plan[i].bands.size(); ++b)
                band_labels.push_back({i, b});
        std::vector<double> label_cy(band_labels.size());
        std::vector<double> label_half(band_labels.size()); // half text-extent along the leaf axis
        for (std::size_t i = 0; i < band_labels.size(); ++i) {
            const auto& pl = clade_plan[band_labels[i].plan_index];
            const CladeBand& bd = pl.bands[band_labels[i].band_index];
            // Centre of the band's true vertical extent: midway between the top edge of its first
            // row and the bottom edge of its last. (Was dev_y(mean index), a whole row too high —
            // the same index-vs-offset slip as the arms; see `row_top`.)
            label_cy[i] = (row_top(static_cast<double>(bd.first_v)) + row_top(static_cast<double>(bd.last_v) + 1.0)) / 2.0 + pl.offset_y * height;
            const double fs = std::max(slot_px * pl.label_scale, 2.5);
            const std::string nm = clade_display_for(clade_sections[pl.rank].name);
            const double tw = pdf.text_size(clade_label_one_line(nm), fs).first;
            // half text-extent along the leaf axis. text_size under-reports the rendered rotated
            // advance by ~10-12%, so use 0.6·tw (not tw/2) or two adjacent sub-labels still touch.
            // A horizontal label stacked over n lines is (n-1) line pitches taller.
            const double extra_lines = static_cast<double>(clade_label_lines(nm).size() - 1);
            label_half[i] = (pl.rotation == 0) ? fs * 0.6 + extra_lines * clade_label_line_spacing * fs / 2.0 : tw * 0.6;
        }
        {
            std::unordered_map<int, std::vector<std::size_t>> by_slot;
            for (std::size_t i = 0; i < band_labels.size(); ++i) // keyed by whole column: a 2.2 declutters against a 2
                by_slot[static_cast<int>(std::lround(clade_plan[band_labels[i].plan_index].slot))].push_back(i);
            const double decl_gap = 0.004 * height; // gap between separated labels (~4px @1000)
            for (auto& [slot, idxs] : by_slot) {
                if (idxs.size() < 2) continue;
                std::sort(idxs.begin(), idxs.end(), [&](std::size_t a, std::size_t b) { return label_cy[a] < label_cy[b]; });
                std::size_t k = 0;
                while (k < idxs.size()) {
                    std::size_t j = k; // grow a cluster of mutually-overlapping labels
                    while (j + 1 < idxs.size()
                           && label_cy[idxs[j + 1]] - label_cy[idxs[j]] < label_half[idxs[j]] + decl_gap + label_half[idxs[j + 1]])
                        ++j;
                    if (j > k) {
                        double mean = 0.0, span = 0.0;
                        for (std::size_t m = k; m <= j; ++m) mean += label_cy[idxs[m]];
                        mean /= static_cast<double>(j - k + 1);
                        for (std::size_t m = k; m < j; ++m) span += label_half[idxs[m]] + decl_gap + label_half[idxs[m + 1]];
                        label_cy[idxs[k]] = mean - span / 2.0;
                        for (std::size_t m = k + 1; m <= j; ++m)
                            label_cy[idxs[m]] = label_cy[idxs[m - 1]] + label_half[idxs[m - 1]] + decl_gap + label_half[idxs[m]];
                    }
                    k = j + 1;
                }
            }
        }
        for (std::size_t label_index = 0; label_index < band_labels.size(); ++label_index) {
            const auto& plan = clade_plan[band_labels[label_index].plan_index];
            const CladeBand& band = plan.bands[band_labels[label_index].band_index];
            const Clade& clade = clade_sections[plan.rank];
            const double cx = clades_left
                ? clade_right_edge - slot_px * (plan.slot + 1.0)
                : x_clade0 + slot_px * (plan.slot + 1.0); // AD pos_x
            // AD clades.cc:287 label_size = slot.width * scale with NO upper clamp; the prior
            // ae cap (14) bit H1 (slot_px ~15.3) and made the labels smaller than AD (r6 item #1).
            // slot_px*label_scale <= 0.02*clades_area_h (<= ~20px) by construction, so no guard needed
            // beyond a tiny floor. H3/BVic slot_px (7-9.8) are unaffected (well below the old cap).
            const double clade_fs = std::max(slot_px * plan.label_scale, 2.5);
            // One arrow per BAND, spanning exactly that band — AD's per-section draw. (ae previously
            // drew a single arrow over the clade's LARGEST band only, which made a fragmented clade
            // look like one short bracket instead of several, hiding the very thing §10.5 asks you
            // to fix. The brackets never span across a gap: each is its own band's extent.)
            const long ext_first = band.first_v, ext_last = band.last_v;
            {
                // AD's clade double-arrow spans the FULL vertical extent of the section: from
                // pos_y_above(first) = the TOP edge of the first leaf's row (half a row above its
                // centre) to pos_y_below(last) = the BOTTOM edge of the last leaf's row (half a row
                // below its centre) — see acmacs-tal layout.cc:253-268 / clades.cc:271-272. ae drew
                // centre-to-centre (dev_y(first)..dev_y(last)), one whole vertical_step too short
                // (missing half a row at each end), so short clades like C.1.7 read as a stub arrow
                // (r7 item #2). `row_top` reaches the row edges = AD.
                // pos_y_above(first) / pos_y_below(last) via `row_top`, which carries the 0-based
                // leaf index → 1-based vertical offset conversion the old `dev_y(ext_first)` left
                // out. Measured on cc/tal/test/tree-hz-clade-lines.json (800pt, 8 leaves, 95pt
                // rows): clade P = L3..L5, whose rows span y 210..495, was bracketed at 115..400 —
                // exactly one row high, on L2..L4. Every clade bracket, arm and label in every ae
                // tree was off by that row, and it is why a "coincident" hz boundary never
                // coincided: the hz side (which uses leaves[i].y, already 1-based) was right.
                const double y0 = row_top(static_cast<double>(ext_first));
                const double y1 = row_top(static_cast<double>(ext_last) + 1.0);
                // AD splits these two rules in a way ae had merged into one line:
                //   * Clades::draw (cc/clades.cc:281-283) draws an arm from the bracket arrow out to
                //     the matrix-facing edge of the clades viewport — it never reaches INTO the matrix;
                //   * the part that crosses the matrix is registered on the time-series instead, and
                //     is emitted once, below.
                // ae drew a single line from the matrix's NEAR edge all the way to the arrow, which in
                // the clades-right layout painted it straight across the matrix, over-drawing the hz
                // separator there.
                // The arm still has to MEET the matrix, though. Measured on AD's own output —
                // 2026-0223-ssm/sp/h1-cdc.asr.after-2021.sp.pdf: the clade arms all end at x=311.59 and
                // the matrix rule runs 311.59..420.70 (= the 24 slot separators' span), so AD's clades
                // viewport ABUTS the matrix and the two segments join seamlessly. ae lays its columns
                // out with an inter-column gap AD does not have, so stopping the arm at the clades
                // column edge left an 8.4pt white break that AD has no trace of (Sarah, 19 Sep). Run the
                // arm to the matrix's NEAR edge instead: same join as AD, still not across the matrix.
                // P1: AD (clades.hh:79, parameters.hh:14) draws the two horizontal clade arms as
                // GREY 0.5px (Line default width 0.5). Same px→pt scale as the hz-section marker
                // (which uses line_width 1.0 directly and matched AD @600dpi), so 0.5 → 0.5.
                // Gated by main's clades_horizontal_lines toggle (PR #29).
                if (params.clades_horizontal_lines) {
                    // arm: arrow → the matrix's NEAR edge (right edge when the clades column is on the
                    // right, left edge when it is on the left). Never the far edge: that is the matrix crossing.
                    const double arm_end = ts_w > 0.0 ? (clades_left ? x_ts0 : (x_ts0 + ts_w)) : line_to;
                    pdf.line(arm_end, y0, cx, y0, GREY, 0.5 * devw);
                    pdf.line(arm_end, y1, cx, y1, GREY, 0.5 * devw);
                    // AD Clades::add_separators_to_time_series (cc/clades.cc:206-212), gated by
                    // time_series_top_separator / _bottom_separator (both default true, clades.hh:81)
                    // — here the same clades_horizontal_lines toggle. warn_if_present = true, as AD
                    // passes for both ends.
                    register_matrix_rule(ext_first, GREY, 0.5, true, "clade");
                    register_matrix_rule(ext_last + 1, GREY, 0.5, true, "clade");
                }
                // vertical double-arrow spine with FILLED triangular heads (AD double_arrow).
                // The spine runs only between the two arrowhead BASES, so the tips are pure
                // triangle apexes with no line poking through to the point. For a band shorter
                // than two full heads the head length is capped to half the band so the two heads
                // meet base-to-base at the centre (points still at the extremes), instead of
                // overlapping into an inward-pointing bowtie; no spine is drawn in that case.
                // AD draws FULL-length heads regardless of band height and a spine ONLY between the
                // head bases (Surface::arrow: line(la,lb) where la,lb are the head attachment points).
                // For a band shorter than two heads the bases cross, so no spine is drawn and the two
                // narrow full-length heads overlap into a thin double-arrow — NOT the fat base-to-base
                // filled diamond a half-band cap produced (the ♦ vs ↕ bug on C.1.7.1/C.1.7.2).
                const double head_len = ahl;
                // P1: AD (clades.hh:23-36, parameters.hh:14) draws the arrow SPINE at the Line
                // default width — BLACK ~1.0px (vs the 0.5px grey arms). Same 1:1 px→pt scale as
                // the hz-section marker's line_width 1.0. Raised 0.4 → 1.0 (clade brackets were
                // too thin — known r6 residual). The width is clades_line_width (default 1.0 = AD).
                const double spine_w = params.clades_line_width * devw;
                if (params.clades_arrows) {
                    if (y1 - head_len > y0 + head_len)
                        pdf.line(cx, y0 + head_len, cx, y1 - head_len, BLACK, spine_w);
                    pdf.filled_triangle(cx, y0, cx - ahw, y0 + head_len, cx + ahw, y0 + head_len, BLACK); // top head (apex up at y0)
                    pdf.filled_triangle(cx, y1, cx - ahw, y1 - head_len, cx + ahw, y1 - head_len, BLACK); // bottom head (apex down at y1)
                }
                else {
                    // Feb slide style (clades "arrows": false): a plain line over the band's full
                    // extent, however short the band — there are no heads to leave room for.
                    pdf.line(cx, y0, cx, y1, BLACK, spine_w);
                }
            }
            {
                const std::string name = clade_display_for(clade.name);
                // label centred on the clade's vertical extent (AD vpos=middle), shifted by the
                // per-clade offset, then decluttered (see pre-pass) so same-slot labels don't overlap.
                const double center_y = label_cy[label_index];
                // NO halo behind the clade name (r7 item #3): AD draws the clade labels with a plain
                // transparent background (acmacs-tal Clades::draw calls surface.text with no halo) —
                // the label sits in the white clade column beside its arrow. The r3 white-halo box was
                // an ae-only addition Sarah has now reverted; pass halo_width 0 so the background is
                // transparent (matches AD).
                if (plan.rotation == 0) {
                    // horizontal: right of the arrow normally, left of it when clades sit left of the matrix.
                    // A multi-line name stacks top-to-bottom, the block centred on the band; lines share
                    // the left edge (right of the bracket) or the right edge (left of it).
                    const auto lines = clade_label_lines(name);
                    const double pitch = clade_label_line_spacing * clade_fs;
                    const double first_y = center_y + clade_fs * 0.32 - pitch * static_cast<double>(lines.size() - 1) / 2.0;
                    for (std::size_t ln = 0; ln < lines.size(); ++ln) {
                        const double tw0 = pdf.text_size(lines[ln], clade_fs).first;
                        const double tx = clades_left ? (cx - ahw - clade_fs * 0.1 - tw0 + plan.offset_x * height)
                                                      : (cx + ahw + clade_fs * 0.1 + plan.offset_x * height);
                        pdf.text(tx, first_y + pitch * static_cast<double>(ln), lines[ln], clade_fs, BLACK, /*center=*/false, /*monospace=*/false, /*halo_width=*/0.0, WHITE);
                    }
                }
                else {
                    // clockwise (top→bottom), vertically centred; placed BESIDE the double-arrow with a
                    // small gap, not overlapping it. AD's clade labels (C.1.7, D.2, …) sit clear to the
                    // LEFT of their double-arrow spine when clades_left (a visible gap between the label's
                    // right edge and the arrow), so anchor at cx - ahw - 1.05·fs (arrow half-width + a
                    // ~1·fs clearance). (r6 briefly moved this to cx - 0.78·fs to overlap the arrow — that
                    // was mis-aimed; AD does NOT overlap, so reverted to the beside-the-arrow offset.)
                    const double tx = clades_left ? (cx - ahw - clade_fs * 1.05 + plan.offset_x * height)
                                                  : (cx + ahw + clade_fs * 0.1 + plan.offset_x * height);
                    // rotated labels do not stack: a multi-line name is drawn on one line
                    const std::string one_line = clade_label_one_line(name);
                    const double tw = pdf.text_size(one_line, clade_fs).first;
                    pdf.text_rotated(tx, center_y - tw / 2.0, one_line, clade_fs, BLACK, 90.0, /*halo_width=*/0.0, WHITE);
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
        // AD add_separators_to_time_series iterates the MERGED section list (shown only), not the
        // `.tal` entries — so a curated split gets its own pair of rules and a hidden section none.
        // The outer guard stays on params.hz_sections: a `.tal` that never runs an `hz-sections`
        // command draws no separators at all, exactly as before.
        if (!params.hz_sections.empty()) {
            std::unordered_map<std::string, long> name_index;
            name_index.reserve(layout.leaves.size());
            for (std::size_t i = 0; i < layout.leaves.size(); ++i)
                name_index.emplace(layout.leaves[i].name, static_cast<long>(i));
            for (const auto& [id, first_name, last_name, prefix, shown] : hz_drawn) {
                if (!shown)
                    continue;
                // AD HzSections::add_separators_to_time_series (cc/hz-sections.cc:172): suppress the
                // "already added" warning for an auto-split id like "C.1-1", where a line shared with
                // the clade the split came from is expected. An entry with no id warns, as AD's
                // `id.size() < 3` does.
                const bool warn_if_present = id.size() < 3 || id[id.size() - 2] != '-';
                // GREY 1.0 = AD HzSections::Parameters::line (acmacs-tal cc/hz-sections.hh:60), and
                // deliberately HEAVIER than the clade rule's 0.5: in AD the hz separator is the
                // prominent line. ae drew 0.4, which was both 2.5x too thin and, being under the
                // clade's 0.5, inverted the relationship. Verified on AD's own output rather than its
                // header — 2026-0223 and the current rounds cannot show it (their sections are
                // clade-derived, so every boundary is clade-claimed and the hz width never renders),
                // but 2022-0221-ssm/sp/h1pdm.cdc.sp.pdf runs its `hz` sub-program and carries both
                // families: 16 clade rules at 0.5 and 4 hz separators at 1.0, at 20 distinct y with
                // none doubled — which also demonstrates this registry from AD's output.
                if (const auto it = name_index.find(first_name); it != name_index.end())
                    register_matrix_rule(it->second, GREY, 1.0, warn_if_present, "hz-section");
                // ...and the bottom rule above `section.last->last_next_leaf` — the leaf AFTER the
                // section, so it collapses into the next section's top rule, and does not exist at
                // all when the section ends on the tree's last leaf.
                if (const auto it = name_index.find(last_name); it != name_index.end())
                    register_matrix_rule(it->second + 1, GREY, 1.0, warn_if_present, "hz-section");
            }
        }
        // AD TimeSeries::draw_horizontal_lines (cc/time-series.cc:282): one pass over the registry,
        // each rule spanning the time-series viewport only. Emitted BEFORE the vertical slot
        // separators so the verticals stay on top (see the z-order note above).
        for (const auto& [leaf_below, rule] : matrix_rules) {
            const double y = row_top(static_cast<double>(leaf_below));
            pdf.line(x_ts0, y, x_ts0 + ts_w, y, rule.color, rule.width * devw);
        }
        for (std::size_t i = 0; i <= n_slots; ++i) // vertical separators (AD SlotSeparator default = BLACK, 0.5px)
            pdf.line(x_ts0 + static_cast<double>(i) * slot_w, top, x_ts0 + static_cast<double>(i) * slot_w, bottom, BLACK, 0.5 * devw);
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

        // --- date-colour key (AD): a horizontal viridis gradient at the bottom date band, keying the
        //     date→colour scale used to colour antigens in the section maps. Sig pages only. Drawn
        //     BEFORE the date text so the month/year tokens render ON TOP of the bar (Sarah r6 sig:
        //     "text on top, bar behind/overlapping upward"). Anchored at the YEAR-token top so the bar
        //     sits behind the year token and extends down, the month name staying on white above it. ---
        if (params.hz_section_labels) {
            // viridis quadratic-bezier gradient (anchors #440154, #40ffff, #fde725), per-term trunc
            const auto viridis = [](double t) -> Color {
                const double u = 1.0 - t;
                const auto ch = [&](int a, int b, int c) { return static_cast<int>(u * u * a + 2.0 * u * t * b + t * t * c); };
                return Color{static_cast<unsigned>((ch(0x44, 0x40, 0xfd) << 16) | (ch(0x01, 0xff, 0xe7) << 8) | ch(0x54, 0xff, 0x25))};
            };
            // Sarah's explicit choice: the viridis date bar spans vertically behind BOTH date rows
            // of the bottom band — the month token AND the year token sit ON the gradient (text drawn
            // on top). Deliberate deviation from AD (AD covers only the month row). key_y = month-token
            // top (bottom+2), key_h spans down to the year-token bottom (month_w + pair_gap + year_w),
            // with a ~1px pad each side.
            const double key_y = bottom + 1.0;                             // just above the month-token top
            const double key_h = month_w + pair_gap + year_w + 2.0;        // both rows: month top → year bottom
            const int nseg = 72;
            for (int i = 0; i < nseg; ++i) {
                const Color col = viridis((i + 0.5) / nseg);
                pdf.rectangle(x_ts0 + (static_cast<double>(i) / nseg) * ts_w, key_y, ts_w / nseg + 0.6, key_h, col, 0.0, col);
            }
        }
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
                // AD reads "Mon YY" top-to-bottom (month token first/higher, year token below it) in
                // BOTH date bands. The two bands are mirror-images about the matrix, so the token that
                // is "nearest the matrix" differs between them, but the on-page READING ORDER is the
                // same: month above, year below. (Sarah r6 item #4 — the top band was emitting year
                // above month, i.e. reversed "YY Mon"; the bottom band was already correct.)
                // top band (above the matrix): month higher, year just above the matrix edge.
                pdf.text_rotated(lx, top - 2.0 - year_w - pair_gap - month_w, mon, slot_fs, BLACK, 90.0);
                pdf.text_rotated(lx, top - 2.0 - year_w, yy, slot_fs, BLACK, 90.0);
                // bottom band (below the matrix): month just below the matrix, year below month.
                pdf.text_rotated(lx, bottom + 2.0, mon, slot_fs, BLACK, 90.0);
                pdf.text_rotated(lx, bottom + 2.0 + month_w + pair_gap, yy, slot_fs, BLACK, 90.0);
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
        const double dash_len = dash_col_w * (params.dash_fill_fraction > 0.0 ? params.dash_fill_fraction : 0.6);
        const double dash_lw = std::clamp(vstep * 0.6, 0.15, 2.5); // thin marks, AD-like white space
        const double pos_fs = std::clamp(dash_col_w_ref * 0.5, 6.0, 11.0); // font off the DEFAULT column width, not the (tunable) actual one
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
            const double leg_fs = std::clamp(dash_col_w_ref * 0.42, 5.0, 9.0); // font off the DEFAULT column width, not the (tunable) actual one
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
        // DELIBERATE DIVERGENCE FROM AD — Sarah's call, 19 Sep 2026. AD draws this bar at its own
        // absolute 0.5 (measured: width 0.5, dash length 4.82, on
        // 2026-0223-ssm/sp/h1-cdc.asr.after-2021.sp.pdf), and a `0.5 * devw` here reproduced that
        // exactly. She looked at it beside AD and asked for this one bar to stay THIN — the row-pitch
        // width it has always had — while every other stroke on the page takes AD's absolute value.
        // So this is the one width that intentionally does NOT get `devw`: it keeps scaling with the
        // composition, which is what makes it fine (0.0827 on the composed sig page vs AD's 0.5).
        // Do not "restore AD parity" here without asking her.
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
        // AD HzSectionMarker::draw (acmacs-tal cc/hz-sections.cc:249-281): per shown section a "]"
        // that OPENS toward the dash table. The vertical SPINE is on the FAR (map) side — the right
        // edge of the thin marker strip — and BOTH arms run LEFT from the spine to the dash-table's
        // right edge (a black continuation of the grey section-separator lines, via AD's
        // draw_horizontal_line_between(time_series, marker)). The section LETTER (A,B,C… over shown
        // sections) is centred ON the spine, just below the top arm, in a white box that erases the
        // spine locally. AD constants (conf/tal.json:14-15,102): line_width 1.0, label_size 2.5,
        // marker strip width_to_height_ratio 0.005 (× the element viewport height = the tree band).
        const double strip_w = 0.005 * marker_treeH;        // AD width_to_height_ratio (marker viewport height)
        const double x_table = x_ts0 + ts_w;                // dash-table right edge = arm LEFT end
        const double x_spine = x_hzmark0 + strip_w;         // marker strip right edge = spine / arm RIGHT end
        const double marker_lw = 1.0 * devw;                // AD hz-section-marker line_width (absolute)
        const double label_fs  = 2.5 * strip_w;             // AD label_size × strip width (≈0.0125·treeH)
        for (const auto& [id, first_name, last_name, prefix, shown] : hz_drawn) {
            if (!shown)
                continue;
            const auto itf = name_y.find(first_name), itl = name_y.find(last_name);
            if (itf == name_y.end() || itl == name_y.end())
                continue;
            double y_top = dev_y(itf->second - 0.5), y_bot = dev_y(itl->second + 0.5); // gap-lines above/below
            if (y_top > y_bot)
                std::swap(y_top, y_bot);
            pdf.line(x_table, y_top, x_spine, y_top, BLACK, marker_lw);   // top arm    (table -> spine)
            pdf.line(x_table, y_bot, x_spine, y_bot, BLACK, marker_lw);   // bottom arm  (table -> spine)
            pdf.line(x_spine, y_top, x_spine, y_bot, BLACK, marker_lw);   // spine       (far/right side)
            if (!prefix.empty()) {
                // r10 — letter sits BELOW the top arm, inside the bracket, matching AD exactly
                // (hz-sections.cc:270-271). Sarah's r8 straddle (glyph centred ON the arm) read too
                // HIGH, overlapping the horizontal arm; she asked to bring the letter + white box down
                // to the AD position. AD (surface y DOWN, text anchored at BASELINE, spine = right):
                //   white box  = top-left {right-0.7w, y_top+0.5h}, size {1.4w, 2.0h}
                //                 → spans y ∈ [y_top+0.5h, y_top+2.5h], entirely below the arm.
                //   letter baseline at y_top+2.0h → glyph box [y_top+1.0h, y_top+2.0h], inside the box.
                // ae's pdf.text y is the glyph-box TOP (not baseline), y increasing downward, so
                // glyph-box-top = y_top+1.0h reproduces AD's [y_top+1.0h, y_top+2.0h]. The white box
                // (top y_top+0.5h, height 2.0h) leaves the arm itself visible above it.
                const auto [w, h] = pdf.text_size(prefix, label_fs);
                pdf.rectangle(x_spine - w * 0.7, y_top + h * 0.5, w * 1.4, h * 2.0, WHITE, 0.0, WHITE);
                pdf.text(x_spine - w * 0.5, y_top + h * 1.0, prefix, label_fs, BLACK, /*center=*/false);
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
        const double lx = width - margin_r - block_w; // right-aligned block
        double ly = vmargin + legend_fs;
        for (const auto& [name, color] : legend_items) {
            pdf.rectangle(lx, ly - swatch * 0.85, swatch, swatch, color, 0.4, color);
            pdf.text(lx + swatch + 5.0, ly, name, legend_fs, BLACK, /*center=*/false);
            ly += line_h;
        }
    }

    // --- geographic inset: continent-coloured world map in the lower-left (acmacs-tal
    //     LegendContinentMap). AD sizes it as a Scaled 0.15 of the page HEIGHT (not width)
    //     at offset {0, 0.93}; ae fits the continent path bbox to box_w, so the rendered
    //     continents ~= box_w (AD's literal 0.15*height leaves internal viewport margins and
    //     renders ~0.134*height of continents). Match AD's rendered map: ~0.134*height wide,
    //     bottom-left, its band ~y[0.91,0.97]*height. Independent of page width so the inset
    //     is the same physical size across subtypes (h1/h3/bvic), as in AD. ---
    if (params.geo_inset) {
        const double box_w = 0.134 * height;
        const double box_h = box_w / continent_map_aspect();
        const double box_x = margin;
        const double box_y = 0.972 * height - box_h;
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
        std::unordered_map<std::string, std::size_t> leaf_order_by_name; // draw-order index, for the report's neighbour fields
        leaf_by_name.reserve(layout.leaves.size());
        leaf_order_by_name.reserve(layout.leaves.size());
        for (std::size_t lo = 0; lo < layout.leaves.size(); ++lo) {
            leaf_by_name.emplace(layout.leaves[lo].name, layout.leaves[lo].node);
            leaf_order_by_name.emplace(layout.leaves[lo].name, lo);
        }
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
        // Descend to the first (or last) SHOWN leaf under `start`, following the child order the
        // tree is drawn in — the node's own extent, which is what AD's report prints.
        const auto edge_leaf = [&tree, &pos](node_index_base_t start, bool want_first) -> std::string {
            node_index_t at{start};
            while (*at <= 0) { // <=0 is an inode (0 is the root)
                node_index_t pick{0};
                bool got{false};
                for (const node_index_t child : tree.inode(at).children) {
                    if (pos.find(*child) == pos.end())
                        continue;
                    pick = child;
                    got = true;
                    if (want_first)
                        break;
                }
                if (!got)
                    return {}; // nothing shown under it (cannot happen for a node that is being labelled)
                at = pick;
            }
            return tree.leaf(at).name;
        };
        // resolve each curated label to its anchor (the MRCA branch point) + text metrics
        struct Anchor { double nx, ny, mid_x, fs, tw, off_x, off_y; int nlines; std::string text; Color color; bool pinned; std::string first, last; bool off_rel_h; std::string node_id; std::size_t ord;
                        // The node's own first/last SHOWN leaf in draw order, recomputed from the tree being
                        // drawn — what the label-position dump reports, as AD does. `first`/`last` above stay the
                        // authored `.tal` values, because the sidecar/drag editor matches its entry by those.
                        // The two differ whenever the node has gained leaves since the `.tal` was written, and
                        // reporting the current pair is what lets a pasted block stay valid against a rebuilt tree.
                        std::string cur_first, cur_last; };
        std::vector<Anchor> anchors;
        // Curated entries carrying `"show": false` — "this transition exists, do NOT label it".
        // They resolve to a real node like any other (so the dump lists nothing stale), but they are
        // kept OUT of `anchors`: they are never placed, never reserved as obstacles, never drawn.
        // The label-position dump reports them with their authored offset, as AD's does.
        std::vector<Anchor> hidden;
        for (std::size_t lno = 0; lno < params.mrca_labels.size(); ++lno) {
            const MrcaLabel& label = params.mrca_labels[lno];
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
            // Measure with the face and the metric the label is actually DRAWN with: monospace
            // (`pdf.text(..., monospace=true)` below) and the pen advance. `text_size` selects
            // sans-serif and returns the ink extent, so it under-measured every label by an amount
            // that depended on its characters — a median 0.36pt on this round's h1 but 5.26pt for a
            // label whose glyphs are all narrow ones. `tw` is the collision box AND the leader's attach
            // edge, so that error both under-counted overlaps and let the leader land inside the
            // text: the worst-measured label was the one that looked best, because its leader was
            // effectively 5pt closer than every other label's.
            double tw = 0.0;
            for (const auto& t : toks) tw = std::max(tw, pdf.text_size_monospace(t, fs).first);
            Anchor anchor{nx, ny, mid_x, fs, tw, label.offset_x, label.offset_y, static_cast<int>(toks.size()), label.text, color, label.pinned, label.first, label.last, label.offset_rel_height, label.node_id, lno,
                          edge_leaf(*node, true), edge_leaf(*node, false)};
            (label.show ? anchors : hidden).push_back(std::move(anchor));
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
            // Occupancy-grid resolution. This is only a FAST PRE-FILTER — box_hits_ink runs right after
            // it and is the exact test — so the cell can be as fine as memory allows, and it needs to
            // be: mark_h marks a whole cell ROW per horizontal branch, so at the old 0.33*fs (~3.1pt)
            // nothing could be placed within ~3pt of any ink whatever `pad` said. That is why the pad
            // sweep was a no-op. At 0.08*fs the tree band costs roughly 750x1250 cells, about 1MB.
            const double cell = std::max(mrca_fs * 0.08, 0.2);

            const int GX = std::clamp(static_cast<int>((gx1 - gx0) / cell), 1, 2600);
            const int GY = std::clamp(static_cast<int>((gy1 - gy0) / cell), 1, 3400);
            std::vector<unsigned char> occ(static_cast<std::size_t>(GX) * static_cast<std::size_t>(GY), 0);
            const auto col = [&](double x) { return std::clamp(static_cast<int>((x - gx0) / (gx1 - gx0) * GX), 0, GX - 1); };
            const auto row = [&](double y) { return std::clamp(static_cast<int>((y - gy0) / (gy1 - gy0) * GY), 0, GY - 1); };
            const auto mark_h = [&](double xa, double xb, double y) { const int r = row(y); const int c0 = col(std::min(xa, xb)), c1 = col(std::max(xa, xb)); for (int c = c0; c <= c1; ++c) occ[static_cast<std::size_t>(r) * GX + c] = 1; };
            const auto mark_v = [&](double x, double ya, double yb) { const int c = col(x); const int r0 = row(std::min(ya, yb)), r1 = row(std::max(ya, yb)); for (int r = r0; r <= r1; ++r) occ[static_cast<std::size_t>(r) * GX + c] = 1; };
            const auto mark_box = [&](double rx, double ry, double rw, double rh) { const int c0 = col(rx), c1 = col(rx + rw), r0 = row(ry), r1 = row(ry + rh); for (int r = r0; r <= r1; ++r) for (int c = c0; c <= c1; ++c) occ[static_cast<std::size_t>(r) * GX + c] = 1; };
            // How much BLACK TREE the leader has to cross to reach its label. Walking the occupancy
            // grid costs O(length/cell) instead of O(branches), which is what makes it affordable to
            // charge every shortlisted candidate for it. A leader that traverses the whole tree reads as
            // a line ruled across the page — the sweep below will happily produce those, because the
            // roomiest whitespace on a tree page is the sparse right-hand side, on the far side of
            // everything. This is what keeps the labels on the near side.
            const auto leader_ink_cells = [&](double x0, double y0, double x1, double y1) -> int {
                const int steps = std::clamp(static_cast<int>(std::hypot(x1 - x0, y1 - y0) / cell) + 1, 1, 2000);
                int hits = 0, pr = -1, pc = -1;
                for (int k = 0; k <= steps; ++k) {
                    const double t = static_cast<double>(k) / steps;
                    const int r = row(y0 + (y1 - y0) * t), c = col(x0 + (x1 - x0) * t);
                    if (r == pr && c == pc) continue;
                    pr = r; pc = c;
                    if (occ[static_cast<std::size_t>(r) * GX + c]) ++hits;
                }
                return hits;
            };
            const auto box_free = [&](double rx, double ry, double rw, double rh) -> bool {
                if (rx < gx0 || rx + rw > gx1 || ry < gy0 || ry + rh > gy1) return false;
                const int c0 = col(rx), c1 = col(rx + rw), r0 = row(ry), r1 = row(ry + rh);
                for (int r = r0; r <= r1; ++r) for (int c = c0; c <= c1; ++c) if (occ[static_cast<std::size_t>(r) * GX + c]) return false;
                return true;
            };
            // tree ink: every node's horizontal edge (parent.x -> node.x) + inode vertical connectors.
            // Recorded EXACTLY as axis-aligned rectangles (segment + the drawn line's half-width) as
            // well as rasterised into `occ`: the grid is the fast candidate filter, but its cell is
            // ~fs/3 wide, so "free in the grid" only means "no ink within about a cell". The exact
            // rects give a crossing test that is true to the rendered stroke — used to VETO any
            // candidate whose text box touches a branch (constraint #1: the aa text must never
            // intersect the black tree lines) and to report the metric below.
            struct InkRect { double x0, y0, x1, y1; };
            std::vector<InkRect> ink;
            ink.reserve(layout.leaves.size() + 2 * layout.inodes.size());
            const double hw = tree_line_width * 0.5; // drawn half-width of a branch (the stroke pdf.line() lays down)
            const auto add_h = [&](double xa, double xb, double y) { ink.push_back({std::min(xa, xb), y - hw, std::max(xa, xb), y + hw}); };
            const auto add_v = [&](double x, double ya, double yb) { ink.push_back({x - hw, std::min(ya, yb), x + hw, std::max(ya, yb)}); };
            for (const auto& ln : layout.leaves) {
                node_index_t self{ln.node};
                if (*self == root) continue;
                const auto p = pos.find(*tree.parent(self));
                const double px = p != pos.end() ? dev_x(p->second.first) : dev_x(ln.x);
                mark_h(px, dev_x(ln.x), dev_y(ln.y));
                add_h(px, dev_x(ln.x), dev_y(ln.y));
            }
            for (const auto& in : layout.inodes) {
                node_index_t self{in.node};
                if (*self != root) {
                    const auto p = pos.find(*tree.parent(self));
                    const double px = p != pos.end() ? dev_x(p->second.first) : dev_x(in.x);
                    mark_h(px, dev_x(in.x), dev_y(in.y));
                    add_h(px, dev_x(in.x), dev_y(in.y));
                }
                double ymin = 1e18, ymax = -1e18;
                for (const node_index_t ch : tree.inode(node_index_t{in.node}).children) {
                    const auto f = pos.find(*ch);
                    if (f != pos.end()) { const double cy = dev_y(f->second.second); ymin = std::min(ymin, cy); ymax = std::max(ymax, cy); }
                }
                if (ymax >= ymin) { mark_v(dev_x(in.x), ymin, ymax); add_v(dev_x(in.x), ymin, ymax); }
            }
            // exact "does this (padded) text box touch any branch?" — the constraint-#1 veto.
            const auto box_hits_ink = [&](double bx0, double by0, double bx1, double by1) -> bool {
                for (const InkRect& r : ink)
                    if (r.x0 < bx1 && bx0 < r.x1 && r.y0 < by1 && by0 < r.y1) return true;
                return false;
            };
            // keep labels clear of the top-left title and the positioned strain-name labels
            if (!params.title.empty()) mark_box(margin + aa_left, gy0, 0.18 * width, mrca_fs * 1.6);
            for (const auto& b : text_label_boxes) mark_box(b[0], b[1], b[2] - b[0], b[3] - b[1]);
            // ...and the lower-left world-map inset. It never needed reserving while the tree started
            // on the page margin — its own basal branches covered that corner, so nothing could be
            // placed there anyway. The label band opens exactly that corner up, so reserve it
            // explicitly (same geometry as the draw call above) or a label can land on the map.
            if (params.geo_inset) {
                const double box_w = 0.134 * height, box_h = box_w / continent_map_aspect();
                mark_box(margin, 0.972 * height - box_h, box_w, box_h);
            }

            // --- candidate search + conflict-minimising local search (finds a near-branch,
            // crossing-free layout when one exists, as AD's hand layout proves it does) ---
            const double PI = 3.14159265358979323846;
            // Where the leader meets the label: the MID-HEIGHT of the RIGHT edge of the TEXT. Sarah's
            // call, 20 Sep 2026, after seeing the alternatives rendered — she prefers one consistent
            // attach to the branch-dependent one.
            //
            // With ONE exception, which is not a hedge: it applies where the rule is geometrically
            // impossible. If the branch is level with or inside the box's own horizontal span, the
            // right edge lies on the far side of the letters and the leader can only get there by
            // being ruled across them. Measured on the round: **118 of 121 labels sit wholly left of
            // their branch**, so the plain rule covers them; the 3 that do not are exactly the 3 that
            // were drawing a leader through their own glyphs, by up to 7.65pt. Those take the near
            // horizontal edge instead. A hand-placed label can always be nudged out of the exception.
            //
            // The box passed in is the COLLISION box, which is taller than the glyphs: a line owns a
            // row of `lineh = 1.18 * fs` with its glyphs (a cap is ~0.72 * fs) centred in it, so the
            // box edge sits `0.23 * fs` clear of the ink top and bottom. That padding does not bite
            // HERE, and the two edges this rule uses are the two it cannot reach: the padding is
            // vertically symmetric, so the box's mid-height IS the ink's, and `x0..x1` is already the
            // text width, so `x1` IS the end of the glyphs. (It would bite on a top or bottom edge,
            // which is why the branch-dependent rule this replaced had to subtract it.) The padding
            // stays as it is — it is load-bearing in the overlap tests and the placement search.
            //
            // The visible gap between the leader and the letters is NOT set here: the leader is drawn
            // short of this point by `leader_gap` at the draw site, so the placement search keeps
            // costing the true attach point while the reader sees a small gap.
            //
            // For the record, since it is a deliberate divergence: this is NOT what AD draws for a
            // report tree. AD picks one of three points by where the branch sits
            // (`acmacs-tal/cc/draw-aa-transitions.cc:823-836`), and measured on AD's own 2026-0825-tc2
            // renders its commonest attach is the box's TOP-CENTRE (89 of 119 single-line labels;
            // side-mid 17, bottom-centre 12). ae drew that for two commits and it was rejected on
            // looks. `:219` — AD's `auto_placed` path, back-ported from ae — is the unconditional
            // mid-right this now matches, so the two engines agree there and nowhere else.
            const auto attach_pt = [](double ax, double ay, double fs, double x0, double y0, double x1, double y1, double& cx, double& cy) {
                if (ax > x1) {                          // the ordinary case: box wholly LEFT of the branch
                    cx = x1;                            // the end of the glyphs
                    cy = (y0 + y1) * 0.5;               // ...at their mid-height
                    return;
                }
                // The branch is level with, or inside, the box's horizontal span, so the right edge
                // cannot be reached without ruling the leader across the label's own letters. Meet the
                // near HORIZONTAL edge of the ink at its centre instead — AD's own answer to the same
                // situation (`draw-aa-transitions.cc:823-836`). The row padding DOES bite on these two
                // edges, unlike the mid-right above where it cancels, so subtract it here.
                const double ink = fs * 0.23;
                cx = (x0 + x1) * 0.5;
                cy = (y1 < ay) ? y1 - ink                // box wholly ABOVE the branch -> its bottom edge
                               : y0 + ink;               // otherwise -> its top edge
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
            // `tier` records which envelope the candidate came from — 1 = the target shape
            // (short, 22°..72° diagonal), 2 = the relaxed envelope, 3 = the whole-band sweep, 0 = a
            // pinned label's authored spot. Carried only so the metrics line can say how much of a
            // layout had to leave the ideal envelope; nothing in the search reads it.
            struct Cand { double x0, y0, x1, y1, cx, cy, base; int tier; };
            std::vector<std::vector<Cand>> cands(anchors.size());
            const double gapL = mrca_fs * 0.45; // min gap between the label's right edge and the branch
            // Clearance kept clear of tree ink around each label. Held at AD's 0.3: widening it to
            // 0.45 measurably squeezed the top-of-tree labels out of the thin left-hand gaps they
            // had been using and exiled them to the right of their branches. Text/branch separation
            // is enforced exactly by box_hits_ink, so pad only has to look right, not to be safe.
            const double pad = mrca_fs * 0.3;
            // --- leader-line shape targets (constraints #3 and #4) -------------------------------
            // #4 "the lines should not be too long": `len_soft` is the length a leader may reach for
            // free; beyond it the cost grows QUADRATICALLY, so the search will accept a slightly
            // worse angle rather than a leader twice as long, and `len_max` is a hard ceiling.
            // The old code had neither: its only length term was linear (len*1.8) against a 0.35*height
            // reach, so a far-flung candidate could always buy its way out of a local conflict.
            const double len_soft = 0.018 * height;
            const double len_max  = 0.110 * height;
            // #3 "leader lines should be NE-SW, and not exactly horizontal": measure the leader's angle
            // from the horizontal and aim it at 45°. `ang_min` is a HARD floor — a candidate shallower
            // than this is not generated at all, which is what actually removes the near-horizontal
            // leaders (the old code only added a soft penalty when |dy| < 1.6*fs, which a long leader
            // satisfied while still running at 5°). `ang_max` keeps them off the vertical, which reads
            // as a stray tick rather than a leader.
            // The angle a leader should aim for DEPENDS ON ITS LENGTH — one target for every length is
            // what pinned the old placer at a flat ~25 degrees everywhere. The hand layout has two
            // distinct populations: short leaders run nearly level ("beside the node and a little
            // down", the stated default — median 7 degrees in the 15-30pt band) and only once a label
            // has to travel does it go diagonal (median 30 degrees beyond 30pt).
            const double ang_short  = 10.0 * PI / 180.0;  // aim for short leaders
            const double ang_long   = 30.0 * PI / 180.0;  // ...and for long ones
            const double ang_min    = 4.0 * PI / 180.0;
            const double ang_max    = 72.0 * PI / 180.0;
            const double ang_l1     = 0.018 * height;       // at/below this, ang_short
            const double ang_l2     = 0.045 * height;       // at/above this, ang_long
            const auto ang_target_for = [&](double L) {
                const double t = std::clamp((L - ang_l1) / std::max(ang_l2 - ang_l1, 1e-9), 0.0, 1.0);
                return ang_short + (ang_long - ang_short) * t;
            };
            // A visible short leader is PREFERRED to none (no leader is only for tucking mid-tree), so a
            // placement close enough that the renderer draws no leader at all pays a small penalty.
            const double K_noleader = 120.0;
            // Cost weights, chosen by sweeping each one over the three report trees and reading the
            // metrics line below (h1/h3/bvic `*.after-2021`). They are only a preference ordering: every
            // term here is worth far less than one overlap, which the search scores at 1e6.
            const double K_len_max2 = 0.30 * height; // tier-2 reach
            const double K_t2       = 700.0;         // flat surcharge for leaving the target envelope
            const double K_nw       = 250.0;        // flat surcharge for the NW-SE mirror (label ABOVE the branch).
                                                     // Stiff on purpose: with the band there is nearly always a
                                                     // below-the-branch spot, and this is what takes it. Measured on
                                                     // H1, wrong-direction leaders 8 (at 400) -> 0.
            const double K_wlen     = 2.5;           // per-point leader length
            const double K_wquad    = 6.0;           // per (length - len_soft)/fs, squared
            const double K_wang     = 10.0;          // per degree away from the target
            const double K_t3d      = 4.0;           // per point of distance for a band-sweep spot
            const double K_wink     = 22.0;          // per tree-ink cell the leader crosses. NOTE (measured):
                                                     // the hand layout's leaders cross a median of 9-11 cells,
                                                     // the placer's 3-4 — a leader that stays beside its branch
                                                     // runs along the branch, one that escapes into the band
                                                     // crosses nothing. So this term charges for exactly the
                                                     // short placements the hand layout prefers.
            // PINNED labels (user dragged them in the WYSIWYG editor) are NOT auto-placed: each sits at
            // its authored offset (box top-left = node point + offset*page — the editor's exact inverse)
            // and is RESERVED in the occupancy grid up-front, so the auto search for the remaining labels
            // routes around it (and the pairwise conflict terms keep their leaders/boxes off it too).
            for (std::size_t i = 0; i < anchors.size(); ++i) {
                if (!anchors[i].pinned) continue;
                const double lineh = anchors[i].fs * 1.18, th = anchors[i].nlines * lineh, tw = anchors[i].tw;
                const double x0 = anchors[i].nx + anchors[i].off_x * (anchors[i].off_rel_h ? height : width), y0 = anchors[i].ny + anchors[i].off_y * height;
                mark_box(x0 - pad, y0 - pad, tw + 2.0 * pad, th + 2.0 * pad);
            }
            for (std::size_t i = 0; i < anchors.size(); ++i) {
                const double fs = anchors[i].fs, lineh = fs * 1.18, th = anchors[i].nlines * lineh, tw = anchors[i].tw;
                if (anchors[i].pinned) {
                    // one fixed candidate at the authored offset, taking the same AD attach rule as
                    // the auto-placed ones (attach_pt) — a hand-dragged box gets the leader AD would
                    // have given it, which is the whole point of matching the reference renders.
                    const double x0 = anchors[i].nx + anchors[i].off_x * (anchors[i].off_rel_h ? height : width), y0 = anchors[i].ny + anchors[i].off_y * height;
                    double cx, cy; attach_pt(anchors[i].mid_x, anchors[i].ny, fs, x0, y0, x0 + tw, y0 + th, cx, cy);
                    cands[i].push_back({x0, y0, x0 + tw, y0 + th, cx, cy, 0.0, 0});
                    continue;
                }
                const double ax = anchors[i].mid_x, ay = anchors[i].ny;
                // Sample the LEADER itself (polar around the anchor), not the box centre: the leader's
                // length and angle ARE the constraints, so generating them directly means every
                // candidate satisfies #3/#4 by construction instead of being talked into it by a
                // penalty. (angle, length) here only POSITIONS the box — it is sampled as if the
                // leader ended at the box's right edge, mid-height. The point actually drawn is
                // whichever of AD's three attach points `attach_pt` returns for the finished box, and
                // that is what `emit_at` below costs; this is a sampler, not the model.
                //   down == true  -> attach BELOW the anchor (device +y is DOWN) -> box sits lower-left
                //                    of the branch, so the leader runs up-and-right: a NE-SW line (#3).
                //   down == false -> the NW-SE mirror; generated too (a tight tree may have no room
                //                    below) but carried at a flat penalty so it is only ever a fallback.
                const auto emit_at = [&](double cx, double cy, double y0, bool down, double extra) {
                    if (cx > ax - gapL) return;                                                   // box must sit LEFT of the branch (#3,#5)
                    const double x0 = cx - tw;
                    if (!box_free(x0 - pad, y0 - pad, tw + 2.0 * pad, th + 2.0 * pad)) return;     // clear of tree ink, with margin (#1)
                    if (box_hits_ink(x0 - pad, y0 - pad, x0 + tw + pad, y0 + th + pad)) return;    // exact re-check against the drawn stroke (#1)
                    // (cx, cy) above only positioned the box. The leader actually drawn runs to the
                    // attach point on the FINISHED box, so cost that one — otherwise the search
                    // optimises a length and angle the renderer does not draw.
                    double tx, ty; attach_pt(ax, ay, fs, x0, y0, x0 + tw, y0 + th, tx, ty);
                    const double La = std::hypot(ax - tx, ay - ty);
                    const double tha = std::atan2(std::abs(ay - ty), std::max(std::abs(ax - tx), 1e-9));
                    double base = La * K_wlen;                                                       // prefer SHORT leaders (#4)
                    if (La > len_soft) { const double o = (La - len_soft) / fs; base += o * o * K_wquad; } // ...and grow the cost QUADRATICALLY past the comfortable length (#4)
                    base += std::abs(tha - ang_target_for(La)) * (180.0 / PI) * K_wang;               // level-ish when short, diagonal when long
                    if (La < fs * 0.6) base += K_noleader;                                            // a visible short leader beats none
                    if (!down) base += K_nw;                                                         // NW-SE mirror: allowed, but only as a fallback (#3)
                    base += extra;
                    cands[i].push_back({x0, y0, x0 + tw, y0 + th, tx, ty, base, extra > 0.0 ? 2 : 1});
                };
                // For each (angle, length), offer the box CENTRED on that point, sitting just BELOW it,
                // and sitting just ABOVE it. The box used to be centred on the leader endpoint always,
                // and that single choice cannot express the commonest hand placement: "beside the node
                // and a little down". At a shallow angle a centred box straddles the branch's own
                // horizontal edge and is rejected for hitting ink, so the placer had to leave at a
                // steeper angle or a longer leader to find clear space. Hanging the box below (or above)
                // the point puts it clear of that line while staying beside the node.
                const auto emit = [&](double L, double theta, bool down, double extra) {
                    const double cx = ax - L * std::cos(theta);
                    const double cy = ay + (down ? 1.0 : -1.0) * L * std::sin(theta);
                    emit_at(cx, cy, cy - th * 0.5, down, extra);   // centred on the point
                    emit_at(cx, cy, cy,            down, extra);   // hanging below it
                    emit_at(cx, cy, cy - th,       down, extra);   // sitting above it
                };
                // Tier 1 — inside the target envelope: 22°..72°, up to len_max. Every candidate here
                // is a well-formed diagonal leader of bounded length.
                const int NTH = 16, NL = 26;
                for (int s = 0; s < 2; ++s) {
                    for (int t = 0; t <= NTH; ++t) {
                        const double theta = ang_min + (ang_max - ang_min) * t / NTH;
                        const double lmin = std::max(gapL / std::cos(theta), fs * 0.9);
                        if (lmin > len_max) continue;
                        for (int k = 0; k <= NL; ++k) emit(lmin + (len_max - lmin) * k / NL, theta, s == 0, 0.0);
                    }
                }
                // Tier 2 — the relaxed envelope (8°..86°, reach out to 0.30·height), ALWAYS generated.
                // The shape rules (#3, #4) are what the user wants "ideally"; not overlapping (#1, #2)
                // is what they want absolutely. Withholding the far/shallow placements to enforce the
                // ideal costs the search the room it needs to untangle a congested cluster and trades a
                // hard constraint for a soft one — measurably so: gating tier 2 on "tier 1 came up
                // short" took h3's residual conflicts from 10 to 14. So offer them always, at a flat
                // surcharge that no in-envelope candidate can ever lose to, and let the conflict terms
                // (weighted ~1e6) spend it only where they must.
                const double len_max2 = K_len_max2;
                {
                    const double ang_min2 = 8.0 * PI / 180.0, ang_max2 = 86.0 * PI / 180.0;
                    for (int s = 0; s < 2; ++s)
                        for (int t = 0; t <= NTH; ++t) {
                            const double theta = ang_min2 + (ang_max2 - ang_min2) * t / NTH;
                            const double lmin = std::max(gapL / std::cos(theta), fs * 0.9);
                            if (lmin > len_max2) continue;
                            for (int k = 0; k <= NL; ++k) emit(lmin + (len_max2 - lmin) * k / NL, theta, s == 0, K_t2);
                        }
                }
                // Tier 3 — whole-band sweep, for labels the leader-shaped tiers leave STARVED.
                // A label on a BASAL branch sits near the left edge of the tree band, so almost all of
                // the left half-plane those tiers search is off-page or under the root's own connectors.
                // Measured on the H3 report tree, the worst-placed basal label reached the search with
                // FIVE candidates and the next with 18, against 100+ for a mid-tree label — and those
                // starved labels accounted for four of the nine residual conflicts, because with five
                // placements to choose from there is nothing to move them to. So the trigger is
                // starvation, not emptiness. The sweep also returns a SPREAD of free boxes rather than
                // the single nearest, because two labels can hang off the SAME MRCA node (the B/Vic tree
                // has such a pair): the old one-box fallback handed both the identical box, and with one
                // candidate each no amount of searching could separate them.
                if (cands[i].size() < 24) {
                    const double step = std::max(fs * 0.6, 2.0);
                    struct Spot { double x0, y0, d; };
                    std::vector<Spot> spots;
                    for (double y0 = gy0; y0 + th <= gy1; y0 += step) {
                        for (double x0 = gx0; x0 + tw <= gx1; x0 += step) {
                            if (!box_free(x0 - pad, y0 - pad, tw + 2.0 * pad, th + 2.0 * pad)) continue;
                            if (box_hits_ink(x0 - pad, y0 - pad, x0 + tw + pad, y0 + th + pad)) continue;
                            spots.push_back({x0, y0, std::hypot(ax - (x0 + tw * 0.5), ay - (y0 + th * 0.5))});
                        }
                    }
                    std::sort(spots.begin(), spots.end(), [](const Spot& a, const Spot& b) { return a.d < b.d; });
                    std::vector<Spot> pick;                                  // nearest first, thinned so they are genuinely different places
                    for (const Spot& sp : spots) {
                        bool dup = false;
                        // Spread these WIDE. Two labels hanging off the SAME MRCA node get near-identical
                        // spot lists, so if the list only covers one small pocket they cannot be separated
                        // however hard the search tries.
                        for (const Spot& q : pick) if (std::abs(sp.x0 - q.x0) < tw * 0.8 && std::abs(sp.y0 - q.y0) < th * 2.0) { dup = true; break; }
                        if (!dup) pick.push_back(sp);
                        if (pick.size() >= 40) break;
                    }
                    for (const Spot& sp : pick) {
                        double cx, cy; attach_pt(ax, ay, fs, sp.x0, sp.y0, sp.x0 + tw, sp.y0 + th, cx, cy);
                        // A sweep spot is chosen for being FREE, not for the leader it implies, so charge
                        // it the same shape cost the leader-shaped tiers pay. Without this the sweep
                        // spots come out at whatever angle the whitespace happens to sit at — measured:
                        // enabling the sweep alone took h3's leaders below 22° from 1 to 8. Ranking the
                        // spots by shape as well as distance keeps the rescue and the house style.
                        const double theta = std::atan2(std::abs(ay - cy), std::max(std::abs(ax - cx), 1e-9));
                        // Charge distance the same way the leader tiers do — linear plus a quadratic
                        // past the comfortable length. A flat linear term is far too weak against the
                        // 1e4 tier surcharge: on the B/Vic tree a rescued label flew 204pt
                        // clear across the page (a 20%-of-page leader crossing two others) because the
                        // extra distance cost only a few hundred.
                        double base = 1.0e4 + sp.d * K_t3d + std::abs(theta - ang_target_for(sp.d)) * (180.0 / PI) * K_wang;
                        if (sp.d > len_soft) { const double o = (sp.d - len_soft) / fs; base += o * o * K_wquad; }
                        if (cy < ay) base += K_nw;                      // above the branch: the NW-SE mirror
                        // ...and keep it on the LEFT, where every other label lives. Free space is easiest
                        // to find on the sparse right of a tree, so without this the sweep exiles the
                        // starved labels into the right margin on leaders ruled across the whole page.
                        if (sp.x0 + tw > ax) base += 5000.0 + (sp.x0 + tw - ax) * 10.0;
                        // ramp, not a step: a sweep spot at 0deg (dead horizontal) must cost much more
                        // than one at 20deg, while still costing far less than a conflict, so the rescue
                        // takes the most diagonal free spot it can and a flat leader only as a last resort.
                        if (theta < ang_min) base += 600.0 + (ang_min - theta) * (180.0 / PI) * 200.0;
                        cands[i].push_back({sp.x0, sp.y0, sp.x0 + tw, sp.y0 + th, cx, cy, base, 3});
                    }
                }
                // Last resort — not one position but a COLUMN of them down the left edge, ignoring ink.
                // On a full-size tree (~10k leaves at a fraction of a point per row) the canopy
                // is solid black at grid resolution, so nothing above finds anywhere free and every label
                // arrives here. The historical single position put all of them at their own anchor's
                // height against gx0 — which on the full H1 tree meant 51 labels on top of each other
                // (measured: 123 text/text overlaps, every leader dead horizontal). The ink is
                // unavoidable on such a tree; labels landing on each other is not. Offering a spread lets
                // the ordinary conflict search stack them in branch order on sloped leaders.
                if (cands[i].empty()) {
                    for (int xs = 0; xs < 3; ++xs) {
                        const double x0 = gx0 + xs * tw * 0.35;
                        for (int k = -12; k <= 12; ++k) {
                            const double y0 = std::clamp(ay - th * 0.5 + k * th * 1.3, gy0, gy1 - th);
                            double cx, cy; attach_pt(ax, ay, fs, x0, y0, x0 + tw, y0 + th, cx, cy);
                            if (cx > ax - gapL * 0.5) continue;               // still left of the branch
                            const double theta = std::atan2(std::abs(ay - cy), std::max(ax - cx, 1e-9));
                            const double Lr = std::hypot(ax - cx, ay - cy);
                            double base = 1.0e5 + Lr * K_wlen + std::abs(theta - ang_target_for(Lr)) * (180.0 / PI) * K_wang;
                            if (cy < ay) base += K_nw;
                            cands[i].push_back({x0, y0, x0 + tw, y0 + th, cx, cy, base, 3});
                        }
                    }
                    if (cands[i].empty()) { // not even that fits: one position, as before
                        const double x0 = gx0, y0 = std::clamp(ay - th * 0.5, gy0, gy1 - th);
                        double cx, cy; attach_pt(ax, ay, fs, x0, y0, x0 + tw, y0 + th, cx, cy);
                        cands[i].push_back({x0, y0, x0 + tw, y0 + th, cx, cy, 1.0e5, 3});
                    }
                }
                std::sort(cands[i].begin(), cands[i].end(), [](const Cand& a, const Cand& b) { return a.base < b.base; });
                // Thin the sweep down to a shortlist the search can afford — but thin it so the
                // shortlist still SPANS the envelope. Taking the N cheapest (what the old code did, and
                // what a plain nearest-neighbour thinning still does) is a trap: `base` is dominated by
                // leader length, so the N cheapest are all the short ones clustered round the anchor,
                // and every far placement — the one a congested label actually needs — is cut before the
                // search ever sees it. That is why widening the reach changed nothing: the extra reach
                // was pruned away again here. So bucket by (side, angle, log-length) and keep the best
                // candidate in each bucket: the shortlist then covers near AND far, shallow AND steep,
                // above AND below, and `base` still ranks within each bucket.
                // Two passes, because the search needs two different things and neither alone works:
                //   near field — many finely-spaced placements around the anchor, which is how a label
                //     shuffles by a few points to clear a neighbour it *nearly* fits past;
                //   far field  — a few placements at every angle and every distance out to the full
                //     reach, which is how a label in a hopelessly congested pocket gets out of it.
                // Thinning by nearest-neighbour alone keeps only the near field (everything far is
                // costlier, so the cap eats it — measured: widening the reach then changed nothing).
                // Bucketing alone keeps only a sparse skeleton of the near field (measured: h3's
                // conflicts went 11 -> 15). Take the union.
                {
                    std::vector<Cand> keep;
                    keep.reserve(300);
                    const double sep = fs * 0.5;
                    // NOTE: this keys on the ATTACH POINT, so the three box variants emitted per
                    // (angle, length) — centred, hanging below, sitting above — can collapse to one
                    // survivor when the clamp puts their attach points together. Keying on the BOX
                    // instead was measured and is no better (11.7pt vs 11.4pt baseline, 3 seeds).
                    for (const Cand& c : cands[i]) {            // pass 1: near field, finely spaced
                        bool dup = false;
                        for (const Cand& k : keep) if (std::hypot(c.cx - k.cx, c.cy - k.cy) < sep) { dup = true; break; }
                        if (!dup) keep.push_back(c);
                        if (keep.size() >= 110) break;
                    }
                    const int ABINS = 10, LBINS = 8;            // pass 2: one representative per (side, angle, log-distance) cell
                    const double lo = std::log(std::max(fs * 0.9, 1.0)), hi = std::log(std::max(len_max2, fs * 2.0));
                    const auto cell = [&](const Cand& d) {
                        const double ddx = anchors[i].mid_x - d.cx, ddy = anchors[i].ny - d.cy;
                        const double th_ = std::atan2(std::abs(ddy), std::max(std::abs(ddx), 1e-9));
                        const int ab = std::clamp(static_cast<int>(th_ / (PI * 0.5) * ABINS), 0, ABINS - 1);
                        const int lb = std::clamp(static_cast<int>((std::log(std::max(std::hypot(ddx, ddy), 1.0)) - lo) / (hi - lo) * LBINS), 0, LBINS - 1);
                        return static_cast<std::size_t>(((d.cy > anchors[i].ny ? 0 : 1) * ABINS + ab) * LBINS + lb);
                    };
                    std::vector<char> have(static_cast<std::size_t>(2 * ABINS * LBINS), 0);
                    for (const Cand& k : keep) have[cell(k)] = 1;
                    for (const Cand& c : cands[i]) { const std::size_t k = cell(c); if (!have[k]) { have[k] = 1; keep.push_back(c); } }
                    for (Cand& c : keep)
                        c.base += std::min(leader_ink_cells(anchors[i].mid_x, anchors[i].ny, c.cx, c.cy), 80) * K_wink;
                    std::sort(keep.begin(), keep.end(), [](const Cand& a, const Cand& b) { return a.base < b.base; });
                    cands[i].swap(keep);
                }
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
            const long WC = 1000000L, WO = static_cast<long>(1100.0), WA = 130L; // conflicts >> vertical order > adjacent-angle ~ leader length
            std::vector<int> choice(n, 0), best(n, 0);
            const auto icost = [&](std::size_t i, int ci) -> long {
                long c = static_cast<long>(cands[i][ci].base);
                for (std::size_t j = 0; j < n; ++j) if (j != i) c += static_cast<long>(pconf(i, ci, j, choice[j])) * WC + static_cast<long>(inv(i, ci, j, choice[j])) * WO;
                const int r = rankA[i]; // angle similarity with the labels immediately above/below in branch order
                if (r > 0) { const std::size_t nb = ordA[r - 1]; c += static_cast<long>(WA * std::abs(ang(i, ci) - ang(nb, choice[nb]))); }
                if (r + 1 < static_cast<int>(n)) { const std::size_t nb = ordA[r + 1]; c += static_cast<long>(WA * std::abs(ang(i, ci) - ang(nb, choice[nb]))); }
                return c;
            };
            // The restart RNG is fixed so a render is reproducible. AEL_RNG re-seeds it, which is the
            // only way to tell a real improvement from one restart schedule getting lucky: a weight
            // change moves the landscape, and which local optimum the restarts happen to land in can
            // swing the fit by more than the change itself. TEMPORARY knob.
            std::uint32_t rng = std::getenv("AEL_RNG") ? static_cast<std::uint32_t>(std::strtoul(std::getenv("AEL_RNG"), nullptr, 10)) : 2463534242u;
            const auto rnd = [&](int mm) { rng ^= rng << 13; rng ^= rng >> 17; rng ^= rng << 5; return static_cast<int>(rng % static_cast<std::uint32_t>(mm)); };
            const auto conf_i = [&](std::size_t i, int ci) { int c = 0; for (std::size_t j = 0; j < n; ++j) if (j != i) c += pconf(i, ci, j, choice[j]); return c; };
            const auto conf_total = [&]() { int c = 0; for (std::size_t i = 0; i < n; ++i) for (std::size_t j = i + 1; j < n; ++j) c += pconf(i, choice[i], j, choice[j]); return c; };
            const auto inv_i = [&](std::size_t i, int ci) { int c = 0; for (std::size_t j = 0; j < n; ++j) if (j != i) c += inv(i, ci, j, choice[j]); return c; };
            const auto inv_total = [&]() { int c = 0; for (std::size_t i = 0; i < n; ++i) for (std::size_t j = i + 1; j < n; ++j) c += inv(i, choice[i], j, choice[j]); return c; };
            const auto soft_i = [&](std::size_t i, int ci) { double s = 0.0; for (std::size_t j = 0; j < n; ++j) if (j != i) s += psoft(i, ci, j, choice[j]); return s; };
            const auto soft_total = [&]() { double s = 0.0; for (std::size_t i = 0; i < n; ++i) for (std::size_t j = i + 1; j < n; ++j) s += psoft(i, choice[i], j, choice[j]); return s; };
            const auto base_total = [&]() { double b = 0.0; for (std::size_t i = 0; i < n; ++i) b += cands[i][choice[i]].base; return b; };
            // ---- DIAGNOSTIC (AEL_REF) — is a reference layout reachable, and does the objective
            // prefer it?  AEL_REF names a TSV of one (first \t last \t text \t box_x0 \t box_y0),
            // normally the hand-placed layout dumped from the geometry sidecar. For each label we take
            // the CANDIDATE NEAREST the reference box and score that whole assignment with the same
            // objective the search minimises. Two numbers then settle the open question about leader
            // length: if the reference assignment scores BETTER than the search's answer, the search is
            // failing to reach a solution it should (fix the search or the seed); if it scores WORSE,
            // the objective genuinely prefers the long-leader layout and the objective is what must
            // change. Read-only unless AEL_SEEDREF is also set (1 = seed Phase A from it, 2 = seed and
            // skip the random restarts, i.e. pure local descent from the reference).
            std::vector<int> ref_choice; std::vector<double> ref_snap;
            const int seedref = std::getenv("AEL_SEEDREF") ? std::atoi(std::getenv("AEL_SEEDREF")) : 0;
            if (const char* refpath = std::getenv("AEL_REF")) {
                std::unordered_map<std::string, std::pair<double, double>> ref;
                std::ifstream in{refpath};
                std::string line;
                while (std::getline(in, line)) {
                    std::size_t t[4]{}; std::size_t p = 0; bool ok = true;
                    for (int f = 0; f < 4; ++f) { const std::size_t q = line.find('\t', p); if (q == std::string::npos) { ok = false; break; } t[f] = q; p = q + 1; }
                    if (!ok) continue;
                    ref[line.substr(0, t[2])] = {std::stod(line.substr(t[2] + 1, t[3] - t[2] - 1)), std::stod(line.substr(t[3] + 1))};
                }
                // AEL_REFEXACT appends the reference box ITSELF as a candidate, costed by the same
                // formula emit_at uses, instead of snapping to the nearest generated one. Snapping is
                // a confound: the lattice is ~2.5pt coarse near the anchor, and a 2.5pt shift is
                // enough to turn boxes that merely touch in the reference into a counted overlap.
                const bool exact = std::getenv("AEL_REFEXACT") != nullptr;
                ref_choice.assign(n, 0); ref_snap.assign(n, 0.0);
                int rejected_free = 0, rejected_ink = 0, rejected_side = 0;
                for (std::size_t i = 0; i < n; ++i) {
                    const auto it = ref.find(anchors[i].first + "\t" + anchors[i].last + "\t" + anchors[i].text);
                    if (it == ref.end()) { fmt::print(stderr, ">>> aa-label REF: no reference row for label {} — diagnostic skipped\n", i); ref_choice.clear(); break; }
                    const double rx = it->second.first, ry = it->second.second;
                    if (exact) {
                        const double fs = anchors[i].fs, th = anchors[i].nlines * fs * 1.18, tw = anchors[i].tw;
                        const double ax = anchors[i].mid_x, ay = anchors[i].ny;
                        // which of the generator's filters, if any, would have vetoed this box
                        double tx, ty; attach_pt(ax, ay, fs, rx, ry, rx + tw, ry + th, tx, ty);
                        if (tx > ax - gapL) ++rejected_side;
                        if (!box_free(rx - pad, ry - pad, tw + 2.0 * pad, th + 2.0 * pad)) ++rejected_free;
                        if (box_hits_ink(rx - pad, ry - pad, rx + tw + pad, ry + th + pad)) ++rejected_ink;
                        const double La = std::hypot(ax - tx, ay - ty);
                        const double tha = std::atan2(std::abs(ay - ty), std::max(std::abs(ax - tx), 1e-9));
                        double base = La * K_wlen;
                        if (La > len_soft) { const double o = (La - len_soft) / fs; base += o * o * K_wquad; }
                        base += std::abs(tha - ang_target_for(La)) * (180.0 / PI) * K_wang;
                        if (La < fs * 0.6) base += K_noleader;
                        if (ty < ay) base += K_nw;
                        base += std::min(leader_ink_cells(ax, ay, tx, ty), 80) * K_wink; // the thinning pass's surcharge
                        cands[i].push_back({rx, ry, rx + tw, ry + th, tx, ty, base, 1});
                        ref_choice[i] = static_cast<int>(cands[i].size()) - 1; ref_snap[i] = 0.0;
                        continue;
                    }
                    int bc = 0; double bd = std::numeric_limits<double>::max();
                    for (int ci = 0; ci < static_cast<int>(cands[i].size()); ++ci) {
                        const double d = std::hypot(cands[i][ci].x0 - rx, cands[i][ci].y0 - ry);
                        if (d < bd) { bd = d; bc = ci; }
                    }
                    ref_choice[i] = bc; ref_snap[i] = bd;
                }
                if (exact && !ref_choice.empty())
                    fmt::print(stderr, ">>> aa-label REF: reference boxes the generator would have VETOED — right-of-branch={} grid-not-free={} hits-ink={} (of {})\n",
                               rejected_side, rejected_free, rejected_ink, n);
            }
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
            // SEED — sweep the labels down the tree in branch-y order and give each one the cheapest
            // candidate that clashes with nothing already placed and keeps the column running downward.
            // Both the all-zeros start (every label on its own shortest leader, so the crowded ones all
            // pile into the same pocket) and the random restarts below hand Phase A a layout with dozens
            // of conflicts to unpick, and descent then has to fix them one label at a time while every
            // neighbour is also wrong. A left column of labels in the same order as their branches is
            // the arrangement whose leaders *cannot* cross, so building that first starts the search
            // inside — or next to — the feasible region instead of far outside it.
            {
                std::vector<int> seed(n, 0);
                for (int r = 0; r < static_cast<int>(n); ++r) {
                    const std::size_t i = ordA[r];
                    int bc = 0; double bv = std::numeric_limits<double>::max();
                    const double prev_cy = r > 0 ? (cands[ordA[r - 1]][seed[ordA[r - 1]]].y0 + cands[ordA[r - 1]][seed[ordA[r - 1]]].y1) * 0.5
                                                 : -std::numeric_limits<double>::max();
                    for (int ci = 0; ci < static_cast<int>(cands[i].size()); ++ci) {
                        double v = cands[i][ci].base;
                        for (int q = 0; q < r; ++q) { const std::size_t j = ordA[q]; v += static_cast<double>(pconf(i, ci, j, seed[j])) * 1.0e6; }
                        if ((cands[i][ci].y0 + cands[i][ci].y1) * 0.5 < prev_cy) v += 3000.0; // keep the column descending
                        if (v < bv) { bv = v; bc = ci; }
                    }
                    seed[i] = bc;
                }
                choice = seed;
                if (seedref && !ref_choice.empty()) choice = ref_choice; // AEL_SEEDREF: start from the reference instead
            }
            // PHASE A — find a CONFLICT-FREE layout, and among those prefer one in branch-y ORDER
            // (ordered labels over ordered branches cannot cross, so order both fixes #5 and removes
            // the otherwise-stubborn crossings). Score = conflicts >> inversions >> leader length;
            // random restarts escape local minima. This reliably reaches zero on dense trees.
            best = choice;
            double best_scoreA = scoreA();
            int stale = 0;
            for (int restart = 0; restart <= (seedref == 2 ? 0 : 400); ++restart) {
                // Restart 0 descends from the ordered seed above; the rest are random, which is what
                // escapes a local minimum the seed cannot.
                if (restart > 0) for (std::size_t i = 0; i < n; ++i) choice[i] = rnd(std::min<int>(40, static_cast<int>(cands[i].size())));
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
            if (!ref_choice.empty()) { // AEL_REF diagnostic: score the reference assignment against the search's
                const std::vector<int> saved = choice;
                const auto lead = [&](std::size_t i, int ci) { return std::hypot(anchors[i].mid_x - cands[i][ci].cx, anchors[i].ny - cands[i][ci].cy); };
                for (std::size_t i = 0; i < n; ++i) {
                    choice = ref_choice; const int cfr = conf_i(i, ref_choice[i]); const double sfr = soft_i(i, ref_choice[i]);
                    choice = saved;      const int cfs = conf_i(i, saved[i]);
                    fmt::print(stderr, ">>> aa-label REF[{:>3}] snap={:5.1f} | ref lead={:5.1f} base={:7.0f} conf={} soft={:6.1f} tier{} | auto lead={:5.1f} base={:7.0f} conf={} tier{} | moved={:5.1f}\n",
                               i, ref_snap[i], lead(i, ref_choice[i]), cands[i][ref_choice[i]].base, cfr, sfr, cands[i][ref_choice[i]].tier,
                               lead(i, saved[i]), cands[i][saved[i]].base, cfs, cands[i][saved[i]].tier,
                               std::hypot(cands[i][ref_choice[i]].x0 - cands[i][saved[i]].x0, cands[i][ref_choice[i]].y0 - cands[i][saved[i]].y0));
                }
                const auto med = [](std::vector<double> v) { std::sort(v.begin(), v.end()); return v.empty() ? 0.0 : v[v.size() / 2]; };
                std::vector<double> lr, ls, sn;
                for (std::size_t i = 0; i < n; ++i) { lr.push_back(lead(i, ref_choice[i])); ls.push_back(lead(i, saved[i])); sn.push_back(ref_snap[i]); }
                // Break the conflict count down by kind, and re-count it with the search's extra
                // separation margins (m between boxes, mt around text) REMOVED — that is exactly the
                // test the metrics line applies, so a layout that is clean there and dirty here is
                // being rejected by the margins alone, not by a real overlap.
                const auto totals = [&](const char* tag, double leadmed) {
                    int bb = 0, ll = 0, lt = 0, bb0 = 0, ll0 = 0, lt0 = 0;
                    for (std::size_t i = 0; i < n; ++i) for (std::size_t j = i + 1; j < n; ++j) {
                        const Cand& a = cands[i][choice[i]]; const Cand& b = cands[j][choice[j]];
                        if (a.x0 - m < b.x1 && b.x0 - m < a.x1 && a.y0 - m < b.y1 && b.y0 - m < a.y1) ++bb;
                        if (a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1) ++bb0;
                        if (segs_cross(anchors[i].mid_x, anchors[i].ny, a.cx, a.cy, anchors[j].mid_x, anchors[j].ny, b.cx, b.cy)) { ++ll; ++ll0; }
                        if (seg_box(anchors[i].mid_x, anchors[i].ny, a.cx, a.cy, b.x0 - mt, b.y0 - mt, b.x1 + mt, b.y1 + mt)) ++lt;
                        if (seg_box(anchors[j].mid_x, anchors[j].ny, b.cx, b.cy, a.x0 - mt, a.y0 - mt, a.x1 + mt, a.y1 + mt)) ++lt;
                        if (seg_box(anchors[i].mid_x, anchors[i].ny, a.cx, a.cy, b.x0, b.y0, b.x1, b.y1)) ++lt0;
                        if (seg_box(anchors[j].mid_x, anchors[j].ny, b.cx, b.cy, a.x0, a.y0, a.x1, a.y1)) ++lt0;
                    }
                    // and break `base` into the terms that make it up, so a layout that loses on base
                    // says WHICH preference it lost on rather than just by how much
                    double t_len = 0, t_quad = 0, t_ang = 0, t_nol = 0, t_nw = 0, t_ink = 0, t_tier = 0, t_res = 0;
                    int n_nw = 0, n_t2 = 0, n_t3 = 0;
                    for (std::size_t i = 0; i < n; ++i) {
                        const Cand& c = cands[i][choice[i]];
                        const double fs = anchors[i].fs, ax = anchors[i].mid_x, ay = anchors[i].ny;
                        const double La = std::hypot(ax - c.cx, ay - c.cy);
                        const double tha = std::atan2(std::abs(ay - c.cy), std::max(std::abs(ax - c.cx), 1e-9));
                        const double e_len = La * K_wlen;
                        const double e_quad = La > len_soft ? ((La - len_soft) / fs) * ((La - len_soft) / fs) * K_wquad : 0.0;
                        const double e_ang = std::abs(tha - ang_target_for(La)) * (180.0 / PI) * K_wang;
                        const double e_nol = La < fs * 0.6 ? K_noleader : 0.0;
                        const double e_nw = c.cy < ay ? K_nw : 0.0;
                        const double e_ink = std::min(leader_ink_cells(ax, ay, c.cx, c.cy), 80) * K_wink;
                        const double e_tier = c.tier == 2 ? K_t2 : 0.0;
                        t_len += e_len; t_quad += e_quad; t_ang += e_ang; t_nol += e_nol; t_nw += e_nw; t_ink += e_ink; t_tier += e_tier;
                        t_res += c.base - (e_len + e_quad + e_ang + e_nol + e_nw + e_ink + e_tier);
                        if (e_nw > 0) ++n_nw;
                        if (c.tier == 2) ++n_t2;
                        if (c.tier == 3) ++n_t3;
                    }
                    fmt::print(stderr, ">>> aa-label REF totals {:<12} conflicts={:<3} (box/box={} leader/leader={} leader/text={}; with NO margins: {}/{}/{}) soft={:8.1f} inversions={:<3} base={:9.0f} scoreA={:12.0f} leader med={:.1f}pt\n",
                               tag, conf_total(), bb, ll, lt, bb0, ll0, lt0, soft_total(), inv_total(), base_total(), scoreA(), leadmed);
                    fmt::print(stderr, ">>> aa-label REF  base {:<12} length={:.0f} quad={:.0f} angle={:.0f} no-leader={:.0f} above-branch={:.0f}(n={}) leader-ink={:.0f} tier2={:.0f}(n={}) tier3-residual={:.0f}(n={})\n",
                               tag, t_len, t_quad, t_ang, t_nol, t_nw, n_nw, t_ink, t_tier, n_t2, t_res, n_t3);
                };
                choice = ref_choice; totals("REFERENCE", med(lr));
                choice = saved;      totals("SEARCH", med(ls));
                fmt::print(stderr, ">>> aa-label REF snap-to-candidate distance: med={:.1f}pt max={:.1f}pt (how well the candidate set can even express the reference)\n",
                           med(sn), *std::max_element(sn.begin(), sn.end()));
            }
            for (std::size_t i = 0; i < n; ++i) {
                const Cand& c = cands[i][choice[i]];
                done.push_back({anchors[i].mid_x, anchors[i].ny, c.x0, c.y1, anchors[i].fs, c.x0, c.x1, c.y0, c.y1, c.cx, c.cy, anchors[i].nlines, anchors[i].text, anchors[i].color, static_cast<int>(i)});
            }
            { int cc = 0;
              for (std::size_t i = 0; i < n; ++i) for (std::size_t j = i + 1; j < n; ++j) {
                  const int c = pconf(i, choice[i], j, choice[j]);
                  if (c > 0) { cc += c;
                      const Cand& A = cands[i][choice[i]]; const Cand& B = cands[j][choice[j]];
                      std::string kinds;
                      if (A.x0 - m < B.x1 && B.x0 - m < A.x1 && A.y0 - m < B.y1 && B.y0 - m < A.y1) kinds += "box/box ";
                      if (segs_cross(anchors[i].mid_x, anchors[i].ny, A.cx, A.cy, anchors[j].mid_x, anchors[j].ny, B.cx, B.cy)) kinds += "leader/leader ";
                      if (seg_box(anchors[i].mid_x, anchors[i].ny, A.cx, A.cy, B.x0 - mt, B.y0 - mt, B.x1 + mt, B.y1 + mt)) kinds += "i-leader/j-text ";
                      if (seg_box(anchors[j].mid_x, anchors[j].ny, B.cx, B.cy, A.x0 - mt, A.y0 - mt, A.x1 + mt, A.y1 + mt)) kinds += "j-leader/i-text ";
                      fmt::print(stderr, ">>> aa-label placement: residual conflict [{}] — '{}' anchor({:.0f},{:.0f}) box({:.0f},{:.0f} {:.0f}x{:.0f}) tier{} cands={} vs '{}' anchor({:.0f},{:.0f}) box({:.0f},{:.0f} {:.0f}x{:.0f}) tier{} cands={}\n",
                                 kinds, anchors[i].text, anchors[i].mid_x, anchors[i].ny, A.x0, A.y0, A.x1 - A.x0, A.y1 - A.y0, A.tier, cands[i].size(),
                                 anchors[j].text, anchors[j].mid_x, anchors[j].ny, B.x0, B.y0, B.x1 - B.x0, B.y1 - B.y0, B.tier, cands[j].size()); } }
              if (cc > 0) fmt::print(stderr, ">>> aa-label placement: WARNING — {} residual conflict(s) (overlaps/crossings) could not be removed\n", cc); }
            // --- placement METRICS over the final layout ------------------------------------------
            // One line per render, always printed, so a change to the placer is judged on numbers
            // rather than on how the page looks at a glance. Each counter maps to one stated
            // constraint; all four counters should read 0, and the length/angle summary says how
            // close the leaders got to "short, diagonal, never horizontal".
            {
                int ink_hits = 0, text_ovl = 0, lead_text = 0, lead_x = 0, shallow = 0, nonsw = 0, overlong = 0, t2 = 0, t3 = 0, vax_ovl = 0;
                std::vector<double> lens, angs, xings;
                lens.reserve(n); angs.reserve(n); xings.reserve(n);
                for (std::size_t i = 0; i < n; ++i) {
                    const Cand& a = cands[i][choice[i]];
                    if (box_hits_ink(a.x0, a.y0, a.x1, a.y1)) ++ink_hits;                    // #1 text over a black branch
                    for (const auto& b : text_label_boxes)                                    // #2 text over a vaccine/strain name
                        if (a.x0 < b[2] && b[0] < a.x1 && a.y0 < b[3] && b[1] < a.y1) { ++vax_ovl; break; }
                    const double dx = anchors[i].mid_x - a.cx, dy = anchors[i].ny - a.cy;
                    const double L = std::hypot(dx, dy);
                    const double th_deg = std::atan2(std::abs(dy), std::max(std::abs(dx), 1e-9)) * 180.0 / PI;
                    lens.push_back(L); angs.push_back(th_deg);
                    xings.push_back(leader_ink_cells(anchors[i].mid_x, anchors[i].ny, a.cx, a.cy));
                    if (th_deg < 22.0) ++shallow;                                            // #3 too near horizontal
                    if (a.cy < anchors[i].ny) ++nonsw;                                       // #3 label NOT below-left (not a NE-SW leader)
                    if (L > len_max) ++overlong;                                             // #4 past the length ceiling
                    if (a.tier == 2) ++t2;                                                   // left the target envelope to fit
                    if (a.tier == 3) ++t3;                                                   // no leader-shaped spot at all
                    for (std::size_t j = 0; j < n; ++j) {
                        if (j == i) continue;
                        const Cand& b = cands[j][choice[j]];
                        if (j > i && a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1) ++text_ovl;                    // #2 text over text
                        if (seg_box(anchors[i].mid_x, anchors[i].ny, a.cx, a.cy, b.x0, b.y0, b.x1, b.y1)) ++lead_text;        // #2 leader over another label's text
                        if (j > i && segs_cross(anchors[i].mid_x, anchors[i].ny, a.cx, a.cy, anchors[j].mid_x, anchors[j].ny, b.cx, b.cy)) ++lead_x; // #2 leader over leader
                    }
                }
                std::sort(lens.begin(), lens.end()); std::sort(angs.begin(), angs.end()); std::sort(xings.begin(), xings.end());
                const auto med = [](const std::vector<double>& v) { return v.empty() ? 0.0 : v[v.size() / 2]; };
                fmt::print(stderr, ">>> aa-label metrics: n={} | text-over-branch={} text-over-name={} text-over-text={} leader-over-text={} leader-over-leader={}"
                                   " | leader len %page: med={:.1f} max={:.1f} over-{:.0f}px={}"
                                   " | leader angle deg: min={:.0f} med={:.0f} below-22deg={} not-NE/SW={}"
                                   " | leader crosses tree cells: med={:.0f} max={:.0f}"
                                   " | off-envelope={} band-sweep={}\n",
                           n, ink_hits, vax_ovl, text_ovl, lead_text, lead_x,
                           100.0 * med(lens) / height, lens.empty() ? 0.0 : 100.0 * lens.back() / height, len_max, overlong,
                           angs.empty() ? 0.0 : angs.front(), med(angs), shallow, nonsw,
                           med(xings), xings.empty() ? 0.0 : xings.back(), t2, t3);
            }
        }
        else {
            // legacy: honour each label's manual offset, then nudge overlaps downward
            std::vector<Placed> placed;
            for (std::size_t i = 0; i < anchors.size(); ++i) {
                const auto& a = anchors[i];
                const double tx = a.nx + a.off_x * (a.off_rel_h ? height : width);
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

        // --- aa-transition label-position dump (port of AD DrawAATransitions::report,
        //     acmacs-tal cc/draw-aa-transitions.cc:756) ---
        //
        // Every row is directly pasteable into the `.tal`'s `draw-aa-transitions` `per-node` list —
        // which IS the manual label-moving workflow: render, read the offsets the placer chose,
        // hand-edit the ones that want moving, paste the block back. `?`-prefixed keys are AD's
        // convention for "informational, ignored on read".
        //
        // Emitted alongside the clade-section report on stderr AND in `<output>.taleg`
        // (RUNNING-THE-REPORT.md §10.5 documents reading the file instead of scraping stderr), and
        // printed BEFORE the labels are drawn, as AD does, so the tuning loop need not wait out the
        // rest of the render.
        //
        // `first`/`last` are the node's CURRENT extent (Anchor::cur_first/cur_last), recomputed from
        // the tree being drawn exactly as AD recomputes them — so a pasted block refreshes an
        // identity that has gone stale as the tree grew, instead of writing back what it came in with.
        //
        // Two deliberate departures from AD's field set, both forced by how ae identifies a node:
        //   * `first`/`last` are NOT `?`-disabled. AD selects a node by its draw-time `node_id`, so
        //     for AD they are informational; ae has no such id and resolves the node as
        //     MRCA(first,last), so here they carry the identity and must stay live. `node_id` is
        //     echoed back from the `.tal` verbatim — ae neither computes nor consumes it — so a
        //     pasted block keeps the field, but it does not track a rebuilt tree.
        //   * `pinned` is printed. ae AUTO-PLACES un-pinned labels and ignores their offsets, so a
        //     row pasted back without it would be re-placed rather than held where the dump says.
        //
        // Rows are in `.tal` order (Anchor::ord), shown and hidden together, as AD reports both.
        if (params.mrca_labels_report && !(anchors.empty() && hidden.empty())) {
            const auto jstr = [](const std::string& str) {
                std::string out;
                out.reserve(str.size() + 2);
                for (char c : str) {
                    switch (c) {
                        case '"': out += "\\\""; break;
                        case '\\': out += "\\\\"; break;
                        default: if (static_cast<unsigned char>(c) < 0x20) out += ' '; else out += c;
                    }
                }
                return out;
            };
            // the leaf drawn immediately before `first` / after `last` — AD's `?before first` /
            // `?after last`, the hint for widening or narrowing a label's node by hand
            const auto neighbour = [&](const std::string& leaf, long delta) -> std::string {
                const auto found = leaf_order_by_name.find(leaf);
                if (found == leaf_order_by_name.end())
                    return {};
                const long at = static_cast<long>(found->second) + delta;
                if (at < 0 || at >= static_cast<long>(layout.leaves.size()))
                    return {};
                return layout.leaves[static_cast<std::size_t>(at)].name;
            };
            struct ReportRow { std::size_t ord; std::string node_id, name, first, last, before_first, after_last; bool show, pinned, off_rel_h; double off_x, off_y, box_w, box_h; };
            std::vector<ReportRow> rows;
            rows.reserve(done.size() + hidden.size());
            const auto row_of = [&](const Anchor& a, bool show, double off_x, double off_y, double box_w, double box_h) {
                return ReportRow{a.ord, a.node_id, a.text, a.cur_first, a.cur_last, neighbour(a.cur_first, -1), neighbour(a.cur_last, 1), show, a.pinned, a.off_rel_h, off_x, off_y, box_w, box_h};
            };
            for (const auto& p : done) {
                const Anchor& a = anchors[p.aidx];
                // the offset that REPRODUCES the placed box: box top-left = node point + offset*page
                // (the same inverse the sidecar and the drag editor use). x is relative to the page
                // width, or to its height when the label was authored with "offset_h".
                const double rel_w = a.off_rel_h ? height : width;
                rows.push_back(row_of(a, true, (p.x0 - a.nx) / rel_w, (p.y0 - a.ny) / height, (p.x1 - p.x0) / width, (p.y1 - p.y0) / height));
            }
            for (const auto& a : hidden) // never placed: report the authored offset and the text-metric box
                rows.push_back(row_of(a, false, a.off_x, a.off_y, a.tw / width, static_cast<double>(a.nlines) * a.fs * 1.18 / height));
            std::sort(std::begin(rows), std::end(rows), [](const ReportRow& r1, const ReportRow& r2) { return r1.ord < r2.ord; });

            // AD column-aligns on the widest id / name / first / last — that alignment is what makes
            // the block readable and hand-diffable against the previous render.
            std::size_t w_id{0}, w_name{0}, w_first{0}, w_last{0}, w_before{0};
            for (const ReportRow& row : rows) {
                w_id = std::max(w_id, row.node_id.size());
                w_name = std::max(w_name, row.name.size());
                w_first = std::max(w_first, row.first.size());
                w_last = std::max(w_last, row.last.size());
                w_before = std::max(w_before, row.before_first.size());
            }
            fmt::memory_buffer rep;
            const auto app = std::back_inserter(rep);
            fmt::format_to(app, ">>> AA transition labels ({}) vvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvvv\n", rows.size());
            fmt::format_to(app, ">>> paste into the .tal's \"draw-aa-transitions\" \"per-node\"; \"pinned\": true holds a label where you put it\n[\n");
            for (std::size_t rno = 0; rno < rows.size(); ++rno) {
                const ReportRow& row = rows[rno];
                fmt::format_to(app,
                               "    {{\"node_id\": {:>{}s} \"name\": {:<{}s} \"show\": {} \"pinned\": {} "
                               "\"label\": {{\"{}\": [{:9.6f}, {:9.6f}], \"?box\": [{:.4f}, {:.4f}]}}, "
                               "\"first\": {:<{}s} \"last\": {:<{}s} \"?before first\": {:<{}s} \"?after last\": {}}}{}\n",
                               fmt::format("\"{}\",", jstr(row.node_id)), w_id + 4,                                             // node_id
                               fmt::format("\"{}\",", jstr(row.name)), w_name + 4,                                              // name
                               row.show ? "true, " : "false,",                                                                 // show
                               row.pinned ? "true, " : "false,",                                                               // pinned
                               row.off_rel_h ? "offset_h" : "offset", row.off_x, row.off_y, row.box_w, row.box_h,              // label
                               fmt::format("\"{}\",", jstr(row.first)), w_first + 4,                                            // first
                               fmt::format("\"{}\",", jstr(row.last)), w_last + 4,                                              // last
                               row.before_first.empty() ? std::string{"null,"} : fmt::format("\"{}\",", jstr(row.before_first)), w_before + 4,
                               row.after_last.empty() ? std::string{"null"} : fmt::format("\"{}\"", jstr(row.after_last)),
                               rno + 1 < rows.size() ? "," : "");
            }
            fmt::format_to(app, "]\n>>> ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n\n");
            emit_diag(fmt::to_string(rep));
        }

        // Chosen by sweeping 0.00 / 0.10 / 0.15 / 0.22 / 0.30 on the round's h1 and comparing the
        // renders side by side: 0 has the leader touching the glyphs, 0.30 is the old distance,
        // 0.15 (1.43pt at the labels' 9.5pt) reads as pointing at the label without meeting it.
        // Swept on the round's h1 and chosen from the renders (Sarah, 20 Sep 2026). The earlier
        // sweeps that landed on 0.45 were run against the UNDER-MEASURED box of the commit before
        // this one, which is why they read so far out: with the box now matching the glyphs, the
        // same leader sits a good 5pt closer on the worst-measured labels, and the whole scale
        // shifts down. 0.12 puts the drawn end 0.99pt from the letters — close, without touching.
        // (0.05 -> 0.41pt, 0.20 -> 1.64pt, 0.30 -> 2.47pt were the other candidates.)
        const double leader_gap = 0.12;         // fraction of the label's font size
        for (const auto& p : done) {
            // Leader from the branch midpoint (p.nx,p.ny) to the attach point (p.cx,p.cy), stopped a
            // short way short of it so it reads as pointing AT the label rather than touching it.
            //
            // The gap is a LOOKS decision, settled by rendering the round's h1 at several values and
            // choosing (Sarah, 20 Sep 2026). It is applied only here, never to `p.cx,p.cy`, so the
            // placement search goes on costing the true attach point: the gap cannot move a label.
            //
            // The scale matters more than the number. `leader_gap` is a fraction of the label's own
            // font size, so it holds its visual weight when `mrca_fs` changes between subtypes or
            // rounds; a constant in points would look tight on a big label and gaping on a small one.
            // Capped at a fraction of the leader itself so a very short leader is shortened, not
            // reversed.
            if (std::abs(p.cx - p.nx) > p.fs * 0.4 || std::abs(p.cy - p.ny) > p.fs * 0.4) {
                const double lx = p.nx - p.cx, ly = p.ny - p.cy, ll = std::hypot(lx, ly);
                const double gap = std::min(p.fs * leader_gap, ll * 0.4);
                pdf.line(p.nx, p.ny, p.cx + lx / ll * gap, p.cy + ly / ll * gap, BLACK, 0.3); // AD LabelTether{BLACK, 0.3px}; thin => renders mid-grey (was light GREY 0xBEBEBE = too pale)
            }
            // stacked text: one substitution per line, each vertically CENTRED in its row so the
            // glyphs fill the collision box (pdf.text anchors the glyph top at y; a cap is ~0.72*fs
            // tall, so top = row-centre - 0.36*fs). This makes the box match the rendered text, so
            // the attach point (p.cx,p.cy) lands on the edge of the GLYPHS rather than of a box that
            // is taller than they are, and overlap tests are computed where the text actually is.
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
    //
    // Only the file-output path can produce a meaningful sidecar: it names the PDF it describes
    // (`output`) and its geometry is that of the standalone tree page, which the label editor drags
    // boxes on. The shared-surface path (export_tree_into, empty `output` — the signature-page
    // compositor) has no such file and scales the tree into a sub-rect of someone else's page, so
    // emitting one would write "pdf": "" plus coordinates that fit nothing. Skip it there and say so.
    // Today only the label editor sets mrca_label_sidecar, and it always renders to a file, so this
    // just guards a sig-page .tal that happens to carry the setting (settings.cc parses it from any).
    if (!params.mrca_label_sidecar.empty() && output.empty()) {
        fmt::print(stderr, ">>> mrca_label_sidecar '{}' not written: the tree is rendered into a shared surface, not to its own PDF\n", params.mrca_label_sidecar);
    }
    else if (!params.mrca_label_sidecar.empty()) {
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
            const double off_hx = (r.bx0 - r.ax) / height; // geometry-invariant x (see MrcaLabel::offset_rel_height)
            fmt::format_to(std::back_inserter(j),
                           "    {{ \"id\": {}, \"kind\": \"{}\", \"first\": \"{}\", \"last\": \"{}\", \"seq_id\": \"{}\", \"text\": \"{}\", \"nlines\": {}, \"pinned\": {},\n"
                           "      \"anchor\": {{ \"x\": {:.4f}, \"y\": {:.4f} }}, \"tether\": {{ \"x\": {:.4f}, \"y\": {:.4f} }},\n"
                           "      \"box\": {{ \"x0\": {:.4f}, \"y0\": {:.4f}, \"x1\": {:.4f}, \"y1\": {:.4f} }},\n"
                           "      \"offset\": {{ \"x\": {:.6f}, \"y\": {:.6f} }}, \"offset_h\": {{ \"x\": {:.6f}, \"y\": {:.6f} }}, \"color\": \"#{:06x}\", \"fs\": {:.4f} }}",
                           k, r.kind, jstr(r.first), jstr(r.last), jstr(r.seq_id), jstr(r.text), r.nlines, r.pinned ? "true" : "false",
                           r.ax, r.ay, r.tx, r.ty, r.bx0, r.by0, r.bx1, r.by1, off_x, off_y, off_hx, off_y, r.color, r.fs);
            j += (k + 1 < side_rows.size()) ? ",\n" : "\n";
        }
        j += "  ]\n}\n";
        std::ofstream out{params.mrca_label_sidecar};
        out << j;
    }

    return labels_hidden;

} // render_tree_core

// File-output entry point (unchanged behaviour): owned CairoPdf bound to `output`.
std::size_t export_tree_pdf(ae::tree::Tree& tree, const std::filesystem::path& output, double image_size, const TreeDrawParameters& params)
{
    return render_tree_core(tree, output, image_size, params,
                            [&output](double width, double height) { return std::make_unique<ae::draw::CairoPdf>(output, width, height); });
}

// Shared-surface entry point (single-canvas compositor): render into a sub-rectangle of the caller's
// Cairo context, letterboxed (aspect-preserving, centred). Same draw calls as export_tree_pdf.
std::size_t export_tree_into(ae::tree::Tree& tree, _cairo* context, double dst_x, double dst_y, double dst_w, double dst_h,
                             double image_size, const TreeDrawParameters& params)
{
    return render_tree_core(tree, std::filesystem::path{}, image_size, params, [=](double width, double height) {
        const double scale = (width > 0.0 && height > 0.0) ? std::min(dst_w / width, dst_h / height) : 1.0;
        const double w = width * scale, h = height * scale;
        const double x = dst_x + (dst_w - w) / 2.0, y = dst_y + (dst_h - h) / 2.0; // centre in the rect
        return std::make_unique<ae::draw::CairoPdf>(context, x, y, w, h, width, height);
    });
}

} // namespace ae::tal

// ======================================================================
