"""Translate acmacs-tal's settings-v3 `.tal` configs into tal-draw's declarative schema.

The production reports drive `tal` with the AD settings-v3 format — a top-level object
of named arrays where the `"tal"` array is a program of mod commands, each either a
string (a built-in or the name of another array to run) or an object `{"N": cmd, …}`
(`{"?N": …}` = disabled). This translator walks that program and maps the commands onto
the simplified schema that `tal-draw --settings` consumes.

It is **structural, not pixel-perfect**: it reproduces which clades/sections/columns/
transitions appear and the overall portrait page aspect (tree `width-to-height-ratio`
plus a column allowance), but a few things have no tal-draw equivalent yet and are
collected in the returned `warnings` rather than silently dropped:
  - `draw-aa-transitions` curated `per-node` labels select by AD's draw-time
    `node_id` ("vertical.horizontal"), which ae's tree does not carry (it stores a
    single integer id); they are reported, not placed. seq_id-selected `apply.text`
    labels DO translate.
  - the exact WHOCC clade hex palette (ae uses its own stable palette), the full
    vertical clade legend, and the geographic world-map inset.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _loads_relaxed(text: str) -> dict:
    """Parse AD's relaxed JSON: tolerate trailing commas and // line comments."""
    text = re.sub(r"//[^\n]*", "", text)          # // line comments (none nested in .tal strings)
    text = re.sub(r",(\s*[}\]])", r"\1", text)    # trailing commas before } or ]
    return json.loads(text)


def _substitute(obj: Any, defines: dict) -> Any:
    """Recursively replace "$name" string values with defines[name]."""
    if isinstance(obj, str) and obj.startswith("$"):
        return defines.get(obj[1:], obj)
    if isinstance(obj, list):
        return [_substitute(x, defines) for x in obj]
    if isinstance(obj, dict):
        return {k: _substitute(v, defines) for k, v in obj.items()}
    return obj


# Strings that count as false for a `$var` / bare-string condition. Everything else
# non-empty is truthy. Mirrors how `-D name` (truthy flag) vs `-D name=false` read.
_FALSY_STRINGS = {"", "false", "no", "0", "off", "null", "none"}


def _resolve(value: Any, defines: dict) -> Any:
    """Resolve a "$name" reference against defines (None if undefined); else pass through."""
    if isinstance(value, str) and value.startswith("$"):
        return defines.get(value[1:])
    return value


