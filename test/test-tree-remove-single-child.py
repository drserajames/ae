#!/usr/bin/env python3
# Tests for `ae::tree::Tree::remove` (cc/tree/tree.cc, exposed as `ae_backend.tree.Tree.remove`
# and `ae_backend.tree.Nodes.remove`) -- specifically that it never leaves an internal node with
# exactly one child.  TODO.md open-defect #16.
#
# Why this exists: `remove` unlinks the passed nodes and then has to tidy up the inodes that are
# left holding a single child, because a one-child node -- "(X:e)" in newick -- is not a valid
# bifurcating-tree node for the downstream tools.  cmaple 1.0.0 segfaults while reading such a
# tree ("Reading a tree", within seconds) and raxml rejects it; `Tree::select_inodes_with_just_one_child`
# exists for exactly that reason.  The collapse must keep the leaf set and every root-to-tip
# distance identical -- only the shape changes.
#
# Two ways the old code left one-child nodes behind, both covered here:
#   1. at a parent with TWO OR MORE children each reduced to a single member, a single `find_if`
#      fixed only the first, so the second and subsequent ones survived as "(X:e)" forever;
#   2. the root, which the post-order visit never reaches as anybody's child, so a root left
#      holding one child was never collapsed at all.
#
# Everything here is invented: the trees are written in this file, the tip names are "A".."G" and
# "T<n>", and the edge lengths are small multiples of 0.25 chosen to be exact in binary.  NO WHO
# data of any kind -- no strain names, no sequences, no real tree.
#
# Run (from the ae worktree root):
#   PYTHONPATH="$PWD/build:$PWD/py" python3 test/test-tree-remove-single-child.py

import random
import sys
import tempfile
from pathlib import Path

import ae_backend

# ======================================================================

FAILURES = []


def check(condition, message):
    if condition:
        print(f"  ok   {message}")
    else:
        print(f"  FAIL {message}")
        FAILURES.append(message)


def check_eq(actual, expected, message):
    check(actual == expected, f"{message}  (got {actual!r}, expected {expected!r})")


def check_close(actual, expected, message, tolerance=1e-9):
    check(abs(actual - expected) <= tolerance, f"{message}  (got {actual!r}, expected {expected!r})")


# ======================================================================
# helpers


TMPDIR = Path(tempfile.mkdtemp(prefix="ae-tree-remove-"))
_counter = [0]


def load_newick(newick: str):
    """Write `newick` to a scratch file and load it as a Tree."""
    _counter[0] += 1
    path = TMPDIR / f"t{_counter[0]:04d}.newick"
    path.write_text(newick)
    return ae_backend.tree.load(path)


def remove_named_leaves(tree, names):
    """Remove the leaves whose names are in `names`; returns how many were matched."""
    to_remove = [leaf for leaf in tree.select_leaves() if leaf.name() in names]
    if to_remove:
        tree.remove(to_remove)
    return len(to_remove)


def leaf_names(tree):
    return sorted(leaf.name() for leaf in tree.select_leaves())


def root_to_tip(tree):
    """{leaf name: cumulative edge length from the root}."""
    return {leaf.name(): leaf.cumulative_edge() for leaf in tree.select_leaves()}


def one_child_inodes(tree):
    """Count inodes holding exactly one child.

    Deliberately NOT `Tree::select_inodes_with_just_one_child`, which selects on
    `number_of_leaves() < 2` rather than `children.size() == 1` and so misses a one-child inode
    whose single child is an inode with two or more leaves -- i.e. most of the nodes this test is
    about.  Counting children directly is the property we actually care about.
    """
    return sum(1 for inode in tree.select_inodes() if inode.number_of_children() == 1)


# ======================================================================
# 1. the fixed cases


print("fixed cases")

