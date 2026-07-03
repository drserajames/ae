#include <algorithm>
#include <array>
#include <cctype>
#include <cmath>
#include <fstream>
#include <limits>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include "ext/fmt.hh"
#include "ext/simdjson.hh"
#include "map-draw/draw.hh"
#include "draw/cairo-surface.hh"
#include "ad/color.hh"
#include "chart/v3/chart.hh"
#include "chart/v3/chart-seqdb.hh"
#include "chart/v3/serum-circles.hh"
#include "chart/v3/common.hh"
#include "chart/v3/procrustes.hh"
#include "sequences/pos.hh"
#include "locdb/v3/locdb.hh"

// ======================================================================
// Fidelity port of AD acmacs-map-draw as used by the chains-202105 web app.
// The exact behaviours reproduced here (viewport, point sizes as absolute
// device pixels, grid/border, reset greys, clade colouring, recent-layer marks,
// title, legend, procrustes) are documented against the AD sources in TODO.md.
//
// Coordinate system matches AD exactly: NO Y-flip (map Y grows downward, same as
// device); device = (coord - viewport.origin) * (image_size / W), where W =
// ceil(diameter of the minimum bounding ball). Point sizes / line widths are
// absolute device pixels (AD "Pixels" unit) at the reference size of 800.
// ======================================================================

namespace ae::map_draw
{
    using namespace ae::chart::v3;

    namespace
    {
        constexpr double kRefSize = 800.0; // AD Pixels are absolute device px at this canvas size

        // ---- AD acmacs::BoundingBall, ported verbatim (bounding-ball.cc) ----
        struct BoundingBall
        {
            double cx{0.0}, cy{0.0}, diameter{0.0};

            BoundingBall(double min_x, double min_y, double max_x, double max_y)
                : cx{(min_x + max_x) / 2.0}, cy{(min_y + max_y) / 2.0}
            {
                const double vx = min_x - max_x, vy = min_y - max_y;
                diameter = std::sqrt(vx * vx + vy * vy);
            }

            void extend(double px, double py)
            {
                const double dx = px - cx, dy = py - cy;
                const double d2 = dx * dx + dy * dy;
                if (d2 > diameter * diameter * 0.25) {
                    const double dist = std::sqrt(d2);
                    diameter = diameter * 0.5 + dist;
                    const double difference = dist - diameter * 0.5;
                    cx = (diameter * 0.5 * cx + difference * px) / dist;
                    cy = (diameter * 0.5 * cy + difference * py) / dist;
                }
            }
        };

        // Resolve a mapi/plot colour string (already brace-stripped) to an ::Color.
        ::Color resolve_color(std::string_view src, ::Color fallback)
        {
            if (src.empty())
                return fallback;
            return ::Color{std::string{src}};
        }

        // Strip any "{...}" modifier suffix (e.g. "#FF0000{clade-pale}" -> "#FF0000").
        std::string strip_brace(std::string_view src)
        {
            if (const auto pos = src.find('{'); pos != std::string_view::npos)
                src = src.substr(0, pos);
            // trim trailing spaces
            while (!src.empty() && src.back() == ' ')
                src.remove_suffix(1);
            return std::string{src};
        }

        // ---- clade colouring rule extracted from a clades.mapi block ----
        struct CladeCond
        {
            std::string clade;
            bool negate; // '!' prefix => antigen must NOT have this clade
        };
        struct AaCond
        {
            size_t pos1;  // 1-based sequence position (e.g. 156)
            char aa;      // required amino acid (e.g. 'S'); uppercase
            bool negate;  // '!' prefix => must NOT be this aa
        };
        struct ColorRule
        {
            std::vector<CladeCond> conditions{}; // ALL must hold (single "clade" or "clade-all")
            std::vector<AaCond> aa_conditions{}; // ALL must hold (amino-acid selector); needs seqdb sequences
            bool require_sequenced{false};       // "sequenced": true — antigen must have a sequence
            std::string fill{};
            std::string outline{"black"};
            std::string legend_label{};
            bool applicable{true};      // reserved; all selectors are now reproducible after seqdb-populate
        };

