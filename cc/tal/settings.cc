#include <stdexcept>
#include <string>

#include "tal/settings.hh"
#include "ad/rjson-v3.hh"

// ======================================================================

namespace ae::tal
{
    namespace
    {
        bool get_bool(const rjson::v3::value& v, bool dflt = false) { return v.is_null() ? dflt : v.to<bool>(); }
        double get_double(const rjson::v3::value& v, double dflt) { return v.is_null() ? dflt : v.to<double>(); }
        std::string get_string(const rjson::v3::value& v, std::string_view dflt = {}) { return v.is_null() ? std::string{dflt} : std::string{v.to<std::string_view>()}; }
    } // namespace
} // namespace ae::tal

// ----------------------------------------------------------------------

ae::tal::TreeDrawParameters ae::tal::load_draw_settings(const std::filesystem::path& file, double* image_size)
{
    const auto config_read = rjson::v3::parse_file(file.native());
    const rjson::v3::value& config = config_read;
    if (!config.is_object())
        throw std::runtime_error{"tal settings: top-level must be a JSON object"};

    TreeDrawParameters params;
    if (image_size != nullptr && !config["image_size"].is_null())
        *image_size = get_double(config["image_size"], *image_size);

    params.title = get_string(config["title"]);
    params.labels = get_bool(config["labels"]);
    params.color_by_clade = get_bool(config["color_by_clade"]);

    if (const auto& clades = config["clades"]; clades.is_object())
        params.clades = get_bool(clades["show"]);
    if (const auto& time_series = config["time_series"]; time_series.is_object()) {
        params.time_series = get_bool(time_series["show"]);
        params.time_series_interval = get_string(time_series["interval"], "month");
        params.time_series_start = get_string(time_series["start"]);
        params.time_series_end = get_string(time_series["end"]);
    }
    if (const auto& legend = config["legend"]; legend.is_object())
        params.legend = get_bool(legend["show"]);
    if (const auto& aa = config["aa_transitions"]; aa.is_object())
        params.aa_transitions = get_bool(aa["show"]);

    if (const auto& styles = config["clade_styles"]; styles.is_array()) {
        const auto& array = styles.array();
        for (std::size_t i = 0; i < array.size(); ++i) {
            const auto& entry = array[i];
            if (!entry.is_object())
                continue;
            if (std::string name = get_string(entry["name"]); !name.empty())
                params.clade_styles.insert_or_assign(std::move(name), CladeStyle{.color = get_string(entry["color"]), .display_name = get_string(entry["display_name"])});
        }
    }

    return params;

} // ae::tal::load_draw_settings

// ======================================================================
