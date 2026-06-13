#include <algorithm>
#include <cmath>
#include <limits>
#include <vector>

#include "geo/geographic-map.hh"
#include "geo/geographic-path.hh"
#include "draw/cairo-surface.hh"
#include "ad/color.hh"

// ----------------------------------------------------------------------

namespace ae::geo
{
    void export_geographic_pdf(const std::filesystem::path& output, double image_width)
    {
        const auto [first, last] = geographic_map_path();

        // Bounding box over the path. Negative x entries are move markers, so use abs(x).
        constexpr double inf = std::numeric_limits<double>::infinity();
        double min_x{inf}, min_y{inf}, max_x{-inf}, max_y{-inf};
        for (const double* p = first; p + 1 < last; p += 2) {
            const double x = std::abs(p[0]), y = p[1];
            min_x = std::min(min_x, x);
            max_x = std::max(max_x, x);
            min_y = std::min(min_y, y);
            max_y = std::max(max_y, y);
        }
        const double bbox_w = max_x - min_x, bbox_h = max_y - min_y;

        const double margin = image_width * 0.02;
        const double scale = (image_width - 2.0 * margin) / bbox_w;
        const double image_height = bbox_h * scale + 2.0 * margin;

        // Map path coords -> device, preserving the negative-move sign convention.
        // (The path y already runs north→south top-to-bottom, matching PDF's y-down.)
        std::vector<double> dev;
        dev.reserve(static_cast<size_t>(last - first));
        for (const double* p = first; p + 1 < last; p += 2) {
            const double ax = std::abs(p[0]);
            const double dx = (ax - min_x) * scale + margin;
            const double dy = (p[1] - min_y) * scale + margin;
            dev.push_back(p[0] < 0.0 ? -dx : dx);
            dev.push_back(dy);
        }

        const ::Color land{0xE8E8E8};  // light grey land fill
        const ::Color coast{0x808080}; // grey coastline
        const double coast_w = std::max(0.4, image_width / 2000.0);

        ae::draw::CairoPdf pdf{output, image_width, image_height};
        pdf.background(WHITE);
        pdf.path_negative_move(dev.data(), dev.data() + dev.size(), coast, coast_w, land);
    }

} // namespace ae::geo

// ----------------------------------------------------------------------
