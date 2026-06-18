#!/usr/bin/env python3
"""
export_interactive.py — build a self-contained interactive tree+map viewer.

Loads a phylogenetic tree (.tjz) and one or more antigenic charts (.ace) via
ae_backend, links tree tips to chart antigens by normalised strain name, prunes
the (large) tree to the induced subtree of linked tips, and injects the result
into viewer_template.html to produce a single standalone .html file that opens
offline with no external dependencies.

Usage (see run.sh for the environment wiring):
    export_interactive.py --tree h3.asr.tjz \
        --chart vidrl=.../h3-hi-guinea-pig-vidrl/styled.ace \
        [--chart crick=.../styled.ace ...] \
        --subtype "A(H3N2)" --assay HI \
        --out data/h3-hi.html

Each --chart is LABEL=PATH; the label names the centre/source in the viewer.
Multiple charts are supported so the map panel can switch between centres
(the all-centres option). The tree is shared across charts.
"""

import argparse, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

import ae_backend
from ae_backend import tree as TREE

# semantic_clades lives in acmacs-data/ (canonical report clade palette). run.sh adds it
# to PYTHONPATH; insert defensively here too so the exporter works when run directly.
sys.path.insert(0, str(Path("/Users/sarahjames/AC/eu/acmacs-data")))

# --- viewer module bundle (F1) ------------------------------------------------
# The viewer is authored as separate js/*.js modules and inlined into the template
# at export time, so the output stays a single dependency-free file that opens from
# file://. Order matters: state/colour/ui define the shared APIs others use, and
# main.js (entry point) must come last. See CONTRACT.md / PLAN.md.
MODULE_ORDER = [
    "state.js",    # IV.State — selection store + view state + DOM helpers
    "colour.js",   # IV.Colour — colour API
    "ui.js",       # IV.UI — tooltip, legend, controls (used by tree/map handlers)
    "tree.js",     # IV.Tree — phylogram render + highlight
    "map.js",      # IV.Map — antigenic map render + highlight
    "lines.js",    # IV.Lines — Stage-2 overlay scaffold
    "grid.js",     # IV.Grid — Stage-2 all-centres scaffold
    "main.js",     # entry point — MUST be last
]


def build_modules(js_dir: Path) -> str:
    """Concatenate the viewer modules in MODULE_ORDER into one classic script."""
    parts = []
    for name in MODULE_ORDER:
        p = js_dir / name
        if not p.exists():
            raise SystemExit(f"ERROR: viewer module missing: {p}")
        parts.append(f"// ===== {name} =====\n{p.read_text()}")
    return "\n".join(parts)


# --- clade colour palette -----------------------------------------------------
# Canonical report palette comes from acmacs-data/semantic_clades.py (E1, see PLAN
# "Colour matching"). PALETTE is only a fallback used if that module can't be loaded.
PALETTE = [
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f", "#edc948",
    "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac", "#86bcb6", "#d37295",
    "#fabfd2", "#b6992d", "#499894", "#d4a6c8", "#79706e", "#8cd17d",
]
UNMATCHED_COLOR = "#d9d9d9"

# Passage-type marker colours (P1). Mirrors chart_modifier.py serum-circle styling
# (egg=red, cell=blue, reassortant=orange).
PASSAGE_COLOR = {"egg": "#FF0000", "cell": "#0000FF", "reassortant": "#FFA500"}

# decat decompresses .ace (brotli/xz/etc.) to stdout — used only to read the projection
# transformation matrix, which has no ae_backend getter. Resolved at run time.
DECAT = shutil.which("decat") or "/Users/sarahjames/AC/eu/bin/decat"


def clade_palette(subtype: str):
    """Return (name->color, name->legend, name->priority) from the canonical report
    palette (semantic_clades). Priority = position in the concatenated plot-spec lists
    (later = more specific = wins). Returns ({},{},{}) if the module is unavailable."""
    try:
        import semantic_clades as SC
        spec = SC.semantic_plot_spec_data_for_subtype(subtype)
    except Exception as e:
        print(f"[clade] WARNING: semantic_clades unavailable ({e!r}); "
              f"falling back to generated palette", file=sys.stderr)
        return {}, {}, {}
    name2col, name2leg, prio = {}, {}, {}
    i = 0
    for key, entries in spec.items():       # e.g. "clades-v10", "clades-v1"
        for e in entries:
            nm = e["name"]
            name2col[nm] = e["color"]
            name2leg[nm] = e.get("legend") or nm
            prio[nm] = i
            i += 1
    return name2col, name2leg, prio


