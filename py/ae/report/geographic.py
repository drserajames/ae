# Ported from vcm (ssm-report tooling) 2026-0119-tc2/py/vcm/v2/geographic.py, then
# rewired for ae's geo-draw renderer (cc/geo). See py/ae/report/MIGRATION.md.
#
# Geographic time-series maps. The report-side job (TODO #4) is the Python glue:
# extract per-month {location, count} from hidb, write geo-draw's --data JSON, and
# let geo-draw render one PDF per month (named to match what the report embeds:
# geo/<subtype>-<YYYY-MM>.pdf).
#
# Three colouring modes (color_by):
#   "continent" (default) — one dot per location, sized by sqrt(count), continent-coloured.
#                           Records carry flat {name, count}.  (Unchanged from before.)
#   "clade"               — one pie per location; wedges sized by per-clade count, coloured
#                           by clade. Records carry {name, categories:[{name, count}]}.
#                           geo-draw draws the pies + a clade legend.
#   "coloring"            — REPORT-FAITHFUL: one dot per antigen, packed in concentric rings and
#                           coloured by the report's geographic_coloring(subtype) aa/clade `apply`
#                           rules (a Python port of AD ColoringByAminoAcid, using seqdb's
#                           SequenceAA.matches_all). Reproduces AD's `geographic-draw -s
#                           settings.json` maps. Records carry {name, points:[{color, outline,
#                           outline_width, count}]} + top-level point_size/density.
# Clade / aa come from sequence data (seqdb), not hidb directly: each hidb antigen is matched in
# the subtype's seqdb by name/reassortant/passage. Antigens with no resolvable clade -> "unknown"
# ("clade" mode) or the default colouring ("coloring" mode).
#
# Decoupled from ConferenceData: make_geo takes a TimeSeriesRange directly.

import calendar
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from ae.utils.time_series import TimeSeriesRange
from .stat import _import_ae_backend, _norm_date

# ----------------------------------------------------------------------

# report subtype -> hidb virus_type / map title
SUBTYPE_HIDB = {"h1": "A(H1N1)", "h3": "A(H3N2)", "b": "B"}
SUBTYPE_TITLE = {"h1": "A(H1N1)", "h3": "A(H3N2)", "b": "B"}
# report subtype -> seqdb subtype (for clade resolution)
SUBTYPE_SEQDB = {"h1": "A(H1N1)", "h3": "A(H3N2)", "b": "B"}

# ----------------------------------------------------------------------

def _months_in_window(start: str, end: str) -> list[str]:
    """Every month in the half-open [start, end) window as 'YYYY-MM' strings (start/end
    are YYYYMM). Used to pre-seed the periods dict so a map is emitted for *every* month
    in the time-series window, including ones with no hidb data (geo-draw renders an empty
    location list as a blank world map)."""
    months: list[str] = []
    y, m = int(start[:4]), int(start[4:6])
    ey, em = int(end[:4]), int(end[4:6])
    while (y, m) < (ey, em):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return months

# ----------------------------------------------------------------------

