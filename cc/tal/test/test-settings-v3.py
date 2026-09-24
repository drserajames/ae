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

from ae.tal.settings_v3 import load_tal, _eval_condition, translate


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


def check_curated_method_still_computes() -> dict:
    """Curated `per-node` labels suppress the BLANKET per-inode labels (`show`), but they
    must NOT suppress the COMPUTATION the block asks for.

    AD's Settings::add_draw_aa_transitions (acmacs-tal cc/settings.cc:1256) sets
    `aa_transitions.calculate = true` for every `draw-aa-transitions` command, curated or
    not, and HzSections::set_aa_transitions accumulates the resulting per-inode labels into
    each hz-section's aa-transitions text — the text printed on every signature-page map
    title. Dropping the whole block for a curated `.tal` silently fell back to the tree's
    stored "imported" labels, so a `.tal` asking for eu-20200915 never got it.

    An "imported" curated block has nothing to compute, so it still emits no entry."""
    curated = [{"name": "Q1R", "show": True, "?first": "A", "?last": "C"}]
    eu, _ = translate({"tal": [
        {"N": "draw-aa-transitions", "method": "eu-20200915", "non-common-tolerance": 0.7,
         "minimum-number-leaves-in-subtree": 4, "per-node": curated},
    ]})
    eu_aa = eu.get("aa_transitions", {})
    imported, _ = translate({"tal": [
        {"N": "draw-aa-transitions", "method": "imported", "per-node": curated},
    ]})
    blanket, _ = translate({"tal": [
        {"N": "draw-aa-transitions", "method": "eu-20200915"},
    ]})
    return {
        "curated eu-20200915: compute kept on": eu_aa.get("compute") is True,
        "curated eu-20200915: blanket labels off": eu_aa.get("show") is False,
        "curated eu-20200915: method passed through": eu_aa.get("method") == "eu-20200915",
        "curated eu-20200915: tolerance passed through": eu_aa.get("tolerance") == 0.7,
        "curated eu-20200915: min_leaves passed through": eu_aa.get("min_leaves") == 4,
        "curated eu-20200915: mrca label still emitted": len(eu.get("mrca_labels", [])) == 1,
        "curated imported: nothing to compute -> no entry": "aa_transitions" not in imported,
        "uncurated eu-20200915: show and compute both on": (
            blanket.get("aa_transitions", {}).get("show") is True
            and blanket.get("aa_transitions", {}).get("compute") is True),
    }


def check_seq_id_passthrough() -> dict:
    """A `seq_id` select is passed to tal-draw verbatim, whatever its shape. AD matches it as
    an unanchored, case-insensitive regex and tal-draw now does the same (SeqIdMatcher,
    cc/tal/draw-tree.hh), so the translator must NOT rewrite an alternation into its members
    any more — a `(A|B|C)` group is a regex the matcher handles natively."""
    tal = {"tal": [
        {"N": "nodes", "select": {"seq_id": "(P/1_h|Q/2_h|R/3_h)"}, "apply": {"hide": True}},
        {"N": "nodes", "select": {"seq_id": "S/4_h"}, "apply": {"hide": True}},
        {"N": "nodes", "select": {"seq_id": ["T/5_h", "U/6*"]}, "apply": {"hide": True}},
    ]}
    schema, _ = translate(tal)
    nodes = schema.get("nodes", [])
    sel = [n.get("select", {}).get("seq_id", []) for n in nodes]
    return {
        "alternation kept intact as one regex": sel[0] == ["(P/1_h|Q/2_h|R/3_h)"],
        "plain seq_id -> single-entry list": sel[1] == ["S/4_h"],
        "list form preserved, order and all": sel[2] == ["T/5_h", "U/6*"],
    }


def check_dash_bar_colors() -> dict:
    """dash-bar-aa-at `colors` (aa->colour object, "transparent" = don't draw) must pass
    through to the schema as a [{aa,color}] array so the bar shows AD's exact variant colours."""
    tal = {"tal": [
        {"N": "dash-bar-aa-at", "pos": 135, "colors": {"T": "transparent", "K": "#07e8c4", "A": "#00939f"},
         "labels": {"K": {"text": "135K", "color": "#07e8c4"}, "A": {"text": "135A", "color": "#00939f"},
                    "X": {"text": "."}}},
        # a select-based dash-bar (h1-style) must be skipped over ?-disabled stubs and extracted
        {"?N": "dash-bar-aa-at", "id": "disabled", "pos": 999},
        {"N": "dash-bar", "id": "bar-155-156", "nodes": [
            {"select": {"aa": ["156N", "155G"]}, "color": "#03569b"},
            {"select": {"aa": ["155E"]}, "color": "#ffc808"}],
         "labels": [{"text": "156N", "color": "#03569b"}, {"text": "155E", "color": "#ffc808"}]},
    ]}
    schema, _ = translate(tal)
    bars = schema.get("dash_bars", [])
    bar = bars[0] if bars else {}
    cols = {c["aa"]: c["color"] for c in bar.get("colors", [])}
    leg = {l["text"]: l for l in bar.get("legend", [])}
    sel_bar = next((b for b in bars if b.get("selects")), {})
    return {
        "dash-bar pos passed": bar.get("pos") == 135,
        "dash-bar colors -> [{aa,color}]": cols.get("K") == "#07e8c4" and cols.get("A") == "#00939f",
        "dash-bar transparent preserved": cols.get("T") == "transparent",
        "legend carries aa key (for actual-colour swatch)": leg.get("135K", {}).get("aa") == "K",
        "legend skips '.' placeholders": "." not in leg,
        "?N-disabled dash bar skipped, active ones kept": len(bars) == 2 and all("pos" not in b or b["pos"] != 999 for b in bars),
        "select-based dash-bar extracted": len(sel_bar.get("selects", [])) == 2,
        "select conditions parsed": sel_bar.get("selects", [{}])[0].get("aa") == ["156N", "155G"],
    }


