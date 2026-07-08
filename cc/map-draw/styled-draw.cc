#include <algorithm>
#include <cmath>
#include <limits>
#include <optional>
#include <string>
#include <variant>
#include <vector>

#include "ext/fmt.hh"
#include "map-draw/draw.hh"
#include "draw/cairo-surface.hh"
#include "ad/color.hh"
#include "ad/color-hsv.hh"
#include "chart/v3/chart.hh"
#include "chart/v3/styles.hh"
#include "chart/v3/legacy-plot-spec.hh"
#include "chart/v3/layout.hh"

// ======================================================================
// P2 milestone A — headless native render of a chart's on-chart *semantic* styling
// (c["R"] named styles + c["p"] base plot-spec), mirroring kateri's set_style + get_pdf
// for the report by-clade maps. Implements the §1.2 resolver and the §2.2 viewport
// transform+recenter+viewport chain in C++, then draws via cc/draw/cairo-surface.
//
// Viewport chain (the key fidelity step, derived from kateri lib/src/viewport.dart
// roundAndRecenter + lib/src/socket-events.dart get_viewport, and confirmed by
// py/ae/report/chart_modifier.py::export_mapi_for_signature_pages):
//   * transformed layout = projection.transformed_layout() (stored 2x2 transform applied,
//     NO Y-flip — post-transform Y is already screen-down).
//   * kateri computes a native viewport = axis-aligned hull of the transformed layout,
//     then roundAndRecenter: roundedSize = ceil(hull_extent + 1) per axis, and it shifts
//     every point by adjust = roundedSize/2 - hull_centre so the native frame becomes
//     [0,0,roundedSize]. The style's stored viewport V=[x,y,w,h] (the "-reset" family) is
//     the "used" viewport expressed in this recentered space.
//   * Since we draw in the (non-recentered) transformed space directly, the equivalent
//     absolute viewport is  origin = V.origin - adjust = -roundedSize/2 + V.origin +
//     hull_centre,  size = V.size.  This equals the export_mapi_for_signature_pages
//     recovery  (-native/2 + used + native_center).
//
// Point sizes / outline widths / font sizes are absolute device pixels (kateri "sizePixels",
// independent of canvas width: sizePixels * pixelSize * canvasScale == sizePixels). Base
// plot-spec sizes carry kateri's x5 (_sizeScale); semantic-modifier `s`/`o` are used as-is.
// ======================================================================

namespace ae::map_draw
{
    using namespace ae::chart::v3;

    namespace
    {
        constexpr double kSizeScale = 5.0;      // kateri PlotSpecLegacy._sizeScale (base plot-spec sizes)

        // ---- colour model (kateri lib/src/color.dart ColorAndModifier) ----
        // A style colour is a base colour string plus an optional deferred modifier. The
        // report uses two modifiers: ":pale" (desaturate + lighten) and ":bright" (clear the
        // pale modifier, keeping the base colour). Milestone E tracks the (base, pale) pair
        // per point exactly like kateri, so a ":pale" background (e.g. -pale on the serology
        // map) really pales the clade colours and a subsequent ":bright" (vaccine/serology
        // highlight) brings them back to full colour.
        enum class ColorAction { keep, set, pale, bright };
        struct ParsedColor
        {
            ColorAction action{ColorAction::keep};
            ::Color color{TRANSPARENT}; // valid only when action == set
        };

        ParsedColor parse_color(const ae::draw::v2::Color& c)
        {
            if (c.empty())
                return {};
            const std::string& s = c.blocks()[0];
            if (s.empty())
                return {};
            if (s[0] == ':') {
                if (s == ":pale")
                    return {ColorAction::pale, {}};
                if (s == ":bright")
                    return {ColorAction::bright, {}};
                return {}; // unknown modifier: keep current colour (kateri warns + ignores)
            }
            if (s == "T" || s == "transparent")
                return {ColorAction::set, TRANSPARENT};
            return {ColorAction::set, ::Color{std::string_view{s}}};
        }

