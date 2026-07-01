#!/usr/bin/env python3
"""Verification for ae.tal.signature_page vaccine marking (--mark-vaccines).

Uses a synthetic vaccine list (vaccines-test.py: strains "A" and "E") and the
synthetic tree-clades.json (leaves A..E) to check that load_vaccine_names +
match_leaves_by_name select exactly the vaccine leaves — no real data involved.

    python3 cc/tal/test/test-mark-vaccines.py

Skips if ae_backend can't be imported (the matching loads the tree via ae_backend,
so run under the arm64 python3.10).
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "build"))  # ae_backend (ae_backend*.so)
sys.path.insert(0, os.path.join(ROOT, "py"))      # the `ae` package

try:
    import ae_backend  # noqa: F401 — match_leaves_by_name loads the tree via it
except ImportError:
    print("SKIP: ae_backend not importable (run under the arm64 python3.10)")
    sys.exit(0)

from ae.tal.signature_page import load_vaccine_names, match_leaves_by_name


def main():
    names = load_vaccine_names(os.path.join(HERE, "vaccines-test.py"), "TESTVT")
    if names != ["A", "E"]:
        print(f"FAIL: load_vaccine_names -> {names}, want ['A', 'E']")
        sys.exit(1)

    matched = match_leaves_by_name(os.path.join(HERE, "tree-clades.json"), names)
    if sorted(matched) != ["A", "E"]:
        print(f"FAIL: match_leaves_by_name -> {matched}, want ['A', 'E']")
        sys.exit(1)

    print(f"OK: vaccine marking verified (matched {matched} from the synthetic list)")


if __name__ == "__main__":
    main()
