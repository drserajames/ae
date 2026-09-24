#pragma once

#include <cstddef>
#include <filesystem>
#include <map>
#include <memory>
#include <optional>
#include <regex>
#include <string>
#include <string_view>
#include <vector>

// ======================================================================
// TAL (subsystem #3) — Phase B: render a phylogenetic tree (+ aligned columns)
// to PDF.
//
// M1 drew the tree itself (edge segments + inode connectors, optional labels).
// M2 adds, as columns aligned to the tree's leaf rows: per-leaf coloring by
// clade, a clade-sections column (bars from compute_clade_sections), and a
// time-series dash column (per-leaf dashes bucketed by compute_time_series).
//
// Reuses ae::tal::compute_layout / compute_clade_sections / compute_time_series
// (Phase A) and the ae::draw::CairoPdf surface from subsystem #1 — only its
// existing line()/text() primitives, so no surface change is needed. Cairo is
// linked only into the `tal-draw` executable, never into libae/ae_backend.
// See cc/tal/PORTING.md.
// ======================================================================

// Forward declaration of the opaque Cairo context (typedef struct _cairo cairo_t;) for the
// shared-surface tree render entry point below — keeps the Cairo headers out of this interface.
struct _cairo;

namespace ae::tree
{
    class Tree;
}

namespace ae::tal
{
    // Per-clade overrides (from the settings DSL): a colour string ("#1f77b4" or a
    // name like "blue"; empty = use the default palette) and a display name shown in
    // the clade column / legend (empty = use the clade's own name).
    struct CladeStyle
    {
        std::string color{};
        std::string display_name{};
        bool hide{false}; // suppress this clade's bar + label from the clades column / legend (acmacs-tal per-clade show:false)
        // Explicit horizontal slot (AD per-clade slot); unset = compute via set_slots.
        // A double, not an int: the bracket is drawn at slot_width*(slot+1) from the clade
        // column's inner edge, so a fractional slot (0.5) moves the whole staircase step by a
        // half-pitch, and a negative one (> -1) pulls a bracket back towards the neighbouring
        // column, WITHOUT having to shrink `slot.width` (which also sets the level spacing and
        // the label size). AD's own slot_no is an unsigned named_size_t and truncates 2.2 to 2,
        // so this is a deliberate superset of AD, not a parity fix. `std::optional` rather than
        // a -1 sentinel, because -1 is now a usable value.
        std::optional<double> slot{};
        double label_scale{0.0};               // label size = clades slot.width * this scale; 0 = column default
        int rotation_degrees{90};              // label rotation (90 = clockwise / top-to-bottom, 0 = horizontal)
        double section_inclusion_tolerance{0.0}; // merge sections whose gap (leaf indices) <= this (AD make_sections)
        double section_exclusion_tolerance{0.0}; // drop sections whose size (leaves) <= this
        double label_offset_x{0.002};          // label offset, fractions of height (just right of the arrow)
        double label_offset_y{0.0};
    };

    // One `seq_id` selector, compiled. AD matches a `seq_id` select as an UNANCHORED,
    // case-insensitive ECMAScript regex (acmacs-tal cc/tree.cc:396 `select_by_seq_id`), so a
    // pattern is a *substring* test, not equality: `X/1/2024_ABC1234` also selects
    // `X/1/2024_ABC1234D`. Compiled once at settings-load time because a report tree is ~1000
    // selectors x ~100k leaves; a pattern carrying no regex metacharacters takes a
    // case-insensitive substring fast path and never constructs a std::regex.
    struct SeqIdMatcher
    {
        std::string pattern{};                   // exactly as written in the settings
        std::string lowered{};                   // pattern, lowercased — the literal fast path
        std::shared_ptr<const std::regex> re{};  // compiled iff `pattern` has metacharacters
        bool is_literal() const { return re == nullptr; }
        bool matches(std::string_view name) const;
        bool equals(std::string_view name) const; // case-insensitive equality, for the diagnostic
    };

    // Build a matcher for one settings `seq_id` string (a bad regex degrades to a literal, with
    // a warning, rather than throwing out of the whole render).
    SeqIdMatcher make_seq_id_matcher(std::string_view pattern);

