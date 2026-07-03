"""Index page: scan the served root for chain directories and group them.

Ported from AD ``index_page.py``. Directory scanning is relative to the current working
directory, which the server sets to the served root (as the AD aiohttp app did).
"""

import json
import re
from pathlib import Path

# ======================================================================

sReSubtypeDirName = re.compile(
    r"(?P<subtype>h1pdm|h3|bvic|byam)-(?P<assay>hi|hint|fra|prn|mn)"
    r"(?:-(?P<rbc>guinea-pig|turkey|chicken))?-(?P<lab>cdc|cnic|crick|niid|vidrl)")
sAssayToAssay = {"hi": "hi", "hint": "hint", "prn": "neut", "fra": "neut"}

sINDEX = """<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8" />
    {stylesheets}
    {remote_scripts}
    {inline_scripts}
    <title>WHO CC tables</title>
  </head>
  <body>
    <h2>WHO CC tables</h2>
{body}
  </body>
</html>
"""

# ----------------------------------------------------------------------


def index_page_html() -> str:
    remote_scripts = [
        "js/jquery.js",
        "js/chain-index.js",
    ]
    stylesheets = [
        "js/chain-index.css",
    ]
    inline_scripts = [
        f"index_subtypes =\n{json.dumps(collect_index_subtypes(), separators=(',', ':'))};",
    ]
    return sINDEX.format(
        remote_scripts="\n    ".join(f'<script src="{script}" type="module"></script>' for script in remote_scripts),
        inline_scripts="\n    ".join(f'<script>\n{code}\n    </script>' for code in inline_scripts),
        stylesheets="\n    ".join(f'<link rel="stylesheet" href="{stylesheet}">' for stylesheet in stylesheets),
        body="")

# ----------------------------------------------------------------------


def collect_index_subtypes():
    """returns {subtype-assay: {lab: [entry]}}"""
    index_subtypes = {}
    for fn in Path(".").glob("*"):
        if fn.is_dir() and (fn_m := sReSubtypeDirName.match(fn.name)):
            if fn_m.group("subtype") == "h3":
                subtype_assay = f"""{fn_m.group("subtype")}-{sAssayToAssay[fn_m.group("assay")]}"""
            else:
                subtype_assay = fn_m.group("subtype")
            index_subtypes.setdefault(subtype_assay, {}).setdefault(fn_m.group("lab"), []).append(
                {"id": fn.name, **fn_m.groupdict()})
    return index_subtypes

# ======================================================================
# "/api/subtype-data/"

sReTableDate = re.compile(r"-(?P<date>(?P<year>(?:19|20)\d\d)(?P<month>\d\d)\d+[^\.]*)\.")


def collect_tables_of_subtype(subtype_id):
    names = [fn.name for i_none_1280 in ["i-none", "i-1280"] for fn in Path(subtype_id, i_none_1280).glob("*.ace")]
    data = {}
    for name in names:
        if mm := sReTableDate.search(name):
            data.setdefault(mm["year"], {}).setdefault(mm["month"], []).append({"date": mm["date"], "id": name})
        elif "orient" not in name:
            data.setdefault("unknown", []).append(name)
    return data

# ======================================================================
