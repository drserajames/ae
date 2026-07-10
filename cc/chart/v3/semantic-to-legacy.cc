#include <limits>
#include <regex>
#include <string>
#include <variant>
#include <vector>

#include "chart/v3/chart.hh"
#include "chart/v3/styles.hh"
#include "chart/v3/legacy-plot-spec.hh"
#include "chart/v3/point-style.hh"
#include "chart/v3/point-shape.hh"
#include "chart/v3/semantic.hh"
#include "chart/v3/layout.hh"
#include "utils/collection.hh"

// ======================================================================
// P2 — native semantic->legacy plot-spec bake (Chart::semantic_style_to_legacy).
//
// Reproduces kateri's `plotSpecLegacy().setFrom(currentPlotSpec)`
// (kateri lib/src/plot_spec.dart PlotSpecLegacy.setFrom + PlotSpecSemantic): resolve the
// named c["R"] style to a concrete per-point spec (kateri PlotSpecSemantic.activate/apply),
// then collapse the per-point specs to a unique palette + per-point index list, written into
// the legacy plot spec (c["p"] = {"d": drawing order, "p": per-point palette index,
// "P": unique specs}).
//
// The per-point resolution mirrors the (validated) native map renderer
// cc/map-draw/styled-draw.cc, but tracks colours as kateri's ColorAndModifier (base colour
// STRING + optional deferred :pale) rather than resolving them to RGB — because kateri's
// legacy `F`/`O` fields carry the colour string (`fill.toString()`), NOT a paled hex.
//
// Not baked (absent from the report's clades-v10 legacy style, so lossless there): serum
// circles and serum coverage (they restyle sera / split antigens by fold); these live only
// on the serum-coverage / multiple-circles addendum styles, which do not drive the legacy
// plot-spec bake.
// ======================================================================

namespace ae::chart::v3
{
    using namespace ae::chart::v3::semantic;

    namespace
    {
        // ---- kateri ColorAndModifier (lib/src/color.dart): a base colour string plus an
        // optional deferred ":pale" modifier. `:bright` clears the modifier (keeps colour),
        // `:pale` sets it, a plain colour string replaces the colour and clears the modifier.
        struct ColorMod
        {
            std::string color{};
            bool pale{false};

            bool operator==(const ColorMod&) const = default;

            void modify(std::string_view s)
            {
                if (s.empty())
                    return;
                if (s[0] == ':') {
                    if (s == ":bright")
                        pale = false;
                    else if (s == ":pale")
                        pale = true;
                    // unknown modifier: kateri warns + ignores
                }
                else {
                    color = std::string{s};
                    pale = false;
                }
            }

            // kateri ColorAndModifier.toString: "$_color:$_modifier" (the modifier keeps its
            // leading colon, so a paled colour serializes as e.g. "#e72f27::pale").
            std::string to_string() const { return pale ? color + ":" + ":pale" : color; }
        };

        // ---- dynamic::value helpers (mirror cc/map-draw/styled-draw.cc) ----
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

        // kateri Antigen.withinDateRange (chart.dart): a "!D": [first, last] range test.
        bool within_date_range(std::string_view date, std::string_view first, std::string_view last)
        {
            if (date.empty())
                return first.empty();
            return (first.empty() || first <= date) && (last.empty() || last > date);
        }

        // kateri semanticMatch (chart.dart): one selector key/value vs the point's attributes.
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

        // kateri PlotSpec.selectPoints::match — "!i" (per-side index), "!D" (antigen date
        // range) and semantic keys. An empty / non-object selector matches every candidate.
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

        // ---- resolved per-point spec (kateri PointPlotSpec): the identity used for palette
        // dedup. Mirrors kateri's operator== (shown, size, shape, fill, outline, outline
        // width, rotation, aspect, label). Serum circle / coverage are not baked (see header).
        struct PPS
        {
            bool shown{true};
            double size{20.0}; // kateri sizePixels
            point_shape::Shape shape{point_shape::Circle};
            ColorMod fill{"transparent", false};
            ColorMod outline{"black", false};
            double outline_width{1.0};
            double rotation{0.0};
            double aspect{1.0};
            ae::draw::v2::point_label label{};

            bool operator==(const PPS&) const = default;
        };

        // Walk a front style, recursively expanding {R:<name>} references into a flat modifier
        // list (kateri applyEntry parent recursion). Undefined references are tolerated.
        void resolve(const Styles& styles, const std::string& name, std::vector<const StyleModifier*>& out, int depth)
        {
            if (depth > 10)
                return;
            const Style* st = styles.find_if_exists(name);
            if (st == nullptr)
                return;
            for (const auto& m : st->modifiers) {
                if (!m.parent.empty())
                    resolve(styles, m.parent, out, depth + 1);
                else
                    out.push_back(&m);
            }
        }

    } // namespace

