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

# AD antigenic-map-reset recipe (AD conf/tal.json:46-55 + acmacs-map-draw conf/mapi.json:34-38
# `/all-color`). TWO grey classes, confirmed by rasterising reference-AD/addendum-4.pdf @300dpi:
#   * grey88 (#e0e0e0): the default for points NOT on the phylo tree — test antigens are SOLID
#     (fill grey88, OUTLINE grey88 == fill); reference + sera are HOLLOW (transparent fill,
#     grey88 outline). AD `/all-color color:grey88` sets outline == fill for the filled (test)
#     points, so greyed test dots have no contrasting edge (Sarah's round-5 "outline matches
#     fill" feedback — previously we drew them grey88 fill + grey80 outline, a visible mismatch).
#   * gray63 (#a1a1a1): a DARKER grey for antigens that ARE on the tree (sequenced, a leaf is
#     present) but fall OUTSIDE the current section — AD `{select:{in-tree,report:false},
#     fill:gray63, outline:white, outline_width:0.5}`. The white outline separates overlapping
#     dots (invisible against the white grid). This is the "second grey" — it marks the other
#     sequenced strains' positions so they read as real tree viruses, just off-clade.
# In-section antigens are filled by date (viridis) with a thick BLACK outline; vaccines read as
# ordinary in-section points. (grey80 #cccccc seen in the AD raster is the map GRID, a kateri
# trait, not antigen styling.)
GREY88 = "#e0e0e0"   # light grey: non-tree test fill+outline / ref+sera hollow outline (~224)
GRAY63 = "#a1a1a1"   # darker grey: in-tree, off-section antigen fill (medium grey, ~161)
WHITE = "#ffffff"
# Sizes/outlines from AD's LIVE sig-page config (2026-0223-ssm/sp/sp.tal, confirmed
# 2026-06-27). AD units: test 2.5 / reference 3.0 / serum 3.0 / in-section 3.5; scaled to
# kateri px by ~4.03 (in-section 3.5 -> 14.1, matched to AD by isolated-point diameter).
# AD /all-color color:grey88 => test = solid grey fill + grey88 outline (== fill); reference +
# sera = HOLLOW (transparent fill, grey88 outline); in-section = date-colour fill + BLACK outline.
BASE_ANTIGEN = {"fill": GREY88, "outline": GREY88, "outline_width": 1.0, "size": 10.1}
REF_ANTIGEN = {"fill": "transparent", "outline": GREY88, "outline_width": 1.0, "size": 12.1}
BASE_SERUM = {"fill": "transparent", "outline": GREY88, "outline_width": 1.0, "size": 12.1}
# in-tree but off-section: AD's darker gray63 fill with a thin WHITE outline (width 0.5).
INTREE_ANTIGEN = {"fill": GRAY63, "outline": WHITE, "outline_width": 0.5}
INSECTION_ANTIGEN = {"outline": "black", "outline_width": 1.5, "size": 14.1}
NO_DATE_FILL = GRAY63  # in-section antigen whose date falls outside the time-series window
# Sig-page serum circles draw the EMPIRICAL radius (AD spc.tal empirical.show:true). With the
# kateri root fix (plot_spec.dart: `T ? t : e`, matching ae's `T`=theoretical convention),
# theoretical=False selects the empirical radius natively — no inversion workaround needed.
# The env override remains only to render a theoretical variant for verification crops.
import os as _os
SERUM_CIRCLE_THEORETICAL_FLAG = (_os.environ.get("AE_SC_THEORETICAL", "0") != "0")

