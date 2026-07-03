"""Chain entry point (ported from acmacs_py.chain202105.run).

Operational niceties that AD pulled from the acmacs_py umbrella (email notifications,
open_in_emacs on failure, stdout/stderr file redirection) are stubbed out here -- they are
not needed for the port; per-chain logging via Log is preserved.
"""

import sys, datetime, concurrent.futures, socket
from pathlib import Path
from . import error
from .error import KnownError
from .runner import runner_factory
from .log import info

HOSTNAME = socket.gethostname()

# ----------------------------------------------------------------------

def run(chain_dir :Path, setup_py_name :str, force_local_runner :bool = True):
    runner = ChainRunner(chain_dir=chain_dir, setup_py_name=setup_py_name)
    runner.run(force_local_runner=force_local_runner)
    info(f"chain log dir: {runner.log_dir}")

# ----------------------------------------------------------------------

class ChainRunner:

    def __init__(self, chain_dir :Path, setup_py_name :str):
        self.chain_dir = Path(chain_dir).resolve()
        self.setup_py_name = setup_py_name
        self.chain_setup = None
        self.log_dir = None

    def run(self, force_local_runner):
        start = datetime.datetime.now()
        self.load_setup()
        self.setup_log()
        try:
            self.runner = runner_factory(log_prefix=self.log_prefix, force_local=force_local_runner)
            self.main_log(f"chain started with {type(self.runner)}")
            with concurrent.futures.ThreadPoolExecutor() as executor:
                futures = [executor.submit(self.run_chain, chain=chain) for chain in self.chain_setup.chains()]
                for future in concurrent.futures.as_completed(futures):
                    future.result()
            if self.runner.is_failed():
                self.runner.report_failures()
                raise KnownError(f"Parts of chains FAILED, see {HOSTNAME}:{self.log_dir}")
        except:
            self.main_log(f"chain FAILED in: {datetime.datetime.now() - start}")
            sys.stderr.flush()
            raise
        else:
            self.main_log(f"chain completed in: {datetime.datetime.now() - start}")

    def run_chain(self, chain):
        chain.set_output_root_dir(self.chain_dir)
        try:
            chain.run(runner=self.runner, chain_setup=self.chain_setup)
        except error.RunFailed:
            pass                # will be reported by self.run() and self.runner upon completion of other threads

    def setup_log(self):
        self.log_dir = self.chain_dir.joinpath("log")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.main_log_file = self.log_dir.joinpath("Out.log").open("a")
        self.log_prefix = str(self.log_dir.joinpath(datetime.datetime.now().strftime("%y%m%d-%H%M%S-")))
        print(f"{self.log_dir}")

    def load_setup(self):
        # Use a single namespace as both globals and locals so the driver behaves like a
        # module: its top-level imports are visible to ChainSetup's methods (exec with
        # distinct globals/locals would hide module-level imports from method bodies).
        locls = {}
        setup_path = self.chain_dir.joinpath(self.setup_py_name)
        try:
            exec(setup_path.open().read(), locls)
        except FileNotFoundError:
            raise KnownError(f"invalid chain dir: no {setup_path}")
        try:
            chain_setup_cls = locls["ChainSetup"]
        except KeyError:
            raise KnownError(f"invalid chain setup ({setup_path}): ChainSetup class no defined")
        self.chain_setup = chain_setup_cls()

    def main_log(self, message, stderr=False, timestamp=True):
        if timestamp:
            message = f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: {message}"
        print(message)
        if stderr:
            print(message, file=sys.stderr)
        print(message, file=self.main_log_file, flush=True)

# ======================================================================
