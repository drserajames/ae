"""Translate acmacs-tal's settings-v3 `.tal` configs into tal-draw's declarative schema.

The production reports drive `tal` with the AD settings-v3 format — a top-level object
of named arrays where the `"tal"` array is a program of mod commands, each either a
string (a built-in or the name of another array to run) or an object `{"N": cmd, …}`
(`{"?N": …}` = disabled). This translator walks that program and maps the commands onto
the simplified schema that `tal-draw --settings` consumes.

It is **structural, not pixel-perfect**: it reproduces which clades/sections/columns/
transitions appear, but a few styling details have no tal-draw equivalent yet (arbitrary
positioned `apply.text` labels, per-clade hiding, exact layout ratios). Those are
collected in the returned `warnings` rather than silently dropped.
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


def _select(select: dict, warnings: list) -> dict:
    out: dict = {}
    if "seq_id" in select:
        sid = select["seq_id"]
        out["seq_id"] = sid if isinstance(sid, list) else [sid]
    if "cumulative >=" in select:
        out["cumulative_min"] = select["cumulative >="]
    if "date_min" in select:
        out["date_min"] = select["date_min"]
    if "date_max" in select:
        out["date_max"] = select["date_max"]
    for key in select:
        if key not in ("seq_id", "cumulative >=", "date_min", "date_max", "report"):
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
    schema: dict = {"labels": True}
    node_mods: list = []

    def run(program) -> None:
        for item in program:
            if isinstance(item, str):
                if item == "clades-whocc":
                    schema.setdefault("clades", {})["show"] = True   # clades already in the tree
                elif item in tal and isinstance(tal[item], list):
                    run(tal[item])                                    # named sub-array
                else:
                    warnings.append(f"unknown built-in / sub-array {item!r} ignored")
                continue
            if not isinstance(item, dict) or "N" not in item:
                continue  # {"?N": …} disabled, or a comment
            cmd = _substitute(item, defines)
            name = cmd["N"]
            if name == "canvas":
                if "height" in cmd:
                    try:
                        schema["image_size"] = int(float(cmd["height"]))
                    except (TypeError, ValueError):
                        pass
            elif name == "clades":
                clades = schema.setdefault("clades", {})
                clades["show"] = True
                schema["color_by_clade"] = True
                for pc in cmd.get("per-clade", []):
                    if not isinstance(pc, dict) or not pc.get("name"):
                        continue
                    style: dict = {"name": pc["name"]}
                    if pc.get("show") is False:
                        style["hide"] = True
                    if "color" in pc:
                        style["color"] = pc["color"]
                    if isinstance(pc.get("label"), dict) and "text" in pc["label"]:
                        style["display_name"] = pc["label"]["text"]
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
            elif name == "draw-aa-transitions":
                aa = schema.setdefault("aa_transitions", {})
                aa["show"] = True
                # method "imported" -> use the tree's stored transitions; otherwise compute
                aa["compute"] = cmd.get("method", "imported") != "imported"
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
    # de-duplicate warnings, keep order
    seen: set = set()
    schema_warnings = [w for w in warnings if not (w in seen or seen.add(w))]
    return schema, schema_warnings


def load_tal(path, defines: dict | None = None) -> tuple[dict, list]:
    """Load a `.tal` file and translate it. `defines` are -D overrides (name -> value)."""
    tal = _loads_relaxed(Path(path).read_text())
    return translate(tal, defines)
