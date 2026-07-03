"""
ae.utils.traceback — format and report exceptions (with an audible alert).
"""
import sys, traceback, subprocess

# ======================================================================

def format_exception(err: Exception):
    """Format an exception's traceback as a string, prefixing the final line with `> `."""
    tb = traceback.format_exception(err)
    tb[-1] = "> " + tb[-1]
    return "".join(tb)

def report_exception(err: Exception = None, sound: bool = True):
    """Print the formatted traceback of `err` (or the current exception) to stderr; play an
    alert sound unless `sound` is False."""
    if err is None:
        err = sys.exc_info()[1]
    print(format_exception(err), file=sys.stderr)
    if sound:
        subprocess.call(["afplay", "/System/Library/Sounds/Blow.aiff"])

# ======================================================================
