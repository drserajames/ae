"""
ae.adjust — programmatic antigenic-map adjustment (the agent-facing "zero_do").

This is the scriptable equivalent of AD's interactive `acmacs_py.zero_do_5` map
fine-tuning (the report's `adjust/0do` stage). An agent (or a person writing a
script) selects points — including by geometry, `pt.inside(figure)` — moves /
flips them, relaxes, and writes the adjusted `.ace`. No GUI required; rendering a
snapshot for review is a separate optional step (drive kateri via `ae.utils.kateri`).

It is the programmatic half of the combined adjust design (see
py/ae/report/MIGRATION.md Stage B); the interactive half is kateri point-dragging.
Both share the same `ae_backend.chart_v3` core: `set_coordinates` / `Layout.__setitem__`
to write point coordinates, and `set_unmovable` so a subsequent `relax()` keeps moved
points pinned.

Example::

    from ae.adjust import Adjust
    adj = Adjust("prestyled.ace")
    region = adj.figure([[2, 8], [10, 8], [10, 15], [2, 15]])
    outliers = adj.select_antigens(lambda pt: pt.inside(region))
    adj.move(outliers, to=[1, 1])      # re-seed the outliers
    adj.relax()                         # let the map settle
    adj.save("adjusted.ace")

**Coordinate frames.** `figure()`, `move()`, `set_coordinates()`, `move_by()` and
`flip_over_line()` read their coordinates in AD's `"viewport-origin"` frame by default —
an offset from the origin of the map viewport, in transformed (drawn) space — so polygons
and destinations copied out of an AD `adjust/0do` script mean here exactly what they meant
there. The viewport is derived from the chart, as AD does (`Adjust.viewport()`), and — again
as AD does — **computed once and then frozen** for the life of the `Adjust`, so a move
part-way through a script does not shift the frame under the polygons that follow it. It is
not the report's per-map viewport setting. Pass `frame="map-not-transformed"` to author in
raw layout coordinates instead, or `frame="map-transformed"` for absolute drawn ones.

**Running a whole AD `adjust/0do` script.** `Zd` and `Slot` at the bottom of this module
reproduce AD's `acmacs_py.zero_do_5` step machinery — the `<slot_name>/` step directories,
the `NN` snapshot numbering, the `99.ace` final chart and the slot-to-slot chaining that
`map-adjustments.txt` records as provenance. `slot.modify(...)` styles the selection and
`slot.plot()` draws the numbered snapshot with ae's native headless renderer (see
`ae.adjust_render`), so the analyst's select -> look -> re-cut-the-polygon loop works; the
one piece still missing is the outline of the polygon itself, which needs new C++.
"""

import sys
import glob
import math
import asyncio
import importlib.util
from pathlib import Path
from contextlib import contextmanager
from typing import TYPE_CHECKING

from ae import adjust_render

if TYPE_CHECKING:
    from ae.utils.kateri import Communicator

# ----------------------------------------------------------------------

class Figure:
    """A closed polygon in raw (untransformed) layout coordinates — the frame the
    chart stores and `Point.coords` reports. `contains()` is a ray-casting
    point-in-polygon test, used by `Point.inside()`.

    Build one with `Adjust.figure()`, which converts the vertices from whichever
    frame they are authored in (by default AD's `viewport-origin`) into this one.
    Constructing `Figure` directly takes the vertices as already-untransformed."""

    def __init__(self, vertices, source_frame: str = "map-not-transformed", source_vertices=None):
        """Store the polygon vertices (first two coordinates of each). *source_frame*
        and *source_vertices* are diagnostics only — what the caller authored, before
        `Adjust.figure()` converted it."""
        self.vertices = [list(v)[:2] for v in vertices]
        self.source_frame = source_frame
        self.source_vertices = [list(v)[:2] for v in (source_vertices or vertices)]

    def contains(self, point) -> bool:
        """Ray-casting point-in-polygon test; False for a None point."""
        if point is None:
            return False
        x, y = point[0], point[1]
        verts = self.vertices
        n = len(verts)
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = verts[i]
            xj, yj = verts[j]
            if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        return inside


class Point:
    """Selection context passed to predicates. Attribute access delegates to the
    underlying antigen/serum (so `pt.name()`, `pt.sequence_aa()`, `pt.semantic`,
    `pt.designation()` work), plus geometry: `pt.point_no`, `pt.coords`, `pt.x`,
    `pt.y`, and `pt.inside(figure)`.

    It also carries AD's sequence/clade spellings — `pt.aa["<pos><AA>"]`,
    `pt.clade_any_of([...])`, `pt.has_clade(...)`, `pt.has_any_clade_of([...])` — so a
    predicate copied out of an `adjust/0do` script means here what it meant there. AD
    binds those on `SelectionDataAntigen`/`SelectionDataSerum`
    (`acmacs-py/cc/py-antigen.cc:140,156`); ae binds the same data under different
    names (`Antigen.sequence_aa()`, `Antigen.semantic.clades()`), so these are thin
    aliases, not new logic."""

    __slots__ = ("point_no", "no", "kind", "coords", "_obj")

    def __init__(self, point_no, no, kind, obj, coords):
        """Bind a selection point: its global layout index, antigen/serum index, kind
        ("antigen"/"serum"), underlying object and coordinates."""
        self.point_no = point_no      # global layout index
        self.no = no                  # antigen index, or serum index
        self.kind = kind              # "antigen" | "serum"
        self.coords = coords          # [x, y] or None (disconnected)
        self._obj = obj               # the ae_backend Antigen/Serum

    def __getattr__(self, name):
        """Delegate unknown attributes to the underlying antigen/serum."""
        return getattr(self._obj, name)

    @property
    def x(self):
        """The point's x coordinate (None if disconnected)."""
        return self.coords[0] if self.coords else None

    @property
    def y(self):
        """The point's y coordinate (None if disconnected)."""
        return self.coords[1] if self.coords else None

    def inside(self, figure: Figure) -> bool:
        """Whether the point lies inside `figure`."""
        return figure.contains(self.coords)

    # -- AD predicate spellings (sequence / clade) ----------------------
    #
    # AD's adjust predicates are `geometry AND sequence-or-clade`, e.g.
    #   lambda ag: ag.aa["<pos><AA>"] and ag.inside(path)
    #   lambda ag: ag.clade_any_of([...]) and ag.inside(path)
    # ae reaches the same data through `sequence_aa()` / `semantic.clades()`. Keeping
    # AD's names here is what lets a 0do predicate port verbatim.

    @property
    def aa(self):
        """The aligned AA sequence, indexable as AD's `ag.aa[...]`, with the query
        spelled `"<pos><AA>"`: `pt.aa["5A"]` (position 5 is A), `pt.aa["!5A"]` (is
        not), `pt.aa["5A 7N"]` (all of them).

        A point with no sequence answers False to a positive query and True to a
        negated one — it has no position 5, so position 5 is not A. That is AD's
        behaviour too, verified against the real extension across a report cycle."""
        return self._obj.sequence_aa()

    def clades(self) -> list:
        """The point's clades (empty if it carries none)."""
        return list(self._obj.semantic.clades())

    def has_clade(self, clade: str) -> bool:
        """Whether the point carries *clade* — plain membership of the semantic
        `clades` array, which is what `SemanticAttributes::has_clade`
        (`cc/chart/v3/semantic.hh`) does. Reimplemented here over `clades()` because
        C++ binds `has_clade` on `SelectionData` but not on `SemanticAttributes`."""
        return clade in self.clades()

    def has_any_clade_of(self, clades) -> bool:
        """Whether the point carries any clade in *clades*
        (`SemanticAttributes::has_any_clade_of`)."""
        mine = self.clades()
        return any(clade in mine for clade in clades)

    def clade_any_of(self, clades) -> bool:
        """AD's spelling of `has_any_clade_of` (`acmacs-py/cc/py-antigen.cc:14`,
        `clades().exists_any_of`). Same test, kept so 0do predicates port verbatim."""
        return self.has_any_clade_of(clades)

    def is_sequenced(self) -> bool:
        """Whether the point carries an AA sequence at all."""
        return bool(self._obj.sequence_aa())