    struct NodeSelect
    {
        std::vector<SeqIdMatcher> seq_id{};     // leaf-name matches one of these (leaves only)
        std::optional<double> cumulative_min{}; // node cumulative edge length >= this
        std::optional<double> edge_min{};       // node's own edge length >= this (hide long-edge outliers)
        std::string date_min{};                 // leaf date >= this "YYYY-MM-DD" (leaves only)
        std::string date_max{};                 // leaf date <  this "YYYY-MM-DD" (leaves only)
    };

    // A positioned text label drawn at a leaf's tip (acmacs-tal DrawOnTree / nodes apply.text).
    // Offsets and size are fractions of image_size; offset is relative to the leaf tip
    // (default places the text just to its right).
    struct NodeText
    {
        std::string text{};         // the label string
        double offset_x{0.01};      // x offset from the leaf tip, fraction of image_size
        double offset_y{0.0};       // y offset, fraction of image_size (down is positive)
        std::string color{};        // "" -> black
        double size{0.0};           // font size as fraction of image_size; 0 -> default leaf font
    };

    // A curated on-tree label placed at an internal node (acmacs-tal `draw-aa-transitions`
    // `per-node`). AD selects the node by its draw-time `node_id`, which ae's tree does not
    // carry — instead we identify the node as the MRCA of the `first`/`last` leaf seq_ids the
    // entry also records (MRCA(first,last) == that node), and draw the label at its position.
    struct MrcaLabel
    {
        std::string first{};        // seq_id of the node's first leaf
        std::string last{};         // seq_id of the node's last leaf
        std::string text{};         // label string (the aa-transition / clade name)
        double offset_x{0.0};       // x offset from the node; fraction of PAGE WIDTH unless
                                    // offset_rel_height, then of image_size (see below)
        double offset_y{0.0};       // y offset, fraction of image_size (down is positive)
        bool offset_rel_height{false}; // the .tal carried "offset_h" rather than "offset": x is a
                                    // fraction of image_size (== page HEIGHT), not of page width.
                                    // Page width moves when the tree's own width changes between
                                    // rounds, or when the aa-label band changes, and a width-relative
                                    // offset silently drags every pinned label with it — that has
                                    // already cost one rescue pass over a whole hand layout. Height
                                    // is image_size, which is fixed, and it is also what the font
                                    // size scales with, so a height-relative offset holds a label the
                                    // same number of points from its branch whatever the page does.
                                    // "offset" keeps the old meaning exactly, so existing .tal files
                                    // render byte-identically; the editor writes "offset_h" for new
                                    // pins.
        std::string color{};        // "" -> black
        double size{0.0};           // font size as fraction of image_size; 0 -> default font
        bool pinned{false};         // user PINNED this label: place it at its offset (box top-left =
                                    // node + offset*page) and treat it as a fixed obstacle, while the
                                    // other (un-pinned) labels still auto-place around it. Set by the
                                    // WYSIWYG drag editor; un-pinned labels keep the auto-place behaviour.
        bool show{true};            // the `.tal` per-node entry's "show". A `false` entry is curation:
                                    // "this transition exists, do NOT label it". It is carried through
                                    // (not dropped at translation) so the label-position dump can list
                                    // it — AD reports shown and hidden transitions alike — and so a
                                    // dump pasted back into the `.tal` keeps the hidden ones hidden.
                                    // Never placed, never drawn.
        std::string node_id{};      // AD's draw-time node id ("vertical.horizontal"), echoed verbatim
                                    // from the `.tal`. ae has no such id — it identifies the node as
                                    // MRCA(first,last) — but the dump round-trips the field so pasting
                                    // a dumped block back into the `.tal` does not lose it.
    };

    struct NodeApply
    {
        std::optional<bool> hide{};       // hide the node (and its subtree) from the layout
        std::string edge_color{};         // recolour the node's edge line ("#rrggbb"/name)
        std::string label_color{};        // recolour the leaf label (leaves only)
        std::optional<double> label_scale{}; // scale the leaf-label font (leaves only)
        std::optional<NodeText> text{};   // positioned text label at the leaf tip (leaves only)
    };

    struct NodeMod
    {
        NodeSelect select{};
        NodeApply apply{};
    };

    // An amino-acid condition "<pos><aa>" (1-based position, required residue), e.g. "156N".
    struct AaCondition { int pos{0}; char aa{0}; };

