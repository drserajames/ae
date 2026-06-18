#pragma once

#include <string_view>
#include <utility>

// ----------------------------------------------------------------------
// Continent-coloured world-map inset for the TAL signature page (the small map in the
// lower-left of the tree, which doubles as the continent legend). Ported from AD
// acmacs-draw/continent-{path,map}.cc. See cc/tal/continent-map.cc and cc/tal/PORTING.md.
// ----------------------------------------------------------------------

namespace ae::draw
{
    class CairoPdf;
}

namespace ae::tal
{
    // Reference rectangle the per-continent paths live in (AD continent_map_size).
    inline constexpr double continent_map_size[2] = {660.0, 320.0};

    // Aspect (width / height) of the inset; size a layout box with this ratio.
    inline constexpr double continent_map_aspect() { return continent_map_size[0] / continent_map_size[1]; }

    // Per-continent baked outline, negative-move convention with BOTH coords negated on a
    // move entry (AD). [first, last) is a flat double array, stride 2 = {x, y}. Throws if
    // the continent name is unknown.
    std::pair<const double*, const double*> continent_map_path(std::string_view continent);

    // Draw the continent-coloured world map into the device box whose top-left is
    // (box_x, box_y) and size is (box_w, box_h). Each continent (Antarctica omitted) is
    // filled in its ae::geo::continent_color with no outline. The box should carry the
    // continent_map_aspect() ratio, otherwise the map is stretched.
    void draw_continent_inset(ae::draw::CairoPdf& pdf, double box_x, double box_y, double box_w, double box_h);

} // namespace ae::tal

// ----------------------------------------------------------------------
