"""
stat.json.xz writer — counts of antigens/sera in WHO CC tables, by virus type,
lab, date and continent.

This is the ae port of AD's C++ ``hidb5-stat`` tool (hidb-5/cc/hidb5-stat.cc),
which AD's ssm-report ``stat.py`` shelled out to. It produces exactly the
``stat/stat.json.xz`` structure that this package's ``StatisticsTableMaker``
(in report.py) reads to render the LaTeX statistics tables::

    {
      "antigens":    { virus_type: { lab: { date: { continent: count } } } },
      "sera":        { ... },          # deduplicated by serum name
      "sera_unique": { ... },          # every serum counted
      "date": "<generated YYYY-MM-DD>"
    }

For every antigen/serum the count is added across the full cross-product
{virus_type, "all"} × {lab, "all"} × {month, year, "all"} × {continent, "all"},
so the reader can index any aggregate directly (matching hidb5-stat's `update`).
B antigens/sera are additionally counted under BVICTORIA / BYAMAGATA / BUNKNOWN
(by lineage), without an extra "all" virus-type pass.

Data source is **hidb** (`ae_backend.hidb`) + **locationdb** (`ae_backend.locdb_v3`
for continent) — no `chart_v3`, so this does not hit the chart-import-abort bug.

Note: as of this writing the **B hidb fails to load** in `ae_backend.hidb`
(`STRING_ERROR`), an open hidb-side bug — so B counts are absent until that is
fixed. A virus type that fails to load is skipped with a warning rather than
aborting the whole run.
"""

import logging; module_logger = logging.getLogger(__name__)
import sys, json, lzma, datetime, glob, importlib.util
from pathlib import Path

# ----------------------------------------------------------------------

VIRUS_TYPES = ["A(H1N1)", "A(H3N2)", "B"]
ALL = "all"

# ----------------------------------------------------------------------

def make_stat_json(output, start, end, db_dir=None, locdb_file=None, ae_backend=None,
                   virus_types=VIRUS_TYPES):
    """Compute the stat structure from hidb and write it to *output* (xz-compressed
    when the path ends in ``.xz``). *start*/*end* may be ``YYYY-MM-DD`` or ``YYYYMM``
    (half-open range ``start <= date < end``). Returns the stat dict."""
    ae_backend = ae_backend or _import_ae_backend()
    if db_dir:
        ae_backend.hidb.set_dir(str(db_dir))
    if locdb_file:
        import os
        os.environ["LOCDB_V2"] = str(locdb_file)
    resolve = _continent_resolver(ae_backend.locdb_v3.locdb())

    start, end = _norm_date(start), _norm_date(end)
    data_antigens, data_sera, data_sera_unique = {}, {}, {}
    for virus_type in virus_types:
        try:
            db = ae_backend.hidb.hidb(virus_type)
        except Exception as err:
            module_logger.warning("skipping %s: hidb load failed: %s", virus_type, err)
            continue
        _scan_antigens(db, virus_type, start, end, resolve, data_antigens)
        _scan_sera(db, virus_type, start, end, resolve, data_sera, data_sera_unique)

    stat = {
        "antigens": _nest(data_antigens),
        "sera": _nest(data_sera),
        "sera_unique": _nest(data_sera_unique),
        "date": datetime.date.today().strftime("%Y-%m-%d"),
    }
    write_stat(stat, output)
    return stat

# ----------------------------------------------------------------------

def make_stat(stat_dir, db_dir, report_json="report.json", locdb_file=None, ae_backend=None, force=False):
    """Higher-level entry mirroring AD ssm-report ``stat.make_stat``: read the
    time-series dates from *report_json* and write ``<stat_dir>/stat.json.xz``.
    The end date is extended by ~a month (as AD does) so the meeting month is
    included."""
    stat_dir = Path(stat_dir)
    output = stat_dir / "stat.json.xz"
    if output.exists() and not force:
        module_logger.info("exists, not overwriting: %s", output)
        return None
    stat_dir.mkdir(parents=True, exist_ok=True)
    settings = json.loads(Path(report_json).read_text())
    dates = settings["time_series"]["date"]
    end = (datetime.datetime.strptime(_iso(dates["end"]), "%Y-%m-%d").date()
           + datetime.timedelta(days=31)).strftime("%Y-%m-01")
    return make_stat_json(output=output, start=dates["start"], end=end, db_dir=db_dir,
                          locdb_file=locdb_file, ae_backend=ae_backend)

# ----------------------------------------------------------------------

