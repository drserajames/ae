"""Small filesystem helper (ported from acmacs_py.utils, only what the chain uses)."""

from pathlib import Path


def older_than(first :Path, *other):
    "returns if first file is older than second (and third, if passed) or first does not exist. raises if second does not exist"
    try:
        first_mtime = first.stat().st_mtime
    except FileNotFoundError:
        return True
    return all(second.stat().st_mtime > first_mtime for second in other if second)

# ======================================================================