        // Parse an amino-acid selector token like "156S" or "!122Q" into an AaCond.
        std::optional<AaCond> parse_aa_token(std::string_view tok)
        {
            bool negate = false;
            if (!tok.empty() && tok.front() == '!') {
                negate = true;
                tok.remove_prefix(1);
            }
            size_t i = 0;
            size_t pos = 0;
            for (; i < tok.size() && std::isdigit(static_cast<unsigned char>(tok[i])); ++i)
                pos = pos * 10 + static_cast<size_t>(tok[i] - '0');
            if (i == 0 || i >= tok.size())
                return std::nullopt;
            return AaCond{pos, static_cast<char>(std::toupper(static_cast<unsigned char>(tok[i]))), negate};
        }

        std::vector<ColorRule> parse_mapi(const std::filesystem::path& path, std::string_view key)
        {
            std::vector<ColorRule> rules;
            ae::simdjson::Parser parser{path};
            auto& doc = parser.doc();
            for (auto field : doc.get_object()) {
                const std::string_view fkey = field.unescaped_key();
                if (fkey != key)
                    continue;
                for (auto elt : field.value().get_array()) {
                    auto obj = elt.get_object();
                    ColorRule rule;
                    bool is_active_antigen = false;
                    for (auto member : obj) {
                        const std::string_view mkey = member.unescaped_key();
                        if (mkey == "N") {
                            std::string_view v;
                            if (!member.value().get_string().get(v) && v == "antigens")
                                is_active_antigen = true;
                        }
                        else if (mkey == "fill") {
                            std::string_view v;
                            if (!member.value().get_string().get(v))
                                rule.fill = strip_brace(v);
                        }
                        else if (mkey == "outline") {
                            std::string_view v;
                            if (!member.value().get_string().get(v))
                                rule.outline = strip_brace(v);
                        }
                        else if (mkey == "select") {
                            auto sel = member.value().get_object();
                            for (auto sfield : sel) {
                                const std::string_view skey = sfield.unescaped_key();
                                if (skey == "clade") {
                                    std::string_view v;
                                    if (!sfield.value().get_string().get(v)) {
                                        std::string_view cl{v};
                                        const bool neg = !cl.empty() && cl.front() == '!';
                                        rule.conditions.push_back({std::string{neg ? cl.substr(1) : cl}, neg});
                                    }
                                }
                                else if (skey == "clade-all" || skey == "clade_all") {
                                    // list of clade conditions (each may be '!'-negated); ALL must hold.
                                    for (auto ce : sfield.value().get_array()) {
                                        std::string_view v;
                                        if (!ce.get_string().get(v)) {
                                            std::string_view cl{v};
                                            const bool neg = !cl.empty() && cl.front() == '!';
                                            rule.conditions.push_back({std::string{neg ? cl.substr(1) : cl}, neg});
                                        }
                                    }
                                }
                                else if (skey == "amino-acid" || skey == "amino_acid") {
                                    // Per-residue selector, e.g. ["156S"]. After seqdb-populate the
                                    // antigen sequences are available, so evaluate these directly.
                                    for (auto ce : sfield.value().get_array()) {
                                        std::string_view v;
                                        if (!ce.get_string().get(v)) {
                                            if (const auto cond = parse_aa_token(v))
                                                rule.aa_conditions.push_back(*cond);
                                        }
                                    }
                                }
                                else if (skey == "sequenced") {
                                    bool seq = false;
                                    if (!sfield.value().get_bool().get(seq) && seq)
                                        rule.require_sequenced = true;
                                }
                            }
                        }
                        else if (mkey == "legend") {
                            auto leg = member.value().get_object();
                            for (auto lfield : leg) {
                                const std::string_view lkey = lfield.unescaped_key();
                                if (lkey == "label") {
                                    std::string_view v;
                                    if (!lfield.value().get_string().get(v))
                                        rule.legend_label = std::string{v};
                                }
                            }
                        }
                    }
                    if (is_active_antigen && !rule.fill.empty())
                        rules.push_back(std::move(rule));
                }
            }
            return rules;
        }