VACCINE_SIZE = 15  # AD sig-page vaccine mark
VACCINE_LABEL_SIZE = 12
MAP_TITLE_SIZE = 26  # kateri px; sits in the top-left band ABOVE the first horizontal gridline (AD)


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
# AD serum-circle `hide-if` rules (spc.tal) — reproduce AD's HIDDEN circles
# ======================================================================
#
# AD's spc serum-circle block (2026-0223-ssm/sp/spc.tal) draws the EMPIRICAL circle
# for each in-section serum, but HIDES a circle whose radius (or serum name/lab)
# matches any `hide-if` criterion — AD `mapi-settings-serum-circles.cc`
# `apply_serum_circles` gates `make_circle(empirical...)` on
# `!hide_serum_circle(hide_if, serum, empirical.radius())` (l.52-55), and
# `hide_serum_circle` (l.105-128) hides when `(lab absent || info->lab()==lab) &&
# (radius < "<" || radius > ">" || name_matches("name"))`. e.g. a per-lab rule can
# hide every serum from that lab whose empirical circle radius exceeds a threshold.
# Without this, ae drew a circle for EVERY section serum → extra circles AD suppresses.
#
# The rules live in the report's shared `sp/spc.tal` (AD's sp/0do feeds every lab
# `-s spc.tal`; the per-lab *.spc.tal are empty). ae has no path to that file in the
# section-map call, but both AD's sp/0do and ae's gen-sigpages-ae.py run from the
# report dir, so it resolves relative to cwd (override with AE_SPC_TAL).


def _load_serum_circle_hide_rules(spc_tal_path=None) -> list[dict]:
    """Parse the `hide-if` criteria from the report's spc serum-circle block.

    Returns a list of ``{"<":n, ">":n, "name":s, "lab":s}`` dicts (missing keys
    absent), or ``[]`` if no spc.tal / block is found."""
    candidates = []
    env = _os.environ.get("AE_SPC_TAL")
    if env:
        candidates.append(Path(env))
    if spc_tal_path:
        candidates.append(Path(spc_tal_path))
    candidates += [Path.cwd() / "sp" / "spc.tal", Path("sp/spc.tal")]
    for p in candidates:
        try:
            if not p.exists():
                continue
            tal = _loads_relaxed(p.read_text())
            for block in tal.get("serum-circles", []):
                if isinstance(block, dict) and block.get("N") == "serum-circle":
                    return [r for r in block.get("hide-if", []) if isinstance(r, dict)]
        except Exception:
            continue
    return []


def _serum_name_matches(pattern: str, full_name: str) -> bool:
    """AD `Chart::name_matches`: a ``~``-prefixed pattern is a case-insensitive
    regex search over the serum's full name; otherwise a plain containment test
    (approximation of AD's short-name expansion, unused by the report's rules,
    which are all ``~``-prefixed)."""
    if not pattern:
        return False
    if pattern[0] == "~":
        try:
            return re.search(pattern[1:], full_name, re.IGNORECASE) is not None
        except re.error:
            return pattern[1:].upper() in full_name.upper()
    return pattern.upper() in full_name.upper()


def _serum_circle_hidden(rules: list[dict], lab: str, full_name: str, radius: float) -> bool:
    """Port of AD `hide_serum_circle`: hide when a rule's lab is absent or equals
    `lab` AND (radius < ``"<"`` OR radius > ``">"`` OR the serum name matches
    ``"name"``)."""
    for r in rules:
        rlab = r.get("lab")
        if rlab is not None and rlab != lab:
            continue
        less_than = r.get("<")
        more_than = r.get(">")
        name = r.get("name")
        if (less_than is not None and radius < less_than) \
                or (more_than is not None and radius > more_than) \
                or (name is not None and _serum_name_matches(name, full_name)):
            return True
    return False


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
        """The i-th Bernstein basis polynomial of degree `deg` at `t`."""
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
        """Build the viridis colour scale over the `[start_ym, end_ym)` month window
        (`YYYY-MM`); raises ValueError for a malformed window."""
        s, e = _ym(start_ym), _ym(end_ym)
        if not s or not e:
            raise ValueError(f"bad time-series window: {start_ym}..{end_ym}")
        self.start = s
        self.n_slots = max(1, (e[0] - s[0]) * 12 + (e[1] - s[1]))
        self.scale = bezier_gradient(*anchors, self.n_slots)

    def slot_index(self, date_str: str) -> Optional[int]:
        """Month-slot index for a date (`YYYY-MM…`), or None if the date is outside the
        window."""
        d = _ym(date_str)
        if not d:
            return None
        idx = (d[0] - self.start[0]) * 12 + (d[1] - self.start[1])
        return idx if 0 <= idx < self.n_slots else None

    def color_for(self, date_str: str) -> Optional[str]:
        """`#rrggbb` colour for a date, or None if it is outside the window."""
        idx = self.slot_index(date_str)
        return f"#{self.scale[idx]:06x}" if idx is not None else None

    def slot_color(self, idx: int) -> str:
        """`#rrggbb` colour for month slot `idx`."""
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
        """Bind the draw-order leaves, their chart-index maps (`leaf_to_ag` / `leaf_to_sr`),
        the per-serum owner leaf, and the strain→leaf lookup."""
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
        """Draw-order index of a section's first leaf (a large value if unmatched, so it
        sorts last)."""
        idx = match.find_leaf(section["first"])
        return idx if idx is not None else big

    first_to_prefix = {}
    for rank, i in enumerate(sorted(range(len(sections)), key=lambda i: first_index(sections[i]))):
        letter = chr(ord("A") + rank) if rank < 26 else f"A{chr(ord('A') + rank - 26)}"
        sections[i]["prefix"] = letter
        first_to_prefix[sections[i].get("first", "")] = letter  # key by first seq_id (the schema hz_sections carry it)
    return first_to_prefix


