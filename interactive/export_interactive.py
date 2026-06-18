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

import argparse, json, os, re, sys, tempfile
from pathlib import Path

import ae_backend
from ae_backend import tree as TREE

# --- clade colour palette (stable, colour-blind-friendly-ish) -----------------
PALETTE = [
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f", "#edc948",
    "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac", "#86bcb6", "#d37295",
    "#fabfd2", "#b6992d", "#499894", "#d4a6c8", "#79706e", "#8cd17d",
]
UNMATCHED_COLOR = "#d9d9d9"


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
def load_chart(label: str, path: str):
    ch = ae_backend.chart_v3.Chart(path)
    na, ns = ch.number_of_antigens(), ch.number_of_sera()
    lay = ch.projection(0).layout().as_numpy()  # (na+ns, dims)

    ref_idx = set()
    try:
        for sel in ch.select_reference_antigens():
            ref_idx.add(sel.antigen_no if hasattr(sel, "antigen_no") else int(sel))
    except Exception:
        pass

    antigens = []
    for i in range(na):
        ag = ch.antigen(i)
        coord = lay[i]
        x = None if (coord[0] != coord[0]) else round(float(coord[0]), 4)  # NaN -> None
        y = None if (coord[1] != coord[1]) else round(float(coord[1]), 4)
        clades = antigen_clades(ag)
        antigens.append({
            "i": i,
            "name": ag.name(),
            "norm": norm_chart_name(ag.name()),
            "passage": str(ag.passage()) if hasattr(ag, "passage") else "",
            "date": str(ag.date() or ""),
            "x": x, "y": y,
            "clade": clades[0] if clades else None,
            "clades": clades,
            "ref": i in ref_idx,
            "vac": is_vaccine(ag),
        })
    sera = []
    for j in range(ns):
        sr = ch.serum(j)
        coord = lay[na + j]
        x = None if (coord[0] != coord[0]) else round(float(coord[0]), 4)
        y = None if (coord[1] != coord[1]) else round(float(coord[1]), 4)
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


def prune_tree(root: dict, keep_norms: set, norm_clade: dict, norm_ag: dict):
    """Return (pruned_node | None) keeping only paths to leaves whose normalised
    name is in keep_norms. Degree-2 internal nodes are collapsed (path
    compression); x = cumulative edge length ('c')."""
    children = root.get("t", [])
    cum = root.get("c", root.get("M", 0.0)) or 0.0

    if not children:  # leaf
        name = root.get("n", "")
        nn = norm_tree_name(name)
        if nn not in keep_norms:
            return None
        return {
            "id": root.get("I"),
            "x": round(float(cum), 5),
            "name": name, "norm": nn,
            "date": root.get("d", ""),
            "continent": root.get("C", ""),
            "country": root.get("D", ""),
            "clade": norm_clade.get(nn),
            "ag": norm_ag.get(nn, []),
            "children": [],
        }

    kept = [k for k in (prune_tree(c, keep_norms, norm_clade, norm_ag) for c in children) if k]
    if not kept:
        return None
    if len(kept) == 1:
        return kept[0]  # collapse: skip this internal node, keep its single subtree
    return {
        "id": root.get("I"),
        "x": round(float(cum), 5),
        "children": kept,
    }


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

    # parse charts
    charts = []
    for spec in args.chart:
        if "=" not in spec:
            ap.error(f"--chart must be LABEL=PATH, got {spec!r}")
        label, path = spec.split("=", 1)
        print(f"[chart] {label}: {path}", file=sys.stderr)
        charts.append(load_chart(label, path))

    # union of matched normalised names + per-norm clade/antigen index (per chart)
    keep_norms = set()
    norm_clade = {}
    for c in charts:
        for a in c["antigens"]:
            if a["clade"] and a["norm"] not in norm_clade:
                norm_clade[a["norm"]] = a["clade"]

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

    pruned = prune_tree(troot, keep_norms, norm_clade, primary)
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

    # clade -> colour
    clade_set = sorted({a["clade"] for c in charts for a in c["antigens"] if a["clade"]})
    clade_color = {cl: PALETTE[i % len(PALETTE)] for i, cl in enumerate(clade_set)}

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
        "unmatched_color": UNMATCHED_COLOR,
    }

    payload = json.dumps(bundle, separators=(",", ":"))
    tpl = open(args.template).read()
    if "/*__DATA__*/" not in tpl:
        print("ERROR: template missing /*__DATA__*/ placeholder", file=sys.stderr)
        sys.exit(1)
    html = tpl.replace("/*__DATA__*/", payload)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    open(args.out, "w").write(html)
    print(f"[out] wrote {args.out}  ({len(html)//1024} KB)", file=sys.stderr)


if __name__ == "__main__":
    main()