        // Replace "{count}" in a legend label with the actual count.
        std::string legend_text(std::string_view label, size_t count)
        {
            std::string out;
            for (size_t i = 0; i < label.size();) {
                if (label.substr(i, 7) == "{count}") {
                    out += fmt::format("{}", count);
                    i += 7;
                }
                else {
                    out += label[i];
                    ++i;
                }
            }
            return out;
        }

        // ---- vaccine strains, read at RUNTIME from acmacs-data semantic_vaccines.py ----
        // Returns the set of unique vaccine strain names (uppercased) for a subtype key.
        // No strain names are compiled into ae — they live only in the external data file.
        std::set<std::string> parse_vaccines(const std::filesystem::path& path, std::string_view subtype_key)
        {
            std::set<std::string> names;
            std::ifstream in{path};
            if (!in)
                return names;
            const std::string content{std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>()};
            const std::string marker = std::string{"\""} + std::string{subtype_key} + "\": org_table_to_dict(\"\"\"";
            auto start = content.find(marker);
            if (start == std::string::npos)
                return names;
            start += marker.size();
            const auto end = content.find("\"\"\"", start);
            const std::string block = content.substr(start, end == std::string::npos ? std::string::npos : end - start);
            std::istringstream ls{block};
            std::string line;
            bool header_seen = false;
            while (std::getline(ls, line)) {
                const auto l = line.find_first_not_of(" \t");
                if (l == std::string::npos || line[l] != '|')
                    continue;
                if (line.find_first_not_of(" \t|-+") == std::string::npos)
                    continue; // separator row (|---+---|)
                std::vector<std::string> cells;
                for (size_t i = line.find('|'); i != std::string::npos;) {
                    const size_t j = line.find('|', i + 1);
                    if (j == std::string::npos)
                        break;
                    std::string c = line.substr(i + 1, j - i - 1);
                    const auto a = c.find_first_not_of(" \t");
                    const auto b = c.find_last_not_of(" \t");
                    cells.push_back(a == std::string::npos ? std::string{} : c.substr(a, b - a + 1));
                    i = j;
                }
                if (cells.empty())
                    continue;
                if (!header_seen) {
                    std::string first = cells[0];
                    std::transform(first.begin(), first.end(), first.begin(), [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
                    if (first == "name") {
                        header_seen = true;
                        continue;
                    }
                }
                if (cells[0].empty())
                    continue;
                std::string up = cells[0];
                std::transform(up.begin(), up.end(), up.begin(), [](unsigned char ch) { return static_cast<char>(std::toupper(ch)); });
                names.insert(up);
            }
            return names;
        }

        // Map a coloring key (e.g. "clades-A(H3N2)-v1") to a semantic_vaccines.py subtype key.
        std::string vaccine_subtype_key(std::string_view coloring_key)
        {
            if (coloring_key.find("H3N2") != std::string_view::npos)
                return "A(H3N2)";
            if (coloring_key.find("H1N1") != std::string_view::npos)
                return "A(H1N1)";
            if (coloring_key.find("Yam") != std::string_view::npos)
                return "BY";
            if (coloring_key.find("Vic") != std::string_view::npos)
                return "BV";
            return {};
        }

        // Per-point resolved render state.
        struct PR
        {
            enum Shape { Circle, Box } shape{Circle};
            ::Color fill{TRANSPARENT};
            ::Color outline{0xD0D0D0};
            double outline_width{1.0}; // px @ 800
            double size{10.0};         // diameter/side px @ 800
            bool shown{true};
            long z{0};                 // draw order key (higher = on top)
            std::string label{};       // vaccine etc.
        };
    } // namespace

    // ----------------------------------------------------------------------

    void export_map(const Chart& chart_in, projection_index projection_no, const std::filesystem::path& output, const DrawSettings& settings)
    {
        // Populate sequences + clades from seqdb (AD's pipeline does this before drawing;
        // most chain-step .ace files carry NO clade attributes, so without this every point
        // renders grey). Work on a mutable copy so the caller's chart is untouched.
        Chart populated_chart;
        const Chart* chart_ptr = &chart_in;
        if (settings.populate_seqdb) {
            populated_chart = chart_in;
            try {
                populate_from_seqdb(populated_chart, false);
                chart_ptr = &populated_chart;
            }
            catch (const std::exception&) {
                // seqdb unavailable (e.g. SEQDB_V4 unset) — fall back to the chart's own attrs
                chart_ptr = &chart_in;
            }
        }
        const Chart& chart = *chart_ptr;

        if (chart.projections().empty())
            throw std::runtime_error{"cannot draw map: chart has no projections (optimize it first)"};
        if (projection_no >= chart.projections().size())
            throw std::runtime_error{"cannot draw map: projection index out of range"};

        const auto& projection = chart.projections()[projection_no];

        // Reorient to the master (AD chains make_map: chart.orient_to(master)) so framing
        // and orientation match the golden PNGs. procrustes(no scaling) gives the reoriented
        // layout directly (== AD setting the projection transformation and drawing it).
        Layout layout = projection.transformed_layout();
        if (settings.reorient_master) {
            const Chart master{*settings.reorient_master};
            if (!master.projections().empty()) {
                const common_antigens_sera_t common{master, chart, antigens_sera_match_level_t::strict};
                // Need >=1 common point for a meaningful alignment; procrustes on too few points
                // yields a degenerate/NaN transform, so fall back to the unoriented layout.
                if (common.common_antigens() + common.common_sera() >= 3) {
                    const auto pc = procrustes(master.projections()[projection_index{0}], projection, common, procrustes_scaling_t::no);
                    bool any_finite = false;
                    for (const auto pn : pc.secondary_transformed.number_of_points()) {
                        if (pc.secondary_transformed[pn].exists()) {
                            any_finite = true;
                            break;
                        }
                    }
                    if (any_finite)
                        layout = pc.secondary_transformed;
                }
            }
        }
        const auto n_antigens = chart.antigens().size().get();
        const auto n_points = layout.number_of_points().get();
        const double image_size = settings.image_size;
        const double px = image_size / kRefSize; // px scale for absolute sizes (=1 at 800)

        // --- viewport: minimum bounding ball, square, width ceil'd (AD) ---
        constexpr double inf = std::numeric_limits<double>::infinity();
        double min_x{inf}, min_y{inf}, max_x{-inf}, max_y{-inf};
        for (const auto point_no : layout.number_of_points()) {
            if (const auto c = layout[point_no]; c.exists()) {
                min_x = std::min(min_x, c[DIMX]);
                min_y = std::min(min_y, c[DIMY]);
                max_x = std::max(max_x, c[DIMX]);
                max_y = std::max(max_y, c[DIMY]);
            }
        }
        if (min_x > max_x)
            throw std::runtime_error{"cannot draw map: no points with coordinates"};

        BoundingBall bb{min_x, min_y, max_x, max_y};
        for (const auto point_no : layout.number_of_points()) {
            if (const auto c = layout[point_no]; c.exists())
                bb.extend(c[DIMX], c[DIMY]);
        }
        const double W = std::ceil(bb.diameter);
        const double origin_x = bb.cx - W / 2.0;
        const double origin_y = bb.cy - W / 2.0;
        const double scale = image_size / W;
        const auto dx = [=](double x) { return (x - origin_x) * scale; };
        const auto dy = [=](double y) { return (y - origin_y) * scale; }; // NO Y-flip (matches AD)

        ae::draw::CairoPdf surface{output, image_size, image_size};

        // --- stage: background (white viewport rect) ---
        surface.background(WHITE);

        // --- stage: grid (grey80 = #CCCCCC, 1px, spacing 1 map unit) ---
        // AD (acmacs draw-grid.cc / Surface::grid) draws lines at viewport-left + k*step, i.e.
        // at device positions k*scale measured from the left/top edge — NOT snapped to integer
        // map coordinates. Matching this places every grid line on the exact same device pixels
        // as the golden PNGs (otherwise the whole grid is offset by the origin's fractional part).
        {
            const ::Color grid{0xCCCCCC};
            for (double k = 1.0; k < W; k += 1.0) {
                const double d = k * scale;
                surface.line(d, 0.0, d, image_size, grid, 1.0 * px);
                surface.line(0.0, d, image_size, d, grid, 1.0 * px);
            }
        }

        // --- build per-point render state from chart_draw_reset defaults ---
        const auto reference = chart.reference();
        std::vector<PR> pr(n_points);
        for (size_t i = 0; i < n_points; ++i) {
            PR& p = pr[i];
            if (i >= n_antigens) { // serum
                p.shape = PR::Box;
                p.fill = TRANSPARENT;
                p.outline = ::Color{0xD0D0D0};
                p.size = 15.0;
                p.z = 0;
            }
            else if (reference.contains(antigen_index{i})) { // reference antigen: open circle
                p.shape = PR::Circle;
                p.fill = TRANSPARENT;
                p.outline = ::Color{0xD0D0D0};
                p.size = 15.0;
                p.z = 1;
            }
            else { // test antigen: filled grey circle
                p.shape = PR::Circle;
                p.fill = ::Color{0xD0D0D0};
                p.outline = ::Color{0xD0D0D0};
                p.size = 10.0;
                p.z = 2;
            }
            p.outline_width = 1.0;
        }

        long z_counter = 100; // raised points go above all base points

        // --- stage: clade colouring (chart_draw_modify mapi_key) ---
        struct LegendEntry { std::string fill, outline, label; };
        std::vector<LegendEntry> legend_entries;
        if (settings.mapi && settings.coloring_key) {
            const auto rules = parse_mapi(*settings.mapi, *settings.coloring_key);
            for (const auto& rule : rules) {
                if (rule.conditions.empty() && rule.aa_conditions.empty() && !rule.require_sequenced)
                    continue;
                const ::Color fill = resolve_color(rule.fill, TRANSPARENT);
                const ::Color outline = resolve_color(rule.outline, BLACK);
                size_t count = 0;
                for (size_t i = 0; i < n_antigens; ++i) {
                    const auto& ag = chart.antigens()[antigen_index{i}];
                    const auto& sem = ag.semantic();
                    bool match = true;
                    if (rule.require_sequenced && ag.aa().empty())
                        match = false;
                    for (const auto& cond : rule.conditions) {
                        if (match && sem.has_clade(cond.clade) == cond.negate) {
                            match = false;
                            break;
                        }
                    }
                    if (match && !rule.aa_conditions.empty()) {
                        const auto& seq = ag.aa();
                        for (const auto& ac : rule.aa_conditions) {
                            const char got = static_cast<char>(std::toupper(static_cast<unsigned char>(seq[ae::sequences::pos0_t{ac.pos1 - 1}])));
                            if ((got == ac.aa) == ac.negate) {
                                match = false;
                                break;
                            }
                        }
                    }
                    if (match) {
                        PR& p = pr[i];
                        p.fill = fill;
                        p.outline = outline;
                        p.z = ++z_counter;
                        ++count;
                    }
                }
                // Full legend: emit every clade row (incl. zero-count, in mapi order), matching
                // AD's legend which shows rows with show_if_none_selected.
                if (!rule.legend_label.empty())
                    legend_entries.push_back({rule.fill, rule.outline, legend_text(rule.legend_label, count)});
            }
        }

        // --- stage: mark_recent_layer (only if >2 layers) ---
        if (settings.mark_recent_layer) {
            const auto& titers = chart.titers();
            if (titers.number_of_layers().get() > 2) {
                const auto last_layer = layer_index{titers.number_of_layers().get() - 1};
                for (size_t i = 0; i < n_antigens; ++i) {
                    try {
                        const auto layers = titers.layers_with_antigen(antigen_index{i});
                        if (!layers.empty() && layers.back() == last_layer) {
                            pr[i].outline_width = 3.0;
                            pr[i].z = ++z_counter;
                        }
                    }
                    catch (const std::exception&) {}
                }
                for (size_t s = 0; s < chart.sera().size().get(); ++s) {
                    try {
                        const auto layers = titers.layers_with_serum(serum_index{s});
                        if (!layers.empty() && layers.back() == last_layer) {
                            PR& p = pr[n_antigens + s];
                            p.outline_width = 3.0;
                            p.outline = BLACK;
                            p.z = ++z_counter;
                        }
                    }
                    catch (const std::exception&) {}
                }
            }
        }

        // --- stage: mark_vaccines (blue d24 dots + "{location_abbreviated}/{year2}" labels) ---
        // AD chains make_map marks each subtype's vaccine strains. Strain list is read at
        // RUNTIME from acmacs-data/semantic_vaccines.py (never committed into ae).
        if (settings.mark_vaccines && settings.vaccines_file && settings.coloring_key) {
            const std::string subkey = vaccine_subtype_key(*settings.coloring_key);
            if (!subkey.empty()) {
                const auto vnames = parse_vaccines(*settings.vaccines_file, subkey);
                const auto& titers = chart.titers();
                const bool multilayer = titers.number_of_layers().get() > 1;
                for (const auto& vname : vnames) {
                    long best = -1;
                    int best_cell = -1;
                    size_t best_layers = 0;
                    for (size_t i = 0; i < n_antigens; ++i) {
                        const auto& ag = chart.antigens()[antigen_index{i}];
                        std::string nm{static_cast<std::string_view>(ag.name())};
                        const auto slash = nm.find('/');
                        std::string tail = slash == std::string::npos ? nm : nm.substr(slash + 1);
                        std::transform(tail.begin(), tail.end(), tail.begin(), [](unsigned char c) { return static_cast<char>(std::toupper(c)); });
                        if (tail != vname)
                            continue;
                        const int cellv = ag.passage().is_cell() ? 1 : 0;
                        size_t nl = 0;
                        if (multilayer) {
                            try { nl = titers.layers_with_antigen(antigen_index{i}).size(); } catch (const std::exception&) {}
                        }
                        // AD tie-break: prefer cell over egg, then more layers.
                        if (best < 0 || cellv > best_cell || (cellv == best_cell && nl > best_layers)) {
                            best = static_cast<long>(i);
                            best_cell = cellv;
                            best_layers = nl;
                        }
                    }
                    if (best < 0)
                        continue;
                    PR& p = pr[static_cast<size_t>(best)];
                    p.fill = ::Color{0x0000FF}; // blue
                    p.size = 24.0;
                    p.z = ++z_counter;
                    // label "{location_abbreviated}/{year2}" from the chosen antigen's name
                    std::string nm{static_cast<std::string_view>(chart.antigens()[antigen_index{static_cast<size_t>(best)}].name())};
                    std::vector<std::string> parts;
                    std::string cur;
                    for (const char c : nm) {
                        if (c == '/') { parts.push_back(cur); cur.clear(); }
                        else cur += c;
                    }
                    parts.push_back(cur);
                    const std::string loc = parts.size() > 1 ? parts[1] : std::string{};
                    const std::string year = parts.empty() ? std::string{} : parts.back();
                    const std::string yy = year.size() >= 2 ? year.substr(year.size() - 2) : year;
                    std::string abbr;
                    try { abbr = ae::locdb::get().abbreviation(loc); } catch (const std::exception&) {}
                    if (abbr.empty())
                        abbr = loc.substr(0, std::min<size_t>(2, loc.size()));
                    p.label = abbr + "/" + yy;
                }
            }
        }

        // --- optional serum circles (debug/extra; drawn under points) ---
        if (settings.draw_serum_circles) {
            const ::Color sc_color{0x000080};
            for (const auto& sc : serum_circles(chart, projection, serum_circle_fold{2.0})) {
                const double radius_au = sc.empirical().value_or(sc.theoretical().value_or(0.0));
                if (radius_au <= 0.0)
                    continue;
                const auto pt = point_index{n_antigens + sc.serum_no.get()};
                if (pt.get() >= n_points)
                    continue;
                if (const auto c = layout[pt]; c.exists())
                    surface.circle(dx(c[DIMX]), dy(c[DIMY]), radius_au * scale, sc_color, 1.5 * px, TRANSPARENT);
            }
        }

        // --- stage: points, in z order (stable by original index) ---
        std::vector<size_t> order(n_points);
        for (size_t i = 0; i < n_points; ++i)
            order[i] = i;
        std::stable_sort(order.begin(), order.end(), [&pr](size_t a, size_t b) { return pr[a].z < pr[b].z; });

        for (const size_t i : order) {
            const auto c = layout[point_index{i}];
            if (!c.exists() || !pr[i].shown)
                continue;
            const PR& p = pr[i];
            const double cx = dx(c[DIMX]), cy = dy(c[DIMY]);
            const double s = p.size * px;
            const double ow = p.outline_width * px;
            if (p.shape == PR::Box)
                surface.square(cx, cy, s, p.outline, ow, p.fill);
            else
                surface.circle(cx, cy, s / 2.0, p.outline, ow, p.fill);
        }

        // --- stage: vaccine labels (on top of points; AD default offset [0,1], size 12px) ---
        for (const size_t i : order) {
            if (pr[i].label.empty())
                continue;
            const auto c = layout[point_index{i}];
            if (!c.exists())
                continue;
            const double cx = dx(c[DIMX]), cy = dy(c[DIMY]);
            const double font = 12.0 * px;
            const auto [tw, th] = surface.text_size(pr[i].label, font);
            (void)th;
            // horizontally centred, top of text just below the dot (cy + point_size/2), as AD
            surface.text(cx - tw / 2.0, cy + (pr[i].size * px) / 2.0, pr[i].label, font, BLACK, false);
        }

        // --- stage: procrustes arrows (make_pc; black, line 1px, head ~5px wide/10px long) ---
        for (const auto& a : settings.arrows) {
            const double x0 = dx(a[0]), y0 = dy(a[1]), x1 = dx(a[2]), y1 = dy(a[3]);
            const double vx = x1 - x0, vy = y1 - y0;
            const double len = std::sqrt(vx * vx + vy * vy);
            if (len < 1e-6)
                continue;
            const double ux = vx / len, uy = vy / len;         // unit along arrow
            const double aw = 5.0 * px, al = 2.0 * aw;          // AD: width 5px, length 2x width
            const double bx = x1 - ux * al, by = y1 - uy * al;  // base centre of head
            surface.line(x0, y0, bx, by, BLACK, 1.0 * px);      // shaft to head base
            const double px_ = -uy, py_ = ux;                   // perpendicular
            surface.filled_triangle(x1, y1, bx + px_ * aw / 2.0, by + py_ * aw / 2.0, bx - px_ * aw / 2.0, by - py_ * aw / 2.0, BLACK);
        }

        // --- stage: labels (debug: --labels) ---
        if (settings.label_points) {
            const double font = 10.0 * px;
            for (const size_t i : order) {
                const auto c = layout[point_index{i}];
                if (!c.exists())
                    continue;
                const std::string name = i < n_antigens ? fmt::format("{}", chart.antigens()[antigen_index{i}].name())
                                                        : fmt::format("{}", chart.sera()[serum_index{i - n_antigens}].name());
                surface.text(dx(c[DIMX]), dy(c[DIMY]) - pr[i].size * px, name, font, BLACK, true);
            }
        }

        // --- stage: legend (bottom-right, offset [-10,-10]) ---
        // Ports AD map_elements::v1::LegendPointLabel::draw exactly: padding = text_size("O"),
        // box = {max_label_w + pad_w*3 + point_size, line_h*(n-1)*interline + line_h + pad_h*2},
        // marker centred at baseline - line_h/2, text baseline stepped by line_h*interline.
        if (settings.draw_legend && !legend_entries.empty()) {
            const double label_size = 12.0 * px, point_size = 8.0 * px, interline = 2.0;
            const auto [pad_w, pad_h] = surface.text_size("O", label_size);
            double text_w = 0.0, text_h = 0.0;
            for (const auto& e : legend_entries) {
                const auto [w, h] = surface.text_size(e.label, label_size);
                text_w = std::max(text_w, w);
                text_h = std::max(text_h, h);
            }
            const auto n = static_cast<double>(legend_entries.size());
            const double box_w = text_w + pad_w * 3.0 + point_size;
            const double box_h = text_h * (n - 1.0) * interline + text_h + pad_h * 2.0;
            const double box_x = image_size - 10.0 * px - box_w;
            const double box_y = image_size - 10.0 * px - box_h;
            surface.rectangle(box_x, box_y, box_w, box_h, WHITE, 0.0, WHITE);
            surface.rectangle(box_x, box_y, box_w, box_h, BLACK, 0.3 * px, TRANSPARENT);
            const double point_x = box_x + pad_w + point_size / 2.0;
            const double text_x = box_x + pad_w * 2.0 + point_size;
            const double pitch = text_h * interline;
            double baseline = box_y + pad_h + text_h; // AD: first row text baseline
            for (const auto& e : legend_entries) {
                surface.circle(point_x, baseline - text_h / 2.0, point_size / 2.0, resolve_color(strip_brace(e.outline), BLACK), 1.0 * px, resolve_color(strip_brace(e.fill), TRANSPARENT));
                // AD draws text at the baseline; ae text(center=false) places the glyph-box top,
                // so shift up by the glyph height to land the baseline at AD's position.
                surface.text(text_x, baseline - text_h, e.label, label_size, BLACK, false);
                baseline += pitch;
            }
        }

        // --- stage: title (top-left origin [10,10], 12px, black) ---
        if (settings.draw_title) {
            const double text_size = 12.0 * px, pad = 10.0 * px;
            const std::string title = settings.title_override.value_or(fmt::format("{:.4f}", projection.stress()));
            surface.text(pad, pad, title, text_size, BLACK, false);
        }

        // --- stage: border (LAST, on top of everything) ---
        // AD Border::draw strokes the viewport rectangle (device edge 0..size) with width
        // border_width*2 = 2px; the stroke is centred on the edge path so only ~1px shows
        // inside, matching the golden PNGs (which have a single black pixel at the edge).
        surface.rectangle(0.0, 0.0, image_size, image_size, BLACK, 2.0 * px, TRANSPARENT);
    }

    // ----------------------------------------------------------------------

    void export_procrustes(const Chart& primary, projection_index primary_projection, const Chart& secondary, projection_index secondary_projection,
                           const std::filesystem::path& output, const DrawSettings& settings)
    {
        // AD make_pc: draw the PRIMARY chart (its own layout, no reorient master) with clade
        // colouring, overlay arrows from each common point's primary position to its
        // secondary-transformed position (procrustes, no scaling, threshold 0.3), title
        // "RMS: {rms:.4f}".
        const auto& p_proj = primary.projections()[primary_projection];
        const auto& s_proj = secondary.projections()[secondary_projection];
        const common_antigens_sera_t common{primary, secondary, antigens_sera_match_level_t::automatic};
        const auto pc = procrustes(p_proj, s_proj, common, procrustes_scaling_t::no);

        const auto primary_layout = p_proj.transformed_layout();
        const auto& sec = pc.secondary_transformed;
        constexpr double threshold = 0.3;

        DrawSettings s = settings;
        s.reorient_master = std::nullopt; // pc frames on the primary's own layout
        s.title_override = fmt::format("RMS: {:.4f}", pc.rms);
        s.arrows.clear();
        for (const auto& pr : common.points()) {
            const auto pp = primary_layout[pr.first];
            const auto sp = sec[pr.second];
            if (!pp.exists() || !sp.exists())
                continue;
            const double d = std::sqrt((pp[DIMX] - sp[DIMX]) * (pp[DIMX] - sp[DIMX]) + (pp[DIMY] - sp[DIMY]) * (pp[DIMY] - sp[DIMY]));
            if (d > threshold)
                s.arrows.push_back({pp[DIMX], pp[DIMY], sp[DIMX], sp[DIMY]});
        }
        export_map(primary, primary_projection, output, s);
    }

} // namespace ae::map_draw

// ----------------------------------------------------------------------