# ----------------------------------------------------------------------

class Adjust:
    """Programmatic adjustment of one projection of a chart."""

    def __init__(self, chart, projection_no: int = 0, ae_backend=None):
        """Open `chart` (a `Chart` or a path) for adjusting projection `projection_no`.
        Raises ValueError if the chart has no projection to adjust."""
        self._be = ae_backend or _import_ae_backend()
        if isinstance(chart, (str, Path)):
            chart = self._be.chart_v3.Chart(str(chart))
        self.chart = chart
        self.projection_no = projection_no
        self.number_of_antigens = chart.number_of_antigens()
        self.number_of_sera = chart.number_of_sera()
        self._viewport = None
        if chart.number_of_projections() == 0:
            raise ValueError("chart has no projection to adjust — relax it first")

    # -- projection / coordinates ---------------------------------------

    @property
    def projection(self):
        """The projection being adjusted."""
        return self.chart.projection(self.projection_no)

    @property
    def layout(self):
        """The projection's layout."""
        return self.projection.layout()

    def coordinates(self, point_no):
        """Coordinates of one point as a list, or None if it is disconnected."""
        c = self.layout[point_no]
        return list(c) if c is not None else None

    # -- coordinate frames ----------------------------------------------
    #
    # AD's adjust scripts author every polygon and every move destination in the
    # *viewport-origin* frame (acmacs_py.zero_do_5.path/move default,
    # acmacs-map-draw/cc/coordinates.cc `Coordinates::viewport`): the literal is an
    # offset from the origin of the map viewport, in *transformed* map space. The
    # chart itself stores untransformed coordinates. Reading such a literal as a raw
    # layout coordinate selects the wrong points — silently, with no error — so the
    # conversion below is what makes an AD `adjust/0do` script portable verbatim.

    FRAMES = ("viewport-origin", "map-transformed", "map-not-transformed")

    @property
    def transformation(self) -> tuple:
        """The projection's 2D transformation as `(a, b, c, d)`; a transformed point is
        `[x*a + y*c, x*b + y*d]` (`cc/chart/v3/transformation.hh::transform`, which
        carries no translation in 2D)."""
        tr = self.projection.transformation()
        if (as_vector := getattr(tr, "as_vector", None)) is not None:
            values = [float(v) for v in as_vector()]
        else:
            # ae_backend.chart_v3.Transformation currently binds only __str__, which
            # formats Transformation::as_vector() at full precision, e.g. "[1, 0, 0, 1]".
            values = [float(v) for v in str(tr).strip("[] ").split(",")]
        if len(values) != 4:
            raise ValueError(f"expected a 2D transformation (4 values), got {values!r}")
        return tuple(values)

    def transform(self, point) -> list:
        """Map *point* from raw layout coordinates into transformed (drawn) ones."""
        a, b, c, d = self.transformation
        x, y = float(point[0]), float(point[1])
        return [x * a + y * c, x * b + y * d]

    def inverse_transform(self, point) -> list:
        """Map *point* from transformed (drawn) coordinates back into raw layout ones."""
        a, b, c, d = self.transformation
        det = a * d - b * c
        if det == 0.0:
            raise ValueError(f"projection transformation {self.transformation} is singular")
        x, y = float(point[0]), float(point[1])
        return [(x * d - y * c) / det, (y * a - x * b) / det]

    def transformed_layout(self) -> list:
        """The layout with the projection transformation applied — the frame AD draws
        in, and the frame `viewport()` is computed from. `None` for disconnected points."""
        a, b, c, d = self.transformation
        out = []
        for point_no in range(len(self.layout)):
            co = self.coordinates(point_no)
            out.append(None if co is None else [co[0] * a + co[1] * c, co[0] * b + co[1] * d])
        return out

    def viewport(self) -> tuple:
        """AD's map viewport as `(origin_x, origin_y, size)`.

        **Computed once, then frozen** — and that is deliberate, because AD freezes it
        too. `ChartDraw::MapViewport` caches the viewport and only recomputes when
        `recalculate_` is set, which happens in exactly two places, `ChartDraw::rotate`
        and `ChartDraw::flip` (acmacs-map-draw/cc/draw.cc:106,117). Moving points and
        relaxing do **not** invalidate it, so every polygon and every move destination
        in one AD slot is resolved against the same frame, even after earlier steps have
        moved points around.

        Recomputing per call instead — which this did until 2026-09-11 — silently shifts
        the frame under the `path → move → path` pattern that real `adjust/0do` scripts
        use. Measured against the real AD extension over this cycle's 18 readable maps:
        after a bulk move, AD's frame shifts by 0 on every map and the per-call reading
        shifted by 3.7–7.5 map units on every map — bigger than most polygons.

        Call `invalidate_viewport()` (or `rotate`/`flip_ew`/`flip_ns`, which do it for
        you) to force a recomputation, exactly as AD does.

        The computation itself is `ChartDraw::calculate_viewport()`: the minimum bounding
        ball of the *transformed* layout (acmacs-chart-2/cc/bounding-ball.cc), then
        `whole_width()` — round the diameter up to a whole number about the same centre.
        Disconnected points are ignored, as in AD's `Layout::area()`.

        Note this is *not* the report's per-map `viewport()` setting, and not the
        recentered frame `cc/map-draw/styled-draw.cc` uses for report figures."""
        if self._viewport is None:
            self._viewport = self._calculate_viewport()
        return self._viewport

    def invalidate_viewport(self):
        """Drop the cached viewport so the next `viewport()` recomputes it from the
        current layout — AD's `MapViewport::set_recalculate()`."""
        self._viewport = None

    def _calculate_viewport(self) -> tuple:
        "Compute the viewport from the current transformed layout (see `viewport`)."
        points = [p for p in self.transformed_layout() if p is not None]
        if not points:
            raise ValueError("chart has no points with coordinates: cannot compute a viewport")
        min_x = min(p[0] for p in points)
        max_x = max(p[0] for p in points)
        min_y = min(p[1] for p in points)
        max_y = max(p[1] for p in points)
        # BoundingBall(area.min, area.max): the circle through the two opposite corners.
        cx, cy = (min_x + max_x) / 2.0, (min_y + max_y) / 2.0
        diameter = math.hypot(min_x - max_x, min_y - max_y)
        for px, py in points:                                   # BoundingBall::extend
            dx, dy = px - cx, py - cy
            d2 = dx * dx + dy * dy
            if d2 > diameter * diameter * 0.25:
                dist = math.sqrt(d2)
                diameter = diameter * 0.5 + dist
                difference = dist - diameter * 0.5
                cx = (diameter * 0.5 * cx + difference * px) / dist
                cy = (diameter * 0.5 * cy + difference * py) / dist
        size = float(math.ceil(diameter))                       # Viewport::whole_width
        return (cx - size / 2.0, cy - size / 2.0, size)

    def to_layout_coordinates(self, point, frame: str = "viewport-origin") -> list:
        """Convert *point* from *frame* into raw layout coordinates (what the chart
        stores and `set_coordinates` writes). Frames: `"viewport-origin"` (AD's
        default — an offset from the viewport origin, in transformed space),
        `"map-transformed"`, `"map-not-transformed"` (no conversion)."""
        if frame == "map-not-transformed":
            return [float(point[0]), float(point[1])]
        if frame == "viewport-origin":
            origin_x, origin_y, _ = self.viewport()
            point = [origin_x + float(point[0]), origin_y + float(point[1])]
        elif frame != "map-transformed":
            raise ValueError(f"unrecognized frame: {frame!r} (expected one of {self.FRAMES})")
        return self.inverse_transform(point)

    def to_layout_offset(self, offset, frame: str = "viewport-origin") -> list:
        """Convert a *displacement* (not a position) from *frame* into raw layout
        coordinates. A displacement is invariant to the viewport origin, so
        `"viewport-origin"` and `"map-transformed"` agree here."""
        if frame == "map-not-transformed":
            return [float(offset[0]), float(offset[1])]
        if frame not in self.FRAMES:
            raise ValueError(f"unrecognized frame: {frame!r} (expected one of {self.FRAMES})")
        return self.inverse_transform(offset)

    # -- selection ------------------------------------------------------

    def figure(self, vertices, frame: str = "viewport-origin") -> Figure:
        """Build a `Figure` (closed polygon) from `vertices`, authored in *frame*
        (default AD's `"viewport-origin"`, so a polygon copied out of an `adjust/0do`
        script means here what it meant there).

        The vertices are converted into raw layout coordinates, which is where
        `Point.inside()` tests them. That is equivalent to AD's transformed-space test:
        the transformation is an invertible linear map, so it preserves which points
        lie inside the polygon."""
        return Figure([self.to_layout_coordinates(v, frame) for v in vertices],
                      source_frame=frame, source_vertices=vertices)

    def select_antigens(self, predicate=None) -> list[int]:
        """Return the point indices of antigens for which *predicate(Point)* is
        true (all antigens if predicate is None). The Point exposes geometry
        (`inside`/`coords`) and delegates to the antigen."""
        lay = self.layout
        out = []
        for no, ag in self.chart.select_all_antigens():
            c = lay[no]
            pt = Point(no, no, "antigen", ag, list(c) if c is not None else None)
            if predicate is None or predicate(pt):
                out.append(no)
        return out

    def select_sera(self, predicate=None) -> list[int]:
        """Like `select_antigens` but for sera; returned indices are global point
        indices (number_of_antigens + serum_no)."""
        lay = self.layout
        nag = self.number_of_antigens
        out = []
        for sr_no, sr in self.chart.select_all_sera():
            pno = nag + sr_no
            c = lay[pno]
            pt = Point(pno, sr_no, "serum", sr, list(c) if c is not None else None)
            if predicate is None or predicate(pt):
                out.append(pno)
        return out

    # -- moves ----------------------------------------------------------

    def set_coordinates(self, points, to, frame: str = "viewport-origin"):
        """Set every point in *points* to coordinate *to*, authored in *frame*
        (no relax). See `to_layout_coordinates` for the frames."""
        target = self.to_layout_coordinates(to, frame)
        proj = self.projection
        for pno in points:
            proj.set_coordinates(pno, target)

    def move(self, points, to, frame: str = "viewport-origin", pin: bool = False, relax: bool = False):
        """Move every selected point to *to*, authored in *frame* (default AD's
        `"viewport-origin"`, matching `slot.move(sel, to=[x, y])`). With *pin*, mark
        them unmovable so a later relax keeps them there. With *relax*, relax
        immediately. The common "re-seed outliers" pattern is `move(sel, to=[x,y])`
        then a separate `relax()` (default: no pin, no auto-relax — as in AD)."""
        self.set_coordinates(points, to, frame)
        if pin:
            self.pin(points)
        if relax:
            self.relax()

    def move_by(self, points, offset, frame: str = "viewport-origin"):
        """Translate every selected point by *offset* = [dx, dy], authored in *frame*.
        *offset* is a displacement, so the viewport origin does not enter (see
        `to_layout_offset`)."""
        proj = self.projection
        lay = self.layout
        dx, dy = self.to_layout_offset(offset, frame)
        for pno in points:
            c = lay[pno]
            if c is not None:
                proj.set_coordinates(pno, [c[0] + dx, c[1] + dy])

    def flip_over_line(self, points, p1, p2, frame: str = "viewport-origin"):
        """Reflect every selected point across the line through *p1* and *p2*, both
        authored in *frame* (AD passes this line through `slot.path(..., close=False)`,
        i.e. also viewport-origin-relative)."""
        proj = self.projection
        lay = self.layout
        ax, ay = self.to_layout_coordinates(p1, frame)
        bx, by = self.to_layout_coordinates(p2, frame)
        dx, dy = bx - ax, by - ay
        dd = dx * dx + dy * dy
        if dd == 0.0:
            raise ValueError("flip_over_line: p1 and p2 are the same point")
        for pno in points:
            c = lay[pno]
            if c is None:
                continue
            t = ((c[0] - ax) * dx + (c[1] - ay) * dy) / dd
            projx, projy = ax + t * dx, ay + t * dy
            proj.set_coordinates(pno, [2 * projx - c[0], 2 * projy - c[1]])

    # -- whole-map orientation ------------------------------------------
    #
    # These change the projection *transformation*, not the stored coordinates, so
    # they move the drawn map under the viewport — which is why they are the only
    # two operations AD invalidates the cached viewport for (draw.cc:106,117).

    def rotate(self, angle: float):
        """Rotate the whole map by *angle*. AD's `ChartDraw::rotate` takes **radians**
        (`rotate_radians`); the ae backend it delegates to reads a magnitude below 3.15
        as radians and anything larger as degrees. Invalidates the viewport."""
        self.projection.transformation().rotate(angle)
        self.invalidate_viewport()

    def flip_ew(self):
        "Flip the whole map east-west (about the horizontal axis). Invalidates the viewport."
        self.projection.transformation().flip_ew()
        self.invalidate_viewport()

    def flip_ns(self):
        "Flip the whole map north-south (about the vertical axis). Invalidates the viewport."
        self.projection.transformation().flip_ns()
        self.invalidate_viewport()

    # -- pinning / optimization -----------------------------------------

    def pin(self, points):
        "Mark *points* unmovable (a subsequent relax keeps them fixed)."
        self.projection.set_unmovable(list(points))

    def unpin_all(self):
        "Clear all unmovable points."
        self.projection.set_unmovable([])

    def relax(self, rough: bool = False):
        "Re-optimize the projection (respecting unmovable points)."
        self.projection.relax(rough=rough)

    def relax_capturing_intermediates(self, rough: bool = False):
        """Relax this projection in place (all points free), returning the optimiser's
        per-iteration intermediate layouts as a list of `(coords, stress)` — `coords`
        is one `[x, y]` per point (`None` for disconnected), in layout order. The
        projection is left holding the final relaxed layout. Sample these to animate a
        relax (see `adjust_from_kateri`)."""
        return self.projection.relax_capturing_intermediates(rough=rough)

    def stress(self) -> float:
        """Current stress of the projection."""
        return self.projection.stress()

    # -- comparison / output --------------------------------------------

    def procrustes(self, other, scaling: bool = False, match: str = "strict",
                   other_projection_no: int = 0):
        """Procrustes this projection against *other* (a Chart or path) on common
        antigens/sera; returns the `procrustes_data_t` (`.rms`, `.transformation`,
        `.secondary_transformed`)."""
        if isinstance(other, (str, Path)):
            other = self._be.chart_v3.Chart(str(other))
        common = self._be.chart_v3.CommonAntigensSera(self.chart, other, match)
        return self._be.chart_v3.procrustes(
            self.projection, other.projection(other_projection_no), common, scaling)

    def orient_to(self, master):
        """Re-orient this projection to best match *master* (a Chart or path) via
        procrustes. Only the projection *transformation* (rotation / reflection /
        translation) is changed — the raw coordinates are untouched — so pinned
        points keep their stored coordinates while the whole layout is rotated
        into *master*'s frame. Used after `relax()` to undo arbitrary MDS
        re-orientation before showing the result."""
        if isinstance(master, (str, Path)):
            master = self._be.chart_v3.Chart(str(master))
        self.chart.orient_to(master, self.projection_no)

    def point_sequences(self, points, nuc: bool = False) -> list:
        """`(designation, sequence)` for each of *points* (point indices, so sera are
        `number_of_antigens + serum_no`), for `compare_sequences`.

        Unsequenced points are kept, with their empty sequence, because AD keeps them: its
        `subset_to_compare_selected_t` iterates the whole selection and a zero-length
        sequence simply contributes to no position counter."""
        result = []
        for point_no in points:
            if point_no < self.number_of_antigens:
                obj = self.chart.antigen(point_no)
            else:
                obj = self.chart.serum(point_no - self.number_of_antigens)
            result.append((obj.designation(),
                           obj.sequence_nuc() if nuc else obj.sequence_aa()))
        return result

    def compare_sequences(self, set1, set2, output=None, names=("1", "2"),
                          nuc: bool = False, open: bool = False):
        """Compare the sequences of two sets of points and, if *output* is given, write
        the comparison HTML there.

        Port of AD's `chart_draw.compare_sequences(set1=, set2=, output=, open=)`
        (`acmacs-py/cc/py-mapi.cc:191`): the two selections become groups named "1" and
        "2", the amino acids at every position are counted per group, and the positions
        where more than one amino acid occurs across both groups are the ones reported.
        The comparison and the HTML viewer are ae's own
        (`ae.sequences.compare`, shared with `bin/seqdb-compare-sequences`), so the markup
        differs from AD's; the substance — which positions differ, and with which amino
        acids at what frequency — is the same computation.

        *set1* / *set2* are lists of point indices, as `select_antigens` returns. Returns
        the `ae.sequences.compare.Comparison`."""
        from ae.sequences.compare import compare_sequences as _compare_sequences
        groups = {name: self.point_sequences(points, nuc=nuc)
                  for name, points in zip(names, (set1, set2))}
        return _compare_sequences(groups, output=output, open=open)

    def snapshot(self):
        "An independent clone of the current chart (round-trips through json)."
        return self._be.chart_v3.chart_from_json(self.chart.export())

    def save(self, filename):
        "Write the adjusted chart to *filename* (compression by extension)."
        self.chart.write(str(filename))
        return Path(filename)

