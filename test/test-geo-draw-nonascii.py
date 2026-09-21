#!/usr/bin/env python3
# geo-draw must resolve location names written with JSON escapes.
#
# Why this exists: `make_geo` (py/ae/report/geographic.py) writes the records file with
# `json.dumps`, whose default `ensure_ascii=True` turns every non-ASCII character into \uXXXX.
# geo-draw reads it with rjson-v3, which hands strings back raw, so a location whose name is
# non-ASCII was looked up in locdb as the literal escape text, printed
# "WARNING: location not found" and was silently dropped from the geographic map.
#
# The locdb and every name here are invented — NO WHO data. Names cover a BMP character,
# an astral character (a surrogate pair in JSON), a lone surrogate (decodes to U+FFFD), and the
# simple escapes \" and \\. An ASCII name is the control; an unknown name must still warn.
#
# Run (from the ae worktree root, after building):
#   GEO_DRAW=build-py314/geo-draw python3 test/test-geo-draw-nonascii.py

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

GEO_DRAW = os.environ.get("GEO_DRAW", str(Path(__file__).resolve().parents[1].joinpath("build", "geo-draw")))

# name as written in the records file -> locdb key it must resolve to
NAMES = {
    "PLAINTOWN": "PLAINTOWN",
    "测试城": "TESTCITY",               # BMP, 3-byte UTF-8
    "ÉTOILE-SUR-ESSAI": "ETOILE",             # Latin-1 range, 2-byte UTF-8
    "\U0001d4b3TOWN": "ASTRALTOWN",                # astral, 𝒳 in JSON, 4-byte UTF-8
    "\ud800LONE": "LONETOWN",                      # lone high surrogate -> U+FFFD
    'QUOTE "Q" TOWN': "QUOTETOWN",
    "BACK\\SLASH": "BACKSLASHTOWN",
}
LOCDB_KEY_FOR_LONE = "�LONE"
MISSING = "无此地"                    # not in the locdb: must still warn

FAILURES: list[str] = []


def check(cond, message):
    print(f"  {'ok  ' if cond else 'FAIL'} {message}")
    if not cond:
        FAILURES.append(message)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        names = {(LOCDB_KEY_FOR_LONE if k.startswith("\ud800") else k): v for k, v in NAMES.items()}
        locdb = {
            "  version": "locationdb-v2",
            "continents": ["EUROPE"],
            "countries": {"TESTLAND": 0},
            "names": names,
            "locations": {v: [10.0 + i, 20.0 + i, "TESTLAND", "TESTPROVINCE"] for i, v in enumerate(NAMES.values())},
        }
        tmp.joinpath("locdb.json").write_text(json.dumps(locdb, ensure_ascii=False), encoding="utf-8", errors="surrogatepass")

        records = {"periods": [
            {"period": "all", "locations": [{"name": n, "count": 1} for n in NAMES]},
            {"period": "missing", "locations": [{"name": MISSING, "count": 1}]},
        ]}
        text = json.dumps(records)          # ensure_ascii=True, exactly as make_geo writes it
        check("\\u6d4b" in text and "\\ud835\\udcb3" in text, "records file carries \\u escapes (the case under test)")
        tmp.joinpath("records.json").write_text(text)

        res = subprocess.run([GEO_DRAW, "--data", str(tmp / "records.json"), "--prefix", str(tmp / "geo-")],
                             env={**os.environ, "LOCDB_V2": str(tmp / "locdb.json")},
                             capture_output=True, text=True)
        print(res.stdout + res.stderr, end="")
        check(res.returncode == 0, f"geo-draw exit 0 (got {res.returncode})")
        counts = dict(re.findall(r"Wrote .*geo-(\w+)\.pdf \((\d+) location", res.stdout))
        check(counts.get("all") == str(len(NAMES)), f"all {len(NAMES)} names resolve (got {counts.get('all')})")
        check(counts.get("missing") == "0", f"unknown name plots nothing (got {counts.get('missing')})")
        warnings = [ln for ln in res.stderr.splitlines() if "location not found" in ln]
        check(warnings == [f"WARNING: location not found: {MISSING}"],
              f"exactly one warning, for the unknown name, decoded (got {warnings})")

    print(f"{len(FAILURES)} failure(s)")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
