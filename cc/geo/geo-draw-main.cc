#include <cmath>
#include <filesystem>
#include <map>
#include <numbers>
#include <string>
#include <string_view>
#include <vector>

#include "ext/fmt.hh"
#include "ad/rjson-v3.hh"
#include "geo/geographic-map.hh"
#include "geo/geographic-path.hh"
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

// Parse a colour string ("#RRGGBB", "0xRRGGBB", or a hex digit string) into a Color.
// Returns false if it is not a recognisable hex colour (caller then uses the palette).
static bool parse_color(std::string_view spec, Color& out)
{
    std::string s{spec};
    if (s.empty())
        return false;
    if (s[0] == '#')
        s = s.substr(1);
    else if (s.size() > 2 && s[0] == '0' && (s[1] == 'x' || s[1] == 'X'))
        s = s.substr(2);
    if (s.size() != 6)
        return false;
    try {
        size_t consumed = 0;
        const unsigned long v = std::stoul(s, &consumed, 16);
        if (consumed != s.size())
            return false;
        out = Color{static_cast<uint32_t>(v)};
        return true;
    }
    catch (const std::exception&) {
        return false;
    }
}

// Stable category -> colour map shared across all periods of one --data run, so a clade keeps
// its colour in every month's PDF and the legend is consistent. Honours an explicit per-
// category "color" override the first time a category is seen; otherwise uses clade_color().
class CategoryColors
{
  public:
    Color resolve(const std::string& name, std::string_view override_spec)
    {
        if (const auto found = colors_.find(name); found != colors_.end())
            return found->second;
        Color c;
        if (!override_spec.empty() && parse_color(override_spec, c)) {
            // use the override
        }
        else
            c = ae::geo::clade_color(name);
        colors_.emplace(name, c);
        order_.push_back(name);
        return c;
    }

    // Legend in first-seen order.
    std::vector<ae::geo::LegendEntry> legend() const
    {
        std::vector<ae::geo::LegendEntry> out;
        out.reserve(order_.size());
        for (const auto& name : order_)
            out.push_back({name, colors_.at(name)});
        return out;
    }

    bool empty() const { return order_.empty(); }

  private:
    std::map<std::string, Color> colors_{};
    std::vector<std::string> order_{};
};

// One already-coloured dot (one per antigen) in the "coloring" (packed-dots) mode: the colours
// are computed Python-side by applying the report's geographic_coloring apply-rules to each
// antigen's sequence, so geo-draw just plots them.
struct ColoredPoint
{
    Color fill{};
    Color outline{};
    double outline_width{};
};

// Pack `colored` dots (one per antigen) into concentric rings around (center_lon, center_lat) —
// a port of AD GeographicMapWithPointsFromHidb::prepare. `point_size` is the dot diameter and
// `density` the spacing factor (from the report's geographic_settings). Ring offsets are computed
// in device px then converted to lon/lat degrees using the same equirectangular transform
// export_geographic_pdf applies, so the cluster scale matches the rendered map.
static void pack_colored_points(double center_lon, double center_lat, const std::vector<ColoredPoint>& colored,
                                double point_size, double density, double image_width, std::vector<ae::geo::GeoPoint>& out)
{
    if (colored.empty())
        return;
    const double W = ae::geo::geographic_map_size[0], H = ae::geo::geographic_map_size[1];
    const double margin = image_width * 0.02;
    const double scale = (image_width - 2.0 * margin) / W;
    const double deg_per_px_lon = (ae::geo::geographic_map_bounds[2] - ae::geo::geographic_map_bounds[0]) / (scale * W);
    const double deg_per_px_lat = (ae::geo::geographic_map_bounds[1] - ae::geo::geographic_map_bounds[3]) / (scale * H);
    const double radius = point_size / 2.0;
    const auto emit = [&](double lon, double lat, const ColoredPoint& c) {
        ae::geo::GeoPoint p;
        p.lon = lon;
        p.lat = lat;
        p.fill = c.fill;
        p.outline = c.outline;
        p.outline_width = c.outline_width;
        p.radius = radius;
        out.push_back(p);
    };
    size_t idx = 0;
    emit(center_lon, center_lat, colored[idx++]);
    for (size_t ring = 1; idx < colored.size(); ++ring) {
        const double dist_px = point_size * density * static_cast<double>(ring);
        const double dist_lon = dist_px * deg_per_px_lon;
        const double dist_lat = dist_px * deg_per_px_lat;
        const size_t capacity = static_cast<size_t>(2.0 * std::numbers::pi * dist_px * static_cast<double>(ring) / (point_size * density));
        const size_t k = std::min(capacity, colored.size() - idx);
        if (k == 0)
            break;
        const double step = 2.0 * std::numbers::pi / static_cast<double>(k);
        for (size_t i = 0; i < k; ++i) {
            const double ang = static_cast<double>(i) * step;
            emit(center_lon + std::cos(ang) * dist_lon, center_lat + std::sin(ang) * dist_lat, colored[idx++]);
        }
    }
}

