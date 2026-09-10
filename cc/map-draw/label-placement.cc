#include <algorithm>
#include <array>
#include <cmath>
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

        // Cost weights. Ink/off-canvas overlap must dominate everything else: a label that
        // covers a point is always worse than a label that merely sits further away. The
        // distance terms are deliberately strong (and superlinear) — a label that wanders to
        // the far side of the map is technically collision-free but reads as belonging to
        // nothing, which is worse than grazing a point or two.
        constexpr double kWeightInk = 25.0;           // per unit of (overlap area / em^2) with map ink
        constexpr double kWeightOffCanvas = 400.0;    // per unit of (area / em^2) outside the image
        constexpr double kWeightLabel = 90.0;         // per unit of (overlap area / em^2) with another label
        constexpr double kWeightGap = 4.0;            // per em of clear distance from the point
        constexpr double kWeightGapSquared = 1.2;     // per em^2 — keeps labels from drifting away
        constexpr double kWeightDirection = 1.5;      // deviating from "below the point"
        constexpr double kWeightLeader = 1.5;         // a tether is a cost, not free
        constexpr double kWeightLeaderOverInk = 12.0; // per em of tether crossing points/pinned labels
        constexpr double kWeightLeaderCross = 6.0;    // two tethers crossing
        constexpr double kWeightLeaderOverText = 8.0; // per em of tether running through another label

        // Clearance kept between a label box and the ink it must avoid, in em.
        constexpr double kBoxPadEm = 0.12;

        struct Rect
        {
            double x0{0.0}, y0{0.0}, x1{0.0}, y1{0.0};
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
        Candidate make_candidate(const LabelRequest& lab, double off_x, double off_y)
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
            // A tether appears only once the label has been pushed clear enough of its point
            // that the reader would otherwise have to guess which point it belongs to. Below
            // that it stays a plain adjacent label, as AD/kateri always draw it.
            const double leader_threshold = std::max(lab.point_radius * 0.6, lab.text_h * 0.75);
            if (gap > leader_threshold && dist > 1.0e-6) {
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

    } // namespace

    // ----------------------------------------------------------------------

    std::vector<LabelPlacement> place_labels(const std::vector<LabelRequest>& labels, const std::vector<LabelObstacle>& obstacles, double canvas_w, double canvas_h)
    {
        std::vector<LabelPlacement> result(labels.size());

        // Pinned labels keep their authored offset verbatim and become obstacles for the rest
        // (an operator-placed label is a fact of the drawing, like a point).
        std::vector<Rect> ink;
        ink.reserve(obstacles.size() + labels.size());
        for (const auto& o : obstacles)
            ink.push_back(Rect{o.x0, o.y0, o.x1, o.y1});

        std::vector<std::size_t> autos; // indexes into `labels` that we actually place
        for (std::size_t i = 0; i < labels.size(); ++i) {
            const Candidate c = make_candidate(labels[i], labels[i].offset_x, labels[i].offset_y);
            result[i] = LabelPlacement{c.offset_x, c.offset_y, c.box.x0, c.box.y0, c.box.x1, c.box.y1, false, 0.0, 0.0, 0.0, 0.0};
            if (labels[i].pinned)
                ink.push_back(c.box);
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
                    Candidate c = make_candidate(lab, dx * s, dy * s);
                    const double pad = em * kBoxPadEm;
                    const Rect padded{c.box.x0 - pad, c.box.y0 - pad, c.box.x1 + pad, c.box.y1 + pad};
                    double cost = 0.0;
                    for (const Rect& r : ink) {
                        cost += kWeightInk * overlap_area(padded, r) / em2;
                        if (c.leader)
                            cost += kWeightLeaderOverInk * segment_in_rect(c.lx0, c.ly0, c.lx1, c.ly1, r) / em;
                    }
                    cost += kWeightOffCanvas * off_canvas_area(c.box, canvas_w, canvas_h) / em2;
                    const auto [nx, ny] = closest_on_rect(c.box, lab.point_x, lab.point_y);
                    const double gap = std::max(0.0, std::hypot(nx - lab.point_x, ny - lab.point_y) - lab.point_radius) / em;
                    cost += kWeightGap * gap + kWeightGapSquared * gap * gap;
                    cost += kWeightDirection * dir_pen;
                    if (c.leader)
                        cost += kWeightLeader;
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