        // kateri ColorAndModifier.color for the ":pale" modifier (pale factor 0.4).
        ::Color pale_color(::Color base)
        {
            constexpr double pale_factor = 0.4;
            acmacs::color::HSV hsv{base};
            if (hsv.s > 0.0) {
                hsv.s = hsv.s * pale_factor;
                hsv.v = hsv.v + (1.0 - hsv.v) * (1.0 - pale_factor);
            }
            else { // grey / black / white (saturation 0): lighten value only
                double val = hsv.v / pale_factor;
                if (val > 1.0)
                    val = 1.0;
                else if (hsv.v == 0.0)
                    val = 0.5; // black -> mid grey
                hsv.v = val;
            }
            const uint32_t alpha = base.raw_value() & 0xFF000000u; // preserve transparency byte
            return ::Color{alpha | (hsv.rgb() & 0x00FFFFFFu)};
        }

        // Apply a parsed colour to a (base, pale) pair (kateri ColorAndModifier.modify).
        void apply_color(const ParsedColor& pc, ::Color& color, bool& pale)
        {
            switch (pc.action) {
                case ColorAction::keep:
                    break;
                case ColorAction::set:
                    color = pc.color;
                    pale = false;
                    break;
                case ColorAction::bright:
                    pale = false; // clear pale modifier, base colour unchanged
                    break;
                case ColorAction::pale:
                    pale = true;
                    break;
            }
        }

        // Concrete colour for a legend row / title (no deferred modifier): ":pale"/":bright"
        // fall back to the given default.
        ::Color concrete_color(const ae::draw::v2::Color& c, ::Color fallback)
        {
            const ParsedColor pc = parse_color(c);
            return pc.action == ColorAction::set ? pc.color : fallback;
        }

        // ---- dynamic::value helpers (selectors + semantic attribute matching) ----
        bool value_is_bool(const ae::dynamic::value& v) { return std::holds_alternative<bool>(v.data()); }
        bool value_as_bool(const ae::dynamic::value& v) { return std::get<bool>(v.data()); }

        long value_as_long(const ae::dynamic::value& v)
        {
            return std::visit(
                []<typename T>(const T& c) -> long {
                    if constexpr (std::is_same_v<T, long>)
                        return c;
                    else if constexpr (std::is_same_v<T, double>)
                        return static_cast<long>(c);
                    else
                        return -1;
                },
                v.data());
        }

        // A resolved per-point render state.
        struct PR
        {
            ::Color fill{TRANSPARENT};
            bool fill_pale{false};
            ::Color outline{BLACK};
            bool outline_pale{false};
            double outline_width{1.0};
            double size{10.0};                 // device px (diameter / box side)
            point_shape::Shape shape{point_shape::Circle};
            bool shown{true};
            bool has_label{false};
            double label_dx{0.0}, label_dy{1.0};
            double label_size{20.0};
            std::string label_text{};
        };

        struct LegendRowR
        {
            int priority{0};
            std::string text{};
            ::Color fill{TRANSPARENT};
            ::Color outline{BLACK};
            point_shape::Shape shape{point_shape::Circle};
            size_t count{0};
        };

        // Resolution accumulator (§1.2): flat modifier list, viewport, merged legend, title.
        struct Resolved
        {
            std::vector<const semantic::StyleModifier*> modifiers{};
            std::optional<ae::draw::v2::Viewport> viewport{};
            semantic::Legend legend{};
            semantic::Title title{};
            bool title_set{false};
        };

        void merge_legend(semantic::Legend& into, const semantic::Legend& from)
        {
            if (from.shown.has_value()) into.shown = from.shown;
            if (from.add_counter.has_value()) into.add_counter = from.add_counter;
            if (from.point_size.has_value()) into.point_size = from.point_size;
            if (from.show_rows_with_zero_count.has_value()) into.show_rows_with_zero_count = from.show_rows_with_zero_count;
            if (from.box.has_value()) into.box = from.box;
            if (from.row_style.has_value()) into.row_style = from.row_style;
            if (from.title.has_value()) into.title = from.title;
        }

