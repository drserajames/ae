#include <filesystem>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "map-draw/draw.hh"
#include "chart/v3/chart.hh"
#include "py/module.hh"

// ======================================================================
// Python binding for the revived headless antigenic-map renderer (subsystem #1).
// Exposes ae_backend.map_draw.export_map(...) mirroring the AD chains-202105
// make_map / make_pc behaviour. See cc/map-draw/TODO.md.
// ======================================================================

void ae::py::map_draw(pybind11::module_& mdl)
{
    using namespace pybind11::literals;
    using namespace ae::chart::v3;

    auto sub = mdl.def_submodule("map_draw", "headless antigenic-map renderer (fidelity port of AD ChartDraw; see cc/map-draw/TODO.md)");

    // Point-label placement mode for the styled path (milestone I). Passed as a name so the
    // report / batch scripts can plumb a plain string through; empty means "use
    // AE_MAP_DRAW_LABEL_AUTOPLACE", which itself defaults to "auto".
    const auto label_mode_arg = [](const std::string& name) -> std::optional<ae::map_draw::LabelMode> {
        if (name.empty())
            return std::nullopt;
        if (const auto mode = ae::map_draw::label_mode_from_name(name); mode.has_value())
            return mode;
        throw std::invalid_argument{"unrecognized label placement mode \"" + name + "\" (expected auto, auto-lines, inside, inside-layered or off)"};
    };

    sub.def(
        "export_map",
        [](const std::filesystem::path& ace, const std::filesystem::path& output, size_t projection_no, double size, std::optional<std::filesystem::path> reorient_master, std::optional<std::filesystem::path> mapi,
           std::optional<std::string> coloring, bool marks, bool title, bool legend, bool labels, bool serum_circles) {
            const Chart chart{ace};
            ae::map_draw::DrawSettings settings;
            settings.image_size = size;
            settings.reorient_master = reorient_master;
            settings.mapi = mapi;
            settings.coloring_key = coloring;
            settings.mark_recent_layer = marks;
            settings.draw_title = title;
            settings.draw_legend = legend;
            settings.label_points = labels;
            settings.draw_serum_circles = serum_circles;
            ae::map_draw::export_map(chart, projection_index{projection_no}, output, settings);
        },
        "ace"_a, "output"_a, "projection_no"_a = 0, "size"_a = 800.0, "reorient_master"_a = std::nullopt, "mapi"_a = std::nullopt, "coloring"_a = std::nullopt, "marks"_a = true, "title"_a = true,
        "legend"_a = true, "labels"_a = false, "serum_circles"_a = false,
        pybind11::doc("Render one projection of an .ace chart to output (.png -> raster, else PDF), reproducing the AD chains-202105 map styling."));

    sub.def(
        "export_procrustes",
        [](const std::filesystem::path& primary_ace, const std::filesystem::path& secondary_ace, const std::filesystem::path& output, double size, std::optional<std::filesystem::path> mapi,
           std::optional<std::string> coloring) {
            const Chart primary{primary_ace};
            const Chart secondary{secondary_ace};
            ae::map_draw::DrawSettings settings;
            settings.image_size = size;
            settings.mapi = mapi;
            settings.coloring_key = coloring;
            ae::map_draw::export_procrustes(primary, projection_index{0}, secondary, projection_index{0}, output, settings);
        },
        "primary_ace"_a, "secondary_ace"_a, "output"_a, "size"_a = 800.0, "mapi"_a = std::nullopt, "coloring"_a = std::nullopt,
        pybind11::doc("Procrustes render (AD make_pc): draw primary with arrows to secondary (threshold 0.3), title 'RMS: x.xxxx'."));

    // --- P2 milestone A: styled (semantic c["R"] + c["p"]) render, kateri-compatible drop-in ---
    sub.def(
        "export_styled_map",
        [label_mode_arg](const std::filesystem::path& ace, const std::filesystem::path& output, const std::string& style, double width, size_t projection_no, const std::string& labels) {
            const Chart chart{ace};
            ae::map_draw::export_styled_map(chart, projection_index{projection_no}, style, width, output, label_mode_arg(labels));
        },
        "ace"_a, "output"_a, "style"_a, "width"_a = 800.0, "projection_no"_a = 0, "labels"_a = "",
        pybind11::doc("Render a chart's on-chart semantic style (c[\"R\"] named style + c[\"p\"] base plot-spec) to output "
                      "(.png raster, else PDF), mirroring kateri set_style + get_pdf. P2 milestone A.\n"
                      "labels: placement mode for labels with no authored offset — \"auto\" (default: overlap-avoided, "
                      "no leader lines), \"auto-lines\" (same, with leader lines), \"off\" (keep every offset as "
                      "authored); or \"inside\", which puts EVERY label inside the point it names (authored offsets "
                      "overridden, name split across lines, font shrunk to fit, passage suffix stripped), or "
                      "\"inside-layered\", the same layout drawn point-by-point so an overlapping point covers the "
                      "label beneath it instead of the two overprinting. Empty = take it from "
                      "AE_MAP_DRAW_LABEL_AUTOPLACE."));

    // --- P2 batch: load the chart ONCE, render many (style -> output) pairs ---
    // A report renders ~16 named styles from the SAME ~12 MB chart. `export_styled_map`
    // reloads the chart from disk on every call, so the reload dominates the per-map cost.
    // This hoists the single chart load out of the per-style render loop (the per-style
    // render path itself is the unchanged `export_styled_map(chart, ...)` above), producing
    // byte-identical PDFs while paying the load exactly once.
    sub.def(
        "export_styled_maps",
        [label_mode_arg](const std::filesystem::path& ace, const std::vector<std::pair<std::string, std::filesystem::path>>& jobs, double width, size_t projection_no, const std::string& labels) {
            const auto mode = label_mode_arg(labels);
            const Chart chart{ace}; // loaded ONCE, reused for every style
            for (const auto& [style, output] : jobs)
                ae::map_draw::export_styled_map(chart, projection_index{projection_no}, style, width, output, mode);
        },
        "ace"_a, "jobs"_a, "width"_a = 800.0, "projection_no"_a = 0, "labels"_a = "",
        pybind11::doc("Batch of export_styled_map: load the chart from `ace` once and render each (style_name, output_path) "
                      "pair in `jobs`. Byte-identical to calling export_styled_map per pair, but hoists the chart load out of "
                      "the loop (P2 batch optimisation for the report's ~16-style-per-lab render)."));
}

// ----------------------------------------------------------------------