def check_dash_bar_side() -> dict:
    """`"side": "left"` on a dash-bar / dash-bar-aa-at (ae extension): emitted only for "left",
    so default and "right" bars translate exactly as before; a left bar still counts towards the
    page width, and the extra tal-draw column gap it costs (0.012 of the page width, paid only
    while bars remain on the right too) grows the page instead of coming out of the tree."""
    def bars_of(extra_left: dict, extra_right: dict) -> list:
        tal = {"tal": [
            {"N": "dash-bar-aa-at", "id": "p3", "pos": 3, **extra_right},
            {"N": "dash-bar", "id": "grp", "nodes": [{"select": {"aa": ["3A"]}, "color": "black"}], **extra_left},
        ]}
        schema, warnings = translate(tal)
        return schema.get("dash_bars", []), warnings

    default_bars, _ = bars_of({}, {})
    right_bars, _ = bars_of({"side": "right"}, {"side": "right"})
    left_bars, _ = bars_of({"side": "left"}, {})
    odd_bars, odd_warn = bars_of({"side": "middle"}, {})

    def ratio(sides: tuple) -> float:
        prog = [{"N": "margins", "left": 0.01, "right": 0.01},
                {"N": "tree", "width-to-height-ratio": 0.40}]
        for i, side in enumerate(sides):
            cmd = {"N": "dash-bar", "id": f"b{i}", "width-to-height-ratio": 0.01,
                   "nodes": [{"select": {"aa": ["3A"]}, "color": "black"}]}
            if side:
                cmd["side"] = side
            prog.append(cmd)
        schema, _ = translate({"tal": prog})
        return schema.get("width_to_height_ratio")

    # (.40 + 2 * .01 + .01 + .01) / 1.05 = .44 / 1.05
    all_right = ratio((None, None))
    base = round(0.44 / 1.05, 6)
    return {
        "dash-bar side: absent -> no side key": all("side" not in b for b in default_bars),
        "dash-bar side: explicit right -> no side key (schema unchanged)": right_bars == default_bars,
        "dash-bar side: left emitted on the left bar only": [b.get("side") for b in left_bars] == [None, "left"],
        "dash-bar side: unknown value warns and stays right": "side" not in odd_bars[1] and any("side" in w for w in odd_warn),
        "dash-bar side: all-right page width unchanged": all_right == base,
        "dash-bar side: all-left page width = all-right (bars counted, gaps cancel)": ratio(("left", "left")) == base,
        "dash-bar side: mixed page grows by the left column gap (0.012 of width)":
            ratio(("left", None)) == round(0.44 / 1.05 / (1.0 - 0.012), 6),
    }


def check_tip_names_and_edges() -> dict:
    """node-id-size enables per-leaf tip names; continent colouring — whether asked for by
    the `tree` element or by time-series/clades-whocc — must NOT set color_edges.

    AD reference (~/AC/eu/AD/sources/acmacs-tal/): DrawTree strokes every edge in
    `node.color_edge_line` (cc/draw-tree.cc:73 leaf, :88 inode), whose only writers are an
    explicit `nodes apply.tree-edge-line-color` mod (cc/settings.cc:292-295) and the
    branches-by-edge diagnostic (cc/tree.cc:268, RED); its default is BLACK
    (cc/tree.hh:108). A `tree` color-by feeds `coloring()`, which colours the leaf *label*
    (cc/draw-tree.cc:77) plus the matrix/legend/world map — never the edges. So continent
    colouring leaves the tree black. `color_by_pos` is the one color-by ae still maps to
    color_edges (no AD reference render to check it against yet)."""
    tal_tip = {"tal": [{"N": "node-id-size", "size": 0.0002}]}
    s_tip, _ = translate(tal_tip)
    tal_tree_cb = {"tal": [{"N": "tree", "color-by": "continent"}]}
    s_tree, _ = translate(tal_tree_cb)
    tal_tree_pos = {"tal": [{"N": "tree", "color-by": {"N": "pos-aa-frequency", "pos": 135}}]}
    s_pos, _ = translate(tal_tree_pos)
    tal_ts = {"tal": [{"N": "time-series", "start": "2024-03", "end": "2026-03", "color-by": "continent"}]}
    s_ts, _ = translate(tal_ts)
    return {
        "node-id-size -> tip_names": s_tip.get("tip_names") is True,
        "tree color-by continent sets color_by_continent": s_tree.get("color_by_continent") is True,
        "tree continent does NOT set color_edges (AD edges stay black)": "color_edges" not in s_tree,
        "tree color-by pos DOES set color_edges": s_pos.get("color_edges") is True
            and s_pos.get("color_by_pos") == {"pos": 135},
        "time-series continent does NOT set color_edges": "color_edges" not in s_ts,
    }


