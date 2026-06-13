#include <cmath>
#include <filesystem>
#include <string>
#include <string_view>
#include <vector>

#include "ext/fmt.hh"
#include "ad/rjson-v3.hh"
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

// Resolve a location name to a continent-coloured GeoPoint via locdb. Returns false if unknown.
static bool resolve_location(const ae::locdb::v3::Db& db, std::string_view name, double radius, ae::geo::GeoPoint& out)
{
    const auto [resolved, loc] = db.find(name);
    if (!loc)
        return false;
    out.lon = loc->longitude;
    out.lat = loc->latitude;
    out.fill = ae::geo::continent_color(db.continent(loc->country));
    out.radius = radius;
    return true;
}

// --- Time-series mode: render one PDF per period from a JSON data file ---
// { "title_prefix": "H3", "periods": [ {"period":"2024-01",
//   "locations":[{"name":"TOKYO","count":12}, ...]}, ... ] }
// Output: <prefix><period>.pdf, dots sized by sqrt(count), coloured by continent.
static int time_series(const std::filesystem::path& data_file, const std::string& prefix, double image_width)
{
    const auto& db = ae::locdb::v3::get();
    const auto config_read = rjson::v3::parse_file(data_file.native());
    const rjson::v3::value& config = config_read;
    if (!config.is_object())
        throw std::runtime_error{"geo data: top-level must be a JSON object"};

    const std::string title_prefix = config["title_prefix"].is_null() ? std::string{} : std::string{config["title_prefix"].to<std::string_view>()};
    const auto& periods = config["periods"];
    if (!periods.is_array())
        throw std::runtime_error{"geo data: \"periods\" must be an array"};

    const auto& parr = periods.array();
    for (size_t pi = 0; pi < parr.size(); ++pi) {
        const auto& per = parr[pi];
        const std::string period{per["period"].to<std::string_view>()};
        std::vector<ae::geo::GeoPoint> points;
        if (const auto& locs = per["locations"]; locs.is_array()) {
            const auto& larr = locs.array();
            for (size_t li = 0; li < larr.size(); ++li) {
                const auto& rec = larr[li];
                const std::string name{rec["name"].to<std::string_view>()};
                const double count = rec["count"].is_null() ? 1.0 : rec["count"].to<double>();
                const double radius = std::max(3.0, std::sqrt(count) * image_width / 250.0);
                if (ae::geo::GeoPoint pt; resolve_location(db, name, radius, pt))
                    points.push_back(pt);
                else
                    fmt::print(stderr, "WARNING: location not found: {}\n", name);
            }
        }
        const std::string output = prefix + period + ".pdf";
        const std::string title = title_prefix.empty() ? period : (title_prefix + " " + period);
        ae::geo::export_geographic_pdf(std::filesystem::path{output}, image_width, points, title);
        fmt::print("Wrote {} ({} location(s))\n", output, points.size());
    }
    return 0;
}

int main(int argc, char* const argv[])
{
    int exit_code = 0;
    try {
        std::vector<std::string_view> positional;
        std::vector<ae::geo::GeoPoint> points;
        std::string data_file, prefix;
        double width = 0.0; // 0 => unset
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
                ae::geo::GeoPoint pt;
                if (resolve_location(ae::locdb::v3::get(), name, pt.radius, pt))
                    points.push_back(pt);
                else
                    fmt::print(stderr, "WARNING: location not found: {}\n", name);
            }
            else if (arg == "--data" && (i + 1) < argc)
                data_file = argv[++i];
            else if (arg == "--prefix" && (i + 1) < argc)
                prefix = argv[++i];
            else if (arg == "--width" && (i + 1) < argc)
                width = std::stod(argv[++i]);
            else
                positional.push_back(arg);
        }

        if (!data_file.empty()) { // time-series mode
            if (prefix.empty())
                throw std::runtime_error{"--data requires --prefix (output is <prefix><period>.pdf)"};
            return time_series(std::filesystem::path{data_file}, prefix, width > 0.0 ? width : 800.0);
        }

        // single-map mode
        if (positional.empty()) {
            fmt::print(stderr, "Usage: {} [--point lon,lat] [--location NAME] ... <output.pdf> [width]\n"
                               "       {} --data records.json --prefix <out-prefix> [--width N]\n",
                       argv[0], argv[0]);
            return 1;
        }
        const double image_width = width > 0.0 ? width : (positional.size() > 1 ? std::stod(std::string{positional[1]}) : 1000.0);
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
