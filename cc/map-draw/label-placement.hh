#pragma once

#include <array>
#include <functional>
#include <optional>
#include <string>
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
//   * `inside` — EVERY label is drawn CENTRED IN its point (offset [0, 0]), split across lines
//     and shrunk to fit the point's circle, with the passage suffix stripped (see
//     inside_block). Nothing to avoid, nothing to tether, and nothing to search.
//   * `pinned` — no auto-placement at all: every label keeps its offset, which is what the
//     fidelity harness needs when it measures parity against a kateri golden.
// Authored `l.p` offsets are honoured verbatim in `automatic`, `automatic_lines` and `pinned`
// (and are obstacles for the rest) — a hand-adjusted offset is the operator's explicit
// instruction about that label. `inside` is the exception: an authored offset is an
// instruction about where OUTSIDE the point the label goes, which that mode has no use for,
// so it is ignored and every label goes inside. A mode that put some labels inside and left
// the hand-adjusted ones outside would read as a bug rather than a choice.
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

    // One line of an `inside` label, positioned relative to the POINT CENTRE: draw `text` at
    // font `InsideBlock::font_size` with its baseline-left anchor at
    // (centre_x - width / 2, centre_y + baseline_dy).
    struct InsideLine
    {
        std::string text{};
        double width{0.0};       // advance width at the block's font size
        double baseline_dy{0.0}; // baseline offset from the point centre, downward positive
    };

    // A whole `inside` label: the lines to draw and the ink box they occupy, centred on the
    // point in both axes. `width`/`height` are what the caller hands the placer as the label's
    // text box, so the block comes back centred through the ordinary label_offset() mapping.
    struct InsideBlock
    {
        std::vector<InsideLine> lines{};
        double font_size{0.0};
        double width{0.0}, height{0.0};
    };

    // Measure one candidate line at `font_size`: {advance width, ink above baseline, ink below
    // baseline}. The caller owns the text metrics, so it supplies this (CairoPdf::text_size +
    // ::text_ink_height, both on the Helvetica face the labels are drawn with).
    using InsideMeasure = std::function<std::array<double, 3>(std::string_view text, double font_size)>;

    // Lay `label` out inside a point of radius `point_radius`, for a label whose authored size
    // is `font_size`. The passage suffix is stripped, then the plausible ways of breaking the
    // name across lines at its own separators ("XY/1234/25" -> "XY/" + "1234/25", or three
    // lines, …) are each fitted to the point and the one that RENDERS LARGEST wins — a circle
    // is widest across its middle, so two short centred lines commonly beat one long one. Fit
    // is against the circle itself, per line (a line near the middle may be wider than one at
    // the top), not against the inscribed square. Ties go to fewer lines.
    //
    // The font never exceeds `font_size` and never goes below
    // max(kInsideMinFontSize, font_size * kInsideMinFontFactor): a name that cannot reach that
    // floor is laid out with the arrangement that overflows least, drawn AT the floor, and
    // allowed to spill out of its point rather than being moved outside — see the `inside`
    // note in cc/map-draw/TODO.md for why.
    InsideBlock inside_block(std::string_view label, double font_size, double point_radius, const InsideMeasure& measure);

    // Place every label. Pinned labels are returned at their authored offset (and are treated
    // as obstacles for the rest); un-pinned ones are placed as `mode` prescribes.
    // `canvas_w`/`canvas_h` bound the image so a label is never pushed off the page.
    // Deterministic: same input, same output. In `inside` mode EVERY label is centred on its
    // point regardless of its authored offset, and the caller must already have laid the text
    // out with inside_block (the metrics in each LabelRequest are the block's).
    std::vector<LabelPlacement> place_labels(const std::vector<LabelRequest>& labels, const std::vector<LabelObstacle>& obstacles, double canvas_w, double canvas_h, LabelMode mode);

} // namespace ae::map_draw

// ----------------------------------------------------------------------
