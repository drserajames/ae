# Ported from vcm (ssm-report tooling) 2026-0119-tc2/py/vcm/v2/geographic.py, then
# rewired for ae's geo-draw renderer (cc/geo). See py/ae/report/MIGRATION.md.
#
# Geographic time-series maps. The report-side job (TODO #4) is the Python glue:
# extract per-month {location, count} from hidb, write geo-draw's --data JSON, and
# let geo-draw render one PDF per month (named to match what the report embeds:
# geo/<subtype>-<YYYY-MM>.pdf). geo-draw colours dots by continent and sizes them
# by sqrt(count); the AD clade/lineage colouring is a not-yet-available geo-draw
# feature (the per-map "colored by clade" *description* still comes from latex).
#
# Decoupled from ConferenceData: make_geo takes a TimeSeriesRange directly.

import json
import shutil
import subprocess
from pathlib import Path

from ae.utils.time_series import TimeSeriesRange
from .stat import _import_ae_backend, _norm_date

# ----------------------------------------------------------------------

# report subtype -> hidb virus_type / map title
SUBTYPE_HIDB = {"h1": "A(H1N1)", "h3": "A(H3N2)", "b": "B"}
SUBTYPE_TITLE = {"h1": "A(H1N1)", "h3": "A(H3N2)", "b": "B"}

# ----------------------------------------------------------------------

def make_geo(geo_dir: Path, time_series: TimeSeriesRange, hidb_dir=None,
             subtypes: list[str] = ["h1", "h3", "b"], ae_backend=None,
             geo_draw: str | None = None, make_index: bool = True, force: bool = False):
    """Render per-month geographic maps for each subtype into *geo_dir* via geo-draw.

    For each subtype, count hidb antigens by (month, location) over the
    *time_series* window, write geo-draw's `--data` records JSON, and run
    `geo-draw --data … --prefix <geo_dir>/<subtype>-` → `<geo_dir>/<subtype>-<YYYY-MM>.pdf`.
    """
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
            print(f">>> geo: skipping {subtype}: hidb load failed: {err}", file=__import__("sys").stderr)
            continue
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
    *start*/*end* are YYYYMM (half-open). Undated/location-less antigens are skipped."""
    periods: dict[str, dict[str, int]] = {}
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