        // Walk a front style, recursively expanding {R:<name>} references into a flat modifier
        // list (§1.2). Undefined references are tolerated. Viewport is last-writer-wins across
        // the traversal; legend fields merge; title comes from the front (depth 0) style.
        void resolve(const semantic::Styles& styles, const std::string& name, Resolved& out, int depth)
        {
            const semantic::Style* st = styles.find_if_exists(name);
            if (st == nullptr)
                return; // tolerate undefined ref (e.g. "-new-1" on a chart with no previous)
            if (st->viewport.has_value())
                out.viewport = st->viewport;
            merge_legend(out.legend, st->legend);
            if (depth == 0) {
                out.title = st->plot_title;
                out.title_set = true;
            }
            for (const auto& m : st->modifiers) {
                if (!m.parent.empty())
                    resolve(styles, m.parent, out, depth + 1);
                else
                    out.modifiers.push_back(&m);
            }
        }

        // kateri Antigen.withinDateRange (chart.dart): a "!D": [first, last] range test.
        bool within_date_range(std::string_view date, std::string_view first, std::string_view last)
        {
            if (date.empty())
                return first.empty(); // dateless antigen is "at the beginning of all dates"
            return (first.empty() || first <= date) && (last.empty() || last > date);
        }

        // kateri semanticMatch (chart.dart): one selector key/value vs the point's attributes.
        //   * a bool selector value is a *presence* test (attr present == value);
        //   * otherwise a missing attribute never matches;
        //   * a list-valued attribute (clades "C") matches if it contains the value;
        //   * otherwise scalar equality.
        bool semantic_match(std::string_view key, const ae::dynamic::value& selval, const SemanticAttributes& sem)
        {
            const ae::dynamic::value& attr = sem.get(key);
            if (value_is_bool(selval))
                return value_as_bool(selval) == !attr.is_null();
            if (attr.is_null())
                return false;
            if (const auto* arr = std::get_if<ae::dynamic::array>(&attr.data())) { // clades list: contains
                for (const auto& el : arr->data()) {
                    if (el == selval)
                        return true;
                }
                return false;
            }
            return attr == selval;
        }

        // Match a whole selector object against one point (kateri PlotSpec.selectPoints::match):
        // handles "!i" (per-side index), "!D" (antigen date range), and semantic keys. An empty
        // (or non-object) selector matches every candidate.
        bool point_matches(const ae::dynamic::value& selector, const SemanticAttributes& sem, long agsr_no, std::string_view date, bool is_antigen)
        {
            const auto* obj = std::get_if<ae::dynamic::object>(&selector.data());
            if (obj == nullptr)
                return true;
            for (const auto& [key, val] : obj->data()) {
                if (key == "!i") {
                    if (agsr_no != value_as_long(val))
                        return false;
                }
                else if (key == "!D") {
                    if (!is_antigen)
                        return false;
                    std::string_view first{}, last{};
                    if (const auto* arr = std::get_if<ae::dynamic::array>(&val.data())) {
                        const auto& d = arr->data();
                        if (d.size() >= 1)
                            first = d[0].as_string_or_empty();
                        if (d.size() >= 2)
                            last = d[1].as_string_or_empty();
                    }
                    if (!within_date_range(date, first, last))
                        return false;
                }
                else if (!semantic_match(key, val, sem))
                    return false;
            }
            return true;
        }

    } // namespace

    // ----------------------------------------------------------------------

