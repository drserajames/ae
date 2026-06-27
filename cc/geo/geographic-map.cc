#include <algorithm>
#include <cmath>
#include <cstdint>
#include <numbers>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

#include "geo/geographic-map.hh"
#include "geo/geographic-path.hh"
#include "draw/cairo-surface.hh"
#include "ad/color.hh"

// ----------------------------------------------------------------------

namespace ae::geo
{
    Color continent_color(std::string_view continent)
    {
        // Ported from AD acmacs-base/color-continent.cc (primary palette).
        static const std::unordered_map<std::string_view, uint32_t> colors{
            {"EUROPE", 0x00FF00},          {"CENTRAL-AMERICA", 0xAAF9FF}, {"MIDDLE-EAST", 0x8000FF},
            {"NORTH-AMERICA", 0x00008B},   {"AFRICA", 0xFF8000},          {"ASIA", 0xFF0000},
            {"RUSSIA", 0xB03060},          {"AUSTRALIA-OCEANIA", 0xFF69B4}, {"SOUTH-AMERICA", 0x40E0D0},
            {"ANTARCTICA", 0x808080},      {"CHINA-SOUTH", 0xFF0000},     {"CHINA-NORTH", 0x6495ED},
            {"CHINA-UNKNOWN", 0x808080},   {"UNKNOWN", 0x808080},
        };
        if (const auto found = colors.find(continent); found != colors.end())
            return Color{found->second};
        return Color{0x808080}; // grey fallback
    }

    Color clade_color(std::string_view category)
    {
        if (category.empty() || category == "unknown" || category == "UNKNOWN")
            return Color{0x808080};
        // A fixed, distinctive palette (Tableau-10 style) assigned deterministically by name
        // hash so the same clade/lineage always gets the same colour across maps. The caller
        // may still override a category's colour explicitly.
        static const uint32_t palette[] = {
            0x1F77B4, 0xFF7F0E, 0x2CA02C, 0xD62728, 0x9467BD, 0x8C564B,
            0xE377C2, 0x7F7F7F, 0xBCBD22, 0x17BECF, 0xAEC7E8, 0xFFBB78,
            0x98DF8A, 0xFF9896, 0xC5B0D5, 0xC49C94, 0xF7B6D2, 0xC7C7C7,
        };
        constexpr size_t n = sizeof(palette) / sizeof(palette[0]);
        size_t h = 2166136261u; // FNV-1a, stable across runs
        for (const char c : category) {
            h ^= static_cast<unsigned char>(c);
            h *= 16777619u;
        }
        return Color{palette[h % n]};
    }

    void export_geographic_pdf(const std::filesystem::path& output, double image_width, const std::vector<GeoPoint>& points, const std::string& title,
                               const std::vector<LegendEntry>& legend)
    {
        const auto [first, last] = geographic_map_path();

        // The path lives in the full geographic-bounds rectangle [0,W] x [0,H] (verified:
        // abs(x) spans [0, W], y spans up to H). Fit that whole rectangle to the canvas so
        // the path and the lon/lat points share one transform.
        const double W = geographic_map_size[0], H = geographic_map_size[1];
        // AD `geographic-draw` fills the frame edge-to-edge (no white border): the map is the
        // full 2:1 page (width:height = W:H). The title/legend get a small independent inset
        // (~10pt at width 800; AD's title sits ~10pt from the top-left), not a map margin.
        const double scale = image_width / W;
        const double image_height = H * scale;
        const double inset = image_width * 0.0125;
        const auto dev_x = [=](double px) { return px * scale; };
        const auto dev_y = [=](double py) { return py * scale; };

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

        const Color land{WHITE};     // white land fill (AD look: white map, grey coastlines)
        const Color coast{0x808080}; // grey coastline
        const double coast_w = std::max(0.4, image_width / 2000.0);
        const double point_outline_w = std::max(0.5, image_width / 1500.0);

        ae::draw::CairoPdf pdf{output, image_width, image_height};
        pdf.background(WHITE);
        pdf.path_negative_move(dev.data(), dev.data() + dev.size(), coast, coast_w, land);

        for (const auto& pt : points) {
            const auto [x, y] = lonlat_to_dev(pt.lon, pt.lat);
            const double pt_outline_w = pt.outline_width >= 0.0 ? pt.outline_width : point_outline_w;
            if (pt.wedges.empty()) {
                pdf.circle(x, y, pt.radius, pt.outline, pt_outline_w, pt.fill);
            }
            else {
                double total = 0.0;
                for (const auto& w : pt.wedges)
                    total += w.count;
                if (total <= 0.0) // degenerate -> fall back to a dot
                    pdf.circle(x, y, pt.radius, pt.outline, point_outline_w, pt.fill);
                else {
                    constexpr double two_pi = 2.0 * std::numbers::pi;
                    double angle = 0.0;
                    for (const auto& w : pt.wedges) {
                        if (w.count <= 0.0)
                            continue;
                        const double next = angle + (w.count / total) * two_pi;
                        pdf.sector(x, y, pt.radius, angle, next, pt.outline, point_outline_w, w.color);
                        angle = next;
                    }
                }
            }
        }

        if (!title.empty()) {
            const double title_font = image_width / 40.0;
            pdf.text(inset, inset, title, title_font, Color{0}, /*center=*/false); // top-left, as in AD
        }

        // Legend: a small stack of colour swatches + labels in the lower-left corner.
        if (!legend.empty()) {
            const double font = std::max(7.0, image_width / 90.0);
            const double swatch = font;
            const double row_h = font * 1.4;
            const double pad = font * 0.6;
            double max_label_w = 0.0;
            for (const auto& e : legend)
                max_label_w = std::max(max_label_w, pdf.text_size(e.label, font).first);
            const double box_w = pad * 2.0 + swatch + pad + max_label_w;
            const double box_h = pad * 2.0 + row_h * static_cast<double>(legend.size());
            const double box_x = inset;
            const double box_y = image_height - inset - box_h;
            pdf.rectangle(box_x, box_y, box_w, box_h, Color{0x808080}, 0.5, Color{0xFFFFFF});
            double ry = box_y + pad;
            for (const auto& e : legend) {
                pdf.rectangle(box_x + pad, ry, swatch, swatch, Color{0}, 0.4, e.color);
                pdf.text(box_x + pad + swatch + pad, ry, e.label, font, Color{0}, /*center=*/false);
                ry += row_h;
            }
        }
    }

} // namespace ae::geo

// ----------------------------------------------------------------------
