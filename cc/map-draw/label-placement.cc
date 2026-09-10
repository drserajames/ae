#include <algorithm>
#include <array>
#include <bit>
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <utility>

#include "map-draw/label-placement.hh"

// ======================================================================
// Auto-placement solver (see label-placement.hh for what this is and why AD/kateri have no
// equivalent). The shape of the search follows cc/tal/draw-tree.cc's MRCA-label placer, the
// one auto-placer already in the tree: enumerate discrete candidate boxes per label, score
// each against the drawing's ink with a *continuous* penalty (penetration area, not a
// yes/no test, so the search has a gradient to follow), then settle the mutual label-label
// interference with iterated best response. It is much smaller than the tree placer because
// a map carries a handful of labels, not a signature page's few dozen.
// ======================================================================

namespace ae::map_draw
{
    namespace
    {
        // Candidate offsets are (direction x scale). The first direction is kateri's [0, 1]
        // default (straight below the point), so an unobstructed label keeps exactly the
        // position it has today and auto-placement is invisible on maps that don't need it.
        constexpr std::array<std::pair<double, double>, 12> kDirections{{
            {0.0, 1.0},   {0.0, -1.0},  {1.0, 0.0},   {-1.0, 0.0}, {1.0, 1.0},   {-1.0, 1.0},
            {1.0, -1.0},  {-1.0, -1.0}, {0.6, 1.0},   {-0.6, 1.0}, {0.6, -1.0},  {-0.6, -1.0},
        }};
        constexpr std::array<double, 9> kScales{{1.0, 1.35, 1.8, 2.4, 3.2, 4.3, 5.8, 7.8, 10.5}};

        // Mode-independent cost weights. Running off the page or over another auto label is
        // never acceptable whatever the mode, so these dominate; the ink-vs-distance trade
        // that DOES depend on the mode lives in Tuning below. All areas are in em^2 and all
        // lengths in em (em = the label's own text height), so a big label's collisions
        // weigh the same as a small one's.
        constexpr double kWeightOffCanvas = 400.0;    // per unit of (area / em^2) outside the image
        constexpr double kWeightLabel = 90.0;         // per unit of (overlap area / em^2) with another label
        constexpr double kWeightDirection = 1.5;      // deviating from "below the point"
        constexpr double kWeightLeader = 1.5;         // a tether is a cost, not free
        constexpr double kWeightLeaderOverInk = 12.0; // per em of tether crossing points/pinned labels
        constexpr double kWeightLeaderCross = 6.0;    // two tethers crossing
        constexpr double kWeightLeaderOverText = 8.0; // per em of tether running through another label

        // Distance vs ink is the ONLY thing that differs between the two auto modes, and it
        // differs a lot. With a tether the reader is TOLD which point a label belongs to, so
        // distance is merely untidy and stepping on a point is the greater sin. Without one,
        // proximity IS the association, so the balance inverts: a displaced label must stay
        // within reading distance of its own point even at the price of covering some ink —
        // which the labels' white halo (and the operator's own authored offsets, several of
        // which sit squarely on the point cloud) show to be perfectly legible.
        constexpr double kNoInkSaturation = 1.0e9; // ink_saturation value meaning "never saturates"

        struct Tuning
        {
            double weight_ink{0.0};         // per unit of (overlap area / em^2) with the point cloud
            double ink_saturation{0.0};     // em^2 of point-cloud overlap past which it stops counting
            double weight_text{0.0};        // ditto for TEXT ink: legend, title, pinned labels
            double weight_gap{0.0};         // per em of clear distance from the point
            double weight_gap_squared{0.0}; // per em^2 — keeps labels from drifting away
            double gap_soft_limit{0.0};     // em of clear distance past which...
            double weight_gap_excess{0.0};  // ...every further em^2 costs this (hinge; 0 = no hinge)
            bool leaders{false};
        };