def rederive_clades(ch, subtype: str):
    """Re-derive clade attributes the way chart_modifier does so assigned clade names
    are canonical regardless of the input chart's prior styling (PLAN #1,#2). Best
    effort: if seqdb/semantic aren't available, the chart's existing clades are used."""
    try:
        import semantic_clades as SC
        from ae import semantic
        try:
            ch.populate_from_seqdb()
        except Exception as e:
            print(f"[clade] populate_from_seqdb skipped ({e!r})", file=sys.stderr)
        entries = SC.semantic_attribute_data_for_subtype(subtype)["clades"]
        semantic.clade.attributes(chart=ch, entries=entries)
        return True
    except Exception as e:
        print(f"[clade] re-derivation skipped, using stored clades ({e!r})",
              file=sys.stderr)
        return False


def read_transformation(path: str):
    """Read the 2D projection transformation [a,b,c,d] from an .ace via decat (no
    ae_backend getter exists). Returns identity [1,0,0,1] if unavailable."""
    ident = [1.0, 0.0, 0.0, 1.0]
    try:
        out = subprocess.run([DECAT, path], capture_output=True, check=True).stdout
        d = json.loads(out)
        t = d["c"]["P"][0].get("t")
        if isinstance(t, list) and len(t) == 4:
            return [float(v) for v in t]
        return ident
    except Exception as e:
        print(f"[transform] WARNING: could not read transformation for {path} "
              f"({e!r}); using identity", file=sys.stderr)
        return ident


def passage_type(ag):
    """Classify an antigen's passage as egg/cell/reassortant (P1), or None."""
    try:
        if ag.reassortant():
            return "reassortant"
        p = ag.passage()
        if p.is_egg():
            return "egg"
        if p.is_cell():
            return "cell"
    except Exception:
        pass
    return None


def norm_tree_name(s: str) -> str:
    """TOGO/764/2022_OR_4D211EF9 -> TOGO/764/2022 (strip passage+seq-hash, upper)."""
    return re.sub(r"_[A-Za-z0-9]+_[0-9A-Fa-f]{6,}$", "", s).upper()


def norm_chart_name(s: str) -> str:
    """A(H3N2)/THAILAND/8/2022 -> THAILAND/8/2022 (strip subtype prefix, upper)."""
    return re.sub(r"^[AB]\([^)]*\)/", "", s).upper()


def antigen_clades(ag) -> list:
    """Best-effort extraction of clade labels from an antigen's semantic attrs."""
    sem = ag.semantic
    for attr in ("clades",):
        try:
            val = getattr(sem, attr)
            val = val() if callable(val) else val
            if val:
                return list(val)
        except Exception:
            pass
    try:
        v = sem.get("clade") or sem.get("C")
        if v:
            return [v] if isinstance(v, str) else list(v)
    except Exception:
        pass
    return []


def is_vaccine(ag) -> bool:
    try:
        v = ag.semantic.vaccine
        return bool(v() if callable(v) else v)
    except Exception:
        return False


# --- chart loading ------------------------------------------------------------
def apply_transformation(lay, t):
    """Bake the 2D transformation [a,b,c,d] into raw layout coords so plotted x/y are
    oriented (E1, PLAN #5). [x',y'] = [x,y] @ [[a,b],[c,d]]; NaNs pass through."""
    if lay.shape[1] != 2:
        return lay  # only 2D transformation supported; 3D maps plotted raw
    import numpy as np
    M = np.array([[t[0], t[1]], [t[2], t[3]]], dtype=float)
    return lay @ M


def pick_clade(clades, prio):
    """Choose the canonical primary clade for colouring: among an antigen's clade
    labels, the one present in the palette with the highest priority (most specific).
    Returns (primary | None, matched_a_palette_entry: bool)."""
    cand = [c for c in clades if c in prio]
    if cand:
        return max(cand, key=lambda c: prio[c]), True
    return (clades[0] if clades else None), False


def load_chart(label, path, subtype, name2col, name2leg, prio, stats):
    ch = ae_backend.chart_v3.Chart(path)
    if subtype:
        rederive_clades(ch, subtype)
    na, ns = ch.number_of_antigens(), ch.number_of_sera()
    lay = apply_transformation(ch.projection(0).layout().as_numpy(),  # (na+ns, dims)
                               read_transformation(path))

    ref_idx = set()
    try:
        for sel in ch.select_reference_antigens():
            ref_idx.add(sel.antigen_no if hasattr(sel, "antigen_no") else int(sel))
    except Exception:
        pass

    def xy(coord):
        x = None if (coord[0] != coord[0]) else round(float(coord[0]), 4)  # NaN -> None
        y = None if (coord[1] != coord[1]) else round(float(coord[1]), 4)
        return x, y

    antigens = []
    for i in range(na):
        ag = ch.antigen(i)
        x, y = xy(lay[i])
        clades = antigen_clades(ag)
        primary, in_palette = pick_clade(clades, prio) if prio else \
            (clades[0] if clades else None, bool(clades))
        if clades and not in_palette and prio:
            stats["unmatched_clades"].add(clades[0])  # has a clade, none in palette
        pt = passage_type(ag)
        antigens.append({
            "i": i,
            "name": ag.name(),
            "norm": norm_chart_name(ag.name()),
            "passage": str(ag.passage()) if hasattr(ag, "passage") else "",
            "pt": pt,                       # classified passage type (egg/cell/reassortant)
            "date": str(ag.date() or ""),
            "x": x, "y": y,
            "clade": primary,
            "clades": clades,
            "ref": i in ref_idx,
            "vac": is_vaccine(ag),
        })
    sera = []
    for j in range(ns):
        sr = ch.serum(j)
        x, y = xy(lay[na + j])
        sera.append({"i": j, "name": sr.name(), "x": x, "y": y})

    return {"label": label, "name": ch.name(), "antigens": antigens, "sera": sera,
            "n_antigens": na, "n_sera": ns}


