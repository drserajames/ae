#!/usr/bin/env python3
"""Generate a MINIMAL locationdb (v2) covering only the locations asserted by
cc/test/test-virus-name.cc, written xz-compressed to the path given as argv[1].

This is GEOGRAPHY ONLY (place names + dummy coordinates) — it contains no titers,
sequences, or any WHO/GISAID data — so it is safe to generate on public CI. It lets
the "virus name parsing" test run without the private acmacs-data locationdb. Keep
the LOCATIONS / NAMES tables in sync with the test's .location assertions.
"""
import json
import lzma
import sys

# Canonical locations the test resolves to: name -> [lat, lon, country, division].
# Coordinates are irrelevant to the parser here (it only needs the name to resolve),
# so they are left as 0.
LOCATIONS = {
    name: [0.0, 0.0, name, ""]
    for name in [
        "AIN W ZAIN", "BEIJING", "BELGIUM", "BODENSEE", "GUANGDONG",
        "GUANGXI NANNING", "HAWAII", "HONG KONG", "INDIA", "KANSAS",
        "LISBOA", "LYON CHU", "MALI", "NETHERLANDS", "SINGAPORE",
        "SOUTH AFRICA", "VICTORIA",
    ]
}

# Db::find() resolves a location ONLY through the `names` table (name -> key in
# `locations`), never `locations` directly, and it returns the matched *names key*
# as the location string. So every canonical location needs a self-entry here...
NAMES = {name: name for name in LOCATIONS}

# ...and raw tokens that must normalise to a DIFFERENT canonical name go in
# `replacements` (find() recurses through them), not `names`.
REPLACEMENTS = {
    "AINWAZEIN": "AIN W ZAIN",
    "广西南宁": "GUANGXI NANNING",
}

db = {
    "  version": "locationdb-v2",
    "continents": ["ALL"],
    "countries": {name: 0 for name in LOCATIONS},
    "locations": LOCATIONS,
    "names": NAMES,
    "replacements": REPLACEMENTS,
    "cdc_abbreviations": {},
}

out = sys.argv[1] if len(sys.argv) > 1 else "locationdb.json.xz"
with lzma.open(out, "wb") as f:
    f.write(json.dumps(db, ensure_ascii=False).encode("utf-8"))
print(f"wrote minimal locationdb ({len(LOCATIONS)} locations) to {out}")
