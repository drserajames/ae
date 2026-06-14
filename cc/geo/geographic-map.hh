#pragma once

#include <filesystem>
#include <string>
#include <string_view>
#include <vector>

#include "ad/color.hh"

// ----------------------------------------------------------------------

namespace ae::geo
{
    // One wedge of a pie-chart GeoPoint: a category count and its colour. The wedge angle is
    // proportional to `count` relative to the point's total; `label` is the category name
    // (used to build the legend).
    struct GeoWedge
    {
        double count{};
        Color color{0xFF0000};
        std::string label{};
    };

    // A point to plot on the map, given in geographic coordinates. If `wedges` is empty the
    // point is drawn as a single continent-coloured dot (`fill`); otherwise it is drawn as a
    // pie chart with one sector per wedge (clockwise from 12 o'clock, angle ~ count).
    struct GeoPoint
    {
        double lon{};
        double lat{};
        Color fill{0xFF0000};
        Color outline{0}; // black
        double radius{6.0};
        double outline_width{-1.0}; // <0 -> use the renderer's computed default width
        std::vector<GeoWedge> wedges{};
    };

    // A legend entry (category label + colour) drawn in a small box on the map.
    struct LegendEntry
    {
        std::string label{};
        Color color{0xFF0000};
    };

    // Continent fill color (ported from AD acmacs-base/color-continent.cc); grey for unknown.
    Color continent_color(std::string_view continent);

    // Stable category (clade/lineage) colour palette. Returns a deterministic colour for a
    // category name (same name -> same colour across maps); "unknown"/empty -> grey.
    Color clade_color(std::string_view category);

    // Render the equirectangular world base map (land filled + coastline) to a PDF and
    // plot `points` at their lon/lat. `image_width` is the PDF width in device units; the
    // height follows the map's geographic_map_size aspect (~2:1). A non-empty `title` is
    // drawn centred near the top.
    void export_geographic_pdf(const std::filesystem::path& output, double image_width = 1000.0, const std::vector<GeoPoint>& points = {}, const std::string& title = {},
                               const std::vector<LegendEntry>& legend = {});

} // namespace ae::geo

// ----------------------------------------------------------------------
