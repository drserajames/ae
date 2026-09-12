#!/usr/bin/env python3
"""Verification for the eu-20200915 aa-transition method (cc/tree/aa-transitions.cc), the
method the WHO CC report `.tal`s ask `draw-aa-transitions` for.

It is a port of acmacs-tal `cc/aa-transition-20200915.cc` and its distinguishing feature is
ROOT-SEQUENCE ANCHORING: a label's left (ancestral) residue is the right residue of the
nearest ancestor label at the same position, and, where there is no such ancestor, the
residue of the tree's first leaf. ae's own `consensus` method has no such stage and, on the
tree below, produces no labels at all.

The tree (see tree-aa-eu20200915.json; residues J and O are not amino-acid codes):

    root
    |- L1, L2                 all J
    `- A                      O at position 13
       |- L3, L4
       `- B                   O at positions 13 and 15

Expected from eu-20200915:
    A -> J13O   (the root's consensus at 13 is already O, so `consensus` sees no change;
                 eu-20200915 calls the root NOT common because only 1 of its 3 children
                 shares that consensus, labels A, and anchors the left residue to the root
                 sequence's J)
    B -> J15O   (A has no consensus at 15 at all, so `consensus` cannot label anything;
                 eu-20200915 labels B and again anchors to the root sequence)
    B must NOT carry a label at 13: it acquires one while A is processed, but stage 3 sets
    its left residue from A's label (O), and left == right labels are dropped.

    python3 cc/tal/test/test-aa-transitions-eu20200915.py

Skips if ae_backend can't be imported.
"""

import glob
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))


def main():
    so = glob.glob(os.path.join(ROOT, "build", "ae_backend*.so"))
    if not so:
        print("SKIP: ae_backend not built")
        return
    spec = importlib.util.spec_from_file_location("ae_backend", so[0])
    ae = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(ae)
    except ImportError:
        print("SKIP: ae_backend not importable")
        return

    tree_json = os.path.join(HERE, "tree-aa-eu20200915.json")
    failures = []

    def labels(method):
        tree = ae.tree.load(tree_json)
        ae.tree.set_aa_nuc_transition_labels(tree, method=method, set_aa_labels=True)
        # (level, leaves, first, last, transitions) per inode, root first
        return {(row[0], row[1]): row[4] for row in
                ae.tree.report_first_last_leaves(tree, min_number_of_leaves=1)}

    eu = labels("eu-20200915")
    root, clade_a, clade_b = eu.get((0, 6), ""), eu.get((1, 4), ""), eu.get((2, 2), "")

    checks = {
        "eu-20200915 labels clade A with the root-anchored J13O": clade_a == "J13O",
        "eu-20200915 labels clade B with the root-anchored J15O": clade_b == "J15O",
        "eu-20200915 leaves the root unlabelled": root == "",
        "eu-20200915 drops clade B's left==right label at 13": "13" not in clade_b,
    }

    cons = labels("consensus")
    checks["consensus produces neither label (the gap being closed)"] = (
        cons.get((1, 4), "") == "" and cons.get((2, 2), "") == "")

    # the method must be selectable by every spelling acmacs-tal accepts
    for spelling in ("eu_20200915", "eu-20200915-low-mem"):
        checks[f"method spelling {spelling!r} selects eu-20200915"] = (
            labels(spelling).get((1, 4), "") == "J13O")

    for name, ok in checks.items():
        print(f"{'OK  ' if ok else 'FAIL'}: {name}")
        if not ok:
            failures.append(name)
    if failures:
        print(f"\n{len(failures)} failure(s). eu: root={root!r} A={clade_a!r} B={clade_b!r}")
        sys.exit(1)
    print(f"\nOK: {len(checks)} checks passed")


if __name__ == "__main__":
    main()
