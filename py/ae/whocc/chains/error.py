"""Chain engine errors (ported from acmacs_py.chain202105.error).

AD imported KnownError from the acmacs_py umbrella package; here we define a
local minimal KnownError so ae.whocc.chains has no dependency on acmacs_py.
"""


class KnownError (Exception):
    """An error whose message is meant for the user (no traceback needed)."""
    pass


# ----------------------------------------------------------------------

class ChainFailed (KnownError):
    pass


class RunFailed (ChainFailed):
    pass


class WrongFirstChartInIncrementalChain (ChainFailed):

    def __init__(self, message):
        super().__init__(f"""WrongFirstChartInIncrementalChain: {message}""")

# ======================================================================
