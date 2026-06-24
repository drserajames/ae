"""Section <-> antigenic-map coupling for ae signature pages.

This is the ae-native port of acmacs-tal's `AntigenicMaps` coupling (AD
`cc/antigenic-maps.cc` + `cc/hz-sections.cc`). In AD a signature page is one
Cairo canvas: the tree on the left and, on the right, one antigenic map per
*shown* horizontal tree section (hz_section). Each per-section map shows the
whole chart greyed out with that section's antigens highlighted and coloured by
date (a viridis time-series gradient), its sera shown, and a title
``"{prefix}. {label} {aa-transitions}"``.

ae has no single-canvas renderer (maps are drawn by kateri, the tree by
`tal-draw`), so the coupling is reproduced in this orchestration layer:

  1. parse the *shown* hz-sections out of the report's `.tal` settings
     (`parse_sections`) and the time-series window (`parse_time_series`);
  2. match tree leaves to chart antigens/sera by name (`match_leaves`);
  3. for each section collect the antigens whose leaf falls in its
     ``[first, last]`` leaf range, and its sera (deduped to the section that
     owns each serum's first tree leaf) — `antigens_sera_in_section`;
  4. write one named semantic *style* per section into a copy of the chart
     (`build_section_styles`) — kateri renders each by name (`set_style`).

The date gradient (`bezier_gradient` + `slot_color_for`) is a faithful port of
AD `acmacs::color::bezier_gradient` (quadratic Bezier over the viridis anchors
``#440154 / #40ffff / #fde725``) sampled over the time-series month slots, i.e.
the same colour each antigen would get from AD's ``time-series-color-scale``.

Everything here is pure data manipulation over `ae_backend` (chart_v3 + tree);
it does not draw or talk to kateri. The kateri/compose step lives in
`signature_page.py`.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Optional

from .settings_v3 import _loads_relaxed

# AD time-series colour-scale anchors (acmacs-tal ColorScaleParameters default):
# viridis purple -> cyan -> yellow.
VIRIDIS_ANCHORS = (0x440154, 0x40FFFF, 0xFDE725)

# AD antigenic-map-reset recipe (conf/tal.json): all points light grey (grey88) with a
# WHITE outline (so no visible border); in-tree antigens a touch darker (gray63); in-section
# antigens filled by date with a black outline; vaccines small with a small label. Sizes are
# AD's (test 3 / ref 5 / serum 5 / in-section 5 / vaccine 15) scaled to kateri's larger canvas.
GREY88 = "#e0e0e0"   # AD grey88: out-of-section / "older" antigens
GRAY63 = "#a1a1a1"   # AD gray63: in-tree antigens (those with a tree leaf)
WHITE = "#ffffff"
# Small AD-like sizes (kateri px), tuned by eye against the AD reference. AD's data values
# are test 3 / ref 5 / serum 5 / in-section 5 / vaccine 15; kept small here so the grid maps
# read like AD's rather than the report's full-size maps (reset 20 / vaccine 40).
BASE_ANTIGEN = {"fill": GREY88, "outline": WHITE, "outline_width": 0.5, "size": 4}
REF_ANTIGEN_SIZE = 6
BASE_SERUM = {"fill": GREY88, "outline": WHITE, "outline_width": 0.5, "size": 5}
INTREE_ANTIGEN = {"fill": GRAY63, "outline": WHITE, "outline_width": 0.5}
INSECTION_ANTIGEN = {"outline": "black", "outline_width": 0.5, "size": 7}
NO_DATE_FILL = GRAY63  # in-section antigen whose date falls outside the time-series window
VACCINE_SIZE = 15  # AD sig-page vaccine mark
VACCINE_LABEL_SIZE = 12
MAP_TITLE_SIZE = 16  # kateri px; AD's in-map "{prefix}. {label} {aa}" is a small sans title


# ======================================================================
# .tal parsing
# ======================================================================


def _find_command(tal: dict, name: str) -> Optional[dict]:
    """Find the first command object ``{"N": name, ...}`` anywhere in a parsed
    `.tal` (a dict of named sub-programs, each a list of command objects)."""
    for value in tal.values():
        if isinstance(value, list):
            for cmd in value:
                if isinstance(cmd, dict) and cmd.get("N") == name:
                    return cmd
    return None


def parse_sections(tal_path) -> list[dict]:
    """Return the *shown* hz-sections from a `.tal`, in file (tree) order.

    Each entry: ``{id, prefix, first, last, label, aa_transitions}`` where
    ``prefix`` is the section's letter (AD's ``"L"``), ``first``/``last`` are
    leaf seq_ids bounding the section, and ``aa_transitions`` is its label
    suffix. Only sections with ``"show": true`` are returned (AD draws a map
    only for shown sections)."""
    tal = _loads_relaxed(Path(tal_path).read_text())
    hz = _find_command(tal, "hz-sections")
    if not hz:
        return []
    out = []
    for sect in hz.get("sections", []):
        if not isinstance(sect, dict) or not sect.get("show", False):
            continue
        out.append(
            {
                "id": sect.get("id", ""),
                "prefix": sect.get("L", ""),
                "first": sect.get("first", ""),
                "last": sect.get("last", ""),
                "label": sect.get("label", ""),
                "aa_transitions": sect.get("aa_transitions", "") or "",
            }
        )
    return out


def parse_time_series(tal_path) -> Optional[tuple[str, str]]:
    """Return ``(start, end)`` "YYYY-MM" of the `.tal` time-series, or None.

    AD samples the date colour-scale over these monthly slots."""
    tal = _loads_relaxed(Path(tal_path).read_text())
    ts = _find_command(tal, "time-series")
    if not ts or "start" not in ts or "end" not in ts:
        return None
    return (str(ts["start"])[:7], str(ts["end"])[:7])


# ======================================================================
# date -> colour (AD time-series colour scale)
# ======================================================================


def bezier_gradient(c1: int, c2: int, c3: int, n: int) -> list[int]:
    """Quadratic-Bezier colour gradient over three anchor colours — a faithful
    port of acmacs::color::bezier_gradient (per-term integer truncation kept,
    so colours match AD bit-for-bit)."""
    anchors = (c1, c2, c3)
    fact = (1.0, 1.0, 2.0)

    def bern(t: float, deg: int, i: int) -> float:
        return fact[deg] / (fact[i] * fact[deg - i]) * ((1.0 - t) ** (deg - i)) * (t**i)

    out = []
    denom = (n - 1) if n > 1 else 1
    for index in range(n):
        t = index / denom
        r = g = b = 0
        for i, col in enumerate(anchors):
            bn = bern(t, len(anchors) - 1, i)
            r += int(((col >> 16) & 0xFF) * bn)
            g += int(((col >> 8) & 0xFF) * bn)
            b += int((col & 0xFF) * bn)
        out.append((r << 16) | (g << 8) | b)
    return out


def _ym(value: str) -> Optional[tuple[int, int]]:
    m = re.match(r"\s*(\d{4})-(\d{2})", value or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


class DateColorScale:
    """Maps an antigen date to its viridis time-series colour, exactly as AD's
    ``TimeSeries::color_for`` would: a date outside the ``[start, end)`` window
    gets None (it stays greyed)."""

    def __init__(self, start_ym: str, end_ym: str, anchors=VIRIDIS_ANCHORS):
        s, e = _ym(start_ym), _ym(end_ym)
        if not s or not e:
            raise ValueError(f"bad time-series window: {start_ym}..{end_ym}")
        self.start = s
        self.n_slots = max(1, (e[0] - s[0]) * 12 + (e[1] - s[1]))
        self.scale = bezier_gradient(*anchors, self.n_slots)

    def slot_index(self, date_str: str) -> Optional[int]:
        d = _ym(date_str)
        if not d:
            return None
        idx = (d[0] - self.start[0]) * 12 + (d[1] - self.start[1])
        return idx if 0 <= idx < self.n_slots else None

    def color_for(self, date_str: str) -> Optional[str]:
        idx = self.slot_index(date_str)
        return f"#{self.scale[idx]:06x}" if idx is not None else None

    def slot_color(self, idx: int) -> str:
        return f"#{self.scale[idx]:06x}"

    def slot_date_range(self, idx: int) -> tuple[str, str]:
        """[from, to) first-of-month bounds for slot `idx`, for kateri's `!D` selector."""
        y = self.start[0] + (self.start[1] - 1 + idx) // 12
        m = (self.start[1] - 1 + idx) % 12 + 1
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        return (f"{y:04d}-{m:02d}-01", f"{ny:04d}-{nm:02d}-01")


