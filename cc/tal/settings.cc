#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

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
        std::optional<bool> get_opt_bool(const rjson::v3::value& v) { return v.is_null() ? std::nullopt : std::optional<bool>{v.to<bool>()}; }
        std::optional<double> get_opt_double(const rjson::v3::value& v) { return v.is_null() ? std::nullopt : std::optional<double>{v.to<double>()}; }

        // Read a JSON string, or an array of strings, into a vector (null -> empty).
        std::vector<std::string> get_string_list(const rjson::v3::value& v)
        {
            std::vector<std::string> out;
            if (v.is_null())
                return out;
            if (v.is_array()) {
                const auto& array = v.array();
                for (std::size_t i = 0; i < array.size(); ++i)
                    out.push_back(get_string(array[i]));
            }
            else {
                out.push_back(get_string(v));
            }
            return out;
        }
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

    params.width_to_height_ratio = get_double(config["width_to_height_ratio"], 0.0);
    params.title = get_string(config["title"]);
    params.labels = get_bool(config["labels"]);
    params.labels_avoid_collisions = get_bool(config["labels_avoid_collisions"], true);
    params.color_by_clade = get_bool(config["color_by_clade"]);
    params.color_by_continent = get_bool(config["color_by_continent"]);
    if (const auto& cbp = config["color_by_pos"]; cbp.is_object()) {
        params.color_by_pos = static_cast<int>(get_double(cbp["pos"], 0.0));
        if (const auto& colors = cbp["colors"]; colors.is_array()) {
            const auto& color_array = colors.array();
            for (std::size_t j = 0; j < color_array.size(); ++j) {
                const auto& color_entry = color_array[j];
                if (color_entry.is_object())
                    if (const std::string aa = get_string(color_entry["aa"]); !aa.empty())
                        params.color_by_pos_colors.emplace(aa[0], get_string(color_entry["color"]));
            }
        }
    }

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
    params.geo_inset = get_bool(config["geo_inset"]);
    if (const auto& aa = config["aa_transitions"]; aa.is_object()) {
        params.aa_transitions = get_bool(aa["show"]);
        params.aa_transitions_compute = get_bool(aa["compute"]);
        params.aa_transitions_tolerance = get_double(aa["tolerance"], 0.6);
        params.aa_transitions_min_leaves = static_cast<int>(get_double(aa["min_leaves"], 1.0));
    }

    if (const auto& styles = config["clade_styles"]; styles.is_array()) {
        const auto& array = styles.array();
        for (std::size_t i = 0; i < array.size(); ++i) {
            const auto& entry = array[i];
            if (!entry.is_object())
                continue;
            if (std::string name = get_string(entry["name"]); !name.empty())
                params.clade_styles.insert_or_assign(std::move(name), CladeStyle{.color = get_string(entry["color"]), .display_name = get_string(entry["display_name"]), .hide = get_bool(entry["hide"])});
        }
    }

    if (const auto& nodes = config["nodes"]; nodes.is_array()) {
        const auto& array = nodes.array();
        for (std::size_t i = 0; i < array.size(); ++i) {
            const auto& mod_value = array[i];
            if (!mod_value.is_object())
                continue;
            NodeMod mod;
            if (const auto& select = mod_value["select"]; select.is_object()) {
                mod.select.seq_id = get_string_list(select["seq_id"]);
                mod.select.cumulative_min = get_opt_double(select["cumulative_min"]);
                mod.select.edge_min = get_opt_double(select["edge_min"]);
                mod.select.date_min = get_string(select["date_min"]);
                mod.select.date_max = get_string(select["date_max"]);
            }
            if (const auto& apply = mod_value["apply"]; apply.is_object()) {
                mod.apply.hide = get_opt_bool(apply["hide"]);
                mod.apply.edge_color = get_string(apply["edge_color"]);
                mod.apply.label_color = get_string(apply["label_color"]);
                mod.apply.label_scale = get_opt_double(apply["label_scale"]);
                if (const auto& text = apply["text"]; text.is_object()) {
                    if (std::string str = get_string(text["text"]); !str.empty()) {
                        NodeText nt{.text = std::move(str), .color = get_string(text["color"]), .size = get_double(text["size"], 0.0)};
                        if (const auto& offset = text["offset"]; offset.is_array() && offset.array().size() == 2) {
                            nt.offset_x = get_double(offset.array()[0], nt.offset_x);
                            nt.offset_y = get_double(offset.array()[1], nt.offset_y);
                        }
                        mod.apply.text = std::move(nt);
                    }
                }
            }
            params.node_mods.push_back(std::move(mod));
        }
    }

    if (const auto& sections = config["hz_sections"]; sections.is_array()) {
        const auto& array = sections.array();
        for (std::size_t i = 0; i < array.size(); ++i) {
            const auto& entry = array[i];
            if (!entry.is_object())
                continue;
            params.hz_sections.push_back(HzSection{.first = get_string(entry["first"]), .last = get_string(entry["last"]), .label = get_string(entry["label"])});
        }
    }

    if (const auto& bars = config["dash_bars"]; bars.is_array()) {
        const auto& array = bars.array();
        for (std::size_t i = 0; i < array.size(); ++i) {
            const auto& entry = array[i];
            if (!entry.is_object())
                continue;
            DashBarAAAt bar;
            bar.pos = static_cast<int>(get_double(entry["pos"], 0.0));
            if (const auto& colors = entry["colors"]; colors.is_array()) {
                const auto& color_array = colors.array();
                for (std::size_t j = 0; j < color_array.size(); ++j) {
                    const auto& color_entry = color_array[j];
                    if (color_entry.is_object())
                        if (const std::string aa = get_string(color_entry["aa"]); !aa.empty())
                            bar.colors_by_aa.emplace(aa[0], get_string(color_entry["color"]));
                }
            }
            params.dash_bars.push_back(std::move(bar));
        }
    }

    if (const auto& labels = config["mrca_labels"]; labels.is_array()) {
        const auto& array = labels.array();
        for (std::size_t i = 0; i < array.size(); ++i) {
            const auto& entry = array[i];
            if (!entry.is_object())
                continue;
            MrcaLabel label{.first = get_string(entry["first"]), .last = get_string(entry["last"]), .text = get_string(entry["text"]),
                            .color = get_string(entry["color"]), .size = get_double(entry["size"], 0.0)};
            if (const auto& offset = entry["offset"]; offset.is_array() && offset.array().size() == 2) {
                label.offset_x = get_double(offset.array()[0], 0.0);
                label.offset_y = get_double(offset.array()[1], 0.0);
            }
            if (!label.first.empty() && !label.last.empty() && !label.text.empty())
                params.mrca_labels.push_back(std::move(label));
        }
    }

    return params;

} // ae::tal::load_draw_settings

// ======================================================================