def make_geo(geo_dir: Path, time_series: TimeSeriesRange, hidb_dir=None,
             subtypes: list[str] = ["h1", "h3", "b"], ae_backend=None,
             geo_draw: str | None = None, make_index: bool = True, force: bool = False,
             color_by: str = "continent", colorings: dict | None = None,
             point_size: float = 8.0, density: float = 0.8):
    """Render per-month geographic maps for each subtype into *geo_dir* via geo-draw.

    For each subtype, count hidb antigens by (month, location) over the
    *time_series* window, write geo-draw's `--data` records JSON, and run
    `geo-draw --data … --prefix <geo_dir>/<subtype>-` → `<geo_dir>/<subtype>-<YYYY-MM>.pdf`.

    *color_by*:
      "continent" (default) — one continent-coloured dot per location (records carry {name,count}).
      "clade"               — one clade-coloured pie per location, wedges per clade; clade is
                              resolved from seqdb (records carry {name, categories:[{name,count}]}).
      "coloring"            — **report-faithful**: one dot per antigen, packed in rings and
                              coloured by the report's `geographic_coloring(subtype)` aa/clade
                              `apply` rules (resolved via seqdb). This reproduces AD's
                              `geographic-draw -s settings.json` maps. Requires *colorings*
                              = {subtype: geographic_coloring(subtype)} (raw, pre-preprocess);
                              *point_size*/*density* come from `geographic_settings`.
    """
    if color_by not in ("continent", "clade", "coloring"):
        raise ValueError(f"make_geo: color_by must be 'continent', 'clade' or 'coloring', got {color_by!r}")
    if color_by == "coloring" and not colorings:
        raise ValueError("make_geo: color_by='coloring' requires colorings={subtype: geographic_coloring(subtype)}")
    geo_dir = Path(geo_dir)
    geo_dir.mkdir(parents=True, exist_ok=True)
    ae_backend = ae_backend or _import_ae_backend()
    if hidb_dir:
        ae_backend.hidb.set_dir(str(hidb_dir))
    geo_draw = geo_draw or _resolve_geo_draw()
    start, end = _norm_date(time_series.front_YMD()), _norm_date(time_series.after_last_YMD())

    prefixes = {}
    for subtype in subtypes:
        prefix = geo_dir.joinpath(f"{subtype}-")
        if not force and list(geo_dir.glob(f"{subtype}-*.pdf")):
            prefixes[subtype] = prefix
            continue
        try:
            db = ae_backend.hidb.hidb(SUBTYPE_HIDB[subtype])
        except Exception as err:
            print(f">>> geo: skipping {subtype}: hidb load failed: {err}", file=sys.stderr)
            continue
        if color_by == "coloring":
            records = _extract_geo_records_by_coloring(
                db, start, end, ae_backend=ae_backend,
                seqdb_subtype=SUBTYPE_SEQDB.get(subtype, subtype.upper()),
                coloring=colorings[subtype], point_size=point_size, density=density)
        elif color_by == "clade":
            records = _extract_geo_records_by_clade(
                db, SUBTYPE_TITLE.get(subtype, subtype.upper()), start, end,
                ae_backend=ae_backend, seqdb_subtype=SUBTYPE_SEQDB.get(subtype, subtype.upper()))
        else:
            records = _extract_geo_records(db, SUBTYPE_TITLE.get(subtype, subtype.upper()), start, end)
        records_file = geo_dir.joinpath(f"{subtype}-records.json")
        records_file.write_text(json.dumps(records))
        subprocess.check_call([geo_draw, "--data", str(records_file), "--prefix", str(prefix)])
        prefixes[subtype] = prefix

    if make_index and prefixes:
        make_index_html(geo_dir.joinpath("index.html"), prefixes, safari=False)
        make_index_html(geo_dir.joinpath("index.safari.html"), prefixes, safari=True)
    return prefixes

# ----------------------------------------------------------------------

def _extract_geo_records(db, title_prefix: str, start: str, end: str) -> dict:
    """Build geo-draw's `--data` structure: {title_prefix, periods:[{period,
    locations:[{name,count}]}]} from hidb antigens, bucketed by month + location.
    *start*/*end* are YYYYMM (half-open). Undated/location-less antigens are skipped.
    Every month in the window gets a period (empty -> blank map)."""
    periods: dict[str, dict[str, int]] = {p: {} for p in _months_in_window(start, end)}
    for i in range(db.number_of_antigens()):
        ag = db.antigen(i)
        date = ag.date(compact=True)[:6]
        if len(date) != 6 or not (start <= date < end):
            continue
        location = ag.location
        if not location:
            continue
        period = f"{date[:4]}-{date[4:]}"
        periods.setdefault(period, {})
        periods[period][location] = periods[period].get(location, 0) + 1
    return {
        "title_prefix": title_prefix,
        "periods": [
            {"period": period,
             "locations": [{"name": name, "count": count} for name, count in sorted(locs.items())]}
            for period, locs in sorted(periods.items())
        ],
    }

# ----------------------------------------------------------------------

class _CladeResolver:
    """Resolve a hidb antigen's clade via the subtype's seqdb (name/reassortant/passage match).

    Mirrors bin/seqdb-chart-populate-json: select_all().filter_name(...), optionally find_clades()
    with $AC_CLADES_JSON_V2, then read .clades off the first matching seqdb ref. Results are
    memoised per (name, reassortant, passage). Antigens with no match / no clade -> "unknown".
    If seqdb is unavailable, every lookup returns "unknown" (geo still renders, all one bucket)."""

    def __init__(self, ae_backend, seqdb_subtype: str):
        self._cache: dict[tuple, str] = {}
        self._clades_file = os.environ.get("AC_CLADES_JSON_V2")
        try:
            self._seqdb = ae_backend.seqdb.for_subtype(seqdb_subtype)
        except Exception as err:
            print(f">>> geo: seqdb for {seqdb_subtype} unavailable ({err}); all clades -> unknown", file=sys.stderr)
            self._seqdb = None

    def clade(self, ag) -> str:
        if self._seqdb is None:
            return "unknown"
        # hidb antigen exposes name() and readonly passage/reassortant fields.
        name = ag.name()
        passage = getattr(ag, "passage", "") or ""
        reassortant = getattr(ag, "reassortant", "") or ""
        key = (name, reassortant, passage)
        if key in self._cache:
            return self._cache[key]
        clade = "unknown"
        try:
            selected = self._seqdb.select_all().filter_name(name=name, reassortant=reassortant, passage=passage)
            if len(selected):
                selected.find_masters()     # resolve hash-dedup slave->master (find_clades does this
                                            # internally, but not when _clades_file is unset)
                if self._clades_file:
                    try:
                        selected.find_clades(self._clades_file)
                    except Exception:
                        pass
                clades = list(selected[0].clades or [])
                if clades:
                    clade = clades[0]
        except Exception:
            clade = "unknown"
        self._cache[key] = clade
        return clade


