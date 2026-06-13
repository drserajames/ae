#pragma once

#include <filesystem>

// ----------------------------------------------------------------------

namespace ae::geo
{
    // Render the equirectangular world base map (land filled + coastline) to a PDF.
    // `image_width` is the PDF width in device units; the height follows the map's
    // ~2:1 aspect. Plotting located points (lon/lat) + time-series is a later slice.
    void export_geographic_pdf(const std::filesystem::path& output, double image_width = 1000.0);

} // namespace ae::geo

// ----------------------------------------------------------------------