# --- one sibling group reduced to one member (this one already worked) ---
tree = load_newick("((A:1,B:1):1,(C:1,D:1):1);")
check_eq(remove_named_leaves(tree, {"B"}), 1, "case 1: one leaf matched for removal")
check_eq(leaf_names(tree), ["A", "C", "D"], "case 1: leaf set is the input minus B")
check_eq(one_child_inodes(tree), 0, "case 1: no one-child inode  -> (A:2,(C:1,D:1):1);")
check_close(root_to_tip(tree)["A"], 2.0, "case 1: A keeps its root-to-tip distance, B's parent edge folded in")
check_close(root_to_tip(tree)["C"], 2.0, "case 1: C untouched")

# --- two sibling groups, each reduced to one member (was 1 one-child inode) ---
tree = load_newick("(((A:1,B:1):1,(C:1,D:1):1):1,E:1);")
check_eq(remove_named_leaves(tree, {"B", "D"}), 2, "case 2: two leaves matched for removal")
check_eq(leaf_names(tree), ["A", "C", "E"], "case 2: leaf set is the input minus B, D")
check_eq(one_child_inodes(tree), 0, "case 2: no one-child inode  -> ((A:2,C:2):1,E:1);   [was 1 before the fix]")
for name, expected in (("A", 3.0), ("C", 3.0), ("E", 1.0)):
    check_close(root_to_tip(tree)[name], expected, f"case 2: {name} root-to-tip distance unchanged")

# --- three sibling groups, each reduced to one member (was 2 one-child inodes) ---
tree = load_newick("(((A:1,B:1):1,(C:1,D:1):1,(F:1,G:1):1):1,E:1);")
check_eq(remove_named_leaves(tree, {"B", "D", "G"}), 3, "case 3: three leaves matched for removal")
check_eq(leaf_names(tree), ["A", "C", "E", "F"], "case 3: leaf set is the input minus B, D, G")
check_eq(one_child_inodes(tree), 0, "case 3: no one-child inode  -> ((A:2,C:2,F:2):1,E:1);   [was 2 before the fix]")
for name, expected in (("A", 3.0), ("C", 3.0), ("F", 3.0), ("E", 1.0)):
    check_close(root_to_tip(tree)[name], expected, f"case 3: {name} root-to-tip distance unchanged")

# --- nested cascade: a chain of parents each dropping to one child (already worked) ---
tree = load_newick("((((A:1,B:1):1,C:1):1,D:1):1,E:1);")
check_eq(remove_named_leaves(tree, {"B", "C", "D"}), 3, "case 4: three leaves matched for removal")
check_eq(leaf_names(tree), ["A", "E"], "case 4: leaf set is the input minus B, C, D")
check_eq(one_child_inodes(tree), 0, "case 4: the whole chain collapses  -> (A:4,E:1);")
check_close(root_to_tip(tree)["A"], 4.0, "case 4: A's three collapsed ancestor edges all folded in")
check_close(root_to_tip(tree)["E"], 1.0, "case 4: E untouched")

# --- the root itself left with a single child (was 1 one-child inode) ---
tree = load_newick("(((A:1,B:1):1,(C:1,D:1):1):1,E:1);")
check_eq(remove_named_leaves(tree, {"B", "D", "E"}), 3, "case 5: three leaves matched for removal")
check_eq(leaf_names(tree), ["A", "C"], "case 5: leaf set is the input minus B, D, E")
check_eq(one_child_inodes(tree), 0, "case 5: the root collapses too  -> (A:3,C:3);   [was 1 before the fix]")
for name in ("A", "C"):
    check_close(root_to_tip(tree)[name], 3.0, f"case 5: {name} root-to-tip distance unchanged")

# --- a root whose only child is a leaf is left alone (the tree needs an inode) ---
tree = load_newick("((A:1,B:1):1);")
check_eq(remove_named_leaves(tree, {"B"}), 1, "case 6: one leaf matched for removal")
check_eq(leaf_names(tree), ["A"], "case 6: only A is left")
check_close(root_to_tip(tree)["A"], 2.0, "case 6: A's root-to-tip distance is still 2")


