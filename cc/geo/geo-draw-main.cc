#include <filesystem>
#include <string>
#include <string_view>
#include <vector>

#include "ext/fmt.hh"
#include "geo/geographic-map.hh"
#include "locdb/v3/locdb.hh"

// ----------------------------------------------------------------------

// Parse "lon,lat" into a GeoPoint (red dot). Returns false on malformed input.
// (std::stod, not std::from_chars — the floating-point from_chars overload is
// unavailable in Apple Clang's libc++.)
static bool parse_point(std::string_view spec, ae::geo::GeoPoint& out)
{
    const std::string s{spec};
    const auto comma = s.find(',');
    if (comma == std::string::npos)
        return false;
    try {
        size_t consumed_lon = 0, consumed_lat = 0;
        const std::string lon = s.substr(0, comma), lat = s.substr(comma + 1);
        out.lon = std::stod(lon, &consumed_lon);
        out.lat = std::stod(lat, &consumed_lat);
        return consumed_lon == lon.size() && consumed_lat == lat.size();
    }
    catch (const std::exception&) {
        return false;
    }
}

int main(int argc, char* const argv[])
{
    int exit_code = 0;
    try {
        std::vector<std::string_view> positional;
        std::vector<ae::geo::GeoPoint> points;
        for (int i = 1; i < argc; ++i) {
            const std::string_view arg{argv[i]};
            if (arg == "--point" && (i + 1) < argc) {
                ae::geo::GeoPoint pt;
                if (!parse_point(std::string_view{argv[++i]}, pt))
                    throw std::runtime_error{fmt::format("bad --point (expected lon,lat): {}", argv[i])};
                points.push_back(pt);
            }
            else if (arg == "--location" && (i + 1) < argc) {
                const std::string_view name{argv[++i]};
                const auto& db = ae::locdb::v3::get();
                if (const auto [resolved, loc] = db.find(name); loc) {
                    ae::geo::GeoPoint pt;
                    pt.lon = loc->longitude;
                    pt.lat = loc->latitude;
                    pt.fill = ae::geo::continent_color(db.continent(loc->country));
                    points.push_back(pt);
                }
                else {
                    fmt::print(stderr, "WARNING: location not found: {}\n", name);
                }
            }
            else {
                positional.push_back(arg);
            }
        }
        if (positional.empty()) {
            fmt::print(stderr, "Usage: {} [--point lon,lat] [--location NAME] ... <output.pdf> [image-width-px]\n", argv[0]);
            return 1;
        }
        const double image_width = positional.size() > 1 ? std::stod(std::string{positional[1]}) : 1000.0;
        ae::geo::export_geographic_pdf(std::filesystem::path{positional[0]}, image_width, points);
        fmt::print("Wrote {} (world map, width {:.0f}, {} point(s))\n", positional[0], image_width, points.size());
    }
    catch (std::exception& err) {
        fmt::print(stderr, "ERROR: {}\n", err.what());
        exit_code = 2;
    }
    return exit_code;
}

// ----------------------------------------------------------------------
