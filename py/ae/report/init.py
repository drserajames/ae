"""
Working-directory scaffolding + report.json templating.

Port of the *unblocked* parts of AD ssm-report ``py/ssm_report/init.py``: create
the working-dir subdirectories, copy the static template files, and generate the
substituted ``report.json`` / ``setup.json`` that the assembly core
(``ae.report.report``) consumes.

What is intentionally NOT ported here:

* ``init_git`` / ``get_dbs`` / ``get_hidb_seqdb`` — AD scaffolds a bare git repo
  and rsyncs hidb/seqdb/locationdb from the CPE ``albertine`` host (and chmods
  the result on ``i19``). That is site-specific deployment glue, not part of the
  report logic, so it is left to the operator. The ``rr`` / ``sy`` /
  ``rename-report-on-server`` driver scripts are excluded for the same reason
  (they invoke ``ssm-make`` / ``ssh i19`` / ``syput``).
* The figure-generation settings templates (``h3-hi.json``, ``vaccines.*``,
  ``serology.*`` …) and the ``init_settings`` serum-coverage / geographic
  sub-makers — these belong to the map/maker pipeline, which is not yet ported.
  In ae the antigenic-map figures come from kateri (driven via
  ``ae.utils.kateri``) rather than the AD ``acmacs-map-draw`` settings, so these
  templates are deliberately not copied until that pipeline is rebuilt.

Usage:

    PYTHONPATH=build:py bin/ssm-report-init --working-dir <dir>

The working-dir name, if it looks like ``YYYY-MMDD`` (e.g. ``2026-0219``), is
parsed as the meeting date — matching AD's convention.
"""

import logging; module_logger = logging.getLogger(__name__)
from pathlib import Path
import os, sys, re, datetime, shutil, argparse, traceback

# ----------------------------------------------------------------------

# Subdirectories created in a report working dir (AD init_dirs).
WORKING_SUBDIRS = ["tree", "sp", "spc", "merges", "log", "serumcoverage"]

# Static template files copied verbatim into the working dir: (template_name, dest_name).
# setup.json / report.json are NOT here — they are substituted, see make_report_json().
STATIC_TEMPLATES = [
    ("root-gitignore", ".gitignore"),
    ("index.html", "index.html"),
    ("merges-index.html", "merges-index.html"),
    ("README.org", "README.org"),
]

# Templates that carry %(...)s substitutions filled by compute_substitutions().
SUBSTITUTED_TEMPLATES = ["report.json", "setup.json"]


def template_dir():
    """Directory holding the packaged report templates (replaces AD's
    ``$ACMACSD_ROOT/sources/ssm-report/template``)."""
    return Path(__file__).resolve().parent / "templates"

# ----------------------------------------------------------------------

def init(working_dir=".", force=False, today=None):
    """Scaffold a report working directory: subdirs + static templates +
    substituted report.json / setup.json. Returns the resolved working dir."""
    working_dir = Path(working_dir).resolve()
    working_dir.mkdir(parents=True, exist_ok=True)
    init_dirs(working_dir)
    copy_templates(working_dir, force=force)
    make_report_json(working_dir, force=force, today=today)
    module_logger.info("initialized report working dir %s", working_dir)
    return working_dir

# ----------------------------------------------------------------------

def init_dirs(working_dir="."):
    working_dir = Path(working_dir)
    for sub in WORKING_SUBDIRS:
        working_dir.joinpath(sub).mkdir(parents=True, exist_ok=True)

# ----------------------------------------------------------------------

def copy_templates(working_dir=".", force=False):
    working_dir = Path(working_dir)
    tdir = template_dir()
    for src, dest in STATIC_TEMPLATES:
        dest_path = working_dir.joinpath(dest)
        src_path = tdir.joinpath(src)
        if not src_path.exists():
            module_logger.warning("template missing, skipped: %s", src_path)
            continue
        if dest_path.exists() and not force:
            module_logger.debug("exists, not overwriting: %s", dest_path)
            continue
        shutil.copy(src_path, dest_path)
        module_logger.info("copied template %s -> %s", src, dest_path)