# ======================================================================
# leaf <-> chart matching
# ======================================================================


def _nosub(name: str) -> str:
    """Strip a leading subtype prefix ("A(H1N1)/", "B/") from a chart name."""
    parts = name.split("/")
    if parts and (parts[0] == "B" or re.match(r"^A\(", parts[0])):
        parts = parts[1:]
    return "/".join(parts).upper().replace(" ", "_")


def _strain_of_seqid(seq_id: str) -> Optional[str]:
    """LOCATION/ISOLATE/YEAR from a leaf seq_id (drops trailing _PASSAGE_HASH)."""
    parts = seq_id.split("/")
    if len(parts) < 3:
        return None
    return "/".join(parts[:2] + [parts[2].split("_")[0]]).upper()


class LeafMatch:
    """Tree leaves in draw order, matched to chart antigen/serum indexes by name.

    `leaf_to_ag[i]` / `leaf_to_sr[i]` are lists of chart indexes the i-th leaf
    matches. `serum_owner[serum_no]` is the index of the first (top-most) leaf
    matching that serum — AD's "best node", used to keep a serum's circle in a
    single section."""

    def __init__(self, leaves, leaf_to_ag, leaf_to_sr, serum_owner, strain_to_leaf):
        self.leaves = leaves
        self.leaf_to_ag = leaf_to_ag
        self.leaf_to_sr = leaf_to_sr
        self.serum_owner = serum_owner
        self._strain_to_leaf = strain_to_leaf

    def find_leaf(self, seq_id: str) -> Optional[int]:
        """Leaf index for a seq_id: exact match first, then strain-only (so a
        section bound that names a passage/hash variant absent from the tree
        still resolves, the way AD falls back rather than dropping the section)."""
        up = seq_id.upper()
        try:
            return self.leaves.index(up)
        except ValueError:
            pass
        strain = _strain_of_seqid(up)
        return self._strain_to_leaf.get(strain) if strain else None


