"""
Minimal JSON reader replacing AD's ``acmacs_base.json.read_json``.

Two behaviours of the AD reader are preserved because report.py relies on them:

1. Transparent decompression by file extension — the statistics data is read
   from ``stat.json.xz`` (and historically ``.bz2``).
2. Tolerance of ``//`` line comments and trailing commas, so hand-edited
   ``report.json`` files keep working. (The shipped templates use ``?``-prefixed
   keys instead of comments, which are already valid JSON, but tolerating
   comments matches the old behaviour and costs nothing.)
"""

import json
import re
from pathlib import Path

# ----------------------------------------------------------------------

_re_line_comment = re.compile(r"(^|\s)//[^\n]*")
_re_block_comment = re.compile(r"/\*.*?\*/", re.DOTALL)
_re_trailing_comma = re.compile(r",(\s*[}\]])")


def _strip_comments(text):
    text = _re_block_comment.sub("", text)
    text = _re_line_comment.sub(lambda m: m.group(1), text)
    text = _re_trailing_comma.sub(r"\1", text)
    return text


def _read_bytes(path):
    path = Path(path)
    suffixes = path.suffixes
    if suffixes[-1:] == [".xz"]:
        import lzma
        return lzma.open(path, "rb").read()
    if suffixes[-1:] == [".bz2"]:
        import bz2
        return bz2.open(path, "rb").read()
    if suffixes[-1:] == [".gz"]:
        import gzip
        return gzip.open(path, "rb").read()
    return path.read_bytes()


def read_json(path):
    """Read (optionally compressed, comment-tolerant) JSON from *path*."""
    text = _read_bytes(path).decode("utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(_strip_comments(text))


def write_json(data, path, indent=2):
    Path(path).write_text(json.dumps(data, indent=indent, ensure_ascii=False))