def _extract_geo_records_by_clade(db, title_prefix: str, start: str, end: str, *, ae_backend, seqdb_subtype: str) -> dict:
    """Build geo-draw's pie `--data`: {title_prefix, periods:[{period, locations:[{name,
    categories:[{name,count}]}]}]}. hidb antigens are bucketed by (month, location, clade);
    clade resolved from seqdb. *start*/*end* are YYYYMM (half-open). Undated/location-less
    antigens skipped; unresolved clades bucketed as "unknown"."""
    resolver = _CladeResolver(ae_backend, seqdb_subtype)
    # period -> location -> clade -> count (every window month seeded -> blank map if no data)
    periods: dict[str, dict[str, dict[str, int]]] = {p: {} for p in _months_in_window(start, end)}
    for i in range(db.number_of_antigens()):
        ag = db.antigen(i)
        date = ag.date(compact=True)[:6]
        if len(date) != 6 or not (start <= date < end):
            continue
        location = ag.location
        if not location:
            continue
        clade = resolver.clade(ag) or "unknown"
        period = f"{date[:4]}-{date[4:]}"
        per = periods.setdefault(period, {})
        loc = per.setdefault(location, {})
        loc[clade] = loc.get(clade, 0) + 1
    return {
        "title_prefix": title_prefix,
        "periods": [
            {"period": period,
             "locations": [
                 {"name": name,
                  "categories": [{"name": clade, "count": count} for clade, count in sorted(clades.items())]}
                 for name, clades in sorted(locs.items())
             ]}
            for period, locs in sorted(periods.items())
        ],
    }

# ----------------------------------------------------------------------

def _truthy(v) -> bool:
    return v is not None and str(v).strip().lower() in ("true", "1", "yes", "t")


def _present(v) -> bool:
    return v is not None and str(v).strip() != ""


def _norm_coloring(spec: dict):
    """Normalise a report `geographic_coloring(subtype)` spec the way vcm's
    `_preprocess_coloring` does: `aa` given as a space-separated string -> list of
    "POSAA" tokens, and `fill` -> `color`. Returns (default_dict, list_of_rules)."""
    default = dict(spec.get("default") or {})
    rules = []
    for raw in (spec.get("apply") or []):
        r = dict(raw)
        aa = r.get("aa")
        if isinstance(aa, str):
            aa = aa.split()
        r["aa"] = list(aa) if aa else []
        r["color"] = r.get("color") if _present(r.get("color")) else r.get("fill")
        rules.append(r)
    return default, rules


class _Coloring:
    """Apply a report `geographic_coloring(subtype)` spec to antigens — a faithful Python port
    of AD `ColoringByAminoAcid::color`. For each antigen the aa sequence is fetched from the
    subtype's seqdb (name/reassortant/passage match) and the ordered `apply` rules are evaluated:
    a `sequenced` rule sets only the fill; an `aa` rule whose `SequenceAA.matches_all` (incl. `!`
    negation and `-` deletions) is satisfied overrides fill/outline/outline_width; later matches
    win. Unsequenced / unmatched antigens keep the `default` colouring. Results memoised per
    (name, reassortant, passage)."""

    def __init__(self, ae_backend, seqdb_subtype: str, spec: dict):
        self._default, self._rules = _norm_coloring(spec)
        self._cache: dict[tuple, dict] = {}
        try:
            self._seqdb = ae_backend.seqdb.for_subtype(seqdb_subtype)
        except Exception as err:
            print(f">>> geo: seqdb for {seqdb_subtype} unavailable ({err}); coloring -> default only", file=sys.stderr)
            self._seqdb = None

    def _default_result(self) -> dict:
        return {
            "color": self._default.get("color") if _present(self._default.get("color")) else "transparent",
            "outline": self._default.get("outline") if _present(self._default.get("outline")) else "black",
            "outline_width": float(self._default["outline_width"]) if _present(self._default.get("outline_width")) else 1.0,
        }

    def _aa_for(self, name, reassortant, passage):
        if self._seqdb is None:
            return None
        try:
            sel = self._seqdb.select_all().filter_name(name=name, reassortant=reassortant, passage=passage)
            if len(sel):
                sel.find_masters()      # seqdb v4 hash-dedups identical seqs into master/slave;
                                        # slaves carry no inline aa — resolve to the master first,
                                        # else ~half the strains read empty aa -> transparent dot.
                aa = sel[0].aa
                return aa if aa else None
        except Exception:
            return None
        return None

    def color(self, ag) -> dict:
        name = ag.name()
        passage = getattr(ag, "passage", "") or ""
        reassortant = getattr(ag, "reassortant", "") or ""
        key = (name, reassortant, passage)
        if key in self._cache:
            return self._cache[key]
        result = self._default_result()
        aa = self._aa_for(name, reassortant, passage)
        if aa is not None:
            for r in self._rules:
                if _truthy(r.get("sequenced")):
                    result["color"] = r.get("color") or "pink"   # AD: sequenced rule sets fill only
                elif r["aa"]:
                    try:
                        matched = aa.matches_all(r["aa"])
                    except Exception:
                        matched = False
                    if matched:
                        result["color"] = r.get("color") or "pink"
                        result["outline"] = r["outline"] if _present(r.get("outline")) else "transparent"
                        result["outline_width"] = float(r["outline_width"]) if _present(r.get("outline_width")) else 0.0
        self._cache[key] = result
        return result


