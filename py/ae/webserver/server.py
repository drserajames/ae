"""Standard-library HTTP(S) server that serves ae charts from a directory.

The server exposes a small read-only JSON API plus a couple of HTML pages over a
configured root directory of ``.ace`` charts. It is deliberately built on
``http.server.ThreadingHTTPServer`` so it has zero dependencies beyond
``ae_backend``; the API surface (see :class:`ChartHandler`) is stable enough to
be re-hosted behind FastAPI/ASGI later without changing clients.

Routes
------
``GET /``                         HTML index of charts under the root
``GET /healthz``                  ``ok`` (liveness, never touches the backend)
``GET /api/charts``               JSON ``{"charts": [{"path", "size"}...]}``
``GET /api/chart/info?path=REL``  JSON chart summary (antigens/sera/projections)
``GET /api/chart/table?path=REL`` JSON titer table
``GET /chart?path=REL``           HTML summary page for one chart

``REL`` is always a path *relative to the served root*; requests that resolve
outside the root are rejected with 403.
"""

import html
import json
import os
import ssl
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

# ae_backend is imported lazily inside the request handlers so that the module
# can be imported (and the server even started) in an environment where the
# native extension is unavailable — the chart endpoints then return a clean 500
# rather than failing at import time.
CHART_SUFFIXES = (".ace", ".acd1")

# ----------------------------------------------------------------------


def _import_backend():
    import ae_backend  # noqa: PLC0415 — intentional lazy import

    return ae_backend


def list_charts(root: Path) -> list[dict]:
    """Return chart files under *root*, sorted, each as ``{path, size}``."""
    charts = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix in CHART_SUFFIXES:
            charts.append({"path": str(path.relative_to(root)), "size": path.stat().st_size})
    return charts


def resolve_chart(root: Path, rel: str) -> Path:
    """Resolve *rel* against *root*, refusing anything that escapes the root.

    Raises ``PermissionError`` if the resolved path is outside *root* and
    ``FileNotFoundError`` if it is not an existing chart file.
    """
    root = root.resolve()
    candidate = (root / rel).resolve()
    if root != candidate and root not in candidate.parents:
        raise PermissionError(f"path outside served root: {rel!r}")
    if not candidate.is_file() or candidate.suffix not in CHART_SUFFIXES:
        raise FileNotFoundError(f"not a chart file: {rel!r}")
    return candidate


def chart_summary(path: os.PathLike | str) -> dict:
    """Build a JSON-serialisable summary of the chart at *path*."""
    ae_backend = _import_backend()
    chart = ae_backend.chart_v3.Chart(os.fspath(path))

    projections = []
    for pno in range(chart.number_of_projections()):
        proj = chart.projection(pno)
        projections.append(
            {
                "no": pno,
                "stress": proj.stress(),
                "minimum_column_basis": str(proj.minimum_column_basis()),
                "number_of_dimensions": proj.layout().number_of_dimensions(),
                "comment": proj.comment(),
            }
        )

    antigens = [
        {"no": no, "name": ag.name(), "passage": str(ag.passage()), "reassortant": str(ag.reassortant())}
        for no, ag in chart.select_all_antigens()
    ]
    sera = [
        {
            "no": no,
            "name": sr.name(),
            "serum_id": str(sr.serum_id()),
            "passage": str(sr.passage()),
            "reassortant": str(sr.reassortant()),
        }
        for no, sr in chart.select_all_sera()
    ]

    return {
        "name": chart.name_for_file(),
        "number_of_antigens": chart.number_of_antigens(),
        "number_of_sera": chart.number_of_sera(),
        "number_of_projections": chart.number_of_projections(),
        "number_of_layers": chart.titers().number_of_layers(),
        "projections": projections,
        "antigens": antigens,
        "sera": sera,
    }


def titer_table(path: os.PathLike | str) -> dict:
    """Return the titer table of the chart at *path* as nested lists."""
    ae_backend = _import_backend()
    chart = ae_backend.chart_v3.Chart(os.fspath(path))
    titers = chart.titers()
    nags = chart.number_of_antigens()
    nsr = chart.number_of_sera()
    rows = [[str(titers.titer(ag, sr)) for sr in range(nsr)] for ag in range(nags)]
    return {
        "antigens": [ag.name() for _, ag in chart.select_all_antigens()],
        "sera": [sr.name() for _, sr in chart.select_all_sera()],
        "titers": rows,
    }


# ----------------------------------------------------------------------


