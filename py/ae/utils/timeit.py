"""
ae.utils.timeit — context manager reporting the wall-clock time of a block.
"""
import sys, datetime
from contextlib import contextmanager

# ======================================================================

@contextmanager
def timeit(name, report=True):
    """Context manager printing the elapsed time of the wrapped block to stderr (labelled
    `name`), including on exception (which is re-raised)."""
    start = datetime.datetime.utcnow()
    try:
        yield
    except Exception as err:
        print(f">> {name} <{datetime.datetime.utcnow() - start}> with error {err}", file=sys.stderr)
        raise
    else:
        print(f">>> {name} <{datetime.datetime.utcnow() - start}>", file=sys.stderr)

# ======================================================================