def section_title(section: dict) -> str:
    """Compose a section's map title: `<prefix>. <label>  <aa_transitions>`."""
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
    hide_rules: list[dict] = []
    hide_lab = ""
    empirical_radius: dict[int, float] = {}
    if serum_circles:
        from ae import semantic
        semantic.serum_circle.attributes(chart)
        # AD hides some circles per spc.tal `hide-if` (radius/name/lab). Build the lookup
        # of each serum's EMPIRICAL radius (the drawn circle; AD's empirical.show:true /
        # theoretical.show:false) at the fold in use, plus this chart's lab, so the
        # per-section loop below can drop the sera AD suppresses (else ae draws extras).
        hide_rules = _load_serum_circle_hide_rules()
        try:
            hide_lab = chart.info().lab()
        except Exception:
            hide_lab = ""
        if hide_rules:
            for cd in chart.projection().serum_circles(fold=serum_circle_fold):
                e = cd.empirical()
                if e is not None:
                    empirical_radius[cd.serum_no] = e

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
        # AD /all-color color:grey88 recipe: every test antigen solid grey88 fill + grey88 outline
        # (outline == fill); reference antigens HOLLOW (transparent fill, grey88 outline); sera
        # hollow grey88 squares. Then AD's SECOND grey: antigens that are on the tree but outside
        # this section get the darker gray63 fill + thin white outline (so the other sequenced
        # strains' positions read distinctly from the non-tree background). In-section antigens
        # are coloured by date below and override the gray63 (higher-priority later modifiers).
        style.add_modifier(only="antigens", **BASE_ANTIGEN)
        style.add_modifier(selector={"R": True}, only="antigens", **REF_ANTIGEN)  # reference = hollow grey88
        style.add_modifier(only="sera", **BASE_SERUM)
        # in-tree, off-section = gray63, drawn UNDER the grey88 background (AD plotting order).
        # AD (acmacs-tal conf/tal.json antigenic-map-reset) `lower`s every test antigen in
        # ascending-index order, so DrawingOrder ends DESCENDING (lowest chart index on top). The
        # in-tree / sequenced strains cluster at the HIGHER chart indices, so AD draws them at the
        # BOTTOM of the test group and the lighter grey88 (older, lower-index, non-tree background)
        # ends up on top — the map reads light/pale. kateri's default drawing order is the reverse
        # (ascending: highest index on top), which without this would put the darker gray63 in-tree
        # dots ON TOP and make the map read dark. `lower=True` pushes the gray63 set beneath the
        # grey88 background, reproducing AD's "grey88 on top of gray63" texture. In-section antigens
        # are also in-tree but the date-colour modifiers below re-raise them, so they stay on top.
        style.add_modifier(selector={"it": True}, only="antigens", lower=True, **INTREE_ANTIGEN)
        if ag_idx:
            # in-section emphasis (black outline + raise); grey fill for dates outside the window
            style.add_modifier(selector={ag_key: True}, only="antigens", fill=NO_DATE_FILL, raise_=True, **INSECTION_ANTIGEN)
            # colour by date: one modifier per occupied month slot (in-section AND in-month)
            if scale is not None:
                occupied = sorted({scale.slot_index(chart.antigen(a).date()) for a in ag_idx} - {None})
                for slot in occupied:
                    lo, hi = scale.slot_date_range(slot)
                    style.add_modifier(selector={ag_key: True, "!D": [lo, hi]}, only="antigens", fill=scale.slot_color(slot), raise_=True)
        # (AD's sig-page maps do NOT specially colour/label the vaccine antigens — they read as
        # ordinary in-section date-coloured points — so no vaccine marks are applied here.)
        # serum circles (opt-in): empirical circle for each of the section's sera, plus a small
        # dark serum point so the circle centre is visible (AD draws these only when requested).
        # AD hides a serum's circle when its EMPIRICAL radius (or name) trips a spc.tal
        # `hide-if` rule for this lab. A serum with a valid-but-hidden empirical gets NO
        # circle in AD (theoretical.show:false, and fallback only fires when BOTH empirical
        # and theoretical are invalid) — so drop it from this section's circle set. Sera
        # with no empirical are kept: they still get AD's fallback circle.
        circle_sera = [
            s for s in sr_idx
            if not (s in empirical_radius
                    and _serum_circle_hidden(hide_rules, hide_lab,
                                             chart.serum(s).designation(), empirical_radius[s]))
        ] if (serum_circles and hide_rules) else list(sr_idx)
        if serum_circles and circle_sera:
            from ae import semantic
            # AD spc.tal: empirical circle (no dash) with passage-coloured outline
            # (egg #FF4040 / cell #4040FF / reassortant #FFB040), width 0.6; fallback circle
            # (fixed radius) when no empirical circle exists, so sera with no homologous antigen
            # still get a circle (AD draws these — fixes the "missing circle, e.g. cell E").
            # NB: add the per-serum circle modifiers DIRECTLY to this section's style (passing
            # style_name=name) — the previous separate-style-plus-`parent=` indirection did not
            # propagate the per-serum serum_circle modifiers to kateri, so most circles (esp.
            # egg/red) were missing. This mirrors the serum-coverage path (which renders correctly).
            # mark_serum_outline=True reproduces AD spc's `mark_serum:{"outline":"passage",
            # "order":"raise"}`: each circled serum's square outline is recoloured to its passage
            # colour (matching its circle) and raised, per-serum — replacing the old set-wide grey
            # square raise, which kept the grey88 BASE_SERUM outline AD does not use.
            # RADIUS: draw the EMPIRICAL circle, matching AD's live spc.tal
            # (`empirical.show:true`, `theoretical.show:false` — AD plots the empirical,
            # optimised-fit radius; the theoretical is fallback-only). The serum's semantic
            # CI{fold} attribute carries BOTH radii (`e`=empirical, `t`=theoretical, in map
            # units). kateri's serumCircleData (plot_spec.dart) now selects the radius as
            # `(mod["T"] ?? false) ? circleData["t"] : circleData["e"]`, matching ae's
            # `T`=theoretical convention (chart-import.cc: `T` = theoretical(true)/empirical
            # (false)). So theoretical=False here draws the EMPIRICAL circle natively.
            semantic.serum_circle.style(
                chart, style_name=name, sera=list(circle_sera), fold=serum_circle_fold, fallback=True,
                theoretical=SERUM_CIRCLE_THEORETICAL_FLAG,
                mark_serum_outline=True, priority=style.priority,
                circle_style={"outline": {"egg": "#FF4040", "cell": "#4040FF", "reassortant": "#FFB040"},
                              "fill": {"egg": "transparent", "cell": "transparent", "reassortant": "transparent"},
                              "outline_width": 2.4, "dash": 0})
        # in-map title: small Helvetica, hard into the top-left corner above the first gridline
        # (AD) — kateri's default title offset is (30, 30), too far in; pull it close to the corner.
        style.plot_title.text.text = section_title(section)
        style.plot_title.text.font_size = MAP_TITLE_SIZE
        style.plot_title.text.font_face = "helvetica"
        style.plot_title.text.font_weight = "normal"
        style.plot_title.box.origin = "tl"
        style.plot_title.box.offset(6, 3)  # hard into the corner; sits in the band above gridline 1
        results.append({"name": name, "title": section_title(section), "n_antigens": len(ag_idx), "n_sera": len(sr_idx)})
    return results
