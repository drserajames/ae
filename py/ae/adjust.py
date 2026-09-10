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
there. The viewport is recomputed from the chart, as AD does (`Adjust.viewport()`); it is
not the report's per-map viewport setting. Pass `frame="map-not-transformed"` to author in
raw layout coordinates instead, or `frame="map-transformed"` for absolute drawn ones.
"""

import sys
import glob
import math
import asyncio
import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING

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
    `pt.y`, and `pt.inside(figure)`."""

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

        Recomputed from the chart, never stored — this is `ChartDraw::calculate_viewport()`
        (acmacs-map-draw/cc/draw.cc): the minimum bounding ball of the *transformed*
        layout (acmacs-chart-2/cc/bounding-ball.cc), then `whole_width()` — round the
        diameter up to a whole number about the same centre. Disconnected points are
        ignored, as in AD's `Layout::area()`.

        Note this is *not* the report's per-map `viewport()` setting, and not the
        recentered frame `cc/map-draw/styled-draw.cc` uses for report figures."""
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

    def snapshot(self):
        "An independent clone of the current chart (round-trips through json)."
        return self._be.chart_v3.chart_from_json(self.chart.export())

    def save(self, filename):
        "Write the adjusted chart to *filename* (compression by extension)."
        self.chart.write(str(filename))
        return Path(filename)

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