        // `automatic_lines`: the milestone-I tuning, unchanged (renders must stay identical) —
        // it scored every obstacle, text or not, with the one uncapped ink weight.
        constexpr Tuning kTuningLines{25.0, kNoInkSaturation, 25.0, 4.0, 1.2, 0.0, 0.0, true};
        // `automatic` (default): the point cloud costs 1/5 as much AND saturates at 4 em^2,
        // TEXT obstacles cost as much as another auto label (kWeightLabel), and distance costs
        // ~3.5x the linear and ~4x the quadratic plus a hinge past half a text-height. The
        // saturation is what actually keeps these labels home: obstacles are summed rather than
        // unioned, so without a cap a spot inside a cluster of overlapping points is charged
        // several times over for the same ink and every label flees the cluster entirely.
        constexpr Tuning kTuningNoLines{5.0, 4.0, 90.0, 14.0, 5.0, 0.5, 30.0, false};

        // Clearance kept between a label box and the ink it must avoid, in em.
        constexpr double kBoxPadEm = 0.12;
        // `inside` mode: fraction of the point's radius the text block may reach, and the font
        // size below which shrinking stops (whichever of the two floors is larger).
        constexpr double kInsideFitMargin = 0.95;
        constexpr double kInsideMinFontSize = 5.0;    // device px / PDF points
        constexpr double kInsideMinFontFactor = 0.35; // of the authored label size
        // Baseline-to-baseline distance of a multi-line inside label, in em. Tighter than a
        // normal paragraph's leading — these are one-word lines of caps and digits, and every
        // em of block height is font size the fit has to give back.
        constexpr double kInsideLinePitch = 1.12;
        constexpr std::size_t kInsideMaxLines = 3;
        constexpr std::size_t kInsideMaxTokens = 6; // beyond this the tail is not split further
        // An extra line must buy at least this much font size to be worth it — otherwise the
        // name stays on one line. Splitting is a means to a bigger label, not an end.
        constexpr double kInsideSplitGain = 1.05;
        // Hysteresis toward kateri's [0, 1] default, so a label with no real reason to move
        // does not drift off it and the render stays as close to the pre-auto-placement one
        // as the collisions allow.
        constexpr double kBonusDefault = 1.5;

        struct Rect
        {
            double x0{0.0}, y0{0.0}, x1{0.0}, y1{0.0};
        };

        // A rectangle the placer must avoid, plus which of the two ink weights it is scored
        // with (see LabelObstacle::text).
        struct Ink
        {
            Rect box{};
            bool text{false};
        };

        double overlap_area(const Rect& a, const Rect& b)
        {
            const double w = std::min(a.x1, b.x1) - std::max(a.x0, b.x0);
            const double h = std::min(a.y1, b.y1) - std::max(a.y0, b.y0);
            return (w > 0.0 && h > 0.0) ? w * h : 0.0;
        }

        // How much of `r` falls outside the canvas [0, w] x [0, h].
        double off_canvas_area(const Rect& r, double canvas_w, double canvas_h)
        {
            const double area = std::max(0.0, r.x1 - r.x0) * std::max(0.0, r.y1 - r.y0);
            return std::max(0.0, area - overlap_area(r, Rect{0.0, 0.0, canvas_w, canvas_h}));
        }

        // Closest point on the rectangle's boundary (or the interior point itself when the
        // query point is inside — the caller then reports zero gap and draws no tether).
        std::pair<double, double> closest_on_rect(const Rect& r, double px, double py)
        {
            return {std::clamp(px, r.x0, r.x1), std::clamp(py, r.y0, r.y1)};
        }

        bool segments_cross(double ax, double ay, double bx, double by, double cx, double cy, double dx, double dy)
        {
            const auto side = [](double px, double py, double qx, double qy, double rx, double ry) {
                const double v = (qy - py) * (rx - qx) - (qx - px) * (ry - qy);
                return v < 0.0 ? -1 : (v > 0.0 ? 1 : 0);
            };
            return side(ax, ay, bx, by, cx, cy) != side(ax, ay, bx, by, dx, dy) && side(cx, cy, dx, dy, ax, ay) != side(cx, cy, dx, dy, bx, by);
        }