# --- tree pruning -------------------------------------------------------------
def export_tree_json(tree_path: str) -> dict:
    tree = TREE.load(tree_path)
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        tmp = tf.name
    try:
        TREE.export(tree, tmp, 0)
        d = json.load(open(tmp))
    finally:
        os.unlink(tmp)
    return d, tree.number_of_leaves()


def aa_transitions(parent_aa: str, node_aa: str) -> list:
    """AA substitutions on the edge from the nearest kept ancestor to this node (T4,
    PLAN #6), computed by diffing reconstructed ancestral sequences (h3.asr carries an
    'a' sequence on every node). 1-based HA1 positions (they line up with clade names);
    gaps/X ignored. Each node diffs against its immediate parent; when a degree-2 node is
    collapsed away its substitutions are prepended onto the surviving descendant (see
    prune_tree), so the merged edge lists every substitution along the path. The C++
    consensus path (set_aa_nuc_transition_labels) is broken in this build, so we derive
    them here instead."""
    if not parent_aa or not node_aa:
        return []
    subs = []
    for i, (a, b) in enumerate(zip(parent_aa, node_aa)):
        if a != b and a not in "-X" and b not in "-X":
            subs.append({"pos": i + 1, "from": a, "to": b})
    return subs


def prune_tree(root: dict, keep_norms: set, norm_clade: dict, norm_ag: dict,
               norm_pt: dict, parent_aa: str = ""):
    """Return (pruned_node | None) keeping only paths to leaves whose normalised
    name is in keep_norms. Degree-2 internal nodes are collapsed (path
    compression); x = cumulative edge length ('c'). `parent_aa` is the reconstructed
    AA sequence of the nearest kept ancestor, used to compute edge AA transitions."""
    children = root.get("t", [])
    cum = root.get("c", root.get("M", 0.0)) or 0.0
    node_aa = root.get("a", "")
    A = aa_transitions(parent_aa, node_aa)

    if not children:  # leaf
        name = root.get("n", "")
        nn = norm_tree_name(name)
        if nn not in keep_norms:
            return None
        node = {
            "id": root.get("I"),
            "x": round(float(cum), 5),
            "name": name, "norm": nn,
            "date": root.get("d", ""),
            "continent": root.get("C", ""),
            "country": root.get("D", ""),
            "clade": norm_clade.get(nn),
            "passage": norm_pt.get(nn),
            "ag": norm_ag.get(nn, []),
            "children": [],
        }
        if A:
            node["A"] = A
        return node

    # Children diff against THIS node's aa unless this node is collapsed away, in which
    # case its transitions must roll up onto the surviving descendant — handled below.
    kept = [k for k in (prune_tree(c, keep_norms, norm_clade, norm_ag, norm_pt, node_aa)
                        for c in children) if k]
    if not kept:
        return None
    if len(kept) == 1:
        # collapse: skip this internal node. Prepend its edge's transitions (relative to
        # the kept ancestor) so they aren't lost when the node disappears.
        child = kept[0]
        if A:
            child["A"] = A + child.get("A", [])
        return child
    node = {
        "id": root.get("I"),
        "x": round(float(cum), 5),
        "children": kept,
    }
    if A:
        node["A"] = A
    return node


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tree", required=True)
    ap.add_argument("--chart", action="append", required=True,
                    help="LABEL=PATH (repeatable)")
    ap.add_argument("--subtype", default="")
    ap.add_argument("--assay", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--template",
                    default=str(Path(__file__).with_name("viewer_template.html")))
    args = ap.parse_args()

    # canonical report clade palette (name -> colour / legend / priority)
    name2col, name2leg, prio = clade_palette(args.subtype)
    stats = {"unmatched_clades": set()}

    # parse charts
    charts = []
    for spec in args.chart:
        if "=" not in spec:
            ap.error(f"--chart must be LABEL=PATH, got {spec!r}")
        label, path = spec.split("=", 1)
        print(f"[chart] {label}: {path}", file=sys.stderr)
        charts.append(load_chart(label, path, args.subtype,
                                 name2col, name2leg, prio, stats))

    # per-norm canonical clade + passage type (first non-null wins across charts)
    norm_clade, norm_pt = {}, {}
    for c in charts:
        for a in c["antigens"]:
            if a["clade"] and a["norm"] not in norm_clade:
                norm_clade[a["norm"]] = a["clade"]
            if a["pt"] and a["norm"] not in norm_pt:
                norm_pt[a["norm"]] = a["pt"]

    print(f"[tree] loading {args.tree} (this exports the full tree, ~large) ...",
          file=sys.stderr)
    tdict, n_total = export_tree_json(args.tree)
    troot = tdict["tree"]

    # collect tree leaf normalised names so we only keep names present in the tree
    tree_norms = set()
    def collect(n):
        if not n.get("t"):
            tree_norms.add(norm_tree_name(n.get("n", "")))
        else:
            for c in n["t"]:
                collect(c)
    collect(troot)

    # keep = chart antigens that exist in the tree
    chart_norms = {a["norm"] for c in charts for a in c["antigens"]}
    keep_norms = chart_norms & tree_norms
    print(f"[link] tree leaves={n_total}  chart norms={len(chart_norms)}  "
          f"matched={len(keep_norms)}", file=sys.stderr)

    # per-norm -> antigen indices, per chart (for linkage / map highlight)
    for c in charts:
        nm = {}
        for a in c["antigens"]:
            nm.setdefault(a["norm"], []).append(a["i"])
        c["norm_to_ag"] = nm
    # for the tree we attach the first chart's antigen indices (primary linkage key is norm)
    primary = charts[0]["norm_to_ag"]

    pruned = prune_tree(troot, keep_norms, norm_clade, primary, norm_pt)
    if pruned is None:
        print("ERROR: no tips matched; pruned tree is empty.", file=sys.stderr)
        sys.exit(1)

    # count kept leaves
    n_kept = [0]
    def cl(n):
        if not n["children"]:
            n_kept[0] += 1
        for ch in n["children"]:
            cl(ch)
    cl(pruned)
    print(f"[tree] kept leaves={n_kept[0]}", file=sys.stderr)

    # clade -> colour / legend. Canonical palette where available; any clade not in the
    # palette (fallback path, or palette unavailable) gets a stable generated colour.
    clade_set = sorted({a["clade"] for c in charts for a in c["antigens"] if a["clade"]})
    clade_color, clade_legend = {}, {}
    fb = 0
    for cl in clade_set:
        if cl in name2col:
            clade_color[cl] = name2col[cl]
            clade_legend[cl] = name2leg.get(cl, cl)
        else:
            clade_color[cl] = PALETTE[fb % len(PALETTE)]
            clade_legend[cl] = cl
            fb += 1
    if stats["unmatched_clades"]:
        print(f"[clade] {len(stats['unmatched_clades'])} clade label(s) had no palette "
              f"match (shown grey): {sorted(stats['unmatched_clades'])[:12]}"
              f"{' ...' if len(stats['unmatched_clades']) > 12 else ''}", file=sys.stderr)
    print(f"[clade] {len(clade_set)} clades on map; "
          f"{sum(1 for c in clade_set if c in name2col)} canonical, {fb} generated",
          file=sys.stderr)

    bundle = {
        "meta": {
            "subtype": args.subtype,
            "assay": args.assay,
            "tree_file": os.path.basename(args.tree),
            "n_tree_leaves": n_total,
            "n_kept_leaves": n_kept[0],
            "n_matched_norms": len(keep_norms),
        },
        "tree": pruned,
        "charts": charts,
        "clade_color": clade_color,
        "clade_legend": clade_legend,
        "passage_color": PASSAGE_COLOR,
        "unmatched_color": UNMATCHED_COLOR,
    }

    payload = json.dumps(bundle, separators=(",", ":"))
    tpl = open(args.template).read()
    for placeholder in ("/*__DATA__*/", "/*__MODULES__*/"):
        if placeholder not in tpl:
            print(f"ERROR: template missing {placeholder} placeholder", file=sys.stderr)
            sys.exit(1)
    modules = build_modules(Path(args.template).with_name("js"))
    # inline modules first (module source never contains the data token), then data
    html = tpl.replace("/*__MODULES__*/", modules).replace("/*__DATA__*/", payload)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    open(args.out, "w").write(html)
    print(f"[out] wrote {args.out}  ({len(html)//1024} KB)", file=sys.stderr)


if __name__ == "__main__":
    main()