# ----------------------------------------------------------------------
# The Zd / Slot step chain — ae's port of AD's acmacs_py.zero_do_5
# ----------------------------------------------------------------------
#
# An AD `adjust/0do` script is a sequence of *slots*. Each slot is a function decorated
# with `@zd.slot`; the decorator runs it immediately, inside a context manager that
#
#   * names the slot from the function's `__qualname__`, with the enclosing function's
#     `<locals>` replaced by a two-digit slot counter — so a `move_156K` nested in
#     `move_156N_outliers` becomes `move_156N_outliers.01.move_156K`;
#   * gives it a directory of that name, into which snapshots are written as `NN.pdf`,
#     numbered from 00 in the order they are taken;
#   * on exit writes the adjusted chart to `99.ace` in that directory.
#
# Those paths are the provenance the report records — `map-adjustments.txt` refers to
# charts as e.g. `adjust/move_outliers.00.move_right_outliers/99.ace` — so the naming and
# numbering are load-bearing, not cosmetic. A slot chains onto the previous one by
# assigning `slot.chart_filename = <the previous slot function>`: the decorator has by
# then rebound that name to the previous slot's return value, conventionally its
# `final_ace()` path.
#
# What is NOT ported yet (Stage B step 4, the review loop): styling and rendering. AD's
# `slot.modify(...)`, the `modify=` argument of `select_*`, and the `outline`/`fill`
# arguments of `slot.path` all exist here and are recorded, but draw nothing, and no PDF
# or PNG is produced. Snapshot *numbering* is still tracked so that the step numbers do
# not shift once rendering lands.