        // Length of segment AB that runs inside the rectangle (Liang-Barsky clip) — the
        // continuous "tether draws over that label's text" penalty.
        double segment_in_rect(double ax, double ay, double bx, double by, const Rect& r)
        {
            double t0 = 0.0, t1 = 1.0;
            const double dx = bx - ax, dy = by - ay;
            const double p[4] = {-dx, dx, -dy, dy};
            const double q[4] = {ax - r.x0, r.x1 - ax, ay - r.y0, r.y1 - ay};
            for (int e = 0; e < 4; ++e) {
                if (p[e] == 0.0) {
                    if (q[e] < 0.0)
                        return 0.0;
                }
                else {
                    const double s = q[e] / p[e];
                    if (p[e] < 0.0) {
                        if (s > t1)
                            return 0.0;
                        if (s > t0)
                            t0 = s;
                    }
                    else {
                        if (s < t0)
                            return 0.0;
                        if (s < t1)
                            t1 = s;
                    }
                }
            }
            return t1 > t0 ? std::hypot(dx, dy) * (t1 - t0) : 0.0;
        }

        // One candidate position for one label: the offset pair, the device box it resolves
        // to, the tether it would need, and everything about it that does not depend on where
        // the *other* labels end up (precomputed once — the sweeps below only re-score the
        // label-label terms).
        struct Candidate
        {
            double offset_x{0.0}, offset_y{0.0};
            Rect box{};
            bool leader{false};
            double lx0{0.0}, ly0{0.0}, lx1{0.0}, ly1{0.0};
            double static_cost{0.0};
        };

        // Resolve an offset pair to a device text box + its tether, exactly as the renderer
        // will. The box is [anchor, anchor + width] x [baseline - height, baseline].
        // `leaders` is the mode's tether permission — the modes that draw no lines must not
        // score any of the tether terms either.
        Candidate make_candidate(const LabelRequest& lab, double off_x, double off_y, bool leaders)
        {
            Candidate c{};
            c.offset_x = off_x;
            c.offset_y = off_y;
            const double ax = lab.point_x + label_offset(off_x, lab.point_radius, lab.text_w, false);
            const double ay = lab.point_y + label_offset(off_y, lab.point_radius, lab.text_h, true);
            c.box = Rect{ax, ay - lab.text_h, ax + lab.text_w, ay};

            const auto [nx, ny] = closest_on_rect(c.box, lab.point_x, lab.point_y);
            const double dist = std::hypot(nx - lab.point_x, ny - lab.point_y);
            const double gap = std::max(0.0, dist - lab.point_radius);
            // A tether appears once the label is pushed clear enough of its point that the
            // reader would otherwise have to guess which point it belongs to. Below that it
            // stays a plain adjacent label, exactly as AD/kateri always draw it. The threshold
            // is deliberately low: an untethered label a whole text-height from its point is
            // more confusing than a short connector is ugly.
            const double leader_threshold = std::max(lab.point_radius * 0.6, lab.text_h * 0.75);
            if (leaders && gap > leader_threshold && dist > 1.0e-6 && lab.text_w > 0.0 && lab.text_h > 0.0) {
                c.leader = true;
                const double ux = (nx - lab.point_x) / dist, uy = (ny - lab.point_y) / dist;
                c.lx0 = lab.point_x + ux * lab.point_radius;
                c.ly0 = lab.point_y + uy * lab.point_radius;
                c.lx1 = nx;
                c.ly1 = ny;
                if (std::hypot(c.lx1 - c.lx0, c.ly1 - c.ly0) < 1.5) // degenerate — not worth a stroke
                    c.leader = false;
            }
            return c;
        }

        // ---- `inside` mode: breaking a name across lines ----

