"""Shared bootstrap for the hidb command-line tools.

Loads *this* repository's freshly-built ``ae_backend`` (from ``build/``) by
explicit file path, so the tools are not shadowed by any editable install of
``ae_backend`` from a different checkout.

Data files are located purely from the environment (no paths are hard-coded
here). The relevant variables are:

  HIDB_V5       directory holding hidb5.{h1,h3,b}.json.xz
  LOCDB_V2      path to locationdb.json.xz (the virus-name parser needs it)
  VACCINES_JSON path to the whocc vaccines.json (only the vaccines tool needs it)
"""

import os
import sys
import glob
import importlib.util


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


def load_ae_backend():
    """Return the ae_backend module built in this repo's build/ directory."""
    if "ae_backend" in sys.modules:
        return sys.modules["ae_backend"]
    build_dir = os.path.join(_repo_root(), "build")
    sos = sorted(glob.glob(os.path.join(build_dir, "ae_backend*.so")))
    if sos:
        spec = importlib.util.spec_from_file_location("ae_backend", sos[0])
        module = importlib.util.module_from_spec(spec)
        sys.modules["ae_backend"] = module
        spec.loader.exec_module(module)
        return module
    import ae_backend  # fall back to whatever is on PYTHONPATH

    return ae_backend


def require_env(name, what):
    value = os.environ.get(name)
    if not value:
        sys.exit(f"error: ${name} is not set (needed for {what})")
    return value


def open_hidb(ae_backend, virus_type):
    """Open the hidb for ``virus_type`` ("A(H3N2)", "H3", "B", ...).

    Requires $HIDB_V5 (data directory) and $LOCDB_V2 (locationdb, used by the
    virus-name parser when looking antigens up by name).
    """
    require_env("LOCDB_V2", "the virus-name parser / locationdb")
    ae_backend.hidb.set_dir(require_env("HIDB_V5", "the hidb data directory"))
    return ae_backend.hidb.hidb(virus_type)