class Zd:
    """The script-level context of an AD `adjust/0do` run: it hands out numbered slots.

    Port of `acmacs_py.zero_do_5.Zd`. Use it as `ae.adjust` scripts and AD scripts both
    do — decorate each step with `@zd.slot`::

        def outliers_moved(zd: Zd):
            @zd.slot
            def move_outliers(slot: Slot):
                slot.chart_filename = SOURCE
                ...
                return slot.final_ace()
    """

    def __init__(self, cmd=None, directory=None):
        """*cmd* is the command being run (recorded only, as in AD). *directory* is where
        slot directories are created; it defaults to the current directory, which is what
        AD does and what the recorded `adjust/<slot>/99.ace` paths assume."""
        self.num_slots = 0
        self.directory = Path(directory) if directory is not None else Path()
        self.cmd = cmd
        self.section(cmd)

    def section(self, cmd):
        "Hook for a subclass to announce a new section; AD's is a no-op too."

    def slot(self, func):
        """Decorator: run *func* as the next slot and return whatever it returns.

        The slot's name — and so its directory — is `func.__qualname__` with `<locals>`
        replaced by the slot number, reproducing AD's scheme exactly
        (`zero_do_5.py:38`)."""
        slot_name = func.__qualname__.replace("<locals>", f"{self.num_slots:02d}")
        self.num_slots += 1
        with self.slot_context(slot_name) as sl:
            return func(sl)

    @contextmanager
    def slot_context(self, slot_name: str):
        "Run a `Slot` named *slot_name*, finalizing it (99.ace) however the body exits."
        slot = Slot(self, slot_name)
        try:
            yield slot
        finally:
            slot.finalize()