        // The name's own separators, as [begin, end) offsets into it. A break goes AFTER a '/'
        // or '-' (the separator stays with the line it terminates, so "XY/1234/25" can become
        // "XY/" + "1234/25") and at a space (which is dropped). Nothing is ever split
        // mid-token: an arbitrary break inside "1234" reads as a different number.
        std::vector<std::pair<std::size_t, std::size_t>> split_tokens(std::string_view text)
        {
            std::vector<std::pair<std::size_t, std::size_t>> tokens;
            std::size_t start = 0;
            for (std::size_t i = 0; i < text.size(); ++i) {
                if ((text[i] == '/' || text[i] == '-') && i + 1 < text.size()) {
                    tokens.emplace_back(start, i + 1);
                    start = i + 1;
                }
                else if (text[i] == ' ') {
                    if (i > start)
                        tokens.emplace_back(start, i);
                    start = i + 1;
                }
            }
            if (start < text.size())
                tokens.emplace_back(start, text.size());
            if (tokens.empty()) // all-whitespace: one unbreakable token, so the caller has a line
                tokens.emplace_back(0, text.size());
            // A name with more separators than this would blow the arrangement count for no
            // gain — keep the head and leave the tail as one unbreakable token.
            if (tokens.size() > kInsideMaxTokens) {
                const auto last = tokens.back().second;
                tokens.resize(kInsideMaxTokens);
                tokens.back().second = last;
            }
            return tokens;
        }

        // Radius of the smallest circle, concentric with the point, that contains a block of
        // `n` lines measured {advance, ink above baseline, ink below baseline} and stacked
        // `pitch` apart. The block is centred on its INK (not on the em boxes), and each line
        // is tested at its own corners — which is the whole reason splitting pays: a circle is
        // widest across its middle, so a middle line may be far wider than a top one.
        double block_radius(const std::vector<std::array<double, 3>>& lines, double pitch)
        {
            const double top = -lines.front()[1];
            const double bottom = static_cast<double>(lines.size() - 1) * pitch + lines.back()[2];
            const double mid = (top + bottom) / 2.0;
            double radius = 0.0;
            for (std::size_t i = 0; i < lines.size(); ++i) {
                const double baseline = static_cast<double>(i) * pitch - mid;
                const double extreme = std::max(std::abs(baseline - lines[i][1]), std::abs(baseline + lines[i][2]));
                radius = std::max(radius, std::hypot(lines[i][0] / 2.0, extreme));
            }
            return radius;
        }

    } // namespace

    // ----------------------------------------------------------------------

    std::optional<LabelMode> label_mode_from_name(std::string_view name)
    {
        if (name == "auto" || name == "1")
            return LabelMode::automatic;
        if (name == "auto-lines" || name == "lines")
            return LabelMode::automatic_lines;
        if (name == "inside")
            return LabelMode::inside;
        if (name == "off" || name == "pinned" || name == "0")
            return LabelMode::pinned;
        return std::nullopt;
    }

    LabelMode label_mode_from_env()
    {
        const char* const env = std::getenv("AE_MAP_DRAW_LABEL_AUTOPLACE");
        if (env == nullptr || *env == '\0')
            return LabelMode::automatic;
        return label_mode_from_name(env).value_or(LabelMode::automatic);
    }

    // ----------------------------------------------------------------------

    std::string_view strip_passage_suffix(std::string_view label)
    {
        const auto ends_with_ci = [label](std::string_view suffix) {
            if (label.size() <= suffix.size()) // "<= " : never strip the whole label away
                return false;
            for (size_t i = 0; i < suffix.size(); ++i) {
                const auto c = static_cast<unsigned char>(label[label.size() - suffix.size() + i]);
                if (std::tolower(c) != static_cast<unsigned char>(suffix[i]))
                    return false;
            }
            return true;
        };
        for (const std::string_view suffix : {std::string_view{"-cell"}, std::string_view{"-egg"}}) {
            if (ends_with_ci(suffix))
                return label.substr(0, label.size() - suffix.size());
        }
        return label;
    }

