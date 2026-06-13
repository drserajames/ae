#pragma once

#include <filesystem>
#include <string>
#include <string_view>
#include <vector>

#include "ad/color.hh"

// ----------------------------------------------------------------------

namespace ae::geo
{
    // A point to plot on the map, given in geographic coordinates.
    struct GeoPoint
    {
        double lon{};
        double lat{};
        Color fill{0xFF0000};
        Color outline{0}; // black
        double radius{6.0};
    };

    // Continent fill color (ported from AD acmacs-base/color-continent.cc); grey for unknown.
    Color continent_color(std::string_view continent);

    // Render the equirectangular world base map (land filled + coastline) to a PDF and
    // plot `points` at their lon/lat. `image_width` is the PDF width in device units; the
    // height follows the map's geographic_map_size aspect (~2:1). A non-empty `title` is
    // drawn centred near the top.
    void export_geographic_pdf(const std::filesystem::path& output, double image_width = 1000.0, const std::vector<GeoPoint>& points = {}, const std::string& title = {});

} // namespace ae::geo

// ----------------------------------------------------------------------
