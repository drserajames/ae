#pragma once

#include <vector>

// ======================================================================
// P2 milestone I — point-label auto-placement for the styled (semantic) map render.
//
// The report authors a per-chart table of vaccine/serology label offsets (`lox`/`loy` in
// py/ae/semantic/{vaccine,serology}.py) that lands on the chart as the style modifier's
// `l.p`. Those are HAND-ADJUSTED by the operator and must be honoured verbatim — they are
// the whole reason the offset exists. Everything AD and kateri do for labels stops there:
// AD's acmacs-draw `Points::draw_labels` (and the obsolete map_elements::Labels::draw)
// simply evaluates `PointLabel::text_offset()` for the authored offset hint and draws;
// kateri's `addPointLabel` does the same. NEITHER has collision avoidance or leader lines
// — the human is the placement algorithm.
//
// This module supplies the piece that neither has: for labels the operator has NOT adjusted
// (offset still at the [0, 1] default, i.e. no `l.p` in the chart), search the offset space
// for a position that does not collide with the point cloud, the map furniture (legend,
// title) or the other labels, and draw an AD-style tether (`LabelTether{BLACK, 0.3px}`, the
// same convention cc/tal/draw-tree.cc uses for auto-placed MRCA labels) when the label ends
// up far enough from its point that the association is no longer obvious.
//
// Candidates are expressed in kateri's *offset space*, not in device coordinates, so a
// placed label is rendered by exactly the same `label_offset()` mapping as an authored one
// — auto-placement can only ever pick an offset the operator could have typed.
// ======================================================================

namespace ae::map_draw
{
    // kateri addPointLabel::labelOffset (draw_on.dart), mirrored by AD
    // acmacs::draw::PointLabel::text_offset: map one axis of a label offset hint to a device
    // displacement of the text's baseline-left anchor from the point centre. `extent` is the
    // text box's width (horizontal) or height (vertical); `vertical` selects the axis, whose
    // anchor sits at the opposite end of the box (a baseline is at the box BOTTOM).
    //   * |off| >= 1  — the box is pushed clear of the point, `off` point-radii away;
    //   * |off| <  1  — the box is blended across the point, centred at off == 0.
    constexpr double label_offset(double off, double point_radius, double extent, bool vertical)
    {
        if (off >= 1.0)
            return point_radius * off + (vertical ? extent : 0.0);
        if (off > -1.0)
            return point_radius * off + (vertical ? extent * (off + 1.0) / 2.0 : extent * (off - 1.0) / 2.0);
        return point_radius * off - (vertical ? 0.0 : extent);
    }

    // An axis-aligned device-pixel rectangle the placer must keep labels off: a drawn point,
    // the legend box, the title, or an already-placed (pinned) label.
    struct LabelObstacle
    {
        double x0{0.0}, y0{0.0}, x1{0.0}, y1{0.0};
    };

    // One label to place. All geometry is in device pixels.
    struct LabelRequest
    {
        double point_x{0.0}, point_y{0.0}; // point centre
        double point_radius{0.0};          // half the drawn extent, (size + outline_width) / 2
        double text_w{0.0}, text_h{0.0};   // measured text box (text_size(..., helvetica))
        double offset_x{0.0}, offset_y{1.0};
        bool pinned{true}; // authored `l.p` — keep the offset exactly, never auto-place
    };

    // Where a label ended up. `offset_*` is always a valid kateri offset pair, so the caller
    // renders it through label_offset() exactly as it renders an authored offset.
    struct LabelPlacement
    {
        double offset_x{0.0}, offset_y{1.0};
        double x0{0.0}, y0{0.0}, x1{0.0}, y1{0.0}; // the resolved device text box
        bool leader{false};                        // draw a tether from the point to the box
        double leader_x0{0.0}, leader_y0{0.0};     // on the point's edge
        double leader_x1{0.0}, leader_y1{0.0};     // on the box's boundary
    };

    // Place every label. Pinned labels are returned at their authored offset (and are treated
    // as obstacles for the rest); un-pinned ones are searched. `canvas_w`/`canvas_h` bound the
    // image so a label is never pushed off the page. Deterministic: same input, same output.
    std::vector<LabelPlacement> place_labels(const std::vector<LabelRequest>& labels, const std::vector<LabelObstacle>& obstacles, double canvas_w, double canvas_h);

} // namespace ae::map_draw

// ----------------------------------------------------------------------
