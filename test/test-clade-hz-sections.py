#!/usr/bin/env python3
# Tests for the clade-derived signature-page hz-sections
# (cc/tal/clades.cc `apply_section_tolerance` + `compute_hz_sections`, exposed as
# `ae_backend.tal.compute_hz_sections`, and the `.tal` `clades`-block reader
# `ae.tal.settings_v3.parse_clade_section_parameters`).
#
# Why this exists: acmacs-tal builds a signature page's horizontal tree sections from the
# `hz-sections` settings block only while the `hz` sub-program is IN the `tal` program.
# When it is not, `HzSections` receives nothing from settings and its whole list comes from
# `Clades::make_clades()` — the `clades` block's per-clade `show` + section tolerances
# applied to the clade runs of the current tree. This is the port of that path.
#
# What is checked, on trees and settings invented here (NO WHO data — the strain names are
# "V<n>", the clades "ALPHA"/"BETA"/"GAMMA", the substitutions at made-up positions):
#   1. `section-inclusion-tolerance` bridges a run split by interspersed leaves of another
#      clade, and a wider split is NOT bridged;
#   2. `section-exclusion-tolerance` drops the leftover small sections, EXCEPT when every
#      section of a clade is small — acmacs-tal keeps them all in that case, so a clade is
#      never emptied by the exclusion tolerance alone;
#   3. `show: false` drops a clade entirely, and per-clade parameters override the
#      all-clades defaults;
#   4. sections are ordered top-to-bottom and lettered A, B, C…, ids are
#      "{clade}-{section no}", and overlapping sections are flagged `intersect`;
#   5. aa-transitions accumulate from every inode whose subtree CONTAINS the section, with
#      acmacs-tal's add-or-replace semantics (a deeper transition at the same position
#      replaces the shallower one and moves to the end of the list). The substitutions here
#      use `J`/`O`, which are not amino-acid codes at all, so they cannot be mistaken for —
#      or mask — real sequence data (see tools/who-data-gate-allowlist.txt);
#   6. the `.tal` reader reproduces acmacs-tal's settings semantics: `all-clades` first,
#      each `per-clade` entry inheriting those defaults, a repeated name merging rather
#      than duplicating, `"?…"` entries skipped, `show` accepted as a bool or an array
#      (`any_shown()`), and a `clades` block NOT reached by the program ignored.
#
# Run (from the ae worktree root):
#   PYTHONPATH="$PWD/build:$PWD/py" python3 test/test-clade-hz-sections.py

import json
import sys
import tempfile
from pathlib import Path

import ae_backend
from ae.tal.settings_v3 import parse_clade_section_parameters

FAILURES: list[str] = []


def check(condition, message):
    if condition:
        print(f"  ok   {message}")
    else:
        print(f"  FAIL {message}")
        FAILURES.append(message)


def check_eq(got, expected, message):
    check(got == expected, f"{message}: got {got!r}, expected {expected!r}")


# ======================================================================
# tiny invented trees
# ======================================================================


def write_tree(path: Path, leaves, inode_transitions=None):
    """A flat phylo-tree-v3 tree: root -> one inode -> `leaves`.

    `leaves` is a list of (name, [clade, …]). `inode_transitions` optionally nests extra
    inodes around leaf ranges: a list of (first_index, last_index, [transition, …]); each
    becomes an inode wrapping exactly those leaves, innermost last."""
    nodes = [{"n": name, **({"L": clades} if clades else {})} for name, clades in leaves]
    subtree = list(nodes)
    for first, last, transitions in reversed(inode_transitions or []):
        subtree = subtree[:first] + [{"A": transitions, "t": subtree[first:last + 1]}] + subtree[last + 1:]
    path.write_text(json.dumps({"  version": "phylogenetic-tree-v3", "v": "TEST",
                                "tree": {"I": 0, "L": len(leaves), "t": subtree}}))
    return ae_backend.tree.load(str(path))


def params(inclusion=10, exclusion=5, shown=True, display_name=""):
    return ae_backend.tal.CladeSectionParameters(inclusion_tolerance=inclusion, exclusion_tolerance=exclusion,
                                                 shown=shown, display_name=display_name)


def sections(tree, per_clade=None, all_clades=None):
    return ae_backend.tal.compute_hz_sections(tree, per_clade or {}, all_clades or params())