def _extract_geo_records_by_coloring(db, start: str, end: str, *, ae_backend, seqdb_subtype: str,
                                     coloring: dict, point_size: float, density: float) -> dict:
    """Build geo-draw's packed-dots `--data`: per (month, location) one dot per antigen, coloured
    by the report's `geographic_coloring` apply-rules (resolved via seqdb). Identical (fill,
    outline, outline_width) dots at a location are grouped with a `count`. Per-period title is the
    human month ("December 2025") to match AD's geographic-draw. `point_size`/`density` come from
    `geographic_settings` and drive geo-draw's ring packing."""
    colorer = _Coloring(ae_backend, seqdb_subtype, coloring)
    # period -> location -> (color, outline, outline_width) -> count
    # every window month seeded -> a map is emitted even for months with no data
    periods: dict[str, dict[str, dict[tuple, int]]] = {p: {} for p in _months_in_window(start, end)}
    for i in range(db.number_of_antigens()):
        ag = db.antigen(i)
        date = ag.date(compact=True)[:6]
        if len(date) != 6 or not (start <= date < end):
            continue
        location = ag.location
        if not location:
            continue
        c = colorer.color(ag)
        kk = (c["color"], c["outline"], float(c["outline_width"]))
        period = f"{date[:4]}-{date[4:]}"
        loc = periods.setdefault(period, {}).setdefault(location, {})
        loc[kk] = loc.get(kk, 0) + 1

    def _title(period: str) -> str:
        y, m = period.split("-")
        return f"{calendar.month_name[int(m)]} {y}"

    return {
        "point_size": point_size,
        "density": density,
        "periods": [
            {"period": period, "title": _title(period),
             "locations": [
                 {"name": name,
                  # dominant group first (drawn at the cluster centre)
                  "points": [{"color": col, "outline": outl, "outline_width": ow, "count": cnt}
                             for (col, outl, ow), cnt in sorted(groups.items(), key=lambda kv: -kv[1])]}
                 for name, groups in sorted(locs.items())
             ]}
            for period, locs in sorted(periods.items())
        ],
    }

# ----------------------------------------------------------------------

def _resolve_geo_draw() -> str:
    found = shutil.which("geo-draw")
    if found:
        return found
    build = Path(__file__).resolve().parents[3] / "build" / "geo-draw"
    return str(build) if build.exists() else "geo-draw"

# ----------------------------------------------------------------------

def make_index_html(output_file, prefixes, safari):
    with Path(output_file).open("w") as f:
        f.write("<html><head><style>\nimg {border: 1px solid black;}\nul {list-style-type: none;}\nli {margin: 0.5em 0; }\nobject {width: 800px; height: 415px; }\n</style><title>Geographic maps</title></head><body>\n")
        for vt in sorted(prefixes):
            f.write("<h1>{}</h1>\n<ul>".format(vt))
            for fn in sorted(prefixes[vt].parent.glob(prefixes[vt].name + "*.pdf")):
                if safari:
                    f.write('<li><img src="{}" /></li>\n'.format(Path(fn).name))
                else:
                    f.write('<li><object data="{}#toolbar=0"></object></li>\n'.format(Path(fn).name))
            f.write("</ul>\n")
        f.write("</body></html>\n")
