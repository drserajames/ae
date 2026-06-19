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

from ae.tal.settings_v3 import load_tal, _eval_condition, translate, _expand_seq_id


def check_imported_no_curation() -> dict:
    """A draw-aa-transitions block with method 'imported' and NO per-node curation
    must enable aa_transitions.show (draw the tree's stored transitions) — the
    opposite of the curated case, which suppresses it."""
    tal = {"tal": [
        {"N": "draw-aa-transitions", "method": "imported", "minimum-number-leaves-in-subtree": 5},
    ]}
    schema, _ = translate(tal)
    aa = schema.get("aa_transitions", {})
    return {
        "imported (no per-node): show enabled": aa.get("show") is True,
        "imported (no per-node): compute False": aa.get("compute") is False,
        "imported (no per-node): min_leaves": aa.get("min_leaves") == 5,
    }


def check_seq_id_alternation() -> dict:
    """A `(A|B|C)` alternation seq_id (AD regex; tal-draw matches exactly) must expand
    into its exact members so long-branch hides actually fire."""
    expanded = _expand_seq_id("(A/X/1_aa|A/Y/2_bb|A/Z/3_cc)")
    tal = {"tal": [
        {"N": "nodes", "select": {"seq_id": "(P/1_h|Q/2_h|R/3_h)"}, "apply": {"hide": True}},
    ]}
    schema, _ = translate(tal)
    sel = schema.get("nodes", [{}])[0].get("select", {}).get("seq_id", [])
    return {
        "seq_id alternation -> exact list": expanded == ["A/X/1_aa", "A/Y/2_bb", "A/Z/3_cc"],
        "plain seq_id passes through": _expand_seq_id("A/X/1_aa") == ["A/X/1_aa"],
        "nodes seq_id alternation expanded": sel == ["P/1_h", "Q/2_h", "R/3_h"],
    }


def check_dash_bar_colors() -> dict:
    """dash-bar-aa-at `colors` (aa->colour object, "transparent" = don't draw) must pass
    through to the schema as a [{aa,color}] array so the bar shows AD's exact variant colours."""
    tal = {"tal": [
        {"N": "dash-bar-aa-at", "pos": 135, "colors": {"T": "transparent", "K": "#07e8c4", "A": "#00939f"}},
    ]}
    schema, _ = translate(tal)
    bar = schema.get("dash_bars", [{}])[0]
    cols = {c["aa"]: c["color"] for c in bar.get("colors", [])}
    return {
        "dash-bar pos passed": bar.get("pos") == 135,
        "dash-bar colors -> [{aa,color}]": cols.get("K") == "#07e8c4" and cols.get("A") == "#00939f",
        "dash-bar transparent preserved": cols.get("T") == "transparent",
    }


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
        # When draw-aa-transitions carries curated per-node labels (emitted as MRCA
        # labels), aa_transitions.show must NOT be set — otherwise every stored inode
        # transition is also drawn (the H3/H1 purple flood). The imported-transition
        # path is exercised separately below (check_imported_no_curation).
        "aa-transitions: curated per-node suppresses imported show": "aa_transitions" not in schema,
        "draw-aa-transitions per-node -> mrca_label (?first/?last bounds)": any(
            m.get("first") == "A" and m.get("last") == "C" and m.get("text") == "T1K" and m.get("offset") == [0.01, 0.0]
            for m in schema.get("mrca_labels", [])
        ),
        "mrca_label without bounds skipped (only the well-formed one)": len(schema.get("mrca_labels", [])) == 1,
        "if/then gated + for-each dash-bars (145 in, 999 out, 7/8 from for-each)": [b.get("pos") for b in schema.get("dash_bars", [])] == [159, 145, 7, 8],
        "ladderize method -> schema": schema.get("ladderize") == "max-edge-length",
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
        # clades-whocc is a user-defined sub-array here (as in the real report .tal): the
        # translator must RUN it (picking up its curated per-clade) and enable the continent
        # legend, not short-circuit it as a hardcoded builtin.
        "clades-whocc sub-array ran (per-clade hide)": any(
            s.get("name") == "WC_HIDDEN" and s.get("hide") is True for s in schema.get("clade_styles", [])
        ),
        "clades-whocc display_name key": any(
            s.get("name") == "WC_DISP" and s.get("display_name") == "wc" for s in schema.get("clade_styles", [])
        ),
        # under continent colouring the clades column must NOT switch leaves to colour-by-clade
        "clades column keeps continent colouring": schema.get("color_by_clade") is None,
        "no apply.text warning": not any("apply.text" in w for w in warnings),
        "no if-related warning": not any(w.startswith("if:") for w in warnings),
    }
    checks.update(check_eval_condition())
    checks.update(check_imported_no_curation())
    checks.update(check_seq_id_alternation())
    checks.update(check_dash_bar_colors())
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
