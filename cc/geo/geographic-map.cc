#include <algorithm>
#include <cmath>
#include <utility>
#include <vector>

#include "geo/geographic-map.hh"
#include "geo/geographic-path.hh"
#include "draw/cairo-surface.hh"
#include "ad/color.hh"

// ----------------------------------------------------------------------

namespace ae::geo
{
    void export_geographic_pdf(const std::filesystem::path& output, double image_width, const std::vector<GeoPoint>& points)
    {
        const auto [first, last] = geographic_map_path();

        // The path lives in the full geographic-bounds rectangle [0,W] x [0,H] (verified:
        // abs(x) spans [0, W], y spans up to H). Fit that whole rectangle to the canvas so
        // the path and the lon/lat points share one transform.
        const double W = geographic_map_size[0], H = geographic_map_size[1];
        const double margin = image_width * 0.02;
        const double scale = (image_width - 2.0 * margin) / W;
        const double image_height = H * scale + 2.0 * margin;
        const auto dev_x = [=](double px) { return px * scale + margin; };
        const auto dev_y = [=](double py) { return py * scale + margin; };

        // lon/lat -> path coords, equirectangular over geographic_map_bounds
        // (lon_min, lat_max, lon_max, lat_min).
        const double lon_min = geographic_map_bounds[0], lat_max = geographic_map_bounds[1];
        const double lon_max = geographic_map_bounds[2], lat_min = geographic_map_bounds[3];
        const auto lonlat_to_dev = [&](double lon, double lat) {
            const double px = (lon - lon_min) / (lon_max - lon_min) * W;
            const double py = (lat_max - lat) / (lat_max - lat_min) * H;
            return std::pair<double, double>{dev_x(px), dev_y(py)};
        };

        // Transform the path to device coords, preserving the negative-move sign convention.
        std::vector<double> dev;
        dev.reserve(static_cast<size_t>(last - first));
        for (const double* p = first; p + 1 < last; p += 2) {
            const double x = dev_x(std::abs(p[0]));
            dev.push_back(p[0] < 0.0 ? -x : x);
            dev.push_back(dev_y(p[1]));
        }

        const Color land{0xE8E8E8};  // light grey land fill
        const Color coast{0x808080}; // grey coastline
        const double coast_w = std::max(0.4, image_width / 2000.0);
        const double point_outline_w = std::max(0.5, image_width / 1500.0);

        ae::draw::CairoPdf pdf{output, image_width, image_height};
        pdf.background(WHITE);
        pdf.path_negative_move(dev.data(), dev.data() + dev.size(), coast, coast_w, land);

        for (const auto& pt : points) {
            const auto [x, y] = lonlat_to_dev(pt.lon, pt.lat);
            pdf.circle(x, y, pt.radius, pt.outline, point_outline_w, pt.fill);
        }
    }

} // namespace ae::geo

// ----------------------------------------------------------------------