    // A per-leaf dash column (acmacs-tal dash-bar / dash-bar-aa-at). Two flavours:
    //  - pos-based (dash-bar-aa-at): colour each shown leaf by its aa at `pos` (1-based), via
    //    `colors_by_aa` when given else by frequency (most common = grey, variants pop);
    //  - select-based (dash-bar): colour each leaf by the FIRST matching `selects` entry (all of
    //    its conditions hold), else not drawn.
    // `legend` is the position+aa swatch list shown (in colour) at the bottom of the bar.
    struct DashBarAAAt
    {
        int pos{0};
        std::map<char, std::string> colors_by_aa{}; // aa char -> colour string ("#rrggbb"/name)
        std::vector<std::pair<std::vector<AaCondition>, std::string>> selects{}; // (conditions, colour)
        struct LegendItem { std::string text; std::string color; char aa{0}; }; // aa=0 -> no actual-colour lookup
        std::vector<LegendItem> legend{};
        // `.tal` "side": "left" — draw this bar in its own column LEFT of the tree (page margin |
        // left bars | gap | aa-label band | tree root) instead of in the dash-bar band right of the
        // time series. Default false = "right" = the band, so existing trees are unchanged.
        bool left{false};
    };

    // A horizontal section of the tree (acmacs-tal hz-sections): the contiguous run of
    // leaves from `first` to `last` (by seq_id), labelled with `label` in a left marker
    // column, with a separator line across the tree at the section's top boundary.
    struct HzSection
    {
        std::string id{};      // AD hz_section_id_t, "{clade}-{section no}" — the key the curated
                               // entry is merged onto (AD HzSections::update_from_parameters ->
                               // find_add_section, acmacs-tal cc/hz-sections.cc:49)
        std::string first{};
        std::string last{};
        std::string label{};
        std::string prefix{};  // section letter, when the CALLER assigns it (the signature-page
                               // path does: py/ae/tal/signature_page.py supplies the sections the
                               // page is really built from, already lettered in tree order). The
                               // `.tal`'s own "L" is NOT read — see settings_v3.
        bool shown{true};      // AD HzSection::shown — a hidden section still EXISTS (it is reported
                               // and it takes no letter); it is simply not drawn
        std::optional<std::string> aa_transitions{}; // AD HzSection::label_aa_transitions — the CURATED
                               // section text. nullopt when the entry has no key, "" when it is
                               // hand-blanked: the two must stay distinct. The hz-sections dump prints
                               // it in place of the computed list when set (AD aa_transitions_format);
                               // nothing drawn depends on it. See cc/tal/PORTING.md.
    };

