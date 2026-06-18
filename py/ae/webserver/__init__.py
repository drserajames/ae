"""HTTP(S) chart-serving webserver for ae.

This is the ae replacement for the old AD ``acmacs-webserver`` package. That
package was a generic multi-threaded C++ websocket server built on the (now
unmaintained) ``websocketpp`` + standalone-Asio + OpenSSL stack and carried no
chart logic of its own. Since ``ae_backend`` is already a Python extension
module, the chart-serving role is implemented here directly on top of it using
only the Python standard library (``http.server`` + ``ssl``) — no third-party
dependencies, and TLS for the "HTTPS chart serving" the roadmap calls for.

See ``bin/chart-serve`` for the command-line entry point.
"""

from .server import ChartServer, serve, chart_summary, titer_table

__all__ = ["ChartServer", "serve", "chart_summary", "titer_table"]