def match_leaf_names(leaf_names, chart) -> LeafMatch:
    """Match an ordered list of leaf seq_ids (draw order, e.g. from tal-draw's
    `.names` output) to chart antigen/serum indexes by name. Preferred over
    `match_leaves`: the order matches the rendered tree (so hz-section
    ``[first, last]`` ranges are correct) and it avoids iterating the tree in
    Python."""
    ag_names: dict[str, list[int]] = {}
    for no, ag in chart.select_all_antigens():
        ag_names.setdefault(_nosub(ag.name()), []).append(no)
    sr_names: dict[str, list[int]] = {}
    for no, sr in chart.select_all_sera():
        sr_names.setdefault(_nosub(sr.name()), []).append(no)

    leaves = [(name or "").upper() for name in leaf_names]
    leaf_to_ag: dict[int, list[int]] = {}
    leaf_to_sr: dict[int, list[int]] = {}
    serum_owner: dict[int, int] = {}
    strain_to_leaf: dict[str, int] = {}
    for i, seq_id in enumerate(leaves):
        if not seq_id:
            continue
        strain = _strain_of_seqid(seq_id)
        if strain is None:
            continue
        strain_to_leaf.setdefault(strain, i)
        if strain in ag_names:
            leaf_to_ag[i] = ag_names[strain]
        if strain in sr_names:
            leaf_to_sr[i] = sr_names[strain]
            for serum_no in sr_names[strain]:
                serum_owner.setdefault(serum_no, i)  # first leaf in tree order owns the serum
    return LeafMatch([s or "" for s in leaves], leaf_to_ag, leaf_to_sr, serum_owner, strain_to_leaf)


def leaf_names_from_taldraw(tree, settings: Optional[str], tal_draw, tmpdir) -> list[str]:
    """Draw-order leaf seq_ids from `tal-draw <tree> out.names` (ladderized to
    match the rendered tree). Reading from the file dodges the Python tree-leaf
    iteration that trips libc++ hardening on non-UTF-8 leaf names under py3.14."""
    out = Path(tmpdir) / "leaves.names"
    cmd = [str(tal_draw)]
    if settings:
        cmd.append(f"--settings={settings}")
    cmd += [str(tree), str(out)]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
    # leaf names may carry non-UTF-8 bytes; decode leniently (they never match a strain)
    return out.read_text(encoding="utf-8", errors="replace").splitlines()