class Slot:
    """One step of an adjust script: a directory, numbered snapshots, and a final chart.

    Port of `acmacs_py.zero_do_5.Slot`, delegating the actual chart work to `Adjust`
    (reachable as `slot.adjust` if you want the ae-native API). Set `chart_filename` to
    the chart this step starts from — either a path, or the value a previous slot
    returned — and the chart is opened lazily on first use.
    """

    #: Called as `renderer(slot, path, png=bool, open=bool)` when a snapshot is taken.
    #: The default draws the styled map with ae's native headless renderer
    #: (`ae.adjust_render.SnapshotRenderer`). Set it to `None` to number the snapshots
    #: without drawing them, or to your own callable to draw them differently.
    renderer = adjust_render.SnapshotRenderer()

    #: Named style the snapshot is drawn on top of (`c["R"]`). `None` auto-detects the
    #: chart's own clade colouring; `""` uses the renderer's plain grey default, which is
    #: what AD's `reset_plot_spec` produced. See `ae.adjust_render.default_base_style`.
    base_style = None

    #: Write `99.png` beside `99.pdf` when the slot finalizes, as AD does.
    make_final_png = True

    def __init__(self, zd: Zd, slot_name: str):
        "Create the slot; nothing touches the filesystem until a chart or path is needed."
        self.zd = zd
        self.slot_name = slot_name
        self.step = 0
        self.final_step = 99
        self._chart_filename = None
        self._adjust = None
        self.export_final_ace = True
        self.snapshots = []          # [(step, Path)] — every snapshot this slot took
        self.styling = []            # modify()/path() requests, drawn by plot() — see modify()
        self._warned_path = False

    # -- the chart this slot works on -----------------------------------

    @property
    def chart_filename(self):
        "The chart this slot starts from."
        return self._chart_filename

    @chart_filename.setter
    def chart_filename(self, filename):
        """Set the starting chart, discarding any chart already opened. Accepts a path,
        or whatever a previous slot returned (`slot.chart_filename = move_156N`), which
        by convention is that slot's `final_ace()`."""
        self._chart_filename = Path(filename) if filename is not None else None
        self._adjust = None

    @property
    def adjust(self) -> "Adjust":
        """The `Adjust` for this slot's chart, opened on first use (AD's
        `make_chart_draw`). Raises if `chart_filename` was never set."""
        if self._adjust is None:
            if self._chart_filename is None:
                raise RuntimeError("slot: chart_filename is not set")
            self._adjust = Adjust(self._chart_filename)
        return self._adjust

    @property
    def chart(self):
        "The underlying `ae_backend.chart_v3.Chart`."
        return self.adjust.chart

    def final_chart(self):
        """The chart as it now stands, opening `chart_filename` if the slot never got
        round to it (AD's `final_chart` goes through `make_chart_draw` and does the same,
        so a slot that set a filename and then failed still exports its source chart).
        None if there is no chart to open, or it cannot be adjusted."""
        if self._adjust is None and self._chart_filename is None:
            return None
        try:
            return self.adjust.chart
        except (ValueError, RuntimeError) as err:
            print(f">> {self.slot_name}: no chart to export ({err})", file=sys.stderr)
            return None

    # -- paths ----------------------------------------------------------

    def subdir(self) -> Path:
        """This slot's directory, created if needed. As in AD, `parents=False`: the
        parent (normally `adjust/`) must already exist."""
        subd = self.zd.directory / self.slot_name
        subd.mkdir(parents=False, exist_ok=True)
        return subd

    def final_ace(self) -> Path:
        """This slot's final chart path, `<slot_name>/99.ace` — the path the report's
        `map-adjustments.txt` records and the next slot chains onto. Creates the slot
        directory as a side effect, as AD's does."""
        return self.subdir().joinpath(f"{self.final_step:02d}.ace")

    def finalize(self):
        """Take the final (99) snapshot and write `99.ace`. Called for you when the slot
        body exits, however it exits."""
        if self._adjust is None and self._chart_filename is None:
            return                                  # slot never touched a chart
        chart = self.final_chart()
        self.plot(step=self.final_step)
        if self.export_final_ace and chart is not None:
            ace = self.final_ace()
            chart.write(str(ace))
            print(f">>> final {self.slot_name}: {ace}", file=sys.stderr)

    # -- snapshots ------------------------------------------------------

    def plot(self, step: int = None, infix: str = None, png: bool = False, open: bool = False):
        """Draw snapshot *step* (the next in sequence if None) as `NN[.infix].pdf` in this
        slot's directory, styled by everything `modify()` has been told so far.

        The drawing is done by `renderer` — by default
        `ae.adjust_render.SnapshotRenderer`, which renders the semantic style natively and
        never touches the slot's own chart. Set `renderer = None` to keep the numbering
        (which matches AD's) without drawing anything.

        A `.png` is written beside the PDF when *png*, and at the final step when
        `make_final_png`, as AD does."""
        if self._adjust is None and self._chart_filename is None:
            return None
        if step is None:
            step = self.step
            self.step += 1
        name = f"{step:02d}" + (f".{infix}" if infix else "")
        pdf = self.subdir().joinpath(f"{name}.pdf")
        self.snapshots.append((step, pdf))
        if self.renderer is not None:
            self.renderer(self, pdf, png=png or (step == self.final_step and self.make_final_png),
                          open=open)
        return pdf

    # -- styling --------------------------------------------------------

    def modify(self, selected=None, **kwargs):
        """Style *selected* on this slot's snapshots — AD's `slot.modify`, ported.

        *selected* is a list of point numbers as `select_antigens` / `select_sera` return
        them (a serum is `number_of_antigens + serum_no`). The styling keys are AD's —
        `fill`, `outline`, `outline_width`, `show`, `shape`, `size`, `aspect`, `rotation`,
        `order`, `label`, `legend` — translated to ae semantic-style modifiers by
        `ae.adjust_render.normalize_modify`, which reports anything it has to drop.

        Nothing is applied to the chart here: the request is appended to `slot.styling`
        and turned into a throw-away named style when a snapshot is drawn, so the chart
        this slot writes to `99.ace` carries only the geometry the adjust operations
        produced. Later `modify` calls win over earlier ones on the same point, as
        successive `ChartDraw.modify` calls do in AD."""
        self.styling.append({"kind": "modify", "selected": list(selected or ()),
                             "modifier": adjust_render.normalize_modify(kwargs)})

    def reset_plot_spec(self, snapshot: bool = False):
        """Drop all styling and go back to the plain grey baseline — AD's
        `reset_plot_spec`, which strips the clade colours so a marked selection stands out.

        AD rebuilt that baseline point by point (grey test antigens, transparent reference
        antigens and sera, egg shapes, rotated reassortants). ae's renderer draws exactly
        that when no style says otherwise, so the port is to stop drawing on the chart's
        clade style (`base_style = ""`) and forget the accumulated `modify` requests.
        Sizes differ cosmetically: AD used 10/15 px, the renderer's default is 20/32 —
        which is why real scripts follow this with `modify(..., size=10)`."""
        self.base_style = ""
        self.styling = []
        if snapshot:
            self.plot()

    def color_by_clade(self, mapi_dir=None, style: str = None, snapshot: bool = False):
        """Colour the snapshot by clade — AD's `color_by_clade`, ported to ae's styling.

        AD read a `.mapi` file and turned each clade rule into a `ChartDraw.modify` on the
        legacy plot spec. In ae the same clade colouring is already **on the chart**, as a
        `c["R"]` named style the `prestyle` step baked (`clades`, or `clades-v<N>`), so
        this selects that style as the snapshot's base rather than re-deriving it. Pass
        *style* to name one explicitly. *mapi_dir* is accepted so a ported script runs
        verbatim, and ignored — the chart's own style supersedes it."""
        if mapi_dir is not None:
            print(f">> {self.slot_name}: color_by_clade(mapi_dir=…) ignored — ae takes the "
                  f"clade colouring from the chart's own named style", file=sys.stderr)
        self.base_style = style if style is not None else adjust_render.default_base_style(self.chart)
        if snapshot:
            self.plot()

    # -- geometry -------------------------------------------------------

    def path(self, path, outline: str = None, outline_width: float = 1.0, fill: str = None,
             close: bool = True, coordinates_relative_to: str = "viewport-origin") -> Figure:
        """Build the polygon *path* and return it, for use with `pt.inside(...)`.

        *coordinates_relative_to* is AD's name for the coordinate frame and takes AD's
        values; it defaults, as AD does, to `"viewport-origin"`. *close* is accepted for
        signature compatibility: `Figure.contains` treats the vertex list as closed either
        way, and AD only passes `close=False` when the "polygon" is a line handed to
        `flip_over_line`, where closure is meaningless.

        **`outline`/`fill` are recorded but not drawn.** AD outlines the polygon on the
        snapshot; ae has no polygon primitive above the Cairo surface, so that half needs
        new C++ — see `ae.adjust_render.polygon_support_note`, printed once per slot that
        asks for it. The points the polygon caught are still marked, by the `modify=` that
        normally accompanies it, so the select → look → re-cut loop works without it."""
        figure = self.adjust.figure(path, frame=coordinates_relative_to)
        if outline or fill:
            if not self._warned_path:
                self._warned_path = True
                print(f">> {self.slot_name}: {adjust_render.polygon_support_note()}",
                      file=sys.stderr)
            self.styling.append({"kind": "path", "figure": figure, "outline": outline,
                                 "outline_width": outline_width, "fill": fill})
        return figure

    def select_antigens(self, predicate=None, report=20, modify: dict = None,
                        snapshot: bool = True) -> list[int]:
        "Select antigens (all of them if *predicate* is None); see `_select`."
        return self._select("antigens", predicate, report, modify, snapshot)

    def select_sera(self, predicate=None, report=20, modify: dict = None,
                    snapshot: bool = True) -> list[int]:
        "Select sera (all of them if *predicate* is None); see `_select`."
        return self._select("sera", predicate, report, modify, snapshot)

    def _select(self, kind, predicate, report, modify, snapshot) -> list[int]:
        """Run the selection and return **point indices** (for sera these are
        `number_of_antigens + serum_no`, which is what `move` and friends take).

        *report* prints the first N of them, as AD's does — True for all, an int for a
        cap, False for none. *modify* is recorded, not drawn. *snapshot* advances the
        snapshot counter."""
        select = getattr(self.adjust, "select_" + kind)
        selected = select(predicate)
        print(f">>> {len(selected)} {kind} selected", file=sys.stderr)
        if report:
            limit = len(selected) if report is True else int(report)
            for n, point_no in enumerate(selected):
                if n >= limit:
                    print(f"    ... {len(selected) - limit} {kind} more", file=sys.stderr)
                    break
                print(f"    {n:3d} {point_no:5d} {self._designation(kind, point_no)}",
                      file=sys.stderr)
        if modify:
            # AD lets an analyst comment a styling key out by prefixing it with "?"
            self.modify(selected=selected,
                        **{k: v for k, v in modify.items() if k[:1] != "?"})
        if snapshot:
            self.plot()
        return selected

    def _designation(self, kind, point_no) -> str:
        "Best available name for a point, for the selection report."
        adj = self.adjust
        if kind == "antigens":
            obj = adj.chart.antigen(point_no)
        else:
            obj = adj.chart.serum(point_no - adj.number_of_antigens)
        try:
            return obj.designation()
        except Exception:
            return obj.name()

    def move(self, selected, to=None, flip_over_line=None, snapshot: bool = True):
        """Move *selected* to *to*, and/or reflect them over *flip_over_line* (a pair of
        vertices, or a `Figure` from `slot.path(..., close=False)`). Coordinates are in
        the viewport-origin frame, as AD's are."""
        if to is not None:
            self.adjust.move(selected, to=to)
        if flip_over_line is not None:
            vertices = (flip_over_line.source_vertices
                        if isinstance(flip_over_line, Figure) else flip_over_line)
            self.adjust.flip_over_line(selected, vertices[0], vertices[1])
        if snapshot:
            self.plot()

    # -- optimization ---------------------------------------------------

    def relax(self, grid: bool = False, snapshot: bool = True):
        "Re-optimize the projection, optionally running a grid test afterwards."
        self.adjust.relax()
        if grid:
            self.adjust.chart.grid_test()
        if snapshot:
            self.plot()

    def grid(self, move_relax: int = 0, snapshot: bool = True):
        "Run a grid test; returns the backend's result."
        res = self.adjust.chart.grid_test(move_relax=move_relax)
        if snapshot:
            self.plot()
        return res

    def stress(self) -> float:
        "Current stress of the projection."
        return self.adjust.stress()

    def reset_unmovable(self):
        "Unpin every point (AD's name for `Adjust.unpin_all`)."
        self.adjust.unpin_all()

    def rotate(self, angle: float):
        "Rotate the whole map (see `Adjust.rotate` on the angle's units)."
        self.adjust.rotate(angle)

    def flip(self, direction: str = "ew"):
        "Flip the whole map, `\"ew\"` or `\"ns\"`."
        if direction == "ew":
            self.adjust.flip_ew()
        elif direction == "ns":
            self.adjust.flip_ns()
        else:
            raise ValueError(f"flip: expected 'ew' or 'ns', got {direction!r}")

    def orient_to(self, master):
        """Re-orient this map onto *master* by procrustes.

        Note this leaves the cached viewport alone, because AD's does: `slot.orient_to`
        goes straight to the chart and never passes through `ChartDraw::rotate`/`flip`,
        the only two things that invalidate AD's viewport. Call
        `slot.adjust.invalidate_viewport()` if you want the frame to follow."""
        self.adjust.orient_to(master)

    # -- sequence comparison --------------------------------------------

    def compare_sequences(self, set1, set2, overwrite: bool = False, open: bool = True,
                          nuc: bool = False) -> Path:
        """Write a sequence comparison of *set1* vs *set2* into this slot's directory and
        return its path.

        Port of AD's `Slot.compare_sequences` (`acmacs_py.zero_do_5:387`), including the
        file name it writes — `<chart stem>.compare-seq.html` in `slot.subdir()` — so the
        paths recorded as provenance keep meaning, and its `overwrite=False` behaviour: an
        existing file is left alone.

        *set1* / *set2* are lists of point indices, as `slot.select_antigens` returns.
        The comparison itself is ae's (`ae.sequences.compare`, shared with
        `bin/seqdb-compare-sequences`), so the page's markup is not AD's; what it reports
        is the same computation. No snapshot is taken and the chart is not changed, as in
        AD."""
        fn = self.subdir().joinpath(f"{self.chart_filename.stem}.compare-seq.html")
        print(f">>> {fn}  (compare_sequences)", file=sys.stderr)
        if overwrite or not fn.exists():
            self.adjust.compare_sequences(set1, set2, output=fn, open=open, nuc=nuc)
        else:
            print(f">> {fn} already exists (not overriden)", file=sys.stderr)
        return fn

    def procrustes(self, secondary_chart_file=None, step: int = None, threshold: float = 0.3,
                   png: bool = False, open: bool = False, title=None):
        """Procrustes against *secondary_chart_file* (this slot's own starting chart if
        None) and return the result. AD draws arrows onto the snapshot instead of
        returning numbers; the arrows are Stage B step 5."""
        other = secondary_chart_file if secondary_chart_file is not None else self._chart_filename
        result = self.adjust.procrustes(other)
        self.plot(step=step, infix="pc", png=png, open=open)
        return result


