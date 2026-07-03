"""Server context shared by the page builders.

Holds the served root, the clades.mapi coloring source, and the map-draw renderer
configuration. Ported from the AD ``directories.py`` ``CladeData`` (the ``VaccineData``
half is dropped — vaccines are handled inside ``map-draw`` at runtime via
``semantic_vaccines.py``, so no ``vaccines.json`` plumbing is needed here).
"""

import json
import os
from pathlib import Path

# ======================================================================


class CladeData:
    """Reads coloring-block names out of a ``clades.mapi`` file.

    ``clades.mapi`` is plain JSON whose top-level keys are coloring blocks (plus a few
    ``?``-prefixed comment keys); the same file map-draw consumes with ``--mapi``. We only
    need the *names* here — the actual colours are applied inside map-draw.
    """

    sSubtypeToCladePrefix = {
        "h1pdm": "clades-A(H1N1)2009pdm",
        "h3": "clades-A(H3N2)",
        "bvic": "clades-B/Vic",
        "byam": "clades-B/Yam",
    }

    def __init__(self, mapi_file: Path | None):
        self.mapi_file = Path(mapi_file) if mapi_file else None
        self._names: list[str] = []
        if self.mapi_file and self.mapi_file.exists():
            self._names = list(json.load(self.mapi_file.open()).keys())

    def names(self):
        return self._names

    def entry_names_for_subtype(self, subtype: str, date_range: list[str]):
        subtype_prefix = self.sSubtypeToCladePrefix.get(subtype)
        if not subtype_prefix:
            return []
        names = sorted(name for name in self._names if name.startswith(subtype_prefix))
        if date_range[1] < "2018":
            filtered_names = [cn for cn in names if "-v" not in cn]   # old clades only
        elif date_range[0] >= "2018":
            filtered_names = [cn for cn in names if "-v" in cn]       # new clades only
        else:
            filtered_names = []
        return filtered_names or names


# ======================================================================


class AppContext:
    """Everything a page/render call needs, replacing AD's ``request.app[...]`` dict."""

    def __init__(self, root: Path, *, mapi_file: Path | None = None, map_draw_exe: str = "map-draw"):
        self.root = Path(root).resolve()
        # Default the mapi file to clades.mapi under the root, if present.
        if mapi_file is None:
            candidate = self.root / "clades.mapi"
            mapi_file = candidate if candidate.exists() else None
        self.mapi_file = Path(mapi_file).resolve() if mapi_file else None
        self.map_draw_exe = map_draw_exe or os.environ.get("MAP_DRAW_EXE", "map-draw")
        self.clade_data = CladeData(self.mapi_file)


# ======================================================================