def match_leaves(tree, chart) -> LeafMatch:
    """Match tree leaves to chart antigens/sera by iterating the tree in Python.

    Kept for tests / the py3.10 build; the orchestration prefers
    `match_leaf_names` over tal-draw's `.names` (correct draw order + no libc++
    hardening trap on non-UTF-8 leaf names under py3.14)."""
    leaf_names = []
    for ref in tree.select_leaves():
        try:
            leaf_names.append(ref.name())
        except UnicodeDecodeError:
            leaf_names.append("")
    return match_leaf_names(leaf_names, chart)


def antigens_sera_in_section(match: LeafMatch, first: str, last: str) -> tuple[list[int], list[int]]:
    """Chart antigen and serum indexes for the leaf range ``[first, last]``.

    Antigens: every matched antigen on a leaf in the range (AD
    `Tree::chart_antigens_in_section`). Sera: a serum is included only in the
    section that owns its first leaf (AD's front()-node dedup, so a serum's
    circle appears on exactly one map)."""
    n = len(match.leaves)
    fi = match.find_leaf(first)
    li = match.find_leaf(last)
    if fi is None:
        fi = 0
    if li is None:
        li = n - 1
    if fi > li:
        fi, li = li, fi

    ag: set[int] = set()
    sr: set[int] = set()
    for i in range(fi, li + 1):
        for a in match.leaf_to_ag.get(i, ()):
            ag.add(a)
        for s in match.leaf_to_sr.get(i, ()):
            if fi <= match.serum_owner.get(s, -1) <= li:
                sr.add(s)
    return sorted(ag), sorted(sr)


# ======================================================================
# semantic styles
# ======================================================================


def report_styles_from_ace(ace_path) -> tuple[Optional[list[float]], set]:
    """Read the chart's existing semantic styles (built by ae.report): returns
    ``(reset_viewport, style_names)``. The section maps reuse these report styles
    (`-reset` sizes+viewport, `-pale` greying, `-vaccines` marks+labels) so they
    look like AD's, instead of hand-rolled sizes."""
    try:
        data = json.loads(subprocess.check_output(["decat", str(ace_path)]))
    except Exception:
        return None, set()
    styles = data.get("c", {}).get("R", {})
    vp = styles.get("-reset", {}).get("V")
    viewport = list(vp) if isinstance(vp, list) and len(vp) == 4 else None
    return viewport, set(styles.keys())


def vaccine_marks_from_ace(ace_path) -> list:
    """Per-vaccine mark + label data from the chart's ``-vaccines`` style:
    ``[{index, fill, text, offset}]``. Lets the section maps redraw vaccines at AD's
    small sig-page sizes (mark 15 / label 9) with the report's colours + labels,
    rather than inheriting the report's oversized 40/30."""
    try:
        data = json.loads(subprocess.check_output(["decat", str(ace_path)]))
    except Exception:
        return []
    style = data.get("c", {}).get("R", {}).get("-vaccines", {})
    out = []
    for mod in style.get("A", []):
        sel = mod.get("T", {})
        label = mod.get("l", {})
        if "!i" in sel and isinstance(label, dict) and label.get("t"):
            out.append({"index": sel["!i"], "fill": mod.get("F"), "text": label.get("t"),
                        "offset": label.get("p", [0, 1])})
    return out


def reset_viewport_from_ace(ace_path) -> Optional[list[float]]:
    """The report's clades-map viewport (from the chart's ``-reset`` style)."""
    return report_styles_from_ace(ace_path)[0]


def viewport_from_mapi(mapi_path) -> Optional[list[float]]:
    """AD's per-lab **signature-page viewport** from a ``sp.mapi`` file
    (``loc:viewport`` → ``{"N":"viewport","abs":[x,y,size]}``), as ``[x,y,w,h]``.
    This is the viewport AD's report computed for the sig-page maps (kateri
    auto-fit), so each map's antigen cluster fills the cell like AD's — unlike the
    chart's ``-reset`` (clades-map) viewport, which is off-centre for sig pages."""
    try:
        mapi = json.loads(Path(mapi_path).read_text())
    except Exception:
        return None
    for key, value in mapi.items():
        if "viewport" in key and isinstance(value, list):
            for entry in value:
                if isinstance(entry, dict) and entry.get("N") == "viewport" and isinstance(entry.get("abs"), list):
                    abs_ = entry["abs"]
                    if len(abs_) >= 3:
                        return [float(abs_[0]), float(abs_[1]), float(abs_[2]), float(abs_[2])]
    return None