def main(module=None):
    """Run an adjust script from the command line, as AD's `ZD.main()` does: each
    top-level callable in the script is a command, the first one is the default, and the
    chosen one is called with a fresh `Zd`.

    Use it the way an `adjust/0do` script does — `exit(ZD.main())` — after importing this
    module as `ZD`."""
    import argparse

    module = module or sys.modules["__main__"]

    def commands():
        return [name for name, value in vars(module).items()
                if name[0] != "_" and name != "Path" and callable(value)]

    parser = argparse.ArgumentParser(description=module.__doc__)
    parser.add_argument("--command-list", action="store_true", default=False)
    parser.add_argument("command", nargs="?")
    args = parser.parse_args()
    if args.command_list:
        print("\n".join(commands()))
        return 0
    command = args.command or commands()[0]
    return getattr(module, command)(Zd(command))

# ----------------------------------------------------------------------

def _sample_frames(frames, max_frames):
    "Evenly subsample *frames* to at most *max_frames*, always keeping the first and last."
    n = len(frames)
    if max_frames <= 1 or n <= max_frames:
        return list(frames)
    return [frames[round(i * (n - 1) / (max_frames - 1))] for i in range(max_frames)]


def _nearest_orthogonal_2x2(a, b, c, d):
    """Nearest orthogonal matrix (over O(2), reflection allowed) to `H = [[a, b], [c, d]]`
    — the 2×2 case of the SVD polar factor `U·Vᵀ`, i.e. the `Q` maximising `trace(Qᵀ·H)`.
    In 2D the optimum has a closed form: compare the best rotation (`det +1`) against the
    best reflection (`det −1`) and return whichever fits `H` better. Returns a 2×2 list."""
    rot = math.hypot(a + d, c - b)                   # score of the best-fitting rotation
    ref = math.hypot(a - d, b + c)                   # score of the best-fitting reflection
    if rot < 1e-12 and ref < 1e-12:
        return [[1.0, 0.0], [0.0, 1.0]]              # H ≈ 0 (points coincide): identity
    if rot >= ref:
        cos, sin = (a + d) / rot, (c - b) / rot
        return [[cos, -sin], [sin, cos]]             # rotation
    cos, sin = (a - d) / ref, (b + c) / ref
    return [[cos, sin], [sin, -cos]]                 # reflection


