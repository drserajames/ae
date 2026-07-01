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
    """A closed polygon in chart (projection) coordinates. `contains()` is a
    ray-casting point-in-polygon test, used by `Point.inside()`."""

    def __init__(self, vertices):
        self.vertices = [list(v)[:2] for v in vertices]

    def contains(self, point) -> bool:
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
        self.point_no = point_no      # global layout index
        self.no = no                  # antigen index, or serum index
        self.kind = kind              # "antigen" | "serum"
        self.coords = coords          # [x, y] or None (disconnected)
        self._obj = obj               # the ae_backend Antigen/Serum

    def __getattr__(self, name):
        return getattr(self._obj, name)

    @property
    def x(self):
        return self.coords[0] if self.coords else None

    @property
    def y(self):
        return self.coords[1] if self.coords else None

    def inside(self, figure: Figure) -> bool:
        return figure.contains(self.coords)

# ----------------------------------------------------------------------

class Adjust:
    """Programmatic adjustment of one projection of a chart."""

    def __init__(self, chart, projection_no: int = 0, ae_backend=None):
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
        return self.chart.projection(self.projection_no)

    @property
    def layout(self):
        return self.projection.layout()

    def coordinates(self, point_no):
        c = self.layout[point_no]
        return list(c) if c is not None else None

    # -- selection ------------------------------------------------------

    def figure(self, vertices) -> Figure:
        return Figure(vertices)

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

    def set_coordinates(self, points, to):
        """Set every point in *points* to coordinate *to* (no relax)."""
        proj = self.projection
        for pno in points:
            proj.set_coordinates(pno, [float(to[0]), float(to[1])])

    def move(self, points, to, pin: bool = False, relax: bool = False):
        """Move every selected point to *to*. With *pin*, mark them unmovable so a
        later relax keeps them there. With *relax*, relax immediately. The common
        "re-seed outliers" pattern is `move(sel, to=[x,y])` then a separate
        `relax()` (default: no pin, no auto-relax)."""
        self.set_coordinates(points, to)
        if pin:
            self.pin(points)
        if relax:
            self.relax()

    def move_by(self, points, offset):
        """Translate every selected point by *offset* = [dx, dy]."""
        proj = self.projection
        lay = self.layout
        dx, dy = float(offset[0]), float(offset[1])
        for pno in points:
            c = lay[pno]
            if c is not None:
                proj.set_coordinates(pno, [c[0] + dx, c[1] + dy])

    def flip_over_line(self, points, p1, p2):
        """Reflect every selected point across the line through *p1* and *p2*."""
        proj = self.projection
        lay = self.layout
        ax, ay = float(p1[0]), float(p1[1])
        bx, by = float(p2[0]), float(p2[1])
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
