#!/usr/bin/env python3
"""Verification for ae.tal.compute_layout (TAL subsystem #3, Phase A headless layout).

Loads a small, hand-verifiable Newick tree and checks the computed node positions
against values worked out by hand. Run:

    /Library/Frameworks/Python.framework/Versions/3.10/bin/python3 cc/tal/test/test-layout.py

Loads the freshly built ae_backend.so by path via importlib, to bypass any
editable-install copy of ae_backend that may shadow it on sys.path / meta_path.
"""

import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
# Discover the built module by glob so the test is portable (…-darwin.so on macOS,
# …-linux-gnu.so on Linux); it is loaded by path to bypass any editable-install shadow.
import glob as _glob
_built = _glob.glob(os.path.join(ROOT, "build", "ae_backend*.so"))
SO = _built[0] if _built else os.path.join(ROOT, "build", "ae_backend.cpython-310-darwin.so")


def load_ae_backend():
    spec = importlib.util.spec_from_file_location("ae_backend", SO)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def approx(a, b, eps=1e-9):
    return abs(a - b) < eps


def main():
    ae_backend = load_ae_backend()
    tree = ae_backend.tree.load(os.path.join(HERE, "tree-small.newick"))
    # tree: ((A:1,B:1):1,(C:1,(D:1,E:1):1):1);
    layout = ae_backend.tal.compute_layout(tree)

    failures = []

    def check(label, got, want):
        if not (approx(got, want) if isinstance(want, float) else got == want):
            failures.append(f"{label}: got {got!r}, want {want!r}")

    check("height", layout.height, 5.0)
    check("max_cumulative", layout.max_cumulative, 3.0)
    check("n_leaves", len(layout.leaves), 5)
    check("n_inodes", len(layout.inodes), 4)

    # leaves: (name, x=cumulative_edge, y=row)
    expected_leaves = {
        "A": (2.0, 1.0), "B": (2.0, 2.0), "C": (2.0, 3.0),
        "D": (3.0, 4.0), "E": (3.0, 5.0),
    }
    for leaf in layout.leaves:
        want = expected_leaves.get(leaf.name)
        if want is None:
            failures.append(f"unexpected leaf {leaf.name!r}")
            continue
        check(f"leaf {leaf.name} x", leaf.x, want[0])
        check(f"leaf {leaf.name} y", leaf.y, want[1])

    # inodes post-order: (A,B)->1.5@1, (D,E)->4.5@2, (C,(D,E))->3.75@1, root->2.625@0
    inode_y = sorted(n.y for n in layout.inodes)
    for got, want in zip(inode_y, sorted([1.5, 4.5, 3.75, 2.625])):
        check("inode y", got, want)

    if failures:
        print("FAIL")
        for f in failures:
            print("  " + f)
        sys.exit(1)
    print(f"OK: layout verified (height={layout.height}, max_cumulative={layout.max_cumulative}, "
          f"{len(layout.leaves)} leaves, {len(layout.inodes)} inodes)")


if __name__ == "__main__":
    main()