def _kabsch_align(reference, frame):
    """Procrustes/Kabsch-align *frame* onto *reference* — translation + rotation +
    reflection, **no scale**. Both are lists of `[x, y]` or `None`, same order/length.
    The optimiser returns each layout in an arbitrary MDS gauge, so without this every
    streamed frame would rotate/flip/fly off-screen relative to what the operator sees;
    aligning onto the pre-relax layout keeps the animation visually stable. Returns a
    new list with `None` preserved for disconnected points.

    Pure-Python (no numpy): kateri maps are 2D, so the cross-covariance `H = Bᶜᵀ·Aᶜ` of
    the centred common points is a 2×2 matrix whose optimal orthogonal factor `Q` has a
    closed form (see `_nearest_orthogonal_2x2`). Each point maps as `q = (p − c_B)·Q + c_A`,
    reproducing the former numpy `R = Vt.T @ U.T` / `p @ R.T` result to machine precision."""
    idx = [i for i in range(len(frame))
           if frame[i] is not None and i < len(reference) and reference[i] is not None]
    if len(idx) < 2:
        return [list(p) if p is not None else None for p in frame]
    if any(len(frame[i]) != 2 or len(reference[i]) != 2 for i in idx):
        raise NotImplementedError("_kabsch_align: only 2D layouts are supported")

    n = len(idx)
    cAx = sum(reference[i][0] for i in idx) / n      # centroid of the target gauge (kept)
    cAy = sum(reference[i][1] for i in idx) / n
    cBx = sum(frame[i][0] for i in idx) / n          # centroid of the frame being aligned
    cBy = sum(frame[i][1] for i in idx) / n

    a = b = c = d = 0.0                              # H = Bᶜᵀ·Aᶜ, 2×2 cross-covariance
    for i in idx:
        bx, by = frame[i][0] - cBx, frame[i][1] - cBy
        ax, ay = reference[i][0] - cAx, reference[i][1] - cAy
        a += bx * ax; b += bx * ay
        c += by * ax; d += by * ay
    (q00, q01), (q10, q11) = _nearest_orthogonal_2x2(a, b, c, d)

    out = []
    for p in frame:
        if p is None:
            out.append(None)
        else:
            ux, uy = p[0] - cBx, p[1] - cBy         # q = (p − c_B)·Q + c_A
            out.append([ux * q00 + uy * q10 + cAx,
                        ux * q01 + uy * q11 + cAy])
    return out