    InsideBlock inside_block(std::string_view label, double font_size, double point_radius, const InsideMeasure& measure)
    {
        const std::string_view text = strip_passage_suffix(label);
        InsideBlock block{};
        block.font_size = std::max(0.0, font_size);
        if (text.empty() || font_size <= 0.0 || point_radius <= 0.0 || !measure) {
            // A zero-size label (the report's `-no-label` variants set `l.s` to 0) or an empty
            // one: hand back an empty block, which the caller measures as a 0 x 0 box and skips.
            block.font_size = 0.0;
            return block;
        }

        const auto tokens = split_tokens(text);
        const auto line_text = [text, &tokens](std::size_t first, std::size_t last) { // inclusive token range
            return text.substr(tokens[first].first, tokens[last].second - tokens[first].first);
        };
        // Everything is measured once at the authored size and scaled: within a font the metrics
        // are linear in size to well under a pixel, and the winner is re-measured at the size it
        // is actually drawn at before anything is positioned.
        const double pitch = font_size * kInsideLinePitch;
        std::vector<std::array<double, 3>> measured;
        std::vector<std::size_t> best_cuts, cuts;
        double best_fit = 0.0;

        // Arrangements: every way of cutting the token sequence into at most kInsideMaxLines
        // contiguous groups. One bit per internal boundary — a handful of masks for a name.
        const std::size_t boundaries = tokens.size() - 1;
        for (unsigned mask = 0; mask < (1u << boundaries); ++mask) {
            const auto lines = static_cast<std::size_t>(std::popcount(mask)) + 1;
            if (lines > kInsideMaxLines)
                continue;
            cuts.clear();
            measured.clear();
            std::size_t first = 0;
            for (std::size_t b = 0; b <= boundaries; ++b) {
                if (b == boundaries || (mask & (1u << b)) != 0) {
                    measured.push_back(measure(line_text(first, b), font_size));
                    cuts.push_back(b);
                    first = b + 1;
                }
            }
            const double radius = block_radius(measured, pitch);
            if (radius <= 0.0)
                continue;
            // The size this arrangement would render at, capped at the authored size so that
            // arrangements which all fit comfortably tie and the fewest-lines one keeps the win.
            const double fit = std::min(font_size, font_size * point_radius * kInsideFitMargin / radius);
            const double needed = cuts.size() > best_cuts.size() ? best_fit * kInsideSplitGain : best_fit;
            if (fit > needed) {
                best_fit = fit;
                best_cuts = cuts;
            }
        }
        if (best_cuts.empty())
            best_cuts.push_back(boundaries);

        // A name that cannot reach the floor is drawn AT the floor and overflows its point —
        // with the arrangement that overflows least, which is the same one that fitted largest.
        const double floor_size = std::max(kInsideMinFontSize, font_size * kInsideMinFontFactor);
        block.font_size = std::clamp(best_fit, std::min(floor_size, font_size), font_size);

        // Re-measure the winner at the size it will be drawn at, then stack the lines and centre
        // the block's ink on the point.
        measured.clear();
        std::size_t first = 0;
        for (const std::size_t b : best_cuts) {
            const std::string_view line = line_text(first, b);
            measured.push_back(measure(line, block.font_size));
            block.lines.push_back(InsideLine{std::string{line}, measured.back()[0], 0.0});
            first = b + 1;
        }
        const double drawn_pitch = block.font_size * kInsideLinePitch;
        const double top = -measured.front()[1];
        const double bottom = static_cast<double>(measured.size() - 1) * drawn_pitch + measured.back()[2];
        const double mid = (top + bottom) / 2.0;
        for (std::size_t i = 0; i < block.lines.size(); ++i) {
            block.lines[i].baseline_dy = static_cast<double>(i) * drawn_pitch - mid;
            block.width = std::max(block.width, block.lines[i].width);
        }
        block.height = bottom - top;
        return block;
    }

    // ----------------------------------------------------------------------