// --- Time-series mode: render one PDF per period from a JSON data file ---
// { "title_prefix": "H3", "periods": [ {"period":"2024-01", "locations":[
//     {"name":"TOKYO","count":12},                                   // single-dot (continent)
//     {"name":"PARIS","categories":[{"name":"3C.2a1b","count":7},    // pie (clade-coloured)
//                                   {"name":"3C.2a2","count":3,"color":"#FF0000"}]}
//   ]}, ... ] }
// Single-dot locations are sized by sqrt(count) and coloured by continent (unchanged).
// "categories" turns a location into a pie: each wedge angle ~ count, coloured by category
// (stable palette + optional per-category "color"); total radius scaled by sqrt(sum count).
// Output: <prefix><period>.pdf. A clade legend is drawn whenever any pies are present.
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

    // Packed-dots ("coloring") mode parameters (from the report's geographic_settings).
    const double point_size = config["point_size"].is_null() ? 8.0 : config["point_size"].to<double>();
    const double density = config["density"].is_null() ? 0.8 : config["density"].to<double>();

    CategoryColors cat_colors;
    const auto radius_for = [image_width](double count) { return std::max(3.0, std::sqrt(count) * image_width / 250.0); };

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
                const auto& pts_in = rec["points"];
                const auto& cats = rec["categories"];
                if (pts_in.is_array()) { // coloring mode: one dot per antigen, pre-coloured by apply-rule, packed in rings
                    std::vector<ColoredPoint> colored;
                    const auto& qarr = pts_in.array();
                    for (size_t qi = 0; qi < qarr.size(); ++qi) {
                        const auto& q = qarr[qi];
                        ColoredPoint cp;
                        cp.fill = q["color"].is_null() ? Color{"transparent"} : Color{q["color"].to<std::string_view>()};
                        cp.outline = q["outline"].is_null() ? Color{"black"} : Color{q["outline"].to<std::string_view>()};
                        cp.outline_width = q["outline_width"].is_null() ? 0.0 : q["outline_width"].to<double>();
                        const long count = q["count"].is_null() ? 1L : static_cast<long>(q["count"].to<double>());
                        for (long c = 0; c < count; ++c)
                            colored.push_back(cp);
                    }
                    if (colored.empty())
                        continue;
                    if (ae::geo::GeoPoint center; resolve_location(db, name, 0.0, center))
                        pack_colored_points(center.lon, center.lat, colored, point_size, density, image_width, points);
                    else
                        fmt::print(stderr, "WARNING: location not found: {}\n", name);
                }
                else if (cats.is_array()) { // pie mode
                    std::vector<ae::geo::GeoWedge> wedges;
                    double total = 0.0;
                    const auto& carr = cats.array();
                    for (size_t ci = 0; ci < carr.size(); ++ci) {
                        const auto& crec = carr[ci];
                        const std::string cname{crec["name"].to<std::string_view>()};
                        const double ccount = crec["count"].is_null() ? 1.0 : crec["count"].to<double>();
                        const std::string override_spec = crec["color"].is_null() ? std::string{} : std::string{crec["color"].to<std::string_view>()};
                        if (ccount <= 0.0)
                            continue;
                        wedges.push_back({ccount, cat_colors.resolve(cname, override_spec), cname});
                        total += ccount;
                    }
                    if (wedges.empty())
                        continue;
                    ae::geo::GeoPoint pt;
                    if (resolve_location(db, name, radius_for(total), pt)) {
                        pt.wedges = std::move(wedges);
                        points.push_back(std::move(pt));
                    }
                    else
                        fmt::print(stderr, "WARNING: location not found: {}\n", name);
                }
                else { // single-dot mode (continent-coloured) — unchanged
                    const double count = rec["count"].is_null() ? 1.0 : rec["count"].to<double>();
                    if (ae::geo::GeoPoint pt; resolve_location(db, name, radius_for(count), pt))
                        points.push_back(pt);
                    else
                        fmt::print(stderr, "WARNING: location not found: {}\n", name);
                }
            }
        }
        const std::string output = prefix + period + ".pdf";
        const std::string title = !per["title"].is_null() ? std::string{per["title"].to<std::string_view>()}
                                  : (title_prefix.empty() ? period : (title_prefix + " " + period));
        ae::geo::export_geographic_pdf(std::filesystem::path{output}, image_width, points, title, cat_colors.legend());
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
