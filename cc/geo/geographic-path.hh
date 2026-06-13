#pragma once

#include <utility>

// ----------------------------------------------------------------------

namespace ae::geo
{
    // Equirectangular world-map outline, ported from AD acmacs-draw/geographic-path.cc.
    // The path data is licensed CC BY-SA 3.0 (from Wikimedia World_map_with_equator.svg).
    //
    // The accessor returns [first, last) over a flat array of doubles (stride 2 = {x, y}).
    // An entry with a NEGATIVE x marks the start of a new subpath (move-to at |x|); an
    // entry with a non-negative x is a line-to. This "negative-move" convention is consumed
    // by ae::draw::CairoPdf::path_negative_move().
    constexpr const double geographic_map_size[2] = {1261.3, 632.591};
    constexpr const double geographic_map_bounds[4] = {-168.237905, 90.0, 191.762094, -90.0}; // lon_min, lat_max, lon_max, lat_min

    std::pair<const double*, const double*> geographic_map_path();

} // namespace ae::geo

// ----------------------------------------------------------------------
