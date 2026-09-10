#pragma once

#include <array>
#include <filesystem>
#include <optional>
#include <string>
#include <vector>

#include "chart/v3/index.hh"
#include "map-draw/label-placement.hh"

// ----------------------------------------------------------------------

namespace ae::chart::v3
{
    class Chart;
}

namespace ae::map_draw
{
    // Rendering options for a chains-202105-style antigenic-map render. See TODO.md
    // subsystem #1. The renderer reproduces AD acmacs-map-draw's output for the WHO-CC
    // incremental-chain web app: grey base points, clade colouring from a mapi settings
    // block, recent-layer + vaccine marks, stress title and clade legend.
    struct DrawSettings
    {
        double image_size{800.0};
        // Reorient master chart (reorient-master.ace). AD's chains make_map aligns each
        // step to this master via chart.orient_to(master) (procrustes, no scaling) before
        // drawing — essential for framing/orientation to match the golden PNGs.
        std::optional<std::filesystem::path> reorient_master{};
        // Path to a clades.mapi settings file (the coloring DSL). When set together with
        // coloring_key the renderer colours antigens by clade.
        std::optional<std::filesystem::path> mapi{};
        // The mapi "?N" key selecting a coloring block, e.g. "clades-A(H3N2)-v1".
        std::optional<std::string> coloring_key{};
        // Populate sequences + clades from seqdb before drawing (AD's pipeline does this;
        // needed because most chain-step .ace files carry no clade attributes). Default on.
        bool populate_seqdb{true};
        // acmacs-data semantic_vaccines.py used by mark_vaccines to pick vaccine strains at
        // runtime (never committed into ae). If unset, mark_vaccines is skipped.
        std::optional<std::filesystem::path> vaccines_file{};
        bool mark_recent_layer{true};
        bool mark_vaccines{true};
        bool draw_title{true};       // stress line
        bool draw_legend{true};      // clade legend
        bool label_points{false};    // debug: label every point with its name
        bool draw_serum_circles{false};
        // Procrustes overlay (make_pc): arrows in MAP coordinates {x0,y0,x1,y1} and a title
        // override (e.g. "RMS: 0.1234"). Populated by export_procrustes; usually left empty.
        std::vector<std::array<double, 4>> arrows{};
        std::optional<std::string> title_override{};
    };

    // Render one projection of a chart to output (extension .png -> raster, else PDF).
    void export_map(const ae::chart::v3::Chart& chart, ae::projection_index projection_no, const std::filesystem::path& output, const DrawSettings& settings = {});

    // ------------------------------------------------------------------
    // P2 milestone A: headless render of a chart's on-chart *semantic* styling (c["R"] named
    // styles + c["p"] base plot-spec), mirroring kateri's set_style + get_pdf. This is the
    // report map path (by-clade etc.), additive to and independent of export_map above (the
    // fixed AD-chains pipeline). `style_name` selects a front style in chart.styles();
    // `width` is the output width in device px / PDF points. Output extension picks backend
    // (.png raster, else PDF). See cc/map-draw/STYLED-DRAW.md and P2-RENDER-DESIGN.md §1.2/§2.2.
    // `label_mode` selects how point labels WITHOUT an authored `l.p` offset are placed
    // (milestone I; see label-placement.hh): auto / auto-lines / pinned — or the `inside` pair,
    // which takes over EVERY label, authored offset included: `inside` draws all the labels on
    // top of the finished cloud, `inside-layered` paints each one with its own point so an
    // overlapping point covers it. Unset means "whatever AE_MAP_DRAW_LABEL_AUTOPLACE says",
    // which defaults to LabelMode::automatic.
    void export_styled_map(const ae::chart::v3::Chart& chart, ae::projection_index projection_no, std::string_view style_name, double width, const std::filesystem::path& output,
                           std::optional<LabelMode> label_mode = {});

    // Procrustes render: draw `secondary` framed like `primary`, with arrows for common
    // points (threshold 0.3) and an "RMS: {rms:.4f}" title. See make_pc in chains chart.py.
    void export_procrustes(const ae::chart::v3::Chart& primary, ae::projection_index primary_projection, const ae::chart::v3::Chart& secondary,
                           ae::projection_index secondary_projection, const std::filesystem::path& output, const DrawSettings& settings = {});

} // namespace ae::map_draw

// ----------------------------------------------------------------------
