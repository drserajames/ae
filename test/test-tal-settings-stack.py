#! /usr/bin/env python3
"""Checks for the acmacs-tal settings **stack** — AD's `tal -s a -s b -s c …`.

The signature-page command line (`sp/0do`) passes five or six settings files, not one:
`<lab>/sp.mapi`, `<sub>.sp.tal`, `<sub><infix>.tal`, `sp.tal`, optionally `spc.tal`, and
`<page>.sp.tal`. Rendering with only the tree `.tal` silently drops the page title, the
column layout, the canvas height, the map styling and the serum-circle rules.

All data here is invented: made-up clade names, made-up seq_ids, no WHO CC material.
Run: PYTHONPATH=py python3 test/test-tal-settings-stack.py
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "py"))

from ae.tal import section_maps as SM              # noqa: E402
from ae.tal.settings_v3 import load_tal            # noqa: E402

FAILED = 0


def check(label, got, expected):
    global FAILED
    ok = got == expected
    if not ok:
        FAILED += 1
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: got {got!r}, expected {expected!r}")


def write(tmp, name, obj):
    p = Path(tmp) / name
    p.write_text(json.dumps(obj))
    return str(p)


def main():
    tmp = tempfile.mkdtemp(prefix="tal-stack-test-")

    # ------------------------------------------------------------------ [1]
    print("\n[1] builtin programs: an empty <sub>.sp.tal still lays out a page")
    # B/Vic's real `sp/bvic.sp.tal` is `{}`, so AD runs its builtin `tal-default` ->
    # `layout` -> (chart present) `layout-with-maps`, which reaches the tree `.tal`'s own
    # `tal` program through `tal-modifications`.
    tree_tal = write(tmp, "tree.tal", {
        "init": [{"N": "set", "canvas-height": 500, "ladderize-method": "none"}],
        "tal": [{"N": "canvas", "height": "$canvas-height"},
                {"N": "tree", "width-to-height-ratio": 0.4},
                {"N": "time-series", "start": "2024-03", "end": "2024-06",
                 "slot": {"width": 0.01}}],
    })
    empty = write(tmp, "sub.sp.tal", {})
    schema, _ = load_tal([empty, tree_tal], {"chart-present": True}, builtin_programs=True)
    check("canvas height comes from the stack's init", schema.get("image_size"), 500)
    check("the tree .tal's time-series is reached through tal-modifications",
          schema.get("time_series", {}).get("start"), "2024-03")
    check("clades column enabled by builtin layout-with-maps",
          schema.get("clades", {}).get("show"), True)
    # without `chart-present` AD takes `layout-tree-only` instead
    tree_only, _ = load_tal([empty, tree_tal], {}, builtin_programs=True)
    check("$chart-present false still produces a layout (tree-only)",
          tree_only.get("time_series", {}).get("start"), "2024-03")
    # and without the builtins there is no `tal-default` at all -> empty program
    bare, _ = load_tal([empty, tree_tal], {"chart-present": True})
    check("no builtins, no tal-default -> nothing laid out", "time_series" in bare, False)

    # ------------------------------------------------------------------ [2]
    print("\n[2] layout width: one element per (type, id), AD add_element semantics")
    # A page ratio is the SUM of the layout elements' widths. AD's `Settings::add_element`
    # re-initialises an existing element of the same type+id rather than adding a second,
    # so a `tree` configured twice (once by <sub>.sp.tal's layout, once by the tree .tal)
    # contributes ONE width — the last. `Gap` is the exception (add_unique::yes).
    twice = write(tmp, "twice.tal", {
        "tal-default": [{"N": "margins", "left": 0.0, "right": 0.0, "top": 0.0, "bottom": 0.0},
                        {"N": "tree", "width-to-height-ratio": 0.5},
                        {"N": "gap", "width-to-height-ratio": 0.01},
                        {"N": "gap", "width-to-height-ratio": 0.01},
                        {"N": "tree", "width-to-height-ratio": 0.3}],
    })
    schema, _ = load_tal([twice], {})
    check("tree counted once, last value wins; both gaps counted",
          schema.get("width_to_height_ratio"), 0.32)
    ids = write(tmp, "ids.tal", {
        "tal-default": [{"N": "margins", "left": 0.0, "right": 0.0, "top": 0.0, "bottom": 0.0},
                        {"N": "tree", "width-to-height-ratio": 0.5},
                        {"N": "dash-bar", "id": "a", "width-to-height-ratio": 0.01},
                        {"N": "dash-bar", "id": "b", "width-to-height-ratio": 0.01},
                        {"N": "dash-bar", "id": "a", "width-to-height-ratio": 0.02}],
    })
    schema, _ = load_tal([ids], {})
    check("dash-bars are distinct per id; a repeated id updates in place",
          schema.get("width_to_height_ratio"), 0.53)

    # ------------------------------------------------------------------ [3]
    print("\n[3] object-form sub-array invocation, {\"N\": \"<sub-array>\"}")
    objform = write(tmp, "objform.tal", {
        "tal-default": [{"N": "sub"}],
        "sub": [{"N": "clades"}],
    })
    schema, warnings = load_tal([objform], {})
    check("{'N': 'sub'} runs the named sub-array", schema.get("clades", {}).get("show"), True)
    check("and does not warn about an unhandled command",
          any("'sub'" in w for w in warnings), False)

    # ------------------------------------------------------------------ [4]
    print("\n[4] section_maps.load_tal_stack: later file wins, init accumulates")
    a = write(tmp, "a.tal", {"init": [{"N": "set", "x": 1, "y": 1}], "shared": ["from-a"],
                             "only-a": ["a"]})
    b = write(tmp, "b.tal", {"init": [{"N": "set", "y": 2}], "shared": ["from-b"]})
    merged = SM.load_tal_stack([a, b])
    check("later file wins on a name collision", merged["shared"], ["from-b"])
    check("a name only the first file defines survives", merged["only-a"], ["a"])
    check("both files' init blocks are kept", len(merged["init"]), 2)
    check("a single path still loads as one file", SM.load_tal_stack(a)["shared"], ["from-a"])

    # ------------------------------------------------------------------ [5]
    print("\n[5] the time-series window is read from the file that HAS one")
    # On the real stack `<sub>.sp.tal` re-runs `time-series` with no start/end (AD unions
    # the fields onto the one element); taking the first textual match loses the window and
    # the section maps then lose their date colouring.
    layout = write(tmp, "layout.tal", {"tal-default": [{"N": "time-series", "color-by": "continent"}]})
    window = write(tmp, "window.tal", {"tal": [{"N": "time-series", "start": "2025-01", "end": "2025-04"}]})
    check("window found behind a windowless re-init",
          SM.parse_time_series([layout, window]), ("2025-01", "2025-04"))
    check("still works for a single file", SM.parse_time_series(window), ("2025-01", "2025-04"))

    # ------------------------------------------------------------------ [6]
    print("\n[6] hz-sections are read from the whole stack")
    secs = write(tmp, "secs.tal", {"hz": [{"N": "hz-sections", "sections": [
        {"show": True, "id": "ALPHA-0", "L": "A", "first": "AAA_0001", "last": "BBB_0002",
         "label": "Alpha", "aa_transitions": "O10J"},
        {"show": False, "id": "BETA-0", "L": "B", "first": "CCC_0003", "last": "DDD_0004",
         "label": "Beta"},
    ]}]})
    got = SM.parse_sections([empty, secs, layout])
    check("only shown sections, from anywhere in the stack",
          [(s["id"], s["prefix"], s["label"], s["aa_transitions"]) for s in got],
          [("ALPHA-0", "A", "Alpha", "O10J")])

    # ------------------------------------------------------------------ [7]
    print("\n[7] a curated draw-aa-transitions REPLACES the builtin blanket one")
    # AD has one DrawAATransitions element. On the stack the builtin `tal-modifications`
    # runs an uncurated `draw-aa-transitions` before the report `.tal`'s curated block; if
    # the blanket flag survived, the tree would carry the curated labels AND every stored
    # inode transition (the "purple flood").
    curated = write(tmp, "curated.tal", {"tal": [
        {"N": "draw-aa-transitions", "method": "imported", "per-node": [
            {"show": True, "name": "O10J", "?first": "AAA_0001", "?last": "BBB_0002"}]}]})
    schema, _ = load_tal([empty, curated], {"chart-present": True}, builtin_programs=True)
    check("blanket stored-transition labels off when curation is present",
          schema.get("aa_transitions"), None)
    check("the curated label is still emitted", len(schema.get("mrca_labels", [])), 1)
    uncurated = write(tmp, "uncurated.tal", {"tal": [{"N": "draw-aa-transitions", "method": "imported"}]})
    schema, _ = load_tal([empty, uncurated], {"chart-present": True}, builtin_programs=True)
    check("with no curation anywhere, stored transitions stay on",
          (schema.get("aa_transitions") or {}).get("show"), True)

    print("\n" + ("all checks passed" if not FAILED else f"{FAILED} CHECK(S) FAILED"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