def _truthy(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() not in _FALSY_STRINGS
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return bool(value)


def _eval_condition(cond: Any, defines: dict, warnings: list) -> bool:
    """Evaluate an acmacs-tal settings-v3 `if` condition (port of Data::eval_condition).

    Grammar: null->false, bool/number as-is, "$var" resolves+truthy, and one-key objects
    `and`/`or`/`not`/`empty`/`not-empty`/`equal`/`not-equal`.
    """
    if cond is None:
        return False
    if isinstance(cond, bool):
        return cond
    if isinstance(cond, (int, float)):
        return cond != 0
    if isinstance(cond, str):
        if cond.startswith("$"):
            return _truthy(_resolve(cond, defines))
        low = cond.strip().lower()
        if low in ("true", "yes", "1", "on"):
            return True
        if low in _FALSY_STRINGS:
            return False
        warnings.append(f"if: unsupported string condition {cond!r} — treated as false")
        return False
    if isinstance(cond, dict):
        if len(cond) != 1:
            warnings.append(f"if: condition object must have exactly one key: {cond!r} — false")
            return False
        key, val = next(iter(cond.items()))
        if key == "and":
            return bool(val) and all(_eval_condition(c, defines, warnings) for c in val)
        if key == "or":
            return bool(val) and any(_eval_condition(c, defines, warnings) for c in val)
        if key == "not":
            return not _eval_condition(val, defines, warnings)
        if key in ("empty", "not-empty"):
            resolved = _resolve(val, defines)
            if resolved is None:
                is_empty = True
            elif isinstance(resolved, str):
                is_empty = resolved == ""
            else:
                warnings.append(f"if: {key} on non-string {resolved!r} — false")
                return False
            return is_empty if key == "empty" else not is_empty
        if key in ("equal", "not-equal"):
            if not isinstance(val, list) or len(val) < 2:
                warnings.append(f"if: {key} needs an array of 2+ — false")
                return False
            resolved = [_resolve(x, defines) for x in val]
            equal = all(x == resolved[0] for x in resolved[1:])
            return equal if key == "equal" else not equal
        warnings.append(f"if: unrecognized condition clause {key!r} — false")
        return False
    warnings.append(f"if: unsupported condition {cond!r} — false")
    return False


# --- page-width accounting (port of acmacs-tal Layout::width_relative_to_height) -----
#
# acmacs-tal sizes the portrait page from the SUM of every enabled normal-position
# layout element's `width-to-height-ratio`, in program order, plus the left/right
# margins, over (1 + top + bottom margins) — see acmacs-tal cc/draw.cc
# Draw::set_width_to_height_ratio() and cc/layout.cc Layout::width_relative_to_height().
# Each element contributes:
#   tree                : its `width-to-height-ratio`
#   gap                 : `pixels`/canvas-height if given, else `width-to-height-ratio`,
#                         else the 0.05 default (Gap::prepare; pixels takes precedence)
#   time-series         : n_slots * slot.width  (slot.width default 0.01; n_slots =
#                         whole months in [start, end), i.e. end is exclusive)
#   clades              : explicit `width-to-height-ratio` (the reports always set it),
#                         else (n_slots+2)*slot.width — approximated when slots unknown
#   dash-bar / -aa-at / -clades : explicit `width-to-height-ratio`, else the 0.009
#                         DashBarBase default
#   hz-section-marker   : explicit `width-to-height-ratio`, else 0.005
#   tree-only hz-sections, title, draw-aa-transitions, nodes, … : 0 (absolute / no width)
# Defaults from acmacs-tal: canvas-height 1000, margins {left .025, right 0, top .025,
# bottom .025} (a `margins` command overrides only the keys it names).

_DASH_BAR_DEFAULT_WIDTH = 0.009   # DashBarBase(tal, 0.009)
_GAP_DEFAULT_WIDTH = 0.05         # Gap(tal, 0.05)
_TS_SLOT_DEFAULT_WIDTH = 0.01     # TimeSeries::SlotParameters.width
_CLADES_SLOT_DEFAULT_WIDTH = 0.02 # Clades::SlotParameters.width
_HZ_MARKER_DEFAULT_WIDTH = 0.005  # builtin hz-section-marker width-to-height-ratio


def _as_number(value: Any, defines: dict) -> float | None:
    """Resolve a literal or "$ref" to a float, or None if not numeric."""
    if isinstance(value, str) and value.startswith("$"):
        value = _resolve(value, defines)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _time_series_slots(cmd: dict, warnings: list) -> int | None:
    """Number of monthly slots acmacs-tal would draw for a `start`/`end` time-series.

    Months in the half-open range [start, end) (end exclusive), matching
    time_series::make. Only the monthly interval (the report default) is computed.
    """
    start, end = cmd.get("start"), cmd.get("end")
    interval = cmd.get("interval", "month")
    if not (isinstance(start, str) and isinstance(end, str)):
        return None
    m = re.match(r"^(\d{4})-(\d{2})", start)
    n = re.match(r"^(\d{4})-(\d{2})", end)
    if not (m and n):
        return None
    months = (int(n.group(1)) * 12 + int(n.group(2))) - (int(m.group(1)) * 12 + int(m.group(2)))
    if months <= 0:
        return None
    if interval in ("month", "monthly"):
        return months
    if interval in ("year", "yearly"):
        return max(1, months // 12)
    warnings.append(f"time-series interval {interval!r} width not computed — page width approximated")
    return None


def _compute_layout_width(tal: dict, defines: dict, warnings: list) -> float:
    """Replicate acmacs-tal's page width-to-height ratio for the `.tal` program.

    Walks the `tal` program in order — following string and {"N": "<sub-array>"}
    sub-array invocations, `if`/`then`/`else`, and skipping ?-disabled entries — and
    sums each enabled normal-position element's width, then applies the margins.
    """
    canvas_height = 1000.0
    margins = {"left": 0.025, "right": 0.0, "top": 0.025, "bottom": 0.025}
    width = 0.0
    visited: set = set()  # sub-array names already walked (so builtin hooks aren't doubled)

    def walk(program) -> None:
        nonlocal canvas_height, width
        for item in program:
            if isinstance(item, str):
                if item.startswith("?"):
                    continue
                if item in tal and isinstance(tal[item], list):
                    visited.add(item)
                    walk(tal[item])
                continue
            if not isinstance(item, dict) or "N" not in item:
                continue  # {"?N": …} disabled, or a comment
            cmd = _substitute(item, defines)
            name = cmd["N"]
            if name == "if":
                branch = item.get("then") if _eval_condition(item.get("condition"), defines, warnings) else item.get("else")
                if isinstance(branch, list):
                    walk(branch)
                continue
            if name == "canvas":
                h = _as_number(cmd.get("height"), defines)
                if h and h > 0:
                    canvas_height = h
            elif name == "margins":
                for key in ("left", "right", "top", "bottom"):
                    if key in cmd:
                        val = _as_number(cmd[key], defines)
                        if val is not None:
                            margins[key] = val
            elif name == "tree":
                w = _as_number(cmd.get("width-to-height-ratio"), defines)
                if w and w > 0:
                    width += w
            elif name == "gap":
                if "pixels" in cmd:  # pixels override width-to-height-ratio (Gap::prepare)
                    p = _as_number(cmd["pixels"], defines)
                    if p is not None:
                        width += p / canvas_height
                elif "width-to-height-ratio" in cmd:
                    w = _as_number(cmd["width-to-height-ratio"], defines)
                    width += w if w is not None else _GAP_DEFAULT_WIDTH
                else:
                    width += _GAP_DEFAULT_WIDTH
            elif name == "time-series":
                slot = cmd.get("slot") if isinstance(cmd.get("slot"), dict) else {}
                slot_width = _as_number(slot.get("width"), defines)
                if slot_width is None:
                    slot_width = _TS_SLOT_DEFAULT_WIDTH
                slots = _time_series_slots(cmd, warnings)
                if slots is not None:
                    width += slots * slot_width
            elif name == "clades":
                w = _as_number(cmd.get("width-to-height-ratio"), defines)
                if w is not None:
                    width += w
                else:
                    # auto-sized: (n_slots+2)*slot.width. n_slots needs the tree, which
                    # we don't have here; the reports always set width-to-height-ratio,
                    # so this is only an approximation for atypical configs.
                    slot = cmd.get("slot") if isinstance(cmd.get("slot"), dict) else {}
                    slot_width = _as_number(slot.get("width"), defines) or _CLADES_SLOT_DEFAULT_WIDTH
                    width += 2 * slot_width
            elif name in ("dash-bar", "dash-bar-aa-at", "dash-bar-clades"):
                w = _as_number(cmd.get("width-to-height-ratio"), defines)
                width += w if w is not None else _DASH_BAR_DEFAULT_WIDTH
            elif name == "hz-section-marker":
                w = _as_number(cmd.get("width-to-height-ratio"), defines)
                width += w if w is not None else _HZ_MARKER_DEFAULT_WIDTH
            elif name in tal and isinstance(tal[name], list):
                visited.add(name)
                walk(tal[name])  # object-form sub-array invocation {"N": "<sub-array>"}
            # all other commands (title, draw-aa-transitions, nodes, hz-sections in a
            # tree-only layout, set, ladderize, …) are absolute / contribute no width

    walk(tal.get("tal", []))
    # acmacs-tal's builtin tree-only layout (conf/tal.json `layout-tree-only`) draws its
    # tree/time-series/clades as singletons that the user `.tal` above overrides (settings
    # find-or-update by element id), but it ALSO invokes three user-overridable column
    # hooks between the tree and the time-series — `tal-dash-bar-left-1`,
    # `tal-dash-bar-clades`, `tal-dash-bar-left-2` — that the user program does not invoke
    # itself. The reports redefine `tal-dash-bar-clades` to add a per-subtype gap (h3 0.015,
    # h1 0.009; empty for bvic), so its width must be included. Walk any not already visited.
    for hook in ("tal-dash-bar-left-1", "tal-dash-bar-clades", "tal-dash-bar-left-2"):
        if hook not in visited and hook in tal and isinstance(tal[hook], list):
            walk(tal[hook])
    return (width + margins["left"] + margins["right"]) / (1.0 + margins["top"] + margins["bottom"])


def _select(select: dict, warnings: list) -> dict:
    out: dict = {}
    if "seq_id" in select:
        sid = select["seq_id"]
        out["seq_id"] = sid if isinstance(sid, list) else [sid]
    if "cumulative >=" in select:
        out["cumulative_min"] = select["cumulative >="]
    if "edge >=" in select:
        out["edge_min"] = select["edge >="]
    if "date_min" in select:
        out["date_min"] = select["date_min"]
    if "date_max" in select:
        out["date_max"] = select["date_max"]
    known = ("seq_id", "cumulative >=", "edge >=", "date_min", "date_max", "report")
    for key in select:
        if key.startswith("?"):
            continue  # ?-disabled key — silently skip (not an unsupported criterion)
        if key not in known:
            warnings.append(f"nodes.select: unsupported criterion {key!r} ignored")
    return out


def _apply(apply: dict, warnings: list) -> dict:
    out: dict = {}
    if apply.get("hide"):
        out["hide"] = True
    if "tree-edge-line-color" in apply:
        out["edge_color"] = apply["tree-edge-line-color"]
    if "label" in apply and isinstance(apply["label"], dict) and "color" in apply["label"]:
        out["label_color"] = apply["label"]["color"]
    if "text" in apply:
        text = apply["text"]
        if isinstance(text, dict) and text.get("text"):
            node_text: dict = {"text": text["text"]}
            offset = text.get("offset")
            if isinstance(offset, list) and len(offset) == 2:
                node_text["offset"] = offset
            if "color" in text:
                node_text["color"] = text["color"]
            if "size" in text:
                node_text["size"] = text["size"]
            out["text"] = node_text
        else:
            warnings.append("nodes.apply.text without a 'text' string — skipped")
    return out


def translate(tal: dict, defines: dict | None = None) -> tuple[dict, list]:
    """Translate a loaded `.tal` settings-v3 object into (schema, warnings)."""
    defines = dict(defines or {})
    warnings: list = []
    # No per-leaf name labels by default: the production trees have tens of thousands of
    # leaves (AD shows none), and the strain names that *are* wanted come through as
    # positioned `apply.text` labels (DrawOnTree). A `.tal` can re-enable via a `tree`
    # `show-leaf-names` flag (handled below) if ever needed.
    schema: dict = {"labels": False}
    node_mods: list = []

    def run(program) -> None:
        for item in program:
            if isinstance(item, str):
                if item.startswith("?"):
                    continue                                          # "?name" = disabled reference, skip silently
                if item == "clades-whocc":
                    # AD's WHOCC builtin colours the tree + time-series matrix by *continent*
                    # and shows the continent legend (its `{"N":"tree","color-by":"continent",
                    # "legend":{"show":true}}`). Set those first (ae has the exact AD continent
                    # palette) — NOT colour-by-clade: the clades are the labelled right column.
                    schema.setdefault("color_by_continent", True)
                    schema.setdefault("legend", {})["show"] = True
                    # AD's WHOCC builtin also draws the LegendContinentMap (the small
                    # continent-coloured world map lower-left, which doubles as the continent
                    # legend). Mirror it with the geo inset.
                    schema.setdefault("geo_inset", True)
                    if item in tal and isinstance(tal[item], list):
                        # The report .tal usually DEFINES its own `clades-whocc` sub-array — a
                        # `clades` command carrying the curated `per-clade` set (which clades to
                        # show + their display names). Run it so that curation reaches the column
                        # (a hardcoded builtin would have dropped it).
                        run(tal[item])
                    else:
                        schema.setdefault("clades", {})["show"] = True  # builtin fallback: just show the column
                    continue
                if item in tal and isinstance(tal[item], list):
                    run(tal[item])                                    # named sub-array
                else:
                    warnings.append(f"unknown built-in / sub-array {item!r} ignored")
                continue
            if not isinstance(item, dict) or "N" not in item:
                continue  # {"?N": …} disabled, or a comment
            cmd = _substitute(item, defines)
            name = cmd["N"]
            if name == "if":
                # conditional sub-program: run "then" (or "else") if the condition holds.
                # Evaluate against the raw item so "$var" condition refs stay explicit.
                branch = item.get("then") if _eval_condition(item.get("condition"), defines, warnings) else item.get("else")
                if isinstance(branch, list):
                    run(branch)
                elif branch is not None:
                    warnings.append("if: 'then'/'else' must be an array — skipped")
                continue
            if name == "canvas":
                if "height" in cmd:
                    try:
                        schema["image_size"] = int(float(cmd["height"]))
                    except (TypeError, ValueError):
                        pass
            elif name == "clades":
                clades = schema.setdefault("clades", {})
                clades["show"] = True
                # The clades command draws the labelled column; it only recolours the leaves
                # when no explicit leaf colouring is in force. Under the WHOCC continent reports
                # (color_by_continent already set) the matrix stays continent-coloured.
                if not schema.get("color_by_continent"):
                    schema["color_by_clade"] = True
                for pc in cmd.get("per-clade", []):
                    if not isinstance(pc, dict) or not pc.get("name"):
                        continue
                    style: dict = {"name": pc["name"]}
                    if pc.get("show") is False:
                        style["hide"] = True
                    if "color" in pc:
                        style["color"] = pc["color"]
                    if pc.get("display_name"):                       # explicit display-name override
                        style["display_name"] = pc["display_name"]
                    elif isinstance(pc.get("label"), dict) and "text" in pc["label"]:
                        style["display_name"] = pc["label"]["text"]  # label.text doubles as the display name
                    if len(style) > 1:  # name + at least one styling key
                        schema.setdefault("clade_styles", []).append(style)
            elif name == "time-series":
                ts = schema.setdefault("time_series", {})
                ts["show"] = True
                if "start" in cmd:
                    ts["start"] = cmd["start"]
                if "end" in cmd:
                    ts["end"] = cmd["end"]
                ts.setdefault("interval", "month")
                # the matrix is coloured by the time-series color-by (AD reports use continent;
                # ae has the exact AD continent palette). Set the leaf colour mode accordingly.
                if cmd.get("color-by") == "continent":
                    schema["color_by_continent"] = True
                    schema.pop("color_by_clade", None)  # continent wins over the clades-whocc default
            elif name == "draw-aa-transitions":
                # AD's draw-aa-transitions labels the *curated* `per-node` set, not every
                # inode: each entry picks one node by AD's draw-time node_id
                # ("vertical.horizontal") and places its label at an offset. ae's tree has
                # no equivalent node_id (it stores a single integer id), so the curated
                # per-node labels cannot be matched here — report them, don't place them.
                # Crucially, do NOT translate a non-"imported" method to consensus
                # computation: that would label every inode (a purple flood), the opposite
                # of the AD reference. Only the explicit "imported" method (use the tree's
                # stored transitions) shows transitions.
                pernode = cmd.get("per-node")
                if isinstance(pernode, list):
                    n_curated = sum(1 for e in pernode if isinstance(e, dict) and e.get("show", True) and e.get("name"))
                    if n_curated:
                        warnings.append(
                            f"draw-aa-transitions: {n_curated} curated per-node label(s) select by AD "
                            "node_id, which ae's tree does not carry — labels skipped (no equivalent yet)")
                if cmd.get("method", "imported") == "imported":
                    aa = schema.setdefault("aa_transitions", {})
                    aa["show"] = True
                    aa["compute"] = False  # use the tree's stored ("imported") transitions
                    mn = cmd.get("minimum-number-leaves-in-subtree")
                    if isinstance(mn, (int, float)) and mn >= 1:
                        aa["min_leaves"] = int(mn)
            elif name == "hz-sections":
                schema["hz_sections"] = [
                    {"first": s.get("first", ""), "last": s.get("last", ""), "label": s.get("label", "")}
                    for s in cmd.get("sections", []) if isinstance(s, dict) and s.get("show", True)
                ]
            elif name == "dash-bar-aa-at":
                if "pos" in cmd:
                    schema.setdefault("dash_bars", []).append({"pos": int(cmd["pos"])})
            elif name == "nodes":
                select_raw, apply_raw = cmd.get("select", {}), cmd.get("apply", {})
                if not isinstance(select_raw, dict) or not isinstance(apply_raw, dict):
                    warnings.append("nodes with non-object select/apply not supported — skipped")
                else:
                    sel, ap = _select(select_raw, warnings), _apply(apply_raw, warnings)
                    if sel and ap:
                        node_mods.append({"select": sel, "apply": ap})
            elif name == "tree":
                # canvas aspect: the tree's width-to-height-ratio sizes the page width
                # (acmacs-tal then adds the right-hand columns; we approximate the column
                # allowance below so the page comes out portrait like the AD references).
                wh = cmd.get("width-to-height-ratio")
                if isinstance(wh, (int, float)) and wh > 0:
                    schema["tree_width_to_height_ratio"] = float(wh)
                # leaf colouring: color-by is a string ("continent") or an object
                # ({"N": "pos-aa-frequency"|"pos-aa-colors", "pos": N}). Both pos modes
                # map to color_by_pos (frequency colouring; explicit aa scheme approximated).
                cb = cmd.get("color-by")
                if isinstance(cb, str):
                    if cb == "continent":
                        schema["color_by_continent"] = True
                    elif cb not in ("", "uniform"):
                        warnings.append(f"tree color-by {cb!r} not supported — skipped")
                elif isinstance(cb, dict):
                    cbn = cb.get("N")
                    if cbn == "continent":
                        schema["color_by_continent"] = True
                    elif cbn in ("pos-aa-frequency", "pos-aa-colors") and "pos" in cb:
                        schema["color_by_pos"] = {"pos": int(cb["pos"])}
                    else:
                        warnings.append(f"tree color-by {cbn!r} not supported — skipped")
                if isinstance(cmd.get("legend"), dict) and cmd["legend"].get("show"):
                    schema.setdefault("legend", {})["show"] = True
            elif name in ("margins", "gap", "node-id-size", "ladderize", "set"):
                pass  # no tal-draw equivalent / no-op for a one-off render
            else:
                warnings.append(f"command {name!r} not handled — skipped")

    run(tal.get("tal", []))
    if node_mods:
        schema["nodes"] = node_mods

    # Overall page aspect (width / height). acmacs-tal computes this as the program-order
    # SUM of every enabled normal-position layout element's width-to-height-ratio plus the
    # margins (cc/draw.cc Draw::set_width_to_height_ratio + cc/layout.cc
    # Layout::width_relative_to_height) — not a per-column allowance: column COUNT does not
    # predict width (h3 has the most dash columns yet is narrower than h1, whose clades
    # column alone is 0.092 and whose time-series slots are wide). _compute_layout_width
    # replicates that sum so the page matches the AD references (bvic 0.632, h3 0.649,
    # h1 0.794). tal-draw lays the columns out internally as fractions of the page width.
    tree_ratio = schema.pop("tree_width_to_height_ratio", None)
    if tree_ratio:  # a `tree` element with an explicit width-to-height-ratio sets the page
        schema["width_to_height_ratio"] = round(_compute_layout_width(tal, defines, warnings), 4)
    # de-duplicate warnings, keep order
    seen: set = set()
    schema_warnings = [w for w in warnings if not (w in seen or seen.add(w))]
    return schema, schema_warnings


def load_tal(path, defines: dict | None = None) -> tuple[dict, list]:
    """Load a `.tal` file and translate it. `defines` are -D overrides (name -> value)."""
    tal = _loads_relaxed(Path(path).read_text())
    return translate(tal, defines)