async def adjust_from_kateri(comm: "Communicator", projection_no: int = 0,
                             rough: bool = False, max_frames: int = 40,
                             frame_delay: float = 0.02, save=None) -> "Adjust":
    """Interactive (human-facing) half of the adjust stage — the kateri
    point-drag → relax → animate-in-GUI flow (see py/ae/report/MIGRATION.md Stage B).

    The operator drags antigen/serum points in a running kateri; kateri only
    *moves* points (it does not relax). Pressing "Relax" sends `RLAX`, and this:

      1. pulls the edited chart back over the socket (`get_chart`, a `CHRT` payload);
      2. relaxes it with **all points free to move** — the dragged positions are not
         pinned, they are only better *starting* coordinates that help the optimiser
         escape the local optimum — **capturing the optimiser's intermediate layouts**;
      3. subsamples those to ~`max_frames`, Procrustes/Kabsch-aligns each onto the
         pre-relax layout the operator currently sees (so frames don't flip/fly off
         from the optimiser's arbitrary MDS gauge), and streams each as a `LAYT` frame
         (`{"l": coords, "final": bool}`) — kateri repaints each, animating the relax;
      4. marks the last frame `"final": true` (kateri commits that layout, so a later
         `get_chart` returns the relaxed coordinates); the final frame is the true
         optimum, not just the last captured iterate. Optionally writes the adjusted
         `.ace` (`save=<path>`).

    `frame_delay` paces the stream (~`max_frames` frames over a fraction of a second).
    No full `CHRT` is sent for the result — the `LAYT` stream carries it, and kateri
    keeps its own viewport / plot-style / selection stable across frames.

    Note: nothing is pinned, so the relaxed positions of the dragged points generally
    differ from where the operator dropped them. `get_moved_points` is *not* used here
    — it remains available purely as informational reporting.

    *comm* is a connected ``ae.utils.kateri.Communicator``. Returns the `Adjust`
    wrapping the relaxed chart — the same shared `ae_backend.chart_v3` core the
    programmatic front-end (`Adjust`) uses.
    """
    chart = await comm.get_chart()            # ae_backend.chart_v3.Chart with the operator's edits
    adj = Adjust(chart, projection_no=projection_no)
    npoints = adj.number_of_antigens + adj.number_of_sera
    start = [adj.coordinates(i) for i in range(npoints)]     # pre-relax layout kateri shows
    frames = adj.relax_capturing_intermediates(rough=rough)  # projection now holds the final layout
    final_coords = [adj.coordinates(i) for i in range(npoints)]
    anim = [coords for (coords, _stress) in _sample_frames(frames, max_frames)]
    if anim:
        anim[-1] = final_coords               # commit the true optimum, not just the last iterate
    else:
        anim = [final_coords]                 # 0 iterations captured — commit the (already optimal) layout
    for n, coords in enumerate(anim):
        is_last = n == len(anim) - 1
        comm.send_layout(_kabsch_align(start, coords), final=is_last)
        await comm.drain()
        if frame_delay and not is_last:
            await asyncio.sleep(frame_delay)
    if save is not None:
        adj.save(save)
    return adj

# ----------------------------------------------------------------------

def _import_ae_backend():
    if "ae_backend" in sys.modules:
        return sys.modules["ae_backend"]
    try:
        import ae_backend
        return ae_backend
    except ImportError:
        build = Path(__file__).resolve().parents[2] / "build"
        sos = sorted(glob.glob(str(build / "ae_backend*.so")))
        if not sos:
            raise
        spec = importlib.util.spec_from_file_location("ae_backend", sos[0])
        module = importlib.util.module_from_spec(spec)
        sys.modules["ae_backend"] = module
        spec.loader.exec_module(module)
        return module
