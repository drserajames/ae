#pragma once

#include <optional>
#include <string_view>
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
// title) or the other labels.
//
// Candidates are expressed in kateri's *offset space*, not in device coordinates, so a
// placed label is rendered by exactly the same `label_offset()` mapping as an authored one
// — auto-placement can only ever pick an offset the operator could have typed.
//
// FOUR MODES (`LabelMode`, selected per render; see place_labels and label_mode_from_env):
//   * `automatic` (DEFAULT) — auto-placed, never tethered. Because an untethered displaced
//     label has nothing but proximity to say which point it names, this mode is tuned to
//     keep labels tight to their own point: it prefers a near imperfect spot to a distant
//     clean one (a much heavier distance penalty than `automatic_lines`, a hinge past half a
//     text-height of clear space, and a SATURATING point-cloud penalty so a candidate inside
//     a dense cluster is not charged over and over for the same ink).
//   * `automatic_lines` — the same search, tuned loosely, plus an AD-style tether
//     (`LabelTether{BLACK, 0.3px}`, the convention cc/tal/draw-tree.cc uses for auto-placed
//     MRCA labels) once the label ends up far enough away that the association would be lost.
//     Distance is cheap here precisely because the leader line carries the association.
//   * `inside` — the label is drawn CENTRED IN its point (offset [0, 0]) at a font shrunk to
//     the point's inscribed box, with the passage suffix stripped (see strip_passage_suffix
//     and inside_font_size). Nothing to avoid, nothing to tether.
//   * `pinned` — no auto-placement at all: every label keeps its offset, which is what the
//     fidelity harness needs when it measures parity against a kateri golden.
// Authored `l.p` offsets are honoured verbatim in EVERY mode (and are obstacles for the
// rest) — a hand-adjusted offset is the operator's explicit instruction about that label.
// ======================================================================

namespace ae::map_draw
{
    // How a render places the labels the operator has not hand-adjusted. See the header
    // comment above; `automatic` is the default, `pinned` the pre-milestone-I behaviour.
    enum class LabelMode { automatic, automatic_lines, inside, pinned };

    // Parse a mode name as accepted by the API and by AE_MAP_DRAW_LABEL_AUTOPLACE:
    // "auto" / "auto-lines" / "inside" / "off" (aliases: "1" = auto, "0"/"pinned" = off).
    // Returns nullopt for an unknown name so the caller can report it.
    std::optional<LabelMode> label_mode_from_name(std::string_view name);

    // The mode AE_MAP_DRAW_LABEL_AUTOPLACE asks for, or `automatic` when it is unset (an
    // unrecognised value is also `automatic` — a render must never fail on a typo'd env var).
    LabelMode label_mode_from_env();

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
    // the legend box, the title, or an already-placed (pinned) label. `text` marks the ones
    // made of TEXT (legend, title, pinned labels): text over text is unreadable at any
    // weighting, whereas text over a point still reads through its white halo, so the modes
    // that trade ink for proximity may only spend the second kind.
    struct LabelObstacle
    {
        double x0{0.0}, y0{0.0}, x1{0.0}, y1{0.0};
        bool text{false};
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

    // ---- `inside` mode helpers (used by the caller, which owns the text metrics) ----

    // Drop a trailing passage suffix from a point label so it fits inside its point:
    // "XX/23-cell" -> "XX/23", "YY/23-egg" -> "YY/23". Case-insensitive, and only ever a
    // WHOLE trailing "-cell"/"-egg" — a name that merely ends in those letters (…"-eggplant",
    // …"cell") keeps them, and a label that is nothing but the suffix is left alone.
    std::string_view strip_passage_suffix(std::string_view label);

    // Font size at which `text_w` x `text_h` (measured at `font_size`) fits the box inscribed
    // in a point of radius `point_radius`, clamped to [floor, font_size]. The floor is
    // max(kInsideMinFontSize, font_size * kInsideMinFontFactor): a label that cannot reach it
    // is drawn AT the floor and overflows its point rather than being moved outside — see the
    // `inside` note in cc/map-draw/TODO.md for why.
    double inside_font_size(double font_size, double text_w, double text_h, double point_radius);

    // Place every label. Pinned labels are returned at their authored offset (and are treated
    // as obstacles for the rest); un-pinned ones are placed as `mode` prescribes.
    // `canvas_w`/`canvas_h` bound the image so a label is never pushed off the page.
    // Deterministic: same input, same output. In `inside` mode the caller must already have
    // shrunk/stripped the text (the metrics in each LabelRequest are the ones it will draw).
    std::vector<LabelPlacement> place_labels(const std::vector<LabelRequest>& labels, const std::vector<LabelObstacle>& obstacles, double canvas_w, double canvas_h, LabelMode mode);

} // namespace ae::map_draw

// ----------------------------------------------------------------------