# ======================================================================

tmpdir = Path(tempfile.mkdtemp(prefix="tal-clade-sections-"))

# ---------- 1 + 2: tolerances ----------
# 30 leaves. ALPHA occupies 0-4 and 8-14 (a 3-leaf gap of BETA at 5-7); BETA also 20-21.
print("\n[1/2] section inclusion / exclusion tolerance")
leaves = []
for i in range(30):
    if i in range(0, 5) or i in range(8, 15):
        clades = ["ALPHA"]
    elif i in range(5, 8) or i in (20, 21):
        clades = ["BETA"]
    else:
        clades = []
    leaves.append((f"V{i}", clades))
tree = write_tree(tmpdir / "tolerance.tjz", leaves)

raw = {clade.name: len(clade.sections) for clade in ae_backend.tal.compute_clade_sections(tree)}
check_eq(raw, {"ALPHA": 2, "BETA": 2}, "raw clade runs before any tolerance")

# gap ALPHA 8 - 4 = 4 <= 10 -> merged into one [0..14] section of 15 leaves
got = [(s.id, s.first_name, s.last_name, s.size) for s in sections(tree, {"BETA": params(shown=False)})]
check_eq(got, [("ALPHA-0", "V0", "V14", 15)], "inclusion tolerance 10 bridges a 4-leaf gap")

# inclusion 3 < gap 4 -> not bridged: [0..4] size 5 and [8..14] size 7.
# exclusion 5 then drops [0..4] (size 5 <= 5) because not every section is small.
got = [(s.id, s.first_name, s.last_name, s.size)
       for s in sections(tree, {"ALPHA": params(inclusion=3, exclusion=5), "BETA": params(shown=False)})]
check_eq(got, [("ALPHA-0", "V8", "V14", 7)], "inclusion 3 leaves 2 runs; exclusion 5 drops the small one")

# same, exclusion 0 -> both runs survive, numbered -0 and -1 in tree order
got = [(s.id, s.prefix, s.first_name, s.last_name)
       for s in sections(tree, {"ALPHA": params(inclusion=3, exclusion=0), "BETA": params(shown=False)})]
check_eq(got, [("ALPHA-0", "A", "V0", "V4"), ("ALPHA-1", "B", "V8", "V14")],
         "exclusion 0 keeps both runs, ids -0/-1, prefixes A/B top-to-bottom")

# BETA's runs are [5..7] (3) and [20..21] (2): with exclusion 5 EVERY section is small, so
# acmacs-tal keeps them all rather than emptying the clade.
got = [(s.id, s.size) for s in sections(tree, {"ALPHA": params(shown=False), "BETA": params(inclusion=1, exclusion=5)})]
check_eq(got, [("BETA-0", 3), ("BETA-1", 2)], "exclusion keeps all sections when every section is small")

# ---------- 3: show / defaults ----------
print("\n[3] show and per-clade vs all-clades defaults")
check_eq([s.id for s in sections(tree, {"ALPHA": params(shown=False), "BETA": params(shown=False)})], [],
         "every clade hidden -> no sections")
check_eq([s.id for s in sections(tree, all_clades=params(shown=False))], [],
         "all-clades show:false hides clades with no per-clade entry")
check_eq([s.id for s in sections(tree, {"ALPHA": params(shown=True)}, all_clades=params(shown=False))],
         ["ALPHA-0"], "a per-clade entry overrides an all-clades show:false")
check_eq([s.label for s in sections(tree, {"ALPHA": params(display_name="Alpha clade"), "BETA": params(shown=False)})],
         ["Alpha clade"], "display_name becomes the section label")
check_eq([s.label for s in sections(tree, {"BETA": params(shown=False)})], ["ALPHA"],
         "no display_name -> the clade name is the label")

# ---------- 4: order, prefixes, intersect ----------
print("\n[4] ordering, prefixes, intersect")
# GAMMA spans 10-25, overlapping ALPHA's [0..14] and BETA's [20..21].
leaves2 = []
for i in range(30):
    clades = []
    if i in range(0, 15):
        clades.append("ALPHA")
    if i in (20, 21):
        clades.append("BETA")
    if i in range(10, 26):
        clades.append("GAMMA")
    leaves2.append((f"V{i}", clades))