    struct TreeDrawParameters
    {
        // Overall page aspect (width / height). When > 0 the canvas is drawn portrait —
        // width = height * width_to_height_ratio — instead of square (acmacs-tal sizes the
        // canvas width from the tree's width-to-height-ratio plus the right-hand columns;
        // the report .tal's give the tree ratio ~0.4, columns push the page to ~0.63).
        // 0 (default) keeps the historical square canvas.
        double width_to_height_ratio{0.0};
        double edge_line_width_scale{1.0};   // global multiplier on every tree-edge's drawn width
                                             // (AD per-node edge_line_width_scale applied to all
                                             // nodes via the info trees' all-and-intermediate
                                             // tree-edge-line-width mod — the heavy-edge diagnostic
                                             // look); 1.0 = default render unchanged
        std::string ladderize{};             // "" | "none" | "number-of-leaves" | "max-edge-length" — reorder children before layout
        bool labels{false};                  // draw each leaf's name to the right of its tip
        bool labels_avoid_collisions{true};  // suppress leaf labels that would overlap the one above
        bool tip_names{false};               // draw EVERY shown leaf's name at its tip, tiny (~row height),
                                             // no reserved column / no collision avoidance (AD DrawTree,
                                             // faint at page scale, readable when zoomed)
        bool color_by_clade{false};  // colour leaf edges/labels/dashes by first clade
        bool color_by_continent{false}; // colour leaves by geographic continent (acmacs-tal color-by continent)
        bool color_edges{false};     // recolour tree EDGES by the active mode (tree color-by); else edges stay black
        int color_by_pos{0};         // colour leaves by amino acid at this 1-based position (0 = off)
        std::map<char, std::string> color_by_pos_colors{}; // aa char -> colour for color_by_pos; empty = colour by frequency
        bool clades{false};          // draw the clade-sections column
        double clades_slot_width{0.0};   // clade column slot width as a fraction of height (AD clades slot.width); 0 = derived
        // The inter-column gap immediately BEFORE the clades column, as a fraction of page width;
        // < 0 = the shared default (0.012). In the tree-only column order (labels, time-series,
        // clades, dash bars) that is the matrix -> clades gap; on a signature page, where the
        // clades column precedes the matrix, it is the labels -> clades gap. AD gets this knob
        // from the explicit `{"N": "gap"}` element the `.tal` program puts between the two
        // columns; ae lays the columns out itself, so it is exposed here instead. 0 is legal
        // (columns flush) — hence the negative "unset".
        double clades_gap_ratio{-1.0};
        double clades_label_scale{0.0};  // default per-clade label scale (AD all-clades label.scale); 0 = 1.0
        double clades_width_ratio{0.0};  // clade column width as a fraction of height (AD clades width-to-height-ratio); 0 = derived
        bool clades_horizontal_lines{true}; // draw the two faint grey lines at each clade's top & bottom (AD horizontal_line); false = brackets only
        bool clades_arrows{true};          // filled arrowheads at both ends of each clade bracket (AD double_arrow); false = a plain line over the full band
        double clades_line_width{1.0};     // clade bracket line width (AD Line default 1.0); the grey arms stay 0.5
        double clades_band_gap{0.0};       // gap left between brackets whose bands meet: N/2 trimmed off each bracket end, in points at a 1000 pt tall page (scaled by height/1000); 0 = full band
        // AD Clades::Parameters::report (acmacs-tal clades.hh:99) — default TRUE, as in AD: print the
        // clade-section diagnostic (per-clade band count, sizes, node ranges, inter-section gaps, and the
        // hz-section dump + sibling-intersect warnings) before the slow PDF draw. The `.tal`'s clades
        // command can turn it off with `"report": false`. See the block in draw-tree.cc.
        bool clades_report{true};
        // Where to also write that diagnostic. Empty -> `<output>.taleg` next to the rendered PDF
        // (RUNNING-THE-REPORT.md §10.5 reads `tree/<subtype>.taleg`). "-" disables the file.
        std::string clades_report_file{};
        // Print the clade-section diagnostic and STOP, without drawing (tal-draw --clades-report).
        // The §10.5 tuning loop only needs the numbers, and a report tree takes minutes to draw.
        bool clades_report_only{false};
        // Differential-verification hook (tal-draw --transitions-report=FILE): after the node `hide`
        // mods and the aa-transition computation, dump one line per inode --
        //     <first leaf name> TAB <last leaf name> TAB <shown leaves> TAB <labels>
        // -- and STOP without drawing. The (first, last) leaf pair is the only key both engines
        // share (AD's "vertical.horizontal" node_id has no ae equivalent), so this is the ae side
        // of a per-inode diff against AD's `tal --first-last-leaves 1`. Empty = off.
        std::string transitions_report_file{};
        double dash_column_width_ratio{0.0}; // dash-bar column pitch as fraction of drawable width; 0 => 0.022
        double right_margin_ratio{0.0};      // right page margin as fraction of width; 0 => same as the left (0.03).
                                            // Signature pages set this small so the rightmost column (the AA
                                            // colour bars) runs up to the tree panel's edge and the maps can sit
                                            // beside it, as they do in AD.
        double dash_fill_fraction{0.0};      // coloured bar length as fraction of the column; 0 => 0.6
        bool time_series{false};     // draw the time-series dash column
        std::string time_series_interval{"month"}; // year | month | week | day
        std::string time_series_start{};            // optional "YYYY-MM-DD" range start
        std::string time_series_end{};              // optional "YYYY-MM-DD" range end
        double time_series_slot_width{0.0};         // slot width as a fraction of height (AD slot.width); 0 = fallback
        double time_series_label_scale{0.0};        // date-label size = slot_width * scale * height; 0 = derived
        std::string time_series_label_rotation{};   // "clockwise" | "anticlockwise" (date reading direction)
        bool time_series_dates_top{true};           // draw the date band above the matrix; false = words kept invisible (text layer only), band space given to the matrix
        bool time_series_dates_bottom{true};        // same for the band below the matrix
        double time_series_year_separator{0.5};     // stroke width of the slot separator at a year boundary (others stay 0.5)
        std::string title{};         // page title (top, centred); empty = none
        bool legend{false};          // draw a clade colour legend (bottom row)
        bool geo_inset{false};       // draw the continent-coloured world-map inset (lower-left); doubles as the continent legend (acmacs-tal LegendContinentMap)
        bool aa_transitions{false};  // label inodes with their aa-substitution transitions
        bool aa_transitions_compute{false}; // compute the transitions first instead of using the tree's stored ones
        std::string aa_transitions_method{"consensus"}; // "consensus" | "eu-20200915" (acmacs-tal draw-aa-transitions `method`)
        double aa_transitions_tolerance{0.6}; // non-common tolerance (when computing)
        int aa_transitions_min_leaves{1};   // only label an inode's transitions if its subtree has >= this many leaves
        std::map<std::string, CladeStyle> clade_styles{}; // clade name -> override
        std::vector<NodeMod> node_mods{};                 // select/apply mods, applied in order
        std::vector<HzSection> hz_sections{};             // horizontal section bands (left marker column)
        bool hz_section_labels{false};                    // draw the section letters (A/B/C) + brackets in a right-edge marker column (AD hz-section-marker)
        bool clades_before_time_series{false};            // draw the clades column LEFT of the time-series matrix (AD layout-with-maps); default = right (layout-tree-only)
        std::vector<std::string> matches_chart_seq_ids{}; // leaves whose antigen is in the chart — drawn as AD's grey matches-chart-antigen dash-bar
        std::vector<DashBarAAAt> dash_bars{};             // per-leaf aa-at-position dash columns
        std::vector<MrcaLabel> mrca_labels{};             // curated on-tree labels at MRCA(first,last) nodes (draw-aa-transitions per-node)
        bool mrca_labels_auto_place{false};               // auto-place mrca labels into whitespace (ignore per-label offsets), with collision avoidance + tether
        std::string mrca_label_sidecar{};                 // when non-empty, write a "tal-mrca-labels/1" JSON sidecar (page geometry + per-label
                                                          // anchor/tether/box/offset/pinned, device units) to this path — drives the WYSIWYG drag editor
        bool mrca_labels_report{true};                    // print the pasteable aa-transition label-position dump (AD DrawAATransitions::report,
                                                          // acmacs-tal draw-aa-transitions.cc:756) to stderr and to <output>.taleg. AD printed it
                                                          // unconditionally; default ON here for the same reason — the manual label-moving loop needs
                                                          // it without having to ask. NB this is NOT the `.tal`'s draw-aa-transitions "report" key,
                                                          // which in AD switches on the aa-transition COMPUTATION debug trace, not this dump.
    };