class ChartHandler(BaseHTTPRequestHandler):
    server_version = "ae-chart-server/1.0"

    # injected by ChartServer
    root: Path = Path(".")

    # -- helpers --------------------------------------------------------

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, body_html: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = body_html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: HTTPStatus, message: str, *, json_response: bool) -> None:
        if json_response:
            self._send_json({"error": message}, status=status)
        else:
            self._send_html(f"<!doctype html><h1>{int(status)} {status.phrase}</h1><p>{html.escape(message)}</p>", status=status)

    def _chart_path(self, query: dict) -> Path:
        rel = (query.get("path") or [""])[0]
        if not rel:
            raise ValueError("missing 'path' query parameter")
        return resolve_chart(self.root, rel)

    # -- routing --------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 — http.server API
        parts = urlsplit(self.path)
        route = parts.path.rstrip("/") or "/"
        query = parse_qs(parts.query)
        is_api = route.startswith("/api/")
        try:
            if route == "/":
                self._send_html(self._render_index())
            elif route == "/healthz":
                self._send_text("ok")
            elif route == "/api/charts":
                self._send_json({"charts": list_charts(self.root)})
            elif route == "/api/chart/info":
                self._send_json(chart_summary(self._chart_path(query)))
            elif route == "/api/chart/table":
                self._send_json(titer_table(self._chart_path(query)))
            elif route == "/chart":
                self._send_html(self._render_chart(self._chart_path(query)))
            else:
                self._error(HTTPStatus.NOT_FOUND, f"no such route: {route}", json_response=is_api)
        except PermissionError as err:
            self._error(HTTPStatus.FORBIDDEN, str(err), json_response=is_api)
        except FileNotFoundError as err:
            self._error(HTTPStatus.NOT_FOUND, str(err), json_response=is_api)
        except ValueError as err:
            self._error(HTTPStatus.BAD_REQUEST, str(err), json_response=is_api)
        except Exception as err:  # backend/runtime failure
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(err).__name__}: {err}", json_response=is_api)

    # -- HTML rendering -------------------------------------------------

    def _render_index(self) -> str:
        rows = "".join(
            f'<li><a href="/chart?path={html.escape(c["path"])}">{html.escape(c["path"])}</a>'
            f' <small>({c["size"]} bytes)</small></li>'
            for c in list_charts(self.root)
        )
        if not rows:
            rows = "<li><em>no charts found under the served root</em></li>"
        return (
            "<!doctype html><meta charset=utf-8><title>ae chart server</title>"
            f"<h1>ae chart server</h1><p>Serving <code>{html.escape(str(self.root))}</code></p>"
            f"<ul>{rows}</ul>"
        )

    def _render_chart(self, path: Path) -> str:
        summary = chart_summary(path)
        rel = path.relative_to(self.root.resolve())
        proj = "".join(
            f"<li>#{p['no']}: stress={p['stress']:.4f}, "
            f"mcb={html.escape(p['minimum_column_basis'])}, {p['number_of_dimensions']}d</li>"
            for p in summary["projections"]
        ) or "<li><em>none</em></li>"
        return (
            "<!doctype html><meta charset=utf-8>"
            f"<title>{html.escape(summary['name'])}</title>"
            f"<p><a href='/'>&larr; index</a></p>"
            f"<h1>{html.escape(summary['name'])}</h1>"
            f"<p>{summary['number_of_antigens']} antigens &middot; "
            f"{summary['number_of_sera']} sera &middot; "
            f"{summary['number_of_projections']} projections &middot; "
            f"{summary['number_of_layers']} layer(s)</p>"
            f"<h2>Projections</h2><ul>{proj}</ul>"
            f"<p>JSON: <a href='/api/chart/info?path={html.escape(str(rel))}'>info</a> &middot; "
            f"<a href='/api/chart/table?path={html.escape(str(rel))}'>table</a></p>"
        )

    # quieter default logging
    def log_message(self, fmt: str, *args) -> None:
        if self.server.quiet:  # type: ignore[attr-defined]
            return
        super().log_message(fmt, *args)


# ----------------------------------------------------------------------


class ChartServer(ThreadingHTTPServer):
    """Threaded HTTP(S) server that serves charts from *root*.

    Pass *certfile* (and optional *keyfile*) to wrap the listening socket in TLS
    for HTTPS. Use :meth:`serve_forever` directly, or the module-level
    :func:`serve` helper for the common blocking case.
    """

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        root: os.PathLike | str,
        host: str = "127.0.0.1",
        port: int = 8000,
        *,
        certfile: str | None = None,
        keyfile: str | None = None,
        quiet: bool = False,
    ) -> None:
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise NotADirectoryError(f"served root is not a directory: {self.root}")
        self.quiet = quiet

        handler = type("BoundChartHandler", (ChartHandler,), {"root": self.root})
        super().__init__((host, port), handler)

        self.scheme = "http"
        if certfile:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(certfile=certfile, keyfile=keyfile)
            self.socket = context.wrap_socket(self.socket, server_side=True)
            self.scheme = "https"

    @property
    def url(self) -> str:
        host, port = self.server_address[:2]
        return f"{self.scheme}://{host}:{port}/"


def serve(
    root: os.PathLike | str,
    host: str = "127.0.0.1",
    port: int = 8000,
    *,
    certfile: str | None = None,
    keyfile: str | None = None,
    quiet: bool = False,
) -> None:
    """Start a :class:`ChartServer` and block, serving until interrupted."""
    server = ChartServer(root, host, port, certfile=certfile, keyfile=keyfile, quiet=quiet)
    print(f"ae chart server listening on {server.url} (root: {server.root})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()


# convenience for tests: run a server in a background thread
def serve_in_thread(server: ChartServer) -> threading.Thread:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread
