#pragma once

#include <vector>
#include <list>
#include <array>
#include <string>
#include <optional>

#include "utils/float.hh"
#include "utils/log.hh"
#include "utils/named-type.hh"
#include "utils/collection.hh"
#include "draw/v2/viewport.hh"
#include "chart/v3/point-style.hh"
#include "chart/v3/index.hh"

// ----------------------------------------------------------------------

namespace ae::chart::v3::legacy
{
    class PlotSpec;
}

namespace ae::chart::v3::semantic
{
    enum class DrawingOrderModifier { no_change, raise, lower };
    enum class SelectAntigensSera { all, antigens_only, sera_only };

    using Selector = ae::dynamic::value; // object

    struct LegendRow
    {
        int priority{0};
        std::string text{};
    };

    using padding_t = std::array<std::optional<double>, 4>;
    using offset_t = std::array<double, 2>;
    using color_t = named_string_t<std::string, struct color_tag>;

    struct box_t
    {
        std::optional<std::string> origin{}; // :box-rel: in ace-format.org
        std::optional<padding_t> padding{};
        std::optional<offset_t> offset{};
        std::optional<color_t> border_color{};
        std::optional<double> border_width{};
        std::optional<color_t> background_color{};

        bool operator==(const box_t&) const = default;
        void set_origin(std::string_view value);
        void set_padding(double value) { padding = padding_t{value, value, value, value}; }
    };

    struct text_t
    {
        std::optional<std::string> text{};
        std::optional<std::string> font_face{};
        std::optional<std::string> font_weight{};
        std::optional<std::string> font_slant{};
        std::optional<double> font_size{};
        std::optional<color_t> color{};
        std::optional<double> interline{};

        bool operator==(const text_t&) const = default;
        void set_font_face(std::string_view value);
        void set_font_weight(std::string_view value);
        void set_font_slant(std::string_view value);
    };

    struct point_style_fow_t
    {
        std::string outline{"blue"};                       // outline color
        std::string fill{"transparent"};                   // fill color
        double outline_width{1.0};                         // outline width
    };

    struct serum_circle_style_t : public point_style_fow_t
    {
        double fold{2.0};
        bool theoretical{false};                           // false: draw empirical (if available), true: draw theoretical
        bool fallback{true};                               // draw fallback if radius is not available
        long dash{0};                                      // dash
        std::optional<std::pair<double, double>> angles{}; // angles for radius lines
        std::optional<std::string> radius_outline{};
        std::optional<double> radius_outline_width{};
        std::optional<long> radius_dash{};
    };

    struct serum_coverage_style_t
    {
        double fold{2.0};
        point_style_fow_t within{};
        point_style_fow_t outside{};
    };

    // ----------------------------------------------------------------------

    struct Title
    {
        std::optional<bool> shown;
        std::optional<box_t> box;
        text_t text;

        bool operator==(const Title&) const = default;
    };

    // ----------------------------------------------------------------------

    struct Legend
    {
        std::optional<bool> shown;
        std::optional<bool> add_counter{};
        std::optional<double> point_size{};
        std::optional<bool> show_rows_with_zero_count;
        std::optional<box_t> box;
        std::optional<text_t> row_style; // style of text in a legend row
        std::optional<text_t> title;

        bool operator==(const Legend&) const = default;
    };

    inline bool is_default(const Legend& legend) { return legend == Legend{}; }

    // ----------------------------------------------------------------------

    // A figure drawn on the map on top of the points: the selection polygon of AD's
    // `slot.path(outline=...)`, or a procrustes arrow (AD's `chart_draw.procrustes_arrows`).
    //
    // Vertices are in the projection's LAYOUT (untransformed) coordinate space -- the space
    // `Projection::layout()` and `ae.adjust.Figure` use, NOT the transformed/drawing space.
    // The renderer applies the projection transformation to them exactly as it applies it to
    // the points, so a figure stays glued to the map through a re-orientation, and the polygon
    // that is drawn is literally the polygon that made the selection.
    struct PathElement
    {
        std::vector<offset_t> vertices{};    // {x, y} pairs, layout coordinates
        std::string outline{"black"};        // outline color ("transparent" -> no outline)
        std::string fill{"transparent"};     // fill color
        double outline_width{1.0};
        bool close{true};                    // close the outline back to vertex 0 (AD's Figure close)
        // Arrow head at the LAST vertex (AD's ArrowPlotSpec). width <= 0 -> no head.
        double arrow_width{0.0};
        std::string arrow_fill{};            // empty -> same as outline
        std::string arrow_outline{};         // empty -> same as outline
        double arrow_outline_width{1.0};

        bool operator==(const PathElement&) const = default;
    };

    // ----------------------------------------------------------------------

    struct StyleModifier
    {
        std::string parent{};
        Selector selector{};
        SelectAntigensSera select_antigens_sera{SelectAntigensSera::all};
        PointStyle point_style{};
        DrawingOrderModifier order{DrawingOrderModifier::no_change};
        LegendRow legend{};
        std::optional<serum_circle_style_t> serum_circle{};
        std::optional<serum_coverage_style_t> serum_coverage{};
    };

    struct Style
    {
        std::string name{};
        std::string title{};
        int priority{0};
        std::optional<ae::draw::v2::Viewport> viewport{};
        std::vector<StyleModifier> modifiers{};
        std::vector<PathElement> paths{};
        Legend legend{};
        Title plot_title{};

        Style() = default;
        Style(std::string_view a_name) : name{a_name} {}

        // void export_to(legacy::PlotSpec& plot_spec) const;
    };

    class Styles
    {
      public:
        bool empty() const { return styles_.empty(); }
        size_t size() const { return styles_.size(); }
        auto begin() { return styles_.begin(); }
        auto end() { return styles_.end(); }
        auto begin() const { return styles_.begin(); }
        auto end() const { return styles_.end(); }
        void clear() { styles_.clear(); }

        // Update modifier selectors after point removal: value-based selectors
        // (e.g. {"C": "135K"}) are left unchanged, index-based selectors ({"!i": no})
        // are renumbered to match the surviving points, or dropped if the point
        // they refer to was itself removed. Style-level priority/legend/viewport
        // are untouched.
        void remove_points(const point_indexes& points);

        // find or add style by name
        Style& find(std::string_view name);
        const Style* find_if_exists(std::string_view name) const;
        // void find_and_export_to(std::string_view name, legacy::PlotSpec& plot_spec) const;

      private:
        // reference to style can be kept by python program and then
        // new style added. If vector<> is used, relocation of
        // existing style object may happen and reference in python
        // may become invalid. do not use vector<> here!
        std::list<Style> styles_{};
    };
} // namespace ae::chart::v3::semantic

// ----------------------------------------------------------------------