# ----------------------------------------------------------------------

def make_report_json(working_dir=".", force=False, today=None):
    """Write report.json and setup.json into *working_dir*, substituting the
    date-derived fields. Ported from AD ``_make_report_json``."""
    working_dir = Path(working_dir).resolve()
    subst = compute_substitutions(working_dir, today=today)
    tdir = template_dir()
    for name in SUBSTITUTED_TEMPLATES:
        dest = working_dir.joinpath(name)
        if dest.exists() and not force:
            module_logger.debug("exists, not overwriting: %s", dest)
            continue
        template = tdir.joinpath(name)
        if not template.exists():
            module_logger.warning("template missing, skipped: %s", template)
            continue
        dest.write_text(template.read_text() % subst)
        module_logger.info("wrote %s", dest)
    return subst

# ----------------------------------------------------------------------

def compute_substitutions(working_dir=".", today=None):
    """Compute the %(...)s substitution values for report.json / setup.json.

    Faithful port of AD ``_make_report_json``'s date logic. *today* may be
    overridden (a ``datetime.date``) for testing/reproducibility.
    """
    working_dir = Path(working_dir).resolve()
    today = today or datetime.date.today()

    # Hemisphere/year of the vaccine composition meeting season.
    if 2 < today.month < 10:
        hemisphere = "Southern"
        year = str(today.year + 1)
    else:
        hemisphere = "Northern"
        if today.month >= 10:
            year = "{}/{}".format(today.year + 1, today.year + 2)
        else:
            year = "{}/{}".format(today.year, today.year + 1)

    # Meeting date: from the working-dir name (YYYY-MMDD), else a week out.
    m = re.match(r"(\d\d\d\d)-(\d\d)(\d\d)", working_dir.name)
    if m:
        meeting_date = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    else:
        meeting_date = today + datetime.timedelta(days=7)

    if meeting_date.month != 2 and meeting_date.month != 9:
        teleconference = "Teleconference 1"
    elif meeting_date.day < 20:
        teleconference = "Teleconference 2"
    else:
        teleconference = ""

    return {
        "previous_dir": find_previous_dir(working_dir),
        "hemisphere": hemisphere,
        "meeting_date": meeting_date.strftime("%d %B %Y"),
        "year": year,
        "teleconference": teleconference,
        "time_series_start": (meeting_date - datetime.timedelta(days=180)).strftime("%Y-%m-01"),
        "time_series_end": meeting_date.strftime("%Y-%m-01"),
        "twelve_month_ago": (meeting_date - datetime.timedelta(days=365)).strftime("%B %Y"),
        "six_month_ago": (meeting_date - datetime.timedelta(days=183)).strftime("%B %Y"),
    }

# ----------------------------------------------------------------------

def find_previous_dir(working_dir="."):
    """Most recent sibling directory (the previous report), or "". AD's
    ``_find_previous_dir``: siblings sorted descending, first that isn't us."""
    working_dir = Path(working_dir).resolve()
    for dd in sorted(working_dir.parent.glob("*"), reverse=True):
        if dd.is_dir() and dd != working_dir:
            return str(dd)
    return ""

# ----------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description="Scaffold an SSM/seasonal report working directory.",
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--working-dir", dest="working_dir", default=".",
                        help="report working directory to initialize (default: cwd). If its name "
                             "looks like YYYY-MMDD it is parsed as the meeting date.")
    parser.add_argument("--force", action="store_true", default=False,
                        help="overwrite existing report.json / setup.json / template files")
    parser.add_argument("-d", "--debug", dest="loglevel", action="store_const",
                        const=logging.DEBUG, default=logging.INFO, help="enable debug logging")
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.loglevel,
                        format="%(levelname)s %(asctime)s: %(message)s [%(name)s.%(funcName)s %(lineno)d]")
    init(working_dir=args.working_dir, force=args.force)
    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
    except Exception as err:
        logging.error("{}\n{}".format(err, traceback.format_exc()))
        exit_code = 1
    sys.exit(exit_code)
