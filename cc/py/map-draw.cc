#include <filesystem>
#include <optional>
#include <string>

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
        [](const std::filesystem::path& ace, const std::filesystem::path& output, const std::string& style, double width, size_t projection_no) {
            const Chart chart{ace};
            ae::map_draw::export_styled_map(chart, projection_index{projection_no}, style, width, output);
        },
        "ace"_a, "output"_a, "style"_a, "width"_a = 800.0, "projection_no"_a = 0,
        pybind11::doc("Render a chart's on-chart semantic style (c[\"R\"] named style + c[\"p\"] base plot-spec) to output "
                      "(.png raster, else PDF), mirroring kateri set_style + get_pdf. P2 milestone A."));
}

// ----------------------------------------------------------------------
