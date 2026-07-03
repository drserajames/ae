"""
ae.utils.open_file — open (possibly compressed) files by content/extension, with backups.
"""
import sys, lzma, bz2, gzip, datetime
from pathlib import Path

# ======================================================================

def for_reading(path :Path):
    """Open `path` for binary reading, auto-detecting xz / bz2 / gzip / plain by trying each
    reader (`"-"` = stdin). Raises RuntimeError if none can read it."""
    if path == "-":
        return sys.stdin
    for opener in [lzma.LZMAFile, bz2.BZ2File, gzip.GzipFile, open]:
        file = opener(path, "rb")
        try:
            file.peek(1)
            break
        except:
            pass
    else:
        raise RuntimeError(f"Cannot read {path}")
    return file

# ----------------------------------------------------------------------

def for_writing(path :Path, do_backup: bool = True):
    """Open `path` for writing, choosing xz / bz2 / gzip compression by suffix (`"-"` =
    stdout); backs up an existing file first unless `do_backup` is False."""
    if path == "-":
        return sys.stdout
    if do_backup:
        backup(path)
    if path.suffix in [".xz", ".ace", ".jxz", ".tjz"]:
        return lzma.LZMAFile(path, "w")
    elif path.suffix in [".bz2"]:
        return bz2.BZ2File(path, "w")
    elif path.suffix in [".gz"]:
        return gzip.GzipFile(path, "w")
    else:
        return path.open("w")

# ----------------------------------------------------------------------

def backup(path: Path):
    """Move an existing file into a sibling `.backup/` directory under a timestamped name
    (skips files under `/dev` and never overwrites an existing backup)."""
    if path.exists() and path.parents[len(path.parents) - 2] != "/dev":
        backup_dir = path.resolve().parent.joinpath(".backup")
        backup_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.datetime.now()
        new_name = backup_dir.joinpath(f"{path.stem}.~{now:%Y-%m%d-%H%M%S}~{path.suffix}")
        if not new_name.exists():
            path.rename(new_name)

# ======================================================================