def write_stat(stat, output):
    """Write *stat* as JSON to *output*; lzma-compress when the path ends ``.xz``."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(stat, indent=1, ensure_ascii=False)
    if output.suffix == ".xz":
        with lzma.open(output, "wt", encoding="utf-8") as f:
            f.write(text)
    else:
        output.write_text(text)

# ======================================================================
# scanning (ports of hidb5-stat.cc scan_antigens / scan_sera / update)
# ======================================================================

def _scan_antigens(db, virus_type, start, end, resolve, data):
    for i in range(db.number_of_antigens()):
        ag = db.antigen(i)
        date = _antigen_date(ag)
        if not (start <= date < end) or not ag.tables:
            continue
        lab = db.table(ag.tables[0]).lab
        continent = resolve(ag.location)
        _bucket(data, virus_type, lab, date, continent)
        if virus_type == "B":
            _bucket(data, _b_lineage(ag.lineage), lab, date, continent, lineage_only=True)


def _scan_sera(db, virus_type, start, end, resolve, data_sera, data_sera_unique):
    seen_names = set()                     # dedup is per virus type, as in AD
    for i in range(db.number_of_sera()):
        sr = db.serum(i)
        date = _serum_date(db, sr)
        if not (start <= date < end) or not sr.tables:
            continue
        lab = db.table(sr.tables[0]).lab
        continent = resolve(sr.location)
        _bucket(data_sera_unique, virus_type, lab, date, continent)
        if virus_type == "B":
            _bucket(data_sera_unique, _b_lineage(sr.lineage), lab, date, continent, lineage_only=True)
        name = sr.name()
        if name not in seen_names:
            seen_names.add(name)
            _bucket(data_sera, virus_type, lab, date, continent)
            if virus_type == "B":
                _bucket(data_sera, _b_lineage(sr.lineage), lab, date, continent, lineage_only=True)


def _bucket(data, virus_type, lab, date, continent, lineage_only=False):
    """Increment the count across the cross-product of aggregate keys (port of
    hidb5-stat.cc ``update``). With *lineage_only* the virus-type axis is just
    *virus_type* (the B-lineage pass — no extra "all" virus-type rollup)."""
    year = date[:4]
    virus_types = (virus_type,) if lineage_only else (virus_type, ALL)
    for vt in virus_types:
        for lb in (lab, ALL):
            for dt in (date, year, ALL):
                for ct in (continent, ALL):
                    key = (vt, lb, dt, ct)
                    data[key] = data.get(key, 0) + 1

# ----------------------------------------------------------------------

def _antigen_date(ag):
    date = ag.date(compact=True)[:6]
    if not date:
        date = ag.year + "99"
    elif len(date) == 4:
        date += "99"
    return date


def _serum_date(db, sr):
    date = ""
    for ag_no in sr.homologous_antigens:
        date = db.antigen(ag_no).date(compact=True)[:6]
        if date:
            break
    if not date:
        date = sr.year + "99"
    elif len(date) == 4:
        date += "99"
    return date


def _b_lineage(lineage):
    lin = (lineage or "").upper()
    if lin.startswith("V"):
        return "BVICTORIA"
    if lin.startswith("Y"):
        return "BYAMAGATA"
    return "BUNKNOWN"


def _continent_resolver(locdb):
    """location name -> continent, "UNKNOWN" when unresolved (AD's continent fallback).
    AD's single locdb.continent(location) is two steps in ae: location->country->continent."""
    def resolve(location):
        if not location:
            return "UNKNOWN"
        country = locdb.country(location)
        if not country:
            return "UNKNOWN"
        return locdb.continent(country) or "UNKNOWN"
    return resolve


def _nest(data):
    """Flat {(vt, lab, date, continent): count} -> nested dict."""
    out = {}
    for (vt, lab, date, continent), count in data.items():
        out.setdefault(vt, {}).setdefault(lab, {}).setdefault(date, {})[continent] = count
    return out


def _norm_date(s):
    digits = "".join(ch for ch in str(s) if ch.isdigit())
    return digits[:6] if digits else str(s)


def _iso(s):
    """Normalize a date string to YYYY-MM-DD (accepts YYYY-MM-DD or YYYYMM[DD])."""
    digits = "".join(ch for ch in str(s) if ch.isdigit())
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    if len(digits) >= 6:
        return f"{digits[:4]}-{digits[4:6]}-01"
    return str(s)

# ----------------------------------------------------------------------

def _import_ae_backend():
    """Import ae_backend, preferring this repo's build/ (as bin/_hidb_boot does)."""
    if "ae_backend" in sys.modules:
        return sys.modules["ae_backend"]
    try:
        import ae_backend
        return ae_backend
    except ImportError:
        build = Path(__file__).resolve().parents[3] / "build"
        sos = sorted(glob.glob(str(build / "ae_backend*.so")))
        if not sos:
            raise
        spec = importlib.util.spec_from_file_location("ae_backend", sos[0])
        module = importlib.util.module_from_spec(spec)
        sys.modules["ae_backend"] = module
        spec.loader.exec_module(module)
        return module

# ----------------------------------------------------------------------

def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Write stat.json[.xz] (antigen/sera counts) from hidb.")
    parser.add_argument("output", help="output file (stat.json.xz, or .json for plain)")
    parser.add_argument("--start", default="1000-01-01", help="inclusive start date (YYYY-MM-DD or YYYYMM)")
    parser.add_argument("--end", default="3000-01-01", help="exclusive end date (YYYY-MM-DD or YYYYMM)")
    parser.add_argument("--db-dir", default=None, help="hidb directory (overrides $HIDB_V5)")
    parser.add_argument("--locdb", default=None, help="locationdb.json.xz (overrides $LOCDB_V2)")
    parser.add_argument("-d", "--debug", dest="loglevel", action="store_const",
                        const=logging.DEBUG, default=logging.INFO)
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.loglevel, format="%(levelname)s %(asctime)s: %(message)s [%(name)s.%(funcName)s %(lineno)d]")
    stat = make_stat_json(output=args.output, start=args.start, end=args.end,
                          db_dir=args.db_dir, locdb_file=args.locdb)
    total = stat["antigens"].get("all", {}).get("all", {}).get("all", {}).get("all", 0)
    module_logger.info("wrote %s (%d antigens total in range)", args.output, total)
    return 0


if __name__ == "__main__":
    import traceback
    try:
        sys.exit(main())
    except Exception as err:
        logging.error("%s\n%s", err, traceback.format_exc())
        sys.exit(1)