    // Render `tree` to a PDF whose height is `image_size` device units. The width is
    // `image_size` (square) unless params.width_to_height_ratio > 0, in which case the
    // page is portrait (width = image_size * width_to_height_ratio). Takes Tree& because
    // layout computes cumulative edges. Returns the number of leaf labels suppressed by
    // collision avoidance (0 when disabled or none overlap).
    // Apply only the `hide` node-mods (marking nodes shown=false), as the drawing path does
    // before computing its layout. For callers that compute a layout themselves — notably
    // tal-draw's `.names` dump, which otherwise lists every leaf regardless of the settings.
    void apply_node_hide_mods(ae::tree::Tree& tree, const TreeDrawParameters& params);

    // Diagnostic for `seq_id` selectors, run once per render. Reports selectors that select
    // nothing (a stale id left over from an earlier cycle), and — the case that hid a real bug
    // in the 2026-0921 round for years — a selector with no regex metacharacters that matched
    // only as a *substring*, i.e. a truncated or mistyped id silently selecting a longer leaf.
    void report_node_mod_selectors(const ae::tree::Tree& tree, const TreeDrawParameters& params);

    std::size_t export_tree_pdf(ae::tree::Tree& tree, const std::filesystem::path& output, double image_size = 1000.0, const TreeDrawParameters& params = {});

    // Shared-surface form of export_tree_pdf (single-canvas signature-page compositor): render the
    // tree into a sub-rectangle of a caller-supplied Cairo context `context` instead of an owned
    // output file. The page geometry is computed identically (height = image_size, width per
    // width_to_height_ratio) and letterboxed (aspect-preserving, centred) into the device rectangle
    // (dst_x, dst_y, dst_w, dst_h). The context/surface are not owned. Same draw calls as
    // export_tree_pdf — standalone tal-draw file output is unaffected. Returns labels suppressed.
    std::size_t export_tree_into(ae::tree::Tree& tree, _cairo* context, double dst_x, double dst_y, double dst_w, double dst_h,
                                 double image_size = 1000.0, const TreeDrawParameters& params = {});

} // namespace ae::tal

// ======================================================================
