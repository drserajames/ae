#include <algorithm>
#include <limits>
#include <set>
#include <stdexcept>

#include "map-draw/draw.hh"
#include "draw/cairo-surface.hh"
#include "chart/v3/chart.hh"

// ----------------------------------------------------------------------

namespace ae::map_draw
{
    void export_pdf(const ae::chart::v3::Chart& chart, ae::projection_index projection_no, const std::filesystem::path& output, double image_size)
    {
        using namespace ae::chart::v3;

        if (chart.projections().empty())
            throw std::runtime_error{"cannot draw map: chart has no projections (optimize it first)"};
        if (projection_no >= chart.projections().size())
            throw std::runtime_error{"cannot draw map: projection index out of range"};

        const auto layout = chart.projections()[projection_no].transformed_layout();

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

        // --- reference antigens draw as open circles; test antigens are filled ---
        std::set<size_t> reference;
        for (const auto ag_no : chart.reference())
            reference.insert(ag_no.get());
        const auto number_of_antigens = chart.antigens().size().get();

        // Default styling, mirroring AD defaults. Real per-point plot-spec styling is M2 (see TODO.md).
        constexpr double outline_width = 1.0;
        constexpr double test_antigen_radius = 5.0;
        constexpr double reference_antigen_radius = 7.0;
        constexpr double serum_side = 11.0;

        ae::draw::CairoPdf pdf{output, image_size, image_size};
        pdf.background(WHITE);

        for (const auto point_no : layout.number_of_points()) {
            const auto coords = layout[point_no];
            if (!coords.exists())
                continue;
            const double dx = to_device_x(coords[DIMX]);
            const double dy = to_device_y(coords[DIMY]);
            if (const auto idx = point_no.get(); idx < number_of_antigens) {
                if (reference.contains(idx))
                    pdf.circle(dx, dy, reference_antigen_radius, BLACK, outline_width, TRANSPARENT);
                else
                    pdf.circle(dx, dy, test_antigen_radius, BLACK, outline_width, GREEN);
            }
            else {
                pdf.square(dx, dy, serum_side, BLACK, outline_width, TRANSPARENT);
            }
        }
    }

} // namespace ae::map_draw

// ----------------------------------------------------------------------