def check_time_series_slot() -> dict:
    """time-series slot.width / label scale+rotation pass through to the schema."""
    tal = {"tal": [{"N": "time-series", "start": "2024-03", "end": "2026-03",
                    "slot": {"width": 0.005, "label": {"scale": 0.9, "rotation": "clockwise"}}}]}
    s, _ = translate(tal)
    ts = s.get("time_series", {})
    return {
        "slot.width passed": ts.get("slot_width") == 0.005,
        "label.scale passed": ts.get("label_scale") == 0.9,
        "label.rotation passed": ts.get("label_rotation") == "clockwise",
        # absent "dates"/"year-separator" emit nothing, so tal-draw's defaults (both bands, 0.5) apply
        "no dates/year_separator by default": not {"dates_top", "dates_bottom", "year_separator"} & ts.keys(),
        **check_time_series_dates(),
    }


def check_time_series_dates() -> dict:
    """time-series "dates" (bool or {"top", "bottom"}) and "year-separator" reach the schema."""
    def ts(**cmd):
        return translate({"tal": [{"N": "time-series", **cmd}]})[0].get("time_series", {})
    off, on = ts(dates=False), ts(dates=True)
    top_only = ts(dates={"top": False, "bottom": True})
    one_key = ts(dates={"bottom": False})
    return {
        "dates false -> both bands off": (off.get("dates_top"), off.get("dates_bottom")) == (False, False),
        "dates true -> both bands on": (on.get("dates_top"), on.get("dates_bottom")) == (True, True),
        "dates {top,bottom} per band": (top_only.get("dates_top"), top_only.get("dates_bottom")) == (False, True),
        "dates {bottom} leaves top unset": one_key.get("dates_bottom") is False and "dates_top" not in one_key,
        "dates non-bool ignored": not {"dates_top", "dates_bottom"} & ts(dates="no").keys(),
        "year-separator -> float": ts(**{"year-separator": 2}).get("year_separator") == 2.0
                                   and isinstance(ts(**{"year-separator": 2}).get("year_separator"), float),
        "year-separator bool ignored": "year_separator" not in ts(**{"year-separator": True}),
    }


def check_clade_slot_and_gap() -> dict:
    """per-clade `slot` keeps its fraction/sign, and `gap-ratio` reaches the schema.

    A fractional or slightly negative slot moves one bracket towards the matrix without
    shrinking `slot.width` (which also sets the level pitch and the label size). AD's own
    slot_no is an unsigned size_t and truncates, so this is a deliberate ae superset; `int()`
    here used to throw the fraction away before the renderer ever saw it.
    """
    tal = {"tal": [{"N": "clades", "slot": {"width": 0.02}, "gap-ratio": 0.0,
                    "per-clade": [{"name": "Kappa", "slot": 2.2},
                                  {"name": "Lambda", "slot": -0.5},
                                  {"name": "Mu", "slot": 0},
                                  {"name": "Nu"}]}]}
    s, _ = translate(tal)
    styles = {st.get("name"): st for st in s.get("clade_styles", [])}
    return {
        "clade slot keeps its fraction": styles.get("Kappa", {}).get("slot") == 2.2,
        "clade slot keeps its sign": styles.get("Lambda", {}).get("slot") == -0.5,
        "clade slot 0 is not dropped": styles.get("Mu", {}).get("slot") == 0.0,
        "absent clade slot stays absent (auto-place)": "slot" not in styles.get("Nu", {}),
        "clades gap-ratio of 0 reaches the schema": s.get("clades", {}).get("gap_ratio") == 0.0,
    }


def check_clade_band_gap() -> dict:
    """`"band-gap"` on the clades command reaches the schema as a float, and only when set
    (absent keeps the C++ default 0 = brackets over the full band)."""
    on, _ = translate({"tal": [{"N": "clades", "band-gap": 2}]})
    off, _ = translate({"tal": [{"N": "clades"}]})
    bad, _ = translate({"tal": [{"N": "clades", "band-gap": True}]})
    return {
        "clades band-gap reaches the schema as a float": on.get("clades", {}).get("band_gap") == 2.0
                                                        and isinstance(on["clades"]["band_gap"], float),
        "clades band-gap absent -> not emitted": "band_gap" not in off.get("clades", {}),
        "clades band-gap true (not a number) -> not emitted": "band_gap" not in bad.get("clades", {}),
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
    checks.update(check_curated_method_still_computes())
    checks.update(check_seq_id_passthrough())
    checks.update(check_dash_bar_colors())
    checks.update(check_dash_bar_side())
    checks.update(check_tip_names_and_edges())
    checks.update(check_time_series_slot())
    checks.update(check_clade_slot_and_gap())
    checks.update(check_clade_band_gap())
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
