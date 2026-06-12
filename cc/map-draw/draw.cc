#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "ext/fmt.hh"
#include "map-draw/draw.hh"
#include "draw/cairo-surface.hh"
#include "ad/color.hh"
#include "chart/v3/chart.hh"
#include "chart/v3/serum-circles.hh"

// ----------------------------------------------------------------------

namespace ae::map_draw
{
    namespace
    {
        // Resolve a chart plot-spec color (ae::draw::v2::Color, a string like "green"
        // or "#ff0000") to an RGB ::Color, falling back when unset or unparseable.
        ::Color resolve_color(const ae::chart::v3::Color& color, ::Color fallback)
        {
            if (color.empty())
                return fallback;
            try {
                return ::Color{color.blocks().front()};
            }
            catch (const std::exception&) {
                return fallback;
            }
        }
    } // namespace

    void export_pdf(const ae::chart::v3::Chart& chart, ae::projection_index projection_no, const std::filesystem::path& output, double image_size, bool label_points, bool draw_serum_circles)
    {
        using namespace ae::chart::v3;

        if (chart.projections().empty())
            throw std::runtime_error{"cannot draw map: chart has no projections (optimize it first)"};
        if (projection_no >= chart.projections().size())
            throw std::runtime_error{"cannot draw map: projection index out of range"};

        const auto& projection = chart.projections()[projection_no];
        const auto layout = projection.transformed_layout();

        // Use the chart's plot spec, or synthesise the standard defaults (test antigen =
        // green filled circle, reference = open circle, serum = open box) when absent.
        legacy::PlotSpec plot_spec = chart.legacy_plot_spec();
        if (plot_spec.empty())
            plot_spec.initialize(chart.antigens().size(), chart.reference(), chart.sera().size());

        // --- bounding box over the points that have coordinates ---
        constexpr double inf = std::numeric_limits<double>::infinity();
        double min_x{inf}, min_y{inf}, max_x{-inf}, max_y{-inf};
        for (const auto point_no : layout.number_of_points()) {
            if (const auto coords = layout[point_no]; coords.exists()) {
                min_x = std::min(min_x, coords[DIMX]);
                min_y = std::min(min_y, coords[DIMY]);
                max_x = std::max(max_x, coords[DIMX]);
                max_y = std::max(max_y, coords[DIMY]);
            }
        }
        if (min_x > max_x)
            throw std::runtime_error{"cannot draw map: no points with coordinates"};

        // --- square viewport with padding; map chart coords -> device pixels ---
        const double world = std::max(max_x - min_x, max_y - min_y);
        const double padded = (world > 0.0 ? world : 1.0) * 1.1; // ~5% padding each side
        const double center_x = (min_x + max_x) / 2.0;
        const double center_y = (min_y + max_y) / 2.0;
        const double vp_min_x = center_x - padded / 2.0;
        const double vp_max_y = center_y + padded / 2.0;
        const double scale = image_size / padded;
        const auto to_device_x = [=](double x) { return (x - vp_min_x) * scale; };
        const auto to_device_y = [=](double y) { return (vp_max_y - y) * scale; }; // flip Y: chart y is up, PDF y is down

        // Plot-spec size is a multiplier (1.0 = standard). Scale the base point size and
        // line width with the image so a map looks the same at any resolution.
        const double base_radius = image_size / 200.0;
        const double line_scale = image_size / 800.0;

        ae::draw::CairoPdf pdf{output, image_size, image_size};
        pdf.background(WHITE);

        // --- background grid (1 antigenic-unit spacing) + viewport border (AD BackgroundBorderGrid) ---
        {
            const double vp_max_x = vp_min_x + padded;
            const double vp_min_y = vp_max_y - padded;
            const ::Color grid_color{0xCCCCCC};
            const double grid_width = line_scale;
            for (double gx = std::ceil(vp_min_x); gx <= vp_max_x; gx += 1.0)
                pdf.line(to_device_x(gx), 0.0, to_device_x(gx), image_size, grid_color, grid_width);
            for (double gy = std::ceil(vp_min_y); gy <= vp_max_y; gy += 1.0)
                pdf.line(0.0, to_device_y(gy), image_size, to_device_y(gy), grid_color, grid_width);
            const double bw = 1.5 * line_scale;
            const double b = bw / 2.0;
            pdf.line(b, b, image_size - b, b, BLACK, bw);                         // top
            pdf.line(image_size - b, b, image_size - b, image_size - b, BLACK, bw); // right
            pdf.line(image_size - b, image_size - b, b, image_size - b, BLACK, bw); // bottom
            pdf.line(b, image_size - b, b, b, BLACK, bw);                         // left
        }

        // --- serum circles (opt-in) drawn under the points ---
        if (draw_serum_circles) {
            const ::Color sc_color{0x000080}; // navy
            const double sc_width = 1.5 * line_scale;
            for (const auto& sc : serum_circles(chart, projection, serum_circle_fold{2.0})) {
                const double radius_au = sc.empirical().value_or(sc.theoretical().value_or(0.0));
                if (radius_au <= 0.0)
                    continue;
                const point_index pt = chart.antigens().size() + sc.serum_no;
                if (pt >= layout.number_of_points())
                    continue;
                if (const auto coords = layout[pt]; coords.exists())
                    pdf.circle(to_device_x(coords[DIMX]), to_device_y(coords[DIMY]), radius_au * scale, sc_color, sc_width, TRANSPARENT);
            }
        }

        const auto& styles = plot_spec.styles();
        const auto& style_for_point = plot_spec.style_for_point();
        const auto number_of_antigens = chart.antigens().size().get();

        const auto style_of = [&](point_index pn) {
            PointStyle style;
            if (const auto idx = pn.get(); idx < style_for_point.size() && style_for_point[idx] < styles.size())
                style = styles[style_for_point[idx]];
            return style;
        };
        const auto point_name = [&](point_index pn) -> std::string {
            const auto idx = pn.get();
            if (idx < number_of_antigens)
                return fmt::format("{}", chart.antigens()[to_antigen_index(pn)].name());
            return fmt::format("{}", chart.sera()[serum_index{idx - number_of_antigens}].name());
        };

        // Draw in the plot spec's order (typically sera, then reference, then test antigens
        // so test antigens land on top); otherwise fall back to point-index order.
        std::vector<point_index> order;
        if (!plot_spec.drawing_order().empty()) {
            for (const auto point_no : plot_spec.drawing_order())
                order.push_back(point_no);
        }
        else {
            for (const auto point_no : layout.number_of_points())
                order.push_back(point_no);
        }

        // --- points ---
        for (const auto point_no : order) {
            if (point_no >= layout.number_of_points())
                continue;
            const auto coords = layout[point_no];
            if (!coords.exists())
                continue;
            const auto style = style_of(point_no);
            if (!style.shown().value_or(true))
                continue;

            const double dx = to_device_x(coords[DIMX]);
            const double dy = to_device_y(coords[DIMY]);
            const double radius = base_radius * style.size().value_or(1.0);
            const ::Color fill = resolve_color(style.fill(), TRANSPARENT);
            const ::Color outline = resolve_color(style.outline(), BLACK);
            const double outline_width = style.outline_width().value_or(1.0) * line_scale;

            switch (style.shape().value_or(point_shape{point_shape::Circle}).get()) {
                case point_shape::Box:
                    pdf.square(dx, dy, radius * 2.0, outline, outline_width, fill);
                    break;
                case point_shape::Triangle:
                    pdf.triangle(dx, dy, radius, outline, outline_width, fill);
                    break;
                case point_shape::Circle:
                case point_shape::Egg:     // egg shapes approximated as circles
                case point_shape::UglyEgg:
                    pdf.circle(dx, dy, radius, outline, outline_width, fill);
                    break;
            }
        }

        // --- point labels (on top of all points), with basic collision avoidance ---
        // For each label, try its specified position first, then a ring of fallback
        // positions around the point, and pick the first that doesn't overlap a label
        // already placed. Greedy heuristic — not AD's force-directed layout, but it
        // markedly reduces overlap in dense regions.
        const double label_base_font = image_size / 55.0;
        std::vector<std::array<double, 4>> placed; // x0, y0, x1, y1 of placed label boxes
        const auto overlaps = [&placed](double x0, double y0, double x1, double y1) {
            constexpr double pad = 1.0;
            for (const auto& p : placed)
                if (!(x1 + pad <= p[0] || x0 - pad >= p[2] || y1 + pad <= p[1] || y0 - pad >= p[3]))
                    return true;
            return false;
        };
        for (const auto point_no : order) {
            if (point_no >= layout.number_of_points())
                continue;
            const auto coords = layout[point_no];
            if (!coords.exists())
                continue;
            const auto style = style_of(point_no);
            if (!style.shown().value_or(true))
                continue;

            const auto& lbl = style.label();
            std::string text;
            if (lbl.text.has_value() && !lbl.text->empty())
                text = *lbl.text;
            else if (label_points)
                text = point_name(point_no);
            if (text.empty())
                continue;

            const double radius = base_radius * style.size().value_or(1.0);
            const double font = label_base_font * (static_cast<double>(lbl.size) / 16.0);
            const auto [tw, th] = pdf.text_size(text, font);
            const double px = to_device_x(coords[DIMX]);
            const double py = to_device_y(coords[DIMY]);
            const double gap = font * 0.35;
            const double rx = radius + gap + tw / 2.0;
            const double ry = radius + gap + th / 2.0;

            // candidate box-centre offsets from the point; the label's own offset first
            const std::array<std::pair<double, double>, 9> candidates{{
                {static_cast<double>(lbl.offset.x) * font, radius + static_cast<double>(lbl.offset.y) * font},
                {0.0, ry}, {0.0, -ry}, {rx, 0.0}, {-rx, 0.0},
                {rx * 0.7, ry * 0.7}, {-rx * 0.7, ry * 0.7}, {rx * 0.7, -ry * 0.7}, {-rx * 0.7, -ry * 0.7},
            }};
            double cx = px + candidates[0].first, cy = py + candidates[0].second;
            for (const auto& [ox, oy] : candidates) {
                const double bx = px + ox, by = py + oy;
                if (!overlaps(bx - tw / 2.0, by - th / 2.0, bx + tw / 2.0, by + th / 2.0)) {
                    cx = bx;
                    cy = by;
                    break;
                }
            }
            placed.push_back({cx - tw / 2.0, cy - th / 2.0, cx + tw / 2.0, cy + th / 2.0});
            pdf.text(cx, cy, text, font, resolve_color(lbl.color, BLACK), /*center=*/true);
        }

        // --- title (chart name) at top centre ---
        if (const std::string title = chart.name(); !title.empty()) {
            const double title_font = image_size / 30.0;
            pdf.text(image_size / 2.0, title_font, title, title_font, BLACK, /*center=*/true);
        }
    }

} // namespace ae::map_draw

// ----------------------------------------------------------------------
