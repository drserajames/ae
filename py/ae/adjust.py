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
import importlib.util
from pathlib import Path

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

    def save(self, filename):
        "Write the adjusted chart to *filename* (compression by extension)."
        self.chart.write(str(filename))
        return Path(filename)

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
