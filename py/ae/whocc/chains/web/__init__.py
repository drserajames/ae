"""WHO-CC incremental-chains web app (ae port of AD acmacs-whocc/web/chains-202105).

Stdlib ``http.server``-based; ``py/ae`` stays dependency-free. Rendering is delegated to
the ``map-draw`` CLI. Start it with::

    python -m ae.whocc.chains.web.server <root> [--port N] [--map-draw-exe PATH] [--mapi FILE]

See :mod:`.server` for the route list.
"""

from .context import AppContext, CladeData
from .server import ChainsServer, ChainsHandler, serve_in_thread, main

__all__ = ["AppContext", "CladeData", "ChainsServer", "ChainsHandler", "serve_in_thread", "main"]

# ======================================================================
