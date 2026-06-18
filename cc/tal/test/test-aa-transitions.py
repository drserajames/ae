#!/usr/bin/env python3
"""Verification for the consensus aa-transition computation (cc/tree/aa-transitions.cc),
which tal-draw's --aa-transitions-compute relies on.

Loads a synthetic tree where leaves L1-L3,L6 carry MKTII and the derived (L4,L5) clade
carries MKAII, so position 3 has a clear T->A substitution. Computes transitions and
checks the derived branch is labelled T3A.

    /Library/Frameworks/Python.framework/Versions/3.10/bin/python3 cc/tal/test/test-aa-transitions.py

Skips if ae_backend can't be imported (run under the arm64 python3.10).
"""

import importlib.util
import glob
import os
import re
import sys
import tempfile

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
        print("SKIP: ae_backend not importable (run under the arm64 python3.10)")
        return

    tree = ae.tree.load(os.path.join(HERE, "tree-aa.json"))
    ae.tree.set_aa_nuc_transition_labels(tree, method="consensus", set_aa_labels=True)
    out = os.path.join(tempfile.mkdtemp(), "tree-aa-out.json")
    ae.tree.export(tree, out)
    transitions = re.findall(r'"A": \["([^"]*)"\]', open(out).read())

    if "T3A" not in transitions:
        print(f"FAIL: expected T3A among computed transitions, got {transitions}")
        sys.exit(1)
    print(f"OK: consensus aa-transition computed (T3A) — transitions: {transitions}")


if __name__ == "__main__":
    main()
