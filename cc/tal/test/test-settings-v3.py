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

from ae.tal.settings_v3 import load_tal, _eval_condition


def check_eval_condition() -> dict:
    """Direct grammar checks for the if-condition evaluator (port of eval_condition)."""
    d = {"whocc": "true", "off_flag": "false", "region": "EUROPE", "blank": ""}
    w: list = []
    return {
        "cond $var truthy": _eval_condition("$whocc", d, w) is True,
        "cond $var falsy string": _eval_condition("$off_flag", d, w) is False,
        "cond $var undefined": _eval_condition("$missing", d, w) is False,
        "cond and": _eval_condition({"and": ["$whocc", {"not-empty": "$region"}]}, d, w) is True,
        "cond and short-circuits false": _eval_condition({"and": ["$whocc", "$off_flag"]}, d, w) is False,
        "cond or": _eval_condition({"or": ["$off_flag", "$whocc"]}, d, w) is True,
        "cond not": _eval_condition({"not": "$off_flag"}, d, w) is True,
        "cond empty (blank)": _eval_condition({"empty": "$blank"}, d, w) is True,
        "cond not-empty (set)": _eval_condition({"not-empty": "$region"}, d, w) is True,
        "cond not-empty (undefined)": _eval_condition({"not-empty": "$missing"}, d, w) is False,
        "cond equal": _eval_condition({"equal": ["$region", "EUROPE"]}, d, w) is True,
        "cond not-equal": _eval_condition({"not-equal": ["$region", "ASIA"]}, d, w) is True,
    }


def main():
    # defines enable the first `if` block (pos 145) and disable the `not` block (pos 999)
    schema, warnings = load_tal(os.path.join(HERE, "config-test.tal"), {"enable_extra": "true"})
    checks = {
        "canvas->image_size": schema.get("image_size") == 600,
        "clades.show": schema.get("clades", {}).get("show") is True,
        "time-series.start": schema.get("time_series", {}).get("start") == "2020-01",
        "time-series.end": schema.get("time_series", {}).get("end") == "2021-01",
        "aa-transitions imported (not computed)": schema.get("aa_transitions", {}).get("compute") is False,
        "aa-transitions.min_leaves": schema.get("aa_transitions", {}).get("min_leaves") == 5,
        "if/then gated dash-bars (145 in, 999 out)": [b.get("pos") for b in schema.get("dash_bars", [])] == [159, 145],
        "hz-sections (via sub-array)": len(schema.get("hz_sections", [])) == 1,
        "nodes: hide + positioned-text + edge>= all mapped": len(schema.get("nodes", [])) == 3,
        "apply.text -> positioned label": any(
            n.get("apply", {}).get("text", {}).get("text") == "x"
            and n.get("apply", {}).get("text", {}).get("offset") == [0.02, 0.0]
            for n in schema.get("nodes", [])
        ),
        "edge >= -> edge_min": any(
            n.get("select", {}).get("edge_min") == 0.5 for n in schema.get("nodes", [])
        ),
        "no ?-disabled-key warning": not any("?" in w for w in warnings),
        "per-clade show:false -> hide": any(
            s.get("name") == "C1" and s.get("hide") is True for s in schema.get("clade_styles", [])
        ),
        "per-clade color preserved": any(
            s.get("name") == "C2" and s.get("color") == "#1f78b4" for s in schema.get("clade_styles", [])
        ),
        "tree color-by continent": schema.get("color_by_continent") is True,
        "tree legend.show": schema.get("legend", {}).get("show") is True,
        "no apply.text warning": not any("apply.text" in w for w in warnings),
        "no if-related warning": not any(w.startswith("if:") for w in warnings),
    }
    checks.update(check_eval_condition())
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