# ======================================================================
# 2. randomized property test
#
# Build random trees with a known shape, so the expected root-to-tip distance of every kept leaf
# is computed here rather than read back out of the object under test.


def random_tree(rnd, n_tips):
    """Returns (newick, {leaf name: root-to-tip distance}).

    Shape: start from a star of tips, then repeatedly replace a random pair of siblings with an
    inode joining them.  Every node gets an edge length that is a multiple of 0.25 (exact in
    binary), so the expected distances are exact sums.
    """
    names = [f"T{i}" for i in range(1, n_tips + 1)]
    # each entry: (newick fragment, {leaf: distance within this fragment})
    nodes = []
    for name in names:
        edge = rnd.randrange(1, 17) * 0.25
        nodes.append((f"{name}:{edge:g}", {name: edge}))

    while len(nodes) > 2:
        # join a random pair into a new inode
        i, j = rnd.sample(range(len(nodes)), 2)
        if i > j:
            i, j = j, i
        (left_nwk, left_d), (right_nwk, right_d) = nodes[i], nodes[j]
        edge = rnd.randrange(1, 17) * 0.25
        merged_d = {leaf: dist + edge for leaf, dist in {**left_d, **right_d}.items()}
        merged = (f"({left_nwk},{right_nwk}):{edge:g}", merged_d)
        for index in sorted((i, j), reverse=True):
            del nodes[index]
        nodes.append(merged)

    # the remaining entries become the root's children; the root has no edge of its own
    distances = {}
    for _, d in nodes:
        distances.update(d)
    return "(" + ",".join(nwk for nwk, _ in nodes) + ");", distances


print()
print("randomized property test")

rnd = random.Random(20260918)
ROUNDS = 300
worst_one_child = 0
checked_distances = 0

for round_no in range(ROUNDS):
    n_tips = rnd.randrange(20, 401)
    newick, expected_distances = random_tree(rnd, n_tips)

    # remove 1-20 % of the tips, always leaving at least two: with one leaf left the root is a
    # one-child node by necessity, which is the degenerate case case 6 covers separately.
    n_remove = max(1, min(n_tips - 2, round(n_tips * rnd.uniform(0.01, 0.20))))
    removed = set(rnd.sample(sorted(expected_distances), n_remove))

    tree = load_newick(newick)
    matched = remove_named_leaves(tree, removed)
    if matched != n_remove:
        FAILURES.append(f"round {round_no}: matched {matched} leaves for removal, expected {n_remove}")
        break

    kept = sorted(set(expected_distances) - removed)
    if leaf_names(tree) != kept:
        FAILURES.append(f"round {round_no}: leaf set differs from input minus removed")
        break

    remaining = one_child_inodes(tree)
    worst_one_child = max(worst_one_child, remaining)
    if remaining:
        FAILURES.append(f"round {round_no}: {remaining} inode(s) left with exactly one child ({n_tips} tips, {n_remove} removed)")
        break

    actual_distances = root_to_tip(tree)
    bad = [name for name in kept if abs(actual_distances[name] - expected_distances[name]) > 1e-9]
    if bad:
        FAILURES.append(f"round {round_no}: root-to-tip distance changed for {len(bad)} leaf(s), e.g. {bad[0]}")
        break
    checked_distances += len(kept)
else:
    print(f"  ok   {ROUNDS}/{ROUNDS} random trees (20-400 tips, 1-20 % removed): 0 inodes left with one child")
    print(f"  ok   leaf set = input minus removed in all {ROUNDS} trees")
    print(f"  ok   root-to-tip distance unchanged for all {checked_distances} kept leaves")

if worst_one_child:
    print(f"  (worst round left {worst_one_child} one-child inode(s))")


# ======================================================================

print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for failure in FAILURES:
        print(f"  - {failure}")
    sys.exit(1)
print("all checks passed")
