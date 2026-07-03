"""Table page: for one table date, collect the individual + chain maps involving it.

Ported from AD ``table_page.py``. Chart reads go through ``render.get_chart`` /
``render.chart_date`` (ae_backend), replacing AD's ``chart.get_chart`` (acmacs).
Paths are relative to cwd (the served root).
"""

import json
from pathlib import Path

from . import pages_util, render

# ======================================================================

sTablePage = """<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8" />
    {stylesheets}
    {remote_scripts}
    {inline_scripts}
    <title>{table_name}</title>
  </head>
  <body>
    <h2 id="title"></h2>
{body}
  </body>
</html>
"""

# ======================================================================


def table_page_html(ctx, subtype_id, table_date) -> str:
    remote_scripts = [
        "js/jquery.js",
        "js/table-page.js",
    ]
    stylesheets = [
        "js/maps.css",
        "js/table-page.css",
    ]
    data = collect_table_data(ctx, subtype_id=subtype_id, table_date=table_date)
    inline_scripts = [
        f"table_page_data =\n{json.dumps(data, separators=(',', ':'))};",
    ]
    return sTablePage.format(
        remote_scripts="\n    ".join(f'<script src="{script}" type="module"></script>' for script in remote_scripts),
        stylesheets="\n    ".join(f'<link rel="stylesheet" href="{stylesheet}">' for stylesheet in stylesheets),
        inline_scripts="\n    ".join(f'<script>\n{code}\n    </script>' for code in inline_scripts),
        table_name=f"{subtype_id} {table_date}",
        body="")

# ----------------------------------------------------------------------


def collect_table_data(ctx, subtype_id, table_date):

    def collect_table_data_part():
        for patt in ["i-*", "f-*", "b-*"]:
            for subdir in sorted(Path(subtype_id).glob(patt), reverse=True):
                entries = make_entries(subdir, patt[0] == "i")
                if entries:
                    yield {
                        "type": "individual" if patt[0] == "i" else "chain",
                        "chain_id": subdir.name,
                        **entries,
                    }

    def make_entries(subdir, individual):
        entries = {}
        # ignore temp files (with ~pid~ infix) made by export chart
        filenames = [fn for fn in subdir.glob(f"*{table_date}.*") if "~" not in str(fn)]
        if not filenames and subdir.name[0] == "b":  # backward-chain step-naming workaround
            filenames = list(subdir.glob(f"*.{table_date}-*"))
        for filename in filenames:
            key1, key2 = keys_for_filename(filename)
            if individual and key1 == "scratch":
                key1 = "individual"
            entries.setdefault(key1, {})[key2] = str(filename)
            if key2 == "ace":
                chart_date = render.chart_date(filename)
                entries[key1]["date"] = chart_date
                entries.setdefault("date", chart_date)
        return entries

    def keys_for_filename(filename):
        suffx = filename.suffixes
        if suffx[-1] == ".ace":
            if len(suffx) >= 2:                      # 123.20160113-20210625.incremental.ace
                return (suffx[-2][1:], "ace")
            return ("scratch", "ace")
        elif suffx[-1] == ".json":
            if len(suffx) >= 3:                      # 123.20160113-20210625.scratch.grid.json
                return (suffx[-3][1:], suffx[-2][1:])
            return ("scratch", suffx[-2][1:])
        return ("unknown", "".join(suffx))

    return {
        "subtype_id": subtype_id,
        "table_date": table_date,
        "parts": [part_data for part_data in collect_table_data_part() if part_data],
        **pages_util.format_subtype(ctx, subtype_id=subtype_id, date_range=[table_date, table_date]),
    }

# ======================================================================