def viewport_from_layout(chart, pad: float = 1.0) -> list[float]:
    """A square viewport covering all points, in the chart's **raw** layout frame.

    Only a rough fallback: kateri applies the projection's transformation (rotation/flip)
    before drawing, so this raw-frame box is off-centre on a transformed chart. The section
    maps instead pass **no** viewport and let kateri auto-fit/centre each map (which fills
    the cell like AD) — see `build_section_styles`."""
    layout = chart.projection(0).layout()
    xs, ys = [], []
    for coords in layout:
        if coords and len(coords) >= 2 and coords[0] == coords[0] and coords[1] == coords[1]:  # not NaN
            xs.append(coords[0])
            ys.append(coords[1])
    if not xs:
        return [-7.5, -7.5, 15.0, 15.0]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    span = max(max(xs) - min(xs), max(ys) - min(ys)) + 2 * pad
    return [cx - span / 2, cy - span / 2, span, span]


def assign_prefixes(sections, match) -> dict:
    """Assign section letters A, B, C… to the shown sections in **tree (draw) order**
    — by the draw-order index of each section's first leaf — exactly as AD's
    `HzSections::set_prefix()` does (it ignores the .tal "L" field). Mutates each
    section's ``prefix`` and returns ``{section_id: letter}`` for the hz-marker column."""
    big = 1 << 30

    def first_index(section):
        idx = match.find_leaf(section["first"])
        return idx if idx is not None else big

    first_to_prefix = {}
    for rank, i in enumerate(sorted(range(len(sections)), key=lambda i: first_index(sections[i]))):
        letter = chr(ord("A") + rank) if rank < 26 else f"A{chr(ord('A') + rank - 26)}"
        sections[i]["prefix"] = letter
        first_to_prefix[sections[i].get("first", "")] = letter  # key by first seq_id (the schema hz_sections carry it)
    return first_to_prefix


def section_title(section: dict) -> str:
    aa = section.get("aa_transitions", "").strip()
    label = section.get("label", "").strip()
    prefix = section.get("prefix", "").strip()
    head = f"{prefix}. {label}".strip(". ").strip()
    return f"{head}  {aa}".rstrip()