    // ----------------------------------------------------------------------

    void Chart::semantic_style_to_legacy(std::string_view style_name)
    {
        const size_t n_antigens = antigens().size().get();
        const size_t n_sera = sera().size().get();
        const size_t n_points = n_antigens + n_sera;

        const auto sem_of = [&](size_t i) -> const SemanticAttributes& {
            if (i < n_antigens)
                return antigens()[antigen_index{i}].semantic();
            return sera()[serum_index{i - n_antigens}].semantic();
        };

        // kateri _AntigenSerum.isEgg (chart.dart): prefer the semantic "p" attribute ("e"=egg),
        // else a regex on the RAW passage string — matches an "E"/"EGG" segment followed by an
        // optional number then " (" or end-of-string, e.g. the trailing "E1" in "E3/E6/E1/SPE1".
        // ae's passage().is_egg() parses some NIID passages (e.g. "SPE3/SPE1") differently, so we
        // reproduce kateri's literal regex here for byte-exact shape fidelity to its bake.
        static const std::regex egg_rx{R"((?:E(?:GG)?)[0-9X?]*( \(|$))"};
        const auto is_egg = [](const auto& agsr) -> bool {
            const ae::dynamic::value& p = agsr.semantic().get("p");
            if (!p.is_null())
                return p.as_string_or_empty() == std::string_view{"e"};
            const std::string passage = agsr.passage().to_string();
            return std::regex_search(passage, egg_rx);
        };

        // ---- reference antigens (kateri Chart.referenceAntigens): an antigen is "reference"
        //      iff some serum shares its NAME (name only, ignoring annotations / reassortant /
        //      passage). NB this differs from Chart::reference(), which also requires matching
        //      annotations — kateri's looser name-only rule is what the default point spec uses.
        // A point is "reference" (transparent fill, refSize) only if its name matches a serum
        // AND it has coordinates: kateri seeds ddoReferenceAntigens = referenceAntigens().where
        // (hasCoord) and makeDefaultPointSpecs classifies by ddoReferenceAntigens membership, so
        // a disconnected (no-coord) reference strain falls back to the test-antigen default.
        const bool have_projection = !projections().empty();
        const Layout layout = have_projection ? projections()[projection_index{0}].layout() : Layout{};
        const auto has_coord = [&](size_t i) -> bool { return !have_projection || layout[point_index{i}].exists(); };

        std::vector<bool> is_reference(n_antigens, false);
        for (size_t i = 0; i < n_antigens; ++i) {
            if (!has_coord(i))
                continue;
            const auto& ag_name = antigens()[antigen_index{i}].name();
            for (const auto sr_no : sera().size()) {
                if (sera()[sr_no].name() == ag_name) {
                    is_reference[i] = true;
                    break;
                }
            }
        }

        // ---- default per-point spec (kateri PlotSpecSemantic.activate: gray80 default) ----
        constexpr double kTestSize = 20.0, kRefSize = 32.0; // kateri PointPlotSpec.testSize/refSize
        constexpr double kRotReassortant = 0.5;             // kateri rotationReassortant
        std::vector<PPS> pr(n_points);
        for (size_t i = 0; i < n_antigens; ++i) {
            PPS& p = pr[i];
            const auto& ag = antigens()[antigen_index{i}];
            const bool is_ref = is_reference[i];
            const bool reassortant = !ag.reassortant().empty();
            const bool egg = is_egg(ag);
            p.fill = is_ref ? ColorMod{"transparent", false} : ColorMod{"gray80", false};
            p.outline = ColorMod{"gray80", false};
            p.size = is_ref ? kRefSize : kTestSize;
            p.shape = (reassortant || egg) ? point_shape::Egg : point_shape::Circle;
            if (reassortant)
                p.rotation = kRotReassortant;
        }
        for (size_t i = n_antigens; i < n_points; ++i) {
            PPS& p = pr[i];
            const auto& sr = sera()[serum_index{i - n_antigens}];
            const bool reassortant = !sr.reassortant().empty();
            const bool egg = is_egg(sr);
            p.fill = ColorMod{"transparent", false};
            p.outline = ColorMod{"gray80", false};
            p.size = kRefSize;
            p.shape = (reassortant || egg) ? point_shape::UglyEgg : point_shape::Box;
            if (reassortant)
                p.rotation = kRotReassortant;
        }

        // ---- default draw order (kateri makeDefaultDrawingOrder, coord-filtered): sera, then
        //      reference antigens, then test antigens. ----
        std::vector<size_t> order;
        for (size_t i = n_antigens; i < n_points; ++i)
            if (has_coord(i))
                order.push_back(i);
        for (size_t i = 0; i < n_antigens; ++i)
            if (is_reference[i] && has_coord(i))
                order.push_back(i);
        for (size_t i = 0; i < n_antigens; ++i)
            if (!is_reference[i] && has_coord(i))
                order.push_back(i);

        // ---- resolve the front style into a flat modifier list ----
        std::vector<const StyleModifier*> modifiers;
        resolve(styles(), std::string{style_name}, modifiers, 0);

        // ---- apply modifiers in flat order (kateri applyEntry point modification) ----
        for (const StyleModifier* mp : modifiers) {
            const StyleModifier& m = *mp;
            size_t cand_begin = 0, cand_end = n_points;
            if (m.select_antigens_sera == SelectAntigensSera::antigens_only) {
                cand_begin = 0;
                cand_end = n_antigens;
            }
            else if (m.select_antigens_sera == SelectAntigensSera::sera_only) {
                cand_begin = n_antigens;
                cand_end = n_points;
            }

            std::vector<size_t> matched;
            for (size_t i = cand_begin; i < cand_end; ++i) {
                const bool is_ag = i < n_antigens;
                const long agsr = is_ag ? static_cast<long>(i) : static_cast<long>(i - n_antigens);
                const std::string_view date = is_ag ? static_cast<std::string_view>(antigens()[antigen_index{i}].date()) : std::string_view{};
                if (point_matches(m.selector, sem_of(i), agsr, date, is_ag))
                    matched.push_back(i);
            }

            const PointStyle& ms = m.point_style;
            for (const size_t i : matched) {
                PPS& p = pr[i];
                if (const Color f = ms.fill(); !f.empty())
                    p.fill.modify(f.blocks()[0]);
                if (const Color o = ms.outline(); !o.empty())
                    p.outline.modify(o.blocks()[0]);
                if (ms.outline_width().has_value())
                    p.outline_width = *ms.outline_width();
                if (ms.size().has_value())
                    p.size = *ms.size(); // semantic-modifier size is absolute px
                if (ms.shape().has_value())
                    p.shape = ms.shape()->get();
                if (ms.rotation().has_value())
                    p.rotation = static_cast<double>(*ms.rotation());
                if (ms.aspect().has_value())
                    p.aspect = static_cast<double>(*ms.aspect());
                if (ms.shown().has_value())
                    p.shown = *ms.shown();
                if (const ae::draw::v2::point_label dflt{}; ms.label() != dflt)
                    p.label = ms.label();
            }

            // drawing order raise / lower (kateri raiseLowerPoints)
            if (m.order != DrawingOrderModifier::no_change && !matched.empty()) {
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
                if (m.order == DrawingOrderModifier::raise) {
                    order.insert(order.end(), kept.begin(), kept.end());
                    order.insert(order.end(), moved.begin(), moved.end());
                }
                else {
                    order.insert(order.end(), moved.begin(), moved.end());
                    order.insert(order.end(), kept.begin(), kept.end());
                }
            }
        }

        // ---- collapse per-point specs to a unique palette + per-point index (kateri setFrom) ----
        legacy::PlotSpec& ps = legacy_plot_spec();
        ps.styles().clear();
        ps.style_for_point().clear();
        ps.drawing_order().get().clear();

        std::vector<PPS> unique_specs;
        for (size_t point_no = 0; point_no < n_points; ++point_no) {
            const PPS& p = pr[point_no];
            size_t matching = unique_specs.size();
            for (size_t si = 0; si < unique_specs.size(); ++si) {
                if (unique_specs[si] == p) {
                    matching = si;
                    break;
                }
            }
            if (matching == unique_specs.size())
                unique_specs.push_back(p);
            ps.style_for_point().push_back(matching);
        }

        // build the unique-spec palette (kateri setFrom field-omission rules)
        for (const PPS& p : unique_specs) {
            PointStyle out;
            if (!p.shown)
                out.shown(false);
            if (!(p.fill.color == "transparent" && !p.fill.pale)) // kateri: fill != transparent
                out.fill(Color{p.fill.to_string()});
            if (!(p.outline.color == "black" && !p.outline.pale)) // kateri: outline != black
                out.outline(Color{p.outline.to_string()});
            if (p.outline_width != 1.0)
                out.outline_width(p.outline_width);
            if (p.shape != point_shape::Circle)
                out.shape(point_shape{p.shape});
            if (p.size != 10.0) // kateri: sizePixels != 10 -> s = sizePixels / 5
                out.size(p.size / 5.0);
            if (p.rotation != 0.0)
                out.rotation(ae::draw::v2::Rotation{p.rotation});
            if (p.aspect != 1.0)
                out.aspect(ae::draw::v2::Aspect{p.aspect});
            // kateri setFrom does NOT export the label into the legacy palette
            ps.styles().push_back(std::move(out));
        }

        auto& dord = ps.drawing_order().get();
        for (const size_t i : order)
            dord.push_back(point_index{i});
    }

} // namespace ae::chart::v3

// ----------------------------------------------------------------------