tree2 = write_tree(tmpdir / "overlap.tjz", leaves2)
got = sections(tree2, {"BETA": params(exclusion=0)})
check_eq([(s.id, s.prefix) for s in got],
         [("ALPHA-0", "A"), ("GAMMA-0", "B"), ("BETA-0", "C")],
         "sections sorted by first leaf, lettered A,B,C in that order")
check_eq({s.id: s.intersect for s in got}, {"ALPHA-0": True, "GAMMA-0": True, "BETA-0": True},
         "overlapping sections are all flagged intersect")
check_eq([(s.first_vertical, s.last_vertical) for s in got], [(0, 14), (10, 25), (20, 21)],
         "vertical bounds are 0-based shown-leaf rows")

# ---------- 5: aa-transitions ----------
print("\n[5] aa-transition accumulation")
# Nested inodes: [0..29] carries J10O and O20J; [0..14] carries O10J (same position 10 as an
# ancestor -> replaces it AND moves to the end); [0..4] carries J30O (does NOT contain the
# whole ALPHA section [0..14], so it must not contribute).
leaves3 = [(f"V{i}", ["ALPHA"] if i < 15 else ["BETA"]) for i in range(30)]
tree3 = write_tree(tmpdir / "transitions.tjz", leaves3,
                   inode_transitions=[(0, 29, ["J10O", "O20J"]), (0, 14, ["O10J"]), (0, 4, ["J30O"])])
got = {s.id: s.aa_transitions for s in sections(tree3, {"BETA": params(shown=False)})}
check_eq(got, {"ALPHA-0": "O20J O10J"},
         "ancestor transitions accumulate; same position replaced by the deeper one and moved to the end")
got = {s.id: s.aa_transitions for s in sections(tree3, {"ALPHA": params(shown=False)})}
check_eq(got, {"BETA-0": "J10O O20J"}, "a section sees only the inodes that contain it")

# ---------- 6: the .tal clades-block reader ----------
print("\n[6] .tal clades-block reader")
tal_path = tmpdir / "settings.tal"
tal_path.write_text(json.dumps({
    "tal": [{"N": "canvas"}, "clades-block"],
    "clades-block": [{
        "N": "clades",
        "all-clades": {"section-inclusion-tolerance": 40, "show": True},
        "per-clade": [
            "?a disabled comment entry",
            {"name": "ALPHA", "section-exclusion-tolerance": 7},
            {"name": "BETA", "show": False},
            {"name": "GAMMA", "show": [False, True], "display_name": "Gamma"},
            {"name": "ALPHA", "section-inclusion-tolerance": 3},          # merges into the first entry
            {"no-name": "ignored"},
        ],
    }],
    "unreached": [{"N": "clades", "per-clade": [{"name": "DELTA"}]}],
}))
all_clades, per_clade = parse_clade_section_parameters(tal_path)
check_eq(all_clades, {"inclusion_tolerance": 40, "exclusion_tolerance": 5, "shown": True},
         "all-clades read, unset keys keep the acmacs-tal defaults (10/5/shown)")
check_eq(sorted(per_clade), ["ALPHA", "BETA", "GAMMA"], "per-clade names (\"?…\" and name-less entries skipped)")
check_eq(per_clade["ALPHA"],
         {"inclusion_tolerance": 3, "exclusion_tolerance": 7, "shown": True},
         "a repeated per-clade name merges; all-clades inclusion 40 overridden to 3 by the second entry")
check_eq(per_clade["BETA"]["shown"], False, "show:false")
check_eq(per_clade["GAMMA"]["shown"], True, "show:[false,true] -> any_shown() is true")
check_eq(per_clade["GAMMA"]["display_name"], ["Gamma"], "display_name is a list (acmacs-tal indexes it per section)")
check("DELTA" not in per_clade, "a `clades` block the program never reaches is ignored")

no_clades = tmpdir / "no-clades.tal"
no_clades.write_text(json.dumps({"tal": [{"N": "canvas"}]}))
check_eq(parse_clade_section_parameters(no_clades),
         ({"inclusion_tolerance": 10, "exclusion_tolerance": 5, "shown": True}, {}),
         "a .tal with no clades block yields plain defaults and no per-clade entries")

# ======================================================================

print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for failure in FAILURES:
        print(f"  - {failure}")
    sys.exit(1)
print("all checks passed")
