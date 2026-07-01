#!/usr/bin/env python3
"""Verification for ae.tal.compute_clade_sections (TAL subsystem #3, Phase A).

Loads a small phylo-tree-v3 JSON tree with per-leaf clade annotations and checks
the computed clade sections against values worked out by hand.

    python3 cc/tal/test/test-clades.py

Tree (top-to-bottom leaf order A,B,C,D,E), clades: A=X B=X C=Y D=Y E=X
  -> clade X: 2 sections  {A..B size 2}, {E size 1}
  -> clade Y: 1 section   {C..D size 2}

Loads the freshly built ae_backend.so by path via importlib, to bypass any
editable-install copy of ae_backend that may shadow it.
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


def main():
    ae_backend = load_ae_backend()
    tree = ae_backend.tree.load(os.path.join(HERE, "tree-clades.json"))
    clades = ae_backend.tal.compute_clade_sections(tree)

    # Render to a comparable structure: {clade_name: [(first_name, last_name, size), ...]}
    got = {c.name: [(s.first_name, s.last_name, s.size) for s in c.sections] for c in clades}
    expected = {
        "X": [("A", "B", 2), ("E", "E", 1)],
        "Y": [("C", "D", 2)],
    }

    failures = []
    if got != expected:
        failures.append(f"sections mismatch:\n  got      {got}\n  expected {expected}")

    # number_of_leaves per clade
    nleaves = {c.name: c.number_of_leaves for c in clades}
    if nleaves != {"X": 3, "Y": 2}:
        failures.append(f"number_of_leaves mismatch: got {nleaves}, want {{'X': 3, 'Y': 2}}")

    if failures:
        print("FAIL")
        for f in failures:
            print("  " + f)
        sys.exit(1)
    print(f"OK: clade sections verified ({got})")


if __name__ == "__main__":
    main()
