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

import argparse, json, math, os, re, shutil, subprocess, sys, tempfile
from datetime import date
from pathlib import Path

import ae_backend
from ae_backend import tree as TREE

# decat decompresses .ace (brotli/xz/…) to stdout. The report's authoritative plot
# styles (R) and per-antigen semantic attributes (T) live in the chart JSON with no
# convenient ae_backend getter, so v3 reads them straight from the decompressed chart.
DECAT = shutil.which("decat") or "/Users/sarahjames/AC/eu/bin/decat"

# semantic_clades lives in the sibling acmacs-data/ checkout (canonical report clade
# palette). run.sh adds it to PYTHONPATH; insert defensively here too so the exporter
# works when run directly. Resolve relative to this file (…/eu/ae-interactive/interactive
# → …/eu/acmacs-data) rather than hardcoding an absolute path.
ACMACS_DATA = Path(__file__).resolve().parents[2] / "acmacs-data"
sys.path.insert(0, str(ACMACS_DATA))

# --- viewer module bundle (F1) ------------------------------------------------
# The viewer is authored as separate js/*.js modules and inlined into the template
# at export time, so the output stays a single dependency-free file that opens from
# file://. Order matters: state/colour/ui define the shared APIs others use, and
# main.js (entry point) must come last. See CONTRACT.md / PLAN.md.
MODULE_ORDER = [
    "state.js",    # IV.State — selection store + view state + DOM helpers
    "colour.js",   # IV.Colour — colour API
    "ui.js",       # IV.UI — tooltip, legend, controls (used by tree/map handlers)
    "glyph.js",    # IV.Glyph — shared point-shape factory (used by tree + map)
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
# v3: clade colours/legend/priority come from the chart's OWN report plot-spec
# (R["-clades-v10"]) so the viewer matches the report PDF exactly (see read_report_styles).
# semantic_clades / PALETTE below are fallbacks only, used when a chart has no such style.
PALETTE = [
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f", "#edc948",
    "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac", "#86bcb6", "#d37295",
    "#fabfd2", "#b6992d", "#499894", "#d4a6c8", "#79706e", "#8cd17d",
]
UNMATCHED_COLOR = "#d9d9d9"

# Passage-type marker colours (P1). Mirrors chart_modifier.py serum-circle styling
# (egg=red, cell=blue, reassortant=orange).
PASSAGE_COLOR = {"egg": "#FF0000", "cell": "#0000FF", "reassortant": "#FFA500"}


def semantic_clades_token(subtype: str) -> str:
    """Map a display subtype to the key semantic_clades.sData expects
    (A(H3N2) / A(H1N1) / BV / BY). The exporter's --subtype is free-form ("B",
    "B/Victoria", …); semantic_clades keys on BV/BY, so translate (it KeyErrors on "B")."""
    s = (subtype or "").upper()
    if "H3" in s:
        return "A(H3N2)"
    if "H1" in s:
        return "A(H1N1)"
    if "YAM" in s or s == "BY":
        return "BY"
    if "VIC" in s or s in ("B", "BV"):
        return "BV"
    return subtype


def clade_palette(subtype: str):
    """Return (name->color, name->legend, name->priority) from the canonical report
    palette (semantic_clades). Priority = position in the concatenated plot-spec lists
    (later = more specific = wins). Returns ({},{},{}) if the module is unavailable.
    Only a fallback now — clades normally come from the chart's own R style (v3)."""
    try:
        import semantic_clades as SC
        spec = SC.semantic_plot_spec_data_for_subtype(semantic_clades_token(subtype))
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


PASSAGE_FROM_T = {"e": "egg", "c": "cell", "r": "reassortant"}  # chart semantic T.p codes


def read_chart_json(path):
    """Decompress an .ace via decat and return its chart object (`c`), or {} on failure.
    Used to read the report plot-spec styles (R) and per-point semantic attributes (T)
    that have no convenient ae_backend getter."""
    try:
        out = subprocess.run([DECAT, path], capture_output=True, check=True).stdout
        return json.loads(out).get("c", {})
    except Exception as e:
        print(f"[chart-json] WARNING: could not read styles/semantics for {path} "
              f"({e!r}); v3 fields fall back to ae_backend getters", file=sys.stderr)
        return {}


# Per-subtype clade-style auto-detection order. The report names its primary clade
# style differently per subtype: H3 = -clades-v10, H1 = -clades, B/Vic = -clades-v2
# (the current Pango "C" clades — C.5.6/C.5.7 etc. — which -clades-v1 lacks; both v1 and
# v2 PDFs are published but v2 is the detailed/current scheme). First key present wins.
CLADE_STYLE_ORDER = ["-clades-v10", "-clades", "-clades-v2", "-clades-v1"]


def pick_clade_style(R, override=None):
    """Choose the report clade-style key in R. `override` (from --clade-style) forces a
    key (with or without the leading '-'); 'auto'/None uses CLADE_STYLE_ORDER. Returns
    the key, or None if no clade style is present."""
    if override and override != "auto":
        key = override if override.startswith("-") else "-" + override
        return key if key in (R or {}) else None
    for key in CLADE_STYLE_ORDER:
        if key in (R or {}):
            return key
    return None


def clade_rules_from_R(R, key):
    """Ordered clade rules from the report style R[key]['A'], as
    [(clade, fill, legend, legend_priority), ...] in list order. The report applies
    these in order and the LAST matching rule wins a point's colour (so the most
    specific clade combination shows), which `primary_clade` mirrors. Empty if absent."""
    spec = (R or {}).get(key) or {}
    rules = []
    for r in spec.get("A", []):
        c = (r.get("T") or {}).get("C")
        if isinstance(c, str):                  # skip non-clade selectors (e.g. "!i")
            L = r.get("L") or {}
            rules.append((c, r.get("F"), L.get("t") or c, L.get("p")))
    return rules


def continent_palette_from_R(R):
    """continent -> colour from the report style R['-continent']['A'] (selector T.C9)."""
    spec = (R or {}).get("-continent") or {}
    out = {}
    for r in spec.get("A", []):
        c9 = (r.get("T") or {}).get("C9")
        if c9 and r.get("F"):
            out[c9] = r["F"]
    return out


def primary_clade(clades, rules):
    """The clade whose -clades-v10 rule is applied LAST among the antigen's clades —
    the report's layered styling means later rules paint over earlier, so the
    last-matching (most specific) clade is the displayed colour. None if none match."""
    cset = set(clades)
    last = None
    for c, _f, _l, _p in rules:
        if c in cset:
            last = c
    return last


_PANGO_RE = re.compile(r"\(([A-Za-z0-9.]+)\)")


def clade_short(legend):
    """v4 #2: the Pango short name for a clade legend, or None. If the legend carries a
    parenthesised Pango (e.g. "135K 189R (J.2.4)") return that; else if the legend has no
    AA-motif digits it is already a short name ("K"); else (an AA motif like "135K") None."""
    if not legend:
        return None
    m = _PANGO_RE.search(legend)
    if m:
        return m.group(1)
    if not re.search(r"\d", legend):
        return legend
    return None


def read_transformation(proj):
    """Return the 2D projection transformation [a,b,c,d] from ae_backend's
    Transformation object. It exposes no numeric getter (only mutators), but its
    str() is a JSON list of the matrix coefficients, so parse that — in-process, from
    the same projection object used for the layout (so it always matches the coords
    being transformed, unlike re-reading the file's first projection). Returns
    identity [1,0,0,1] (with a warning) if it can't be read."""
    try:
        t = json.loads(str(proj.transformation()))
        if isinstance(t, list) and len(t) == 4:
            return [float(v) for v in t]
        print(f"[transform] WARNING: unexpected transformation {t!r}; using identity",
              file=sys.stderr)
    except Exception as e:
        print(f"[transform] WARNING: could not read transformation ({e!r}); "
              f"using identity", file=sys.stderr)
    return [1.0, 0.0, 0.0, 1.0]


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
    """Strip the leading subtype prefix and uppercase, so chart names match tree tips:
    A(H3N2)/THAILAND/8/2022 -> THAILAND/8/2022; B/HONG KONG/269/2017 -> HONG KONG/269/2017.
    Handles A(...)/, B(...)/ and a bare A/ or B/; a name with no such prefix (e.g.
    BHUTAN/212/2019 — country starting with B, no slash) is left untouched."""
    return re.sub(r"^([AB]\([^)]*\)|[AB])/", "", s).upper()


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
def layout_coords(proj):
    """The projection's layout as a plain list of per-point coord lists, in point order
    (antigens then sera). Disconnected points come back as `[nan, nan, …]` so the
    downstream NaN checks in `xy()` still fire — this matches the fill the old numpy
    `as_numpy()` produced. Pure-Python — no numpy."""
    lay = proj.layout()
    dims = lay.number_of_dimensions()
    nan = float("nan")
    return [[nan] * dims if c is None else [float(v) for v in c] for c in lay]


def apply_transformation(lay, t):
    """Bake the 2D transformation [a,b,c,d] into raw layout coords so plotted x/y are
    oriented (E1, PLAN #5). [x',y'] = [x,y] @ [[a,b],[c,d]]; NaNs pass through. *lay* is
    a list of per-point coord lists (see `layout_coords`); returns a new such list."""
    if not lay or len(lay[0]) != 2:
        return lay  # only 2D transformation supported; 3D maps plotted raw
    a, b, c, d = t
    return [[x * a + y * c, x * b + y * d] for x, y in lay]


_SSM_RE = re.compile(r"(\d{4}-\d{4})-ssm$")   # e.g. 2026-0223-ssm -> 2026-0223


def comparison_charts(path):
    """F2: locate the previous-report and previous-VCM charts for a styled.ace laid out
    as <SSM>/<sub>/styled.ace. Prev report = <SSM>/previous/<sub>/<file> (the `previous`
    symlink → the immediately preceding run). Prev VCM = same <sub>/<file> under the most
    recent sibling <YYYY-MMDD>-ssm whose date prefix is earlier than this run's (the
    symlink chain only reaches the preceding tc, so the VCM is found by scanning siblings).
    Returns (prev_report_path|None, prev_vcm_path|None)."""
    p = Path(path).resolve()
    sub, fname, ssm = p.parent.name, p.name, p.parent.parent

    pr = ssm / "previous" / sub / fname
    prev_report = pr if pr.exists() else None

    prev_vcm = None
    m = _SSM_RE.search(ssm.name)
    if m:
        cur_date = m.group(1)
        earlier = []
        for d in ssm.parent.glob("*-ssm"):
            mm = _SSM_RE.search(d.name)
            if mm and mm.group(1) < cur_date:        # fixed-width YYYY-MMDD: lexical == chronological
                earlier.append((mm.group(1), d))
        if earlier:
            cand = max(earlier)[1] / sub / fname
            prev_vcm = cand if cand.exists() else None
    return prev_report, prev_vcm


def select_new_indices(cur, prev_path, label, kind):
    """Indices of antigens in `cur` not present in the previous chart at prev_path, or
    None (logged) if that chart is missing/unreadable."""
    if prev_path is None:
        print(f"[new] {label}: no previous {kind} chart found; new stays 0 for {kind}",
              file=sys.stderr)
        return None
    try:
        prev = ae_backend.chart_v3.Chart(str(prev_path))
        return {no for no, _ in cur.select_new_antigens(prev)}
    except Exception as e:
        print(f"[new] {label}: {kind} comparison failed ({prev_path}): {e!r}",
              file=sys.stderr)
        return None


def load_chart(label, path, fallback, clade_acc, cont_acc, stats, clade_style="auto"):
    """Load one chart and emit its viewer entry. v3: clade colours/legend/priority,
    continent, passage and the vac/serology flags all come from the chart's OWN report
    styles (R) and per-point semantic attributes (T), so the viewer matches the report.
    The clade style key is chosen per subtype (pick_clade_style; --clade-style overrides).
    `fallback` = (name2col, name2leg, prio) from semantic_clades, used only when a chart
    has no clade style at all. `clade_acc`/`cont_acc` accumulate the shared palettes."""
    ch = ae_backend.chart_v3.Chart(path)
    na, ns = ch.number_of_antigens(), ch.number_of_sera()
    proj = ch.projection(0)
    lay = apply_transformation(layout_coords(proj),  # (na+ns) × dims, pure-Python
                               read_transformation(proj))

    cj = read_chart_json(path)                  # report styles (R) + semantics (T)
    aj, sj = cj.get("a", []), cj.get("s", [])
    style_key = pick_clade_style(cj.get("R", {}), clade_style)
    rules = clade_rules_from_R(cj.get("R", {}), style_key) if style_key else []
    if rules:
        eff = rules                             # report rules, in list order (last wins)
        print(f"[clade] {label}: using report {style_key} ({len(rules)} rules)",
              file=sys.stderr)
    else:                                       # fallback: semantic_clades, ordered so
        name2col, name2leg, prio = fallback     # the last match is the most specific
        eff = sorted(((n, name2col[n], name2leg.get(n, n), prio.get(n, 0)) for n in name2col),
                     key=lambda r: r[3])
        miss = f"--clade-style {clade_style!r} not in chart" if clade_style != "auto" \
            else "no clade style in chart R"
        print(f"[clade] {label}: {miss}; semantic_clades fallback "
              f"({len(eff)} entries)", file=sys.stderr)
    for c, f, l, p in eff:                       # accumulate the shared clade palette
        clade_acc["color"][c] = f
        clade_acc["legend"][c] = l
        clade_acc["prio"][c] = p
    cont_acc.update(continent_palette_from_R(cj.get("R", {})))

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
        T = (aj[i].get("T") or {}) if i < len(aj) else {}
        clades = T.get("C")
        if clades is None:
            clades = antigen_clades(ag)         # ae_backend fallback if no chart JSON
        clades = list(clades) if isinstance(clades, list) else ([clades] if clades else [])
        primary = primary_clade(clades, eff)
        if clades and primary is None:
            stats["unmatched_clades"].add(clades[0])  # has a clade, none in palette
        if primary:
            stats["used_clades"].add(primary)
        antigens.append({
            "i": i,
            "name": ag.name(),
            "norm": norm_chart_name(ag.name()),
            "passage": str(ag.passage()) if hasattr(ag, "passage") else "",
            "pt": PASSAGE_FROM_T.get(T.get("p")) or passage_type(ag),  # T.p canonical
            "date": str(ag.date() or ""),
            "x": x, "y": y,
            "clade": primary,
            "clades": clades,
            "continent": T.get("C9") or None,
            "country": T.get("c9") or None,
            "ref": (i in ref_idx) or bool(T.get("R")),     # T.R = reference flag
            "vac": bool(T.get("V")) or is_vaccine(ag),     # T.V truthy = vaccine
            "serology": bool(T.get("serology")),           # report serology test antigen
            "new": int(T.get("new") or 0),                 # F2 baseline (T.new is absent in styled.ace)
        })

    # F2: T.new isn't stored, so compute "new" by comparing this chart to the previous
    # report and previous VCM. Set 2 vs VCM, then 1 vs report (report wins — the tighter,
    # more recent subset). When a comparison chart is found we own the value for every
    # antigen (non-new → 0); a missing comparison leaves that tier untouched.
    prev_report, prev_vcm = comparison_charts(path)
    new_report = select_new_indices(ch, prev_report, label, "report")
    new_vcm = select_new_indices(ch, prev_vcm, label, "VCM")
    if new_report is not None or new_vcm is not None:
        # if EITHER comparison resolved we own every antigen's value: default all to 0,
        # then set 2 (VCM), then 1 (report overrides — the tighter, more recent subset).
        for ag in antigens:
            i = ag["i"]
            ag["new"] = 0
            if new_vcm is not None and i in new_vcm:
                ag["new"] = 2
            if new_report is not None and i in new_report:
                ag["new"] = 1
        nr = sum(1 for a in antigens if a["new"] == 1)
        nv = sum(1 for a in antigens if a["new"] == 2)
        print(f"[new] {label}: new=1 (vs report) {nr}, new=2 (vs VCM) {nv}", file=sys.stderr)

    norm_to_ags = {}
    for a in antigens:
        norm_to_ags.setdefault(a["norm"], []).append(a["i"])
    circles = serum_circle_data(proj, ns)            # F3, indexed by serum_no
    sera = []
    for j in range(ns):
        sr = ch.serum(j)
        x, y = xy(lay[na + j])
        snorm = norm_chart_name(sr.name())
        homs = norm_to_ags.get(snorm, [])            # #4: all homologous (egg+cell of strain)
        # scalar alias: the homolog whose passage matches the serum's (egg serum -> egg
        # antigen), so consumers on the alias don't get the wrong passage; else first.
        spt = passage_type(sr)
        hom0 = next((i for i in homs if antigens[i].get("pt") == spt), None)
        if hom0 is None and homs:
            hom0 = homs[0]
        sera.append({"i": j, "name": sr.name(), "x": x, "y": y,
                     "norm": snorm,
                     "homologous": homs,                         # #4 all ag indices sharing norm
                     "homologous0": hom0,                        # scalar alias (passage-matched, else first)
                     "passage": str(sr.passage()),               # #6
                     "serum_id": sr.serum_id(),                  # #6
                     "serum_species": sr.serum_species(),        # #6
                     "circle": circles[j]})                      # F3

    out = {"label": label.upper(),                    # #1 display-only uppercase
           "name": ch.name(), "antigens": antigens, "sera": sera,
           "n_antigens": na, "n_sera": ns,
           "stress": round(float(proj.stress()), 4)}
    out.update(chart_titer_data(ch, proj, na, ns))
    return out


def chart_titer_data(ch, proj, na, ns) -> dict:
    """E2: per-chart titer table + log2 titers + column bases, for the stress/error
    overlays (N1/N2/C2). `titers` keeps the raw strings (so the viewer can tell `<`/`>`
    thresholds and `*` missing apart); `logged` is log2(titer/10) with null for missing.
    `column_bases` MUST be the bases the projection was optimised with — when the
    projection carries forced column bases, those (not the recomputed ones) match the
    map coordinates, so the overlay stress reproduces the optimiser's. (Using the
    recomputed bases instead roughly doubles the apparent stress.)"""
    t = ch.titers()
    titers = [[str(t.titer(i, j)) for j in range(ns)] for i in range(na)]
    logged_arr = t.logged_array(na, ns)         # (na x ns) nested list, NaN for missing
    logged = [[None if (v != v) else round(float(v), 4) for v in row]
              for row in logged_arr]
    mcb = proj.minimum_column_basis()
    forced = list(proj.forced_column_bases())
    cb = forced if len(forced) == ns else list(ch.column_bases(mcb))
    colbases = [round(float(x), 4) for x in cb]
    return {"titers": titers, "logged": logged,
            "column_bases": colbases, "min_col_basis": mcb}


def serum_circle_data(proj, ns):
    """F3: per-serum serum-circle radii from proj.serum_circles(fold=2.0). Returns a list
    (indexed by serum_no) of {cb, theoretical, empirical}; theoretical/empirical are
    Optional floats (null when the circle is undefined — no homologous antigen, etc.).
    All-null per serum if the computation is unavailable."""
    blank = [{"cb": None, "theoretical": None, "empirical": None} for _ in range(ns)]
    try:
        circles = proj.serum_circles(fold=2.0)
    except Exception as e:
        print(f"[serum-circle] WARNING: unavailable ({e!r})", file=sys.stderr)
        return blank

    def num(call):
        try:
            v = call()
            return None if v != v else round(float(v), 4)   # NaN -> None
        except Exception:
            return None

    for c in circles:
        no = getattr(c, "serum_no", None)
        if no is None or not (0 <= no < ns):
            continue
        blank[no] = {
            "cb": round(float(c.column_basis), 4),
            "theoretical": num(c.theoretical),
            "empirical": num(c.empirical),
        }
    return blank


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


def aa_transitions(parent_aa: str, node_aa: str, del_cols=frozenset()) -> list:
    """AA substitutions on the edge from the nearest kept ancestor to this node (T4,
    PLAN #6), computed by diffing reconstructed ancestral sequences (h3.asr carries an
    'a' sequence on every node). 1-based HA1 positions (they line up with clade names);
    X ignored. Each node diffs against its immediate parent; when a degree-2 node is
    collapsed away its substitutions are prepended onto the surviving descendant (see
    prune_tree), so the merged edge lists every substitution along the path. The C++
    consensus path (set_aa_nuc_transition_labels) is broken in this build, so we derive
    them here instead.

    Deletions: raxml reconstructs ancestors as un-deleted (gaps are missing data, not a
    state), so a plain residue/residue diff never sees an indel. `reconstruct_indels` runs
    a separate present/absent parsimony over `del_cols` and rewrites internal-node `a` to
    '-' where the clade is deleted; here we then emit those gap edges. At a del_col a
    residue->'-' edge is a deletion and '-'->residue a reversion/insertion; a run of
    contiguous deleted del_cols on one edge merges into one label (e.g. {from:'Δ',
    pos:'162-164', to:''} -> "Δ162-164"). Gaps OUTSIDE del_cols stay ignored (sequencing
    artefacts). For h1/h3 (no del_cols) behaviour is unchanged."""
    if not parent_aa or not node_aa:
        return []
    subs = []
    n = min(len(parent_aa), len(node_aa))
    i = 0
    while i < n:
        a, b = parent_aa[i], node_aa[i]
        if a == b or a == "X" or b == "X":
            i += 1
            continue
        if a != "-" and b != "-":                      # ordinary substitution
            subs.append({"pos": i + 1, "from": a, "to": b})
            i += 1
            continue
        # one side is a gap
        if i in del_cols and b == "-" and a != "-":    # deletion — merge contiguous run
            j = i
            while (j < n and j in del_cols and node_aa[j] == "-"
                   and parent_aa[j] not in ("-", "X")):
                j += 1
            pos = str(i + 1) if (j - i) == 1 else f"{i + 1}-{j}"
            subs.append({"pos": pos, "from": "Δ", "to": ""})
            i = j
            continue
        if i in del_cols and a == "-" and b != "-":    # reversion / re-insertion
            subs.append({"pos": i + 1, "from": "-", "to": b})
            i += 1
            continue
        i += 1                                         # gap outside del_cols -> ignore
    return subs


def reconstruct_indels(troot: dict, min_frac: float = 0.01):
    """Present/absent (Fitch) parsimony for indel columns, mutating internal-node `a` in
    place and returning the set of 0-based deletion columns.

    raxml --ancestral models '-' as missing data, so every internal node is reconstructed
    as un-deleted (e.g. all B/Vic ancestors show K162/N163 even though ~all leaves are
    deleted). A residue/residue diff therefore misses the deletion entirely, and naively
    un-filtering gaps would paint the deletion on every one of tens of thousands of
    terminal branches instead of the one internal branch where the clade lost the codon.

    Fix: pick the columns that are really deleted in a clade (leaf gap fraction >=
    min_frac, which excludes 1-2 leaf sequencing gaps), and for each run a 2-state
    (present/absent) Fitch reconstruction up+down the FULL tree. Where a clade is
    reconstructed absent we overwrite that internal node's `a` at the column with '-', so
    the existing edge diff (aa_transitions) now yields the deletion once, on the correct
    branch, and rolls up through collapsed nodes like any substitution. Leaves are left
    untouched (so colour-by-AA / aa_table are unaffected). Different-length deletions on
    different branches (e.g. Δ162-163 vs Δ162-164) fall out naturally — that is the
    'more than one deletion' case."""
    # Flatten to arrays (iterative — the tree can be tens of thousands of leaves deep).
    nodes, parent, kids, isleaf = [], [], [], []
    stack = [(troot, -1)]
    while stack:
        nd, par = stack.pop()
        idx = len(nodes)
        nodes.append(nd); parent.append(par); kids.append([])
        ch = nd.get("t")
        isleaf.append(not ch)
        if par >= 0:
            kids[par].append(idx)
        if ch:
            for c in ch:
                stack.append((c, idx))
    N = len(nodes)
    # leaf gap frequency per column
    L = max((len(nodes[i].get("a", "")) for i in range(N) if isleaf[i]), default=0)
    if not L:
        return frozenset()
    nleaf = sum(1 for i in range(N) if isleaf[i])
    gapcount = [0] * L
    for i in range(N):
        if isleaf[i]:
            a = nodes[i].get("a", "")
            for c in range(len(a)):
                if a[c] == "-":
                    gapcount[c] += 1
    del_cols = [c for c in range(L) if nleaf and gapcount[c] / nleaf >= min_frac]
    if not del_cols:
        print("[indel] no deletion columns >= "
              f"{min_frac:.3%} gapped — nothing to reconstruct", file=sys.stderr)
        return frozenset()
    PRESENT, ABSENT = 1, 2
    overrides = {}                                     # internal node idx -> {col: '-'}
    for c in del_cols:
        mask = [0] * N
        for i in range(N):                             # leaf states
            if isleaf[i]:
                a = nodes[i].get("a", "")
                ch = a[c] if c < len(a) else "X"
                mask[i] = ABSENT if ch == "-" else (PRESENT | ABSENT) if ch == "X" else PRESENT
        for i in reversed(range(N)):                   # Fitch up (children precede parent)
            if not isleaf[i]:
                inter, union = PRESENT | ABSENT, 0
                for k in kids[i]:
                    inter &= mask[k]; union |= mask[k]
                mask[i] = inter if inter else union
        chosen = [0] * N
        for i in range(N):                             # Fitch down (root first)
            if parent[i] < 0:
                chosen[i] = PRESENT if mask[i] & PRESENT else ABSENT
            else:
                p = chosen[parent[i]]
                chosen[i] = p if (mask[i] & p) else (PRESENT if mask[i] & PRESENT else ABSENT)
            if not isleaf[i] and chosen[i] == ABSENT:
                overrides.setdefault(i, {})[c] = "-"
    for i, ov in overrides.items():                    # apply to internal-node sequences
        la = list(nodes[i].get("a", ""))
        for c, ch in ov.items():
            if c < len(la):
                la[c] = ch
        nodes[i]["a"] = "".join(la)
    print(f"[indel] deletion columns (1-based): {[c + 1 for c in del_cols]}; "
          f"rewrote {len(overrides)} internal nodes", file=sys.stderr)
    return frozenset(del_cols)


def prune_tree(root: dict, keep_norms: set, norm_clade: dict, norm_ag: dict,
               norm_pt: dict, parent_aa: str = "", aa_table: dict = None,
               del_cols=frozenset()):
    """Return (pruned_node | None) keeping only paths to leaves whose normalised
    name is in keep_norms. Degree-2 internal nodes are collapsed (path
    compression); x = cumulative edge length ('c'). `parent_aa` is the reconstructed
    AA sequence of the nearest kept ancestor, used to compute edge AA transitions.
    If `aa_table` is given, each kept leaf's reconstructed AA sequence is recorded
    there as norm -> sequence string (E2 shared norm->aa table for C1)."""
    children = root.get("t", [])
    cum = root.get("c", root.get("M", 0.0)) or 0.0
    node_aa = root.get("a", "")
    A = aa_transitions(parent_aa, node_aa, del_cols)

    if not children:  # leaf
        name = root.get("n", "")
        nn = norm_tree_name(name)
        if nn not in keep_norms:
            return None
        if aa_table is not None and node_aa and nn not in aa_table:
            aa_table[nn] = node_aa
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
    kept = [k for k in (prune_tree(c, keep_norms, norm_clade, norm_ag, norm_pt,
                                   node_aa, aa_table, del_cols)
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


def sanitise(obj):
    """Recursively replace any non-finite float (NaN, ±Infinity) with None so the bundle
    serialises to valid, finite JSON (BUG 3). The per-site `v != v` guards catch NaN but
    not ±Infinity, which a degenerate projection can still emit; left unsanitised, Python's
    default json.dumps writes bare NaN/Infinity — legal JS that parses into wrong values
    with no error. Returns a sanitised copy."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: sanitise(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitise(v) for v in obj]
    return obj


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tree", required=True)
    ap.add_argument("--chart", action="append", required=True,
                    help="LABEL=PATH (repeatable)")
    ap.add_argument("--subtype", default="")
    ap.add_argument("--assay", default="")
    ap.add_argument("--clade-style", default="auto",
                    help="report clade style key in R (e.g. -clades-v10, -clades, "
                         "-clades-v2); 'auto' picks per subtype (default)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--template",
                    default=str(Path(__file__).with_name("viewer_template.html")))
    ap.add_argument("--del-min-frac", type=float, default=0.01,
                    help="a column is treated as a real deletion (reconstructed by "
                         "parsimony, labelled Δ) when >= this fraction of leaves are "
                         "gapped there (default 0.01); below it gaps are ignored as "
                         "sequencing artefacts")
    ap.add_argument("--no-indels", action="store_true",
                    help="disable deletion reconstruction (only residue substitutions "
                         "are labelled, as before)")
    args = ap.parse_args()

    # clade/continent palettes are read from each chart's own report styles (v3); the
    # semantic_clades palette is only a fallback for charts lacking any clade style.
    fallback = clade_palette(args.subtype)
    clade_acc = {"color": {}, "legend": {}, "prio": {}}   # shared clade palette (merged)
    cont_acc = {}                                          # shared continent palette
    stats = {"unmatched_clades": set(), "used_clades": set()}

    # parse charts
    charts = []
    for spec in args.chart:
        if "=" not in spec:
            ap.error(f"--chart must be LABEL=PATH, got {spec!r}")
        label, path = spec.split("=", 1)
        print(f"[chart] {label}: {path}", file=sys.stderr)
        charts.append(load_chart(label, path, fallback, clade_acc, cont_acc, stats,
                                 clade_style=args.clade_style))

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

    # Deletion reconstruction (rewrites internal-node `a` so the edge diff sees indels).
    del_cols = frozenset() if args.no_indels else reconstruct_indels(troot, args.del_min_frac)

    aa_table = {}   # E2: norm -> reconstructed AA sequence (shared, for C1 colour-by-AA)
    pruned = prune_tree(troot, keep_norms, norm_clade, primary, norm_pt,
                        aa_table=aa_table, del_cols=del_cols)
    if pruned is None:
        print("ERROR: no tips matched; pruned tree is empty.", file=sys.stderr)
        sys.exit(1)
    print(f"[aa] sequences for {len(aa_table)} matched norms "
          f"(len {len(next(iter(aa_table.values()))) if aa_table else 0})", file=sys.stderr)

    # count kept leaves
    n_kept = [0]
    def cl(n):
        if not n["children"]:
            n_kept[0] += 1
        for ch in n["children"]:
            cl(ch)
    cl(pruned)
    print(f"[tree] kept leaves={n_kept[0]}", file=sys.stderr)

    # clade colour / legend / priority — restricted to the clades that actually appear
    # on a map, taking the report-authoritative values accumulated from R["-clades-v10"]
    # (or the semantic_clades fallback). Every used clade comes from a matched rule, so
    # it is present in clade_acc; the generated-colour branch is a defensive backstop.
    used = sorted(stats["used_clades"])
    clade_color, clade_legend, clade_priority = {}, {}, {}
    fb = 0
    for cl in used:
        if cl in clade_acc["color"]:
            clade_color[cl] = clade_acc["color"][cl]
            clade_legend[cl] = clade_acc["legend"].get(cl, cl)
            clade_priority[cl] = clade_acc["prio"].get(cl)
        else:
            clade_color[cl] = PALETTE[fb % len(PALETTE)]
            clade_legend[cl] = cl
            clade_priority[cl] = None
            fb += 1
    clade_short_map = {cl: clade_short(clade_legend[cl]) for cl in used}  # v4 #2
    if stats["unmatched_clades"]:
        print(f"[clade] {len(stats['unmatched_clades'])} clade label(s) had no rule "
              f"(shown grey): {sorted(stats['unmatched_clades'])[:12]}"
              f"{' ...' if len(stats['unmatched_clades']) > 12 else ''}", file=sys.stderr)
    print(f"[clade] {len(used)} clades on map ({len(used) - fb} from report styles, "
          f"{fb} generated); {sum(1 for v in clade_short_map.values() if v)} with Pango "
          f"short name; {len(cont_acc)} continent colours", file=sys.stderr)

    bundle = {
        "meta": {
            "subtype": args.subtype,
            "assay": args.assay,
            "tree_file": os.path.basename(args.tree),
            "n_tree_leaves": n_total,
            "n_kept_leaves": n_kept[0],
            "n_matched_norms": len(keep_norms),
            "generated": date.today().isoformat(),   # F1: page-generation date (ISO)
            # True when the source tree carried ancestral AA sequences, so branch AA
            # transitions were computed (E1). Lets the viewer tell "no substitutions on
            # this branch" (A absent) from "transitions weren't exported" (flag false).
            "aa_transitions": bool(aa_table),
        },
        "tree": pruned,
        "charts": charts,
        "clade_color": clade_color,
        "clade_legend": clade_legend,
        "clade_priority": clade_priority,
        "clade_short": clade_short_map,
        "continent_color": cont_acc,
        "passage_color": PASSAGE_COLOR,
        "unmatched_color": UNMATCHED_COLOR,
        "aa": aa_table,
    }

    # BUG 3: sanitise non-finite floats to None; allow_nan=False then asserts none slip
    # through (would raise rather than emit bare NaN/Infinity into the page).
    payload = json.dumps(sanitise(bundle), separators=(",", ":"), allow_nan=False)
    # BUG 4: the bundle is injected as a raw JS literal at `window.IV.__DATA__ = …;`, so a
    # data value containing "</script", "<!--" or "<script" would end the <script> element
    # and break/inject the page. Escape <,>,& — in JSON these appear only inside string
    # values, so the \uXXXX form is safe and round-trips on parse.
    payload = (payload.replace("<", "\\u003c")
                      .replace(">", "\\u003e")
                      .replace("&", "\\u0026"))
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