    std::vector<LabelPlacement> place_labels(const std::vector<LabelRequest>& labels, const std::vector<LabelObstacle>& obstacles, double canvas_w, double canvas_h, LabelMode mode)
    {
        const Tuning tuning = mode == LabelMode::automatic_lines ? kTuningLines : kTuningNoLines;
        std::vector<LabelPlacement> result(labels.size());

        // Pinned labels keep their authored offset verbatim and become obstacles for the rest
        // (an operator-placed label is a fact of the drawing, like a point).
        std::vector<Ink> ink;
        ink.reserve(obstacles.size() + labels.size());
        for (const auto& o : obstacles)
            ink.push_back(Ink{Rect{o.x0, o.y0, o.x1, o.y1}, o.text});

        std::vector<std::size_t> autos; // indexes into `labels` that we actually place
        for (std::size_t i = 0; i < labels.size(); ++i) {
            // `inside` mode drops EVERY label onto offset [0, 0] — kateri's "blended across
            // the point" branch of label_offset(), i.e. the text box centred on the point
            // centre. Nothing to search: the whole point of the mode is that the label sits ON
            // the thing it names. An authored offset says where OUTSIDE the point the operator
            // wants the label, which this mode has no use for, so it is overridden.
            const bool centre_in_point = mode == LabelMode::inside;
            const Candidate c = centre_in_point ? make_candidate(labels[i], 0.0, 0.0, false) : make_candidate(labels[i], labels[i].offset_x, labels[i].offset_y, false);
            result[i] = LabelPlacement{c.offset_x, c.offset_y, c.box.x0, c.box.y0, c.box.x1, c.box.y1, false, 0.0, 0.0, 0.0, 0.0};
            // A zero-size label (the report's `-no-label` style variants set `l.s` to 0, which
            // draws nothing) is left exactly where it is: it is neither an obstacle nor worth
            // placing, and tethering to an invisible box would draw a line to nowhere.
            if (labels[i].text_w <= 0.0 || labels[i].text_h <= 0.0)
                continue;
            if (labels[i].pinned || centre_in_point)
                ink.push_back(Ink{c.box, true});
            else
                autos.push_back(i);
        }
        if (autos.empty())
            return result;

        // --- candidate enumeration + static scoring ---
        std::vector<std::vector<Candidate>> cands(autos.size());
        for (std::size_t k = 0; k < autos.size(); ++k) {
            const LabelRequest& lab = labels[autos[k]];
            const double em = lab.text_h > 0.0 ? lab.text_h : 1.0;
            const double em2 = em * em;
            // The label's own point is ink too — this is what stops the search from parking a
            // label on top of the very point it names.
            std::vector<Candidate>& cc = cands[k];
            cc.reserve(kDirections.size() * kScales.size());
            for (const auto& [dx, dy] : kDirections) {
                // Angular deviation from "below the point" (kateri's default direction).
                const double len = std::hypot(dx, dy);
                const double dir_pen = len > 0.0 ? (1.0 - dy / len) / 2.0 : 1.0;
                for (const double s : kScales) {
                    Candidate c = make_candidate(lab, dx * s, dy * s, tuning.leaders);
                    const double pad = em * kBoxPadEm;
                    const Rect padded{c.box.x0 - pad, c.box.y0 - pad, c.box.x1 + pad, c.box.y1 + pad};
                    double cost = 0.0;
                    // Obstacles are summed, not unioned, so a spot deep in a cluster of
                    // overlapping points is charged for each of them. That is what makes a
                    // label flee a dense cloud entirely; `ink_saturation` caps it, because past
                    // a certain amount of covered ink a label is no less readable for covering
                    // more, and proximity to its own point should take over. Text obstacles are
                    // never capped — text over text is unreadable however little of it there is.
                    double ink_area = 0.0;
                    for (const Ink& r : ink) {
                        const double area = overlap_area(padded, r.box) / em2;
                        if (r.text)
                            cost += tuning.weight_text * area;
                        else
                            ink_area += area;
                        if (c.leader)
                            cost += kWeightLeaderOverInk * segment_in_rect(c.lx0, c.ly0, c.lx1, c.ly1, r.box) / em;
                    }
                    cost += tuning.weight_ink * std::min(ink_area, tuning.ink_saturation);
                    cost += kWeightOffCanvas * off_canvas_area(c.box, canvas_w, canvas_h) / em2;
                    const auto [nx, ny] = closest_on_rect(c.box, lab.point_x, lab.point_y);
                    const double gap = std::max(0.0, std::hypot(nx - lab.point_x, ny - lab.point_y) - lab.point_radius) / em;
                    cost += tuning.weight_gap * gap + tuning.weight_gap_squared * gap * gap;
                    if (const double excess = gap - tuning.gap_soft_limit; tuning.weight_gap_excess > 0.0 && excess > 0.0)
                        cost += tuning.weight_gap_excess * excess * excess;
                    cost += kWeightDirection * dir_pen;
                    if (c.leader)
                        cost += kWeightLeader;
                    if (dx == 0.0 && dy == 1.0 && s == kScales[0])
                        cost -= kBonusDefault; // stay put unless there is a reason to move
                    c.static_cost = cost;
                    cc.push_back(std::move(c));
                }
            }
            std::sort(cc.begin(), cc.end(), [](const Candidate& a, const Candidate& b) { return a.static_cost < b.static_cost; });
        }

        // --- pairwise (label-label) interference ---
        const auto pair_cost = [&](std::size_t ka, const Candidate& a, std::size_t kb, const Candidate& b) {
            const double em = std::max(1.0, labels[autos[ka]].text_h);
            const double emb = std::max(1.0, labels[autos[kb]].text_h);
            double cost = kWeightLabel * overlap_area(a.box, b.box) / (em * emb);
            if (a.leader)
                cost += kWeightLeaderOverText * segment_in_rect(a.lx0, a.ly0, a.lx1, a.ly1, b.box) / em;
            if (b.leader)
                cost += kWeightLeaderOverText * segment_in_rect(b.lx0, b.ly0, b.lx1, b.ly1, a.box) / emb;
            if (a.leader && b.leader && segments_cross(a.lx0, a.ly0, a.lx1, a.ly1, b.lx0, b.ly0, b.lx1, b.ly1))
                cost += kWeightLeaderCross;
            return cost;
        };

        // --- iterated best response: start each label at its best solo position, then let
        //     them take turns moving to their best position given the others, until nothing
        //     improves. With a map's handful of labels this settles in a few sweeps. ---
        const std::size_t n = autos.size();
        std::vector<std::size_t> choice(n, 0);
        const auto total_for = [&](std::size_t k, std::size_t ci) {
            double cost = cands[k][ci].static_cost;
            for (std::size_t j = 0; j < n; ++j)
                if (j != k)
                    cost += pair_cost(k, cands[k][ci], j, cands[j][choice[j]]);
            return cost;
        };
        for (int sweep = 0; sweep < 40; ++sweep) {
            bool changed = false;
            for (std::size_t k = 0; k < n; ++k) {
                double best = total_for(k, choice[k]);
                std::size_t best_i = choice[k];
                for (std::size_t ci = 0; ci < cands[k].size(); ++ci) {
                    if (ci == choice[k])
                        continue;
                    if (const double cost = total_for(k, ci); cost < best - 1.0e-9) {
                        best = cost;
                        best_i = ci;
                    }
                }
                if (best_i != choice[k]) {
                    choice[k] = best_i;
                    changed = true;
                }
            }
            if (!changed)
                break;
        }

        for (std::size_t k = 0; k < n; ++k) {
            const Candidate& c = cands[k][choice[k]];
            result[autos[k]] = LabelPlacement{c.offset_x, c.offset_y, c.box.x0, c.box.y0, c.box.x1, c.box.y1, c.leader, c.lx0, c.ly0, c.lx1, c.ly1};
        }
        return result;

    } // place_labels

} // namespace ae::map_draw

// ----------------------------------------------------------------------