def build_section_styles(chart, sections, match, scale: Optional[DateColorScale], viewport, *,
                         base_priority: int = 50000, available_styles: Optional[set] = None,
                         vaccine_marks: Optional[list] = None, serum_circles: bool = False,
                         serum_circle_fold: float = 2.0):
    """Add one semantic style per section to `chart` and return
    ``[{name, title, n_antigens, n_sera}]``. kateri renders each via set_style.

    To match AD's per-section ``antigenic-map`` look, each style **reuses the
    report's own styles already in the chart** when present: ``-reset`` (AD point
    sizes + viewport), ``-pale`` (grey the whole map), then the section's antigens
    filled by date (viridis time-series colour) + its sera, then ``-vaccines``
    (vaccine marks + on-map strain labels). Titled ``"{prefix}. {label} {aa}"``.
    If those report styles are absent (a chart not styled by ae.report) it falls
    back to a plain grey base.

    Selection uses what kateri's resolver supports (`plot_spec.dart`): a per-section
    boolean semantic attribute (``sg{i}``/``ss{i}`` — one key per section so an
    antigen in nested clades is in several), optionally ANDed with kateri's `!D`
    date-range selector to colour by month slot. (kateri's `!i` matches a single
    index only, so an index *list* can't be used.)"""
    vaccine_marks = vaccine_marks or []

    # serum circles are off by default (AD's antigenic-map-reset does serum-circles-remove);
    # opt-in computes each serum's empirical circle so kateri can draw it.
    if serum_circles:
        from ae import semantic
        semantic.serum_circle.attributes(chart)

    # 1. resolve each section's antigens/sera and tag them with a per-section attribute
    per_section = []
    ag_sections: dict[int, list[int]] = {}
    sr_sections: dict[int, list[int]] = {}
    for si, section in enumerate(sections):
        ag_idx, sr_idx = antigens_sera_in_section(match, section["first"], section["last"])
        per_section.append((section, ag_idx, sr_idx))
        for a in ag_idx:
            ag_sections.setdefault(a, []).append(si)
        for s in sr_idx:
            sr_sections.setdefault(s, []).append(si)

    # in-tree antigens (those matched to a tree leaf) — AD draws these gray63 vs grey88
    in_tree = {a for ags in match.leaf_to_ag.values() for a in ags}

    # tag antigens/sera with per-section + in-tree attributes. Keep the report's existing
    # semantic attributes (clade/continent/vaccine "V"/reference "R") — they drive -vaccines etc.
    for no, ag in chart.select_all_antigens():
        if no in in_tree:
            ag.semantic.set("it", True)
        for si in ag_sections.get(no, ()):
            ag.semantic.set(f"sg{si}", True)
    for no, sr in chart.select_all_sera():
        for si in sr_sections.get(no, ()):
            sr.semantic.set(f"ss{si}", True)

    # 2. one style per section — AD antigenic-map recipe
    results = []
    for si, (section, ag_idx, sr_idx) in enumerate(per_section):
        ag_key, sr_key = f"sg{si}", f"ss{si}"
        name = f"sigsec-{si:02d}"
        style = chart.styles()[name]
        style.priority = base_priority + si
        if viewport:  # else let kateri auto-fit/centre the map (fills the cell like AD)
            style.viewport(*viewport)
        style.legend.shown = False
        # base: all points light grey (grey88), white outline (no visible border), small
        style.add_modifier(only="antigens", **BASE_ANTIGEN)
        style.add_modifier(selector={"R": True}, only="antigens", size=REF_ANTIGEN_SIZE)  # reference antigens a touch bigger
        style.add_modifier(only="sera", **BASE_SERUM)
        style.add_modifier(selector={"it": True}, only="antigens", **INTREE_ANTIGEN)  # in-tree antigens gray63
        if ag_idx:
            # in-section emphasis (black outline + raise); grey fill for dates outside the window
            style.add_modifier(selector={ag_key: True}, only="antigens", fill=NO_DATE_FILL, raise_=True, **INSECTION_ANTIGEN)
            # colour by date: one modifier per occupied month slot (in-section AND in-month)
            if scale is not None:
                occupied = sorted({scale.slot_index(chart.antigen(a).date()) for a in ag_idx} - {None})
                for slot in occupied:
                    lo, hi = scale.slot_date_range(slot)
                    style.add_modifier(selector={ag_key: True, "!D": [lo, hi]}, only="antigens", fill=scale.slot_color(slot), raise_=True)
        # vaccine marks + on-map strain labels, on top — redraw from the report's -vaccines data
        # (colours + label text) at AD's small sig-page sizes (mark 15, label 9; report uses 40/30).
        for vac in vaccine_marks:
            mod = {"only": "antigens", "size": VACCINE_SIZE, "outline": "black", "outline_width": 1.0, "raise_": True,
                   "label": {"text": vac["text"], "size": VACCINE_LABEL_SIZE, "offset": vac.get("offset", [0, 1])}}
            if vac.get("fill"):
                mod["fill"] = vac["fill"]
            style.add_modifier(selector={"!i": vac["index"]}, **mod)
        # serum circles (opt-in): empirical circle for each of the section's sera, plus a small
        # dark serum point so the circle centre is visible (AD draws these only when requested).
        if serum_circles and sr_idx:
            from ae import semantic
            sc_name = f"sigsec-sc-{si:02d}"
            semantic.serum_circle.style(chart, style_name=sc_name, sera=list(sr_idx), fold=serum_circle_fold,
                                        priority=base_priority + 100 + si)
            style.add_modifier(parent=sc_name)
            style.add_modifier(selector={sr_key: True}, only="sera", fill="black", size=6, raise_=True)
        # in-map title: small Helvetica, top-left — AD draws "{prefix}. {label} {aa}"
        style.plot_title.text.text = section_title(section)
        style.plot_title.text.font_size = MAP_TITLE_SIZE
        style.plot_title.text.font_face = "helvetica"
        style.plot_title.text.font_weight = "normal"
        results.append({"name": name, "title": section_title(section), "n_antigens": len(ag_idx), "n_sera": len(sr_idx)})
    return results
