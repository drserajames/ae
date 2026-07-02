"""WHO-CC incremental-chain engine (ported from acmacs_py.chain202105).

Public API used by per-lab drivers (create <chain_dir>/Setup.py):

    from ae.whocc.chains import ChainSetupDefault, IndividualTableMapChain, IncrementalChain

and run a chain with:

    from ae.whocc.chains import run
    run(chain_dir, "Setup.py")            # force_local_runner=True by default
"""

from .error import KnownError, ChainFailed, RunFailed, WrongFirstChartInIncrementalChain
from .chain_setup import ChainSetupDefault
from .chains import ChainBase, IndividualTableMapChain, IncrementalChain, IncrementalMergeMaker
from .run import run, ChainRunner

__all__ = [
    "ChainSetupDefault",
    "ChainBase", "IndividualTableMapChain", "IncrementalChain", "IncrementalMergeMaker",
    "run", "ChainRunner",
    "KnownError", "ChainFailed", "RunFailed", "WrongFirstChartInIncrementalChain",
]

# ======================================================================