    void export_styled_map(const Chart& chart, projection_index projection_no, std::string_view style_name, double width, const std::filesystem::path& output)
    {
        if (chart.projections().empty())
            throw std::runtime_error{"cannot draw styled map: chart has no projections"};
        if (projection_no >= chart.projections().size())
            throw std::runtime_error{"cannot draw styled map: projection index out of range"};

        const auto& projection = chart.projections()[projection_no];
        const Layout layout = projection.transformed_layout();

        const size_t n_antigens = chart.antigens().size().get();
        const size_t n_sera = chart.sera().size().get();
        const size_t n_points = layout.number_of_points().get();

        // ---- semantic accessor per point ----
        const auto sem_of = [&](size_t i) -> const SemanticAttributes& {
            if (i < n_antigens)
                return chart.antigens()[antigen_index{i}].semantic();
            return chart.sera()[serum_index{i - n_antigens}].semantic();
        };

        // ---- base per-point render state from c["p"] legacy plot spec ----
        const auto& base = chart.legacy_plot_spec();
        std::vector<PR> pr(n_points);
        {
            const auto& styles = base.style_for_point();
            const auto& pstyles = base.styles();
            for (size_t i = 0; i < n_points; ++i) {
                PR& p = pr[i];
                if (i < styles.size() && styles[i] < pstyles.size()) {
                    const PointStyle& bs = pstyles[styles[i]];
                    apply_color(parse_color(bs.fill()), p.fill, p.fill_pale);        // kateri base default fill "transparent"
                    apply_color(parse_color(bs.outline()), p.outline, p.outline_pale); // kateri base default outline "black"
                    p.outline_width = bs.outline_width().value_or(1.0);
                    p.size = bs.size().value_or(1.0) * kSizeScale;   // base plot-spec sizes carry x5
                    if (bs.shape().has_value())
                        p.shape = bs.shape()->get();
                    p.shown = bs.shown().value_or(true);
                }
            }
        }

        // ---- draw order from c["p"]["d"] (fallback: natural order) ----
        std::vector<size_t> order;
        for (const auto pt : base.drawing_order())
            order.push_back(pt.get());
        if (order.empty()) {
            for (size_t i = 0; i < n_points; ++i)
                order.push_back(i);
        }

        // ---- resolve the front style (§1.2) ----
        Resolved resolved;
        resolve(chart.styles(), std::string{style_name}, resolved, 0);

        std::vector<LegendRowR> legend_rows;

        // ---- apply modifiers in flat order ----
        for (const semantic::StyleModifier* mp : resolved.modifiers) {
            const semantic::StyleModifier& m = *mp;
            // candidate range by antigens/sera select
            size_t cand_begin = 0, cand_end = n_points;
            if (m.select_antigens_sera == semantic::SelectAntigensSera::antigens_only) {
                cand_begin = 0;
                cand_end = n_antigens;
            }
            else if (m.select_antigens_sera == semantic::SelectAntigensSera::sera_only) {
                cand_begin = n_antigens;
                cand_end = n_points;
            }

            std::vector<size_t> matched;
            for (size_t i = cand_begin; i < cand_end; ++i) {
                const bool is_ag = i < n_antigens;
                const long agsr = is_ag ? static_cast<long>(i) : static_cast<long>(i - n_antigens);
                const std::string_view date = is_ag ? static_cast<std::string_view>(chart.antigens()[antigen_index{i}].date()) : std::string_view{};
                if (point_matches(m.selector, sem_of(i), agsr, date, is_ag))
                    matched.push_back(i);
            }

            // apply point-style fields (colours track the kateri (base, pale) pair)
            const PointStyle& ms = m.point_style;
            for (const size_t i : matched) {
                PR& p = pr[i];
                apply_color(parse_color(ms.fill()), p.fill, p.fill_pale);
                apply_color(parse_color(ms.outline()), p.outline, p.outline_pale);
                if (ms.outline_width().has_value())
                    p.outline_width = *ms.outline_width();
                if (ms.size().has_value())
                    p.size = *ms.size(); // semantic-modifier size is absolute px (no x5)
                if (ms.shape().has_value())
                    p.shape = ms.shape()->get();
                if (ms.shown().has_value())
                    p.shown = *ms.shown();
                if (ms.label().text.has_value() && !ms.label().text->empty()) {
                    p.has_label = true;
                    p.label_text = *ms.label().text;
                    p.label_dx = ms.label().offset.x;
                    p.label_dy = ms.label().offset.y;
                    p.label_size = ms.label().size;
                }
            }

            // drawing order raise / lower
            if (m.order != semantic::DrawingOrderModifier::no_change && !matched.empty()) {
                std::vector<bool> is_matched(n_points, false);
                for (const size_t i : matched)
                    if (i < n_points)
                        is_matched[i] = true;
                std::vector<size_t> kept, moved;
                for (const size_t i : order) {
                    if (is_matched[i])
                        moved.push_back(i);
                    else
                        kept.push_back(i);
                }
                order.clear();
                if (m.order == semantic::DrawingOrderModifier::raise) { // matched go on top (drawn last)
                    order.insert(order.end(), kept.begin(), kept.end());
                    order.insert(order.end(), moved.begin(), moved.end());
                }
                else { // lower: matched go to the bottom (drawn first)
                    order.insert(order.end(), moved.begin(), moved.end());
                    order.insert(order.end(), kept.begin(), kept.end());
                }
            }

            // legend row
            if (!m.legend.text.empty() || m.legend.priority != 0) {
                LegendRowR row;
                row.priority = m.legend.priority;
                row.text = m.legend.text;
                row.fill = concrete_color(ms.fill(), TRANSPARENT);
                row.outline = concrete_color(ms.outline(), BLACK);
                if (ms.shape().has_value())
                    row.shape = ms.shape()->get();
                row.count = matched.size();
                legend_rows.push_back(std::move(row));
            }
        }

        // ---- viewport chain (§2.2) ----
        constexpr double inf = std::numeric_limits<double>::infinity();
        double min_x{inf}, min_y{inf}, max_x{-inf}, max_y{-inf};
        for (const auto pn : layout.number_of_points()) {
            if (const auto c = layout[pn]; c.exists()) {
                min_x = std::min(min_x, c[DIMX]);
                min_y = std::min(min_y, c[DIMY]);
                max_x = std::max(max_x, c[DIMX]);
                max_y = std::max(max_y, c[DIMY]);
            }
        }
        if (min_x > max_x)
            throw std::runtime_error{"cannot draw styled map: no points with coordinates"};
        const double centre_x = (min_x + max_x) / 2.0;
        const double centre_y = (min_y + max_y) / 2.0;
        const double rounded_x = std::ceil(max_x - min_x + 1.0);
        const double rounded_y = std::ceil(max_y - min_y + 1.0);

        double vp_x, vp_y, vp_w, vp_h;
        if (resolved.viewport.has_value()) {
            const auto& V = *resolved.viewport;
            vp_w = V.width;
            vp_h = V.height;
            vp_x = -rounded_x / 2.0 + static_cast<double>(V.x) + centre_x;
            vp_y = -rounded_y / 2.0 + static_cast<double>(V.y) + centre_y;
        }
        else { // no style viewport => kateri's native (recentered) frame
            vp_w = rounded_x;
            vp_h = rounded_y;
            vp_x = centre_x - rounded_x / 2.0;
            vp_y = centre_y - rounded_y / 2.0;
        }

        const double image_w = width;
        const double image_h = width * vp_h / vp_w;
        const auto dev_x = [=](double x) { return (x - vp_x) / vp_w * image_w; };
        const auto dev_y = [=](double y) { return (y - vp_y) / vp_h * image_h; }; // NO Y-flip

        ae::draw::CairoPdf surface{output, image_w, image_h};
        surface.background(WHITE);

        // ---- grid (kateri grid: colour #CCCCCC as rendered in the golden, 1px, step 1 map unit
        //      from vp origin; draw_on.dart's abstract default 0xCCCCCC, matched to the golden) ----
        {
            const ::Color grid{0xCCCCCC};
            const double step_x = image_w / vp_w;
            const double step_y = image_h / vp_h;
            for (double gx = 0.0; gx <= image_w + 0.5; gx += step_x)
                surface.line(gx, 0.0, gx, image_h, grid, 1.0);
            for (double gy = 0.0; gy <= image_h + 0.5; gy += step_y)
                surface.line(0.0, gy, image_w, gy, grid, 1.0);
        }

        // ---- points (draw order: first = bottom) ----
        const auto draw_point = [&](size_t i) {
            const auto c = layout[point_index{i}];
            if (!c.exists() || !pr[i].shown)
                return;
            const PR& p = pr[i];
            const double cx = dev_x(c[DIMX]), cy = dev_y(c[DIMY]);
            const double s = p.size;
            const double ow = p.outline_width;
            const ::Color fill = p.fill_pale ? pale_color(p.fill) : p.fill;       // deferred ":pale" (kateri)
            const ::Color outline = p.outline_pale ? pale_color(p.outline) : p.outline;
            switch (p.shape) {
                case point_shape::Box:
                    surface.square(cx, cy, s, outline, ow, fill);
                    break;
                case point_shape::Triangle:
                    surface.triangle(cx, cy, s / 2.0, outline, ow, fill);
                    break;
                case point_shape::Egg:
                case point_shape::UglyEgg:
                    surface.egg(cx, cy, s, outline, ow, fill);
                    break;
                case point_shape::Circle:
                default:
                    surface.circle(cx, cy, s / 2.0, outline, ow, fill);
                    break;
            }
        };
        for (const size_t i : order)
            draw_point(i);

        // ---- point labels (on top of points) ----
        for (const size_t i : order) {
            if (!pr[i].has_label)
                continue;
            const auto c = layout[point_index{i}];
            if (!c.exists())
                continue;
            const PR& p = pr[i];
            const double cx = dev_x(c[DIMX]), cy = dev_y(c[DIMY]);
            const auto [tw, th] = surface.text_size(p.label_text, p.label_size, true);
            const double point_r = (p.size + p.outline_width) / 2.0; // device px (kateri pointSize)
            // kateri addPointLabel::labelOffset (draw_on.dart), in device px; baseline-left anchor.
            const auto lab_off = [point_r](double off, double extent, bool vertical) -> double {
                if (off >= 1.0)
                    return point_r * off + (vertical ? extent : 0.0);
                if (off > -1.0)
                    return point_r * off + (vertical ? extent * (off + 1.0) / 2.0 : extent * (off - 1.0) / 2.0);
                return point_r * off - (vertical ? 0.0 : extent);
            };
            const double lx = cx + lab_off(p.label_dx, tw, false);
            const double ly = cy + lab_off(p.label_dy, th, true);
            surface.text_font(lx, ly, p.label_text, p.label_size, BLACK, false, false);
        }

        // ---- legend (kateri _Defaults.legend: bottom-left "Bl", offset (10,-10), white box,
        //      black 1px border, padding v5/h10; point size + row text/interline from -clades) ----
        const bool legend_shown = resolved.legend.shown.value_or(true) && !legend_rows.empty();
        if (legend_shown) {
            std::sort(legend_rows.begin(), legend_rows.end(), [](const LegendRowR& a, const LegendRowR& b) { return a.priority < b.priority; });
            const bool add_counter = resolved.legend.add_counter.value_or(false);
            const double point_size = resolved.legend.point_size.value_or(20.0);
            double text_size = 20.0, interline = 0.3;
            if (resolved.legend.row_style.has_value()) {
                if (resolved.legend.row_style->font_size.has_value())
                    text_size = *resolved.legend.row_style->font_size;
                if (resolved.legend.row_style->interline.has_value())
                    interline = *resolved.legend.row_style->interline;
            }
            const double pad_l = 10.0, pad_r = 10.0, pad_t = 5.0, pad_b = 5.0;
            const double point_space = point_size * (interline + 1.2);
            const double count_left_pad = add_counter ? text_size * 1.0 : 0.0;

            double max_text_w = 0.0, row_h = 0.0, max_count_w = 0.0;
            for (const auto& r : legend_rows) {
                const auto [w, h] = surface.text_size(r.text, text_size, true);
                max_text_w = std::max(max_text_w, w);
                row_h = std::max(row_h, h);
                if (add_counter) {
                    const auto [cw, ch] = surface.text_size(fmt::format("{}", r.count), text_size, true);
                    (void)ch;
                    max_count_w = std::max(max_count_w, cw);
                }
            }
            const double n = static_cast<double>(legend_rows.size());
            const double box_w = max_text_w + point_space + count_left_pad + max_count_w + pad_l + pad_r;
            const double box_h = row_h + row_h * (n - 1.0) * (interline + 1.0) + row_h * 0.4 + pad_t + pad_b;
            const double box_x = 0.0 + 10.0;                       // vp.left device (=0) + offset.dx (10 px)
            const double box_y = image_h - 10.0 - box_h;           // vp.bottom device (=image_h) + offset.dy(-10) - height
            surface.rectangle(box_x, box_y, box_w, box_h, BLACK, 1.0, WHITE);

            const double dx = box_x + pad_l;
            double baseline = box_y + pad_t + row_h; // kateri: box.origin.dy + textSize[0].height + padding.top
            for (const auto& r : legend_rows) {
                surface.circle(dx + point_size / 2.0, baseline - row_h * 0.35, point_size / 2.0, r.outline, 1.0, r.fill);
                surface.text_font(dx + point_space, baseline, r.text, text_size, BLACK, false, false);
                if (add_counter) {
                    const auto [cw, ch] = surface.text_size(fmt::format("{}", r.count), text_size, true);
                    (void)ch;
                    surface.text_font(dx + point_space + max_text_w + count_left_pad + max_count_w - cw, baseline, fmt::format("{}", r.count), text_size, BLACK, false, false);
                }
                baseline += row_h * (interline + 1.0);
            }
        }

        // ---- title (kateri _Defaults.title "tl", offset from box O; helvetica bold/normal) ----
        // The "info-" front styles carry a whitespace-only title (" ") — a deliberate blank
        // title (§1.2); skip drawing it entirely so nothing is rendered.
        const auto title_is_blank = [](std::string_view s) { return s.find_first_not_of(" \t") == std::string_view::npos; };
        if (resolved.title_set && resolved.title.shown.value_or(true) && resolved.title.text.text.has_value() && !title_is_blank(*resolved.title.text.text)) {
            const auto& t = resolved.title;
            double off_x = 30.0, off_y = 30.0; // kateri title default offset
            if (t.box.has_value() && t.box->offset.has_value()) {
                off_x = (*t.box->offset)[0];
                off_y = (*t.box->offset)[1];
            }
            const double font = t.text.font_size.value_or(28.0);
            const bool bold = t.text.font_weight.value_or("normal") == "bold";
            const bool italic = t.text.font_slant.value_or("normal") == "italic";
            ::Color col = BLACK;
            if (t.text.color.has_value())
                col = ::Color{static_cast<std::string_view>(*t.text.color)};
            // origin "tl": box top-left at device (off_x, off_y); kateri draws the baseline at
            // box.origin.dy + textHeight + padding.top (padding 0). Baseline-left anchor.
            const auto [ttw, tth] = surface.text_size(*t.text.text, font, true);
            (void)ttw;
            surface.text_font(off_x, off_y + tth, *t.text.text, font, col, bold, italic);
        }
    }

} // namespace ae::map_draw

// ----------------------------------------------------------------------
