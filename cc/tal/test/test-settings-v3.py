#!/usr/bin/env python3
"""Verification for ae.tal.settings_v3 — translating an acmacs-tal settings-v3 `.tal`
config into the tal-draw schema. Pure Python (no ae_backend, no rendering); uses the
synthetic config-test.tal (no real data).

    python3 cc/tal/test/test-settings-v3.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "py"))

from ae.tal.settings_v3 import load_tal


def main():
    schema, warnings = load_tal(os.path.join(HERE, "config-test.tal"), {})
    checks = {
        "canvas->image_size": schema.get("image_size") == 600,
        "clades.show": schema.get("clades", {}).get("show") is True,
        "time-series.start": schema.get("time_series", {}).get("start") == "2020-01",
        "time-series.end": schema.get("time_series", {}).get("end") == "2021-01",
        "aa-transitions imported (not computed)": schema.get("aa_transitions", {}).get("compute") is False,
        "aa-transitions.min_leaves": schema.get("aa_transitions", {}).get("min_leaves") == 5,
        "dash-bar pos": [b.get("pos") for b in schema.get("dash_bars", [])] == [159],
        "hz-sections (via sub-array)": len(schema.get("hz_sections", [])) == 1,
        "nodes: only the hide one mapped": len(schema.get("nodes", [])) == 1,
        "warning for apply.text": any("text" in w for w in warnings),
    }
    failures = [name for name, ok in checks.items() if not ok]
    if failures:
        print("FAIL:")
        for f in failures:
            print(f"  - {f}")
        print(f"  schema={schema}")
        sys.exit(1)
    print(f"OK: settings-v3 translated ({len(checks)} checks, {len(warnings)} warnings)")


if __name__ == "__main__":
    main()
