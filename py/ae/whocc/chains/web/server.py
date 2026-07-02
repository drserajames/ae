"""Standard-library HTTP server for the WHO-CC incremental-chains web app.

This is the ae port of AD's ``acmacs-whocc/web/chains-202105`` aiohttp application. It is
deliberately built on ``http.server.ThreadingHTTPServer`` (the same approach as
``ae.webserver.server``) so that ``py/ae`` stays dependency-free — no aiohttp or any other
third-party runtime import. The route surface mirrors the AD app:

======================================  ===============================================
``GET /``                               HTML index of chain directories under the root
``GET /chain?subtype_id=&chain_id=``    HTML page for one incremental chain
``GET /table?subtype_id=&date=``        HTML page for one table date
``GET /png?...`` / ``GET /pdf?...``     render a map (``type=map``) or procrustes
                                        comparison (``type=pc``) via the map-draw CLI
``GET /ace?ace=REL``                    serve a raw ``.ace`` file
``GET /api/subtype-data/?subtype_id=``  JSON tables-of-subtype listing
``GET /js/...``                         static client assets (js/css/jquery)
======================================  ===============================================

All file parameters are paths *relative to the served root*; requests that resolve outside
the root (or, for ``/js``, outside the packaged asset dir) are rejected with 403. Actual
drawing is delegated to the ``map-draw`` executable (configurable via ``--map-draw-exe`` or
the ``MAP_DRAW_EXE`` env var); see :mod:`.render`.
"""

import argparse
import html
import json
import os
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from .context import AppContext
from . import index_page, chain_page, table_page, render

# ----------------------------------------------------------------------

JS_DIR = Path(__file__).parent / "js"

MIME = {
    "png": "image/png",
    "pdf": "application/pdf",
    "ace": "application/octet-stream",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
}


def _bool_from_str(src):
    return bool(src) and src.lower() in ["true", "yes", "1"]


# request-arg types for /png and /pdf (ported from AD application.sRequestArgTypes)
_REQUEST_ARG_TYPES = [
    ["type", str],
    ["ace", str],
    ["ace1", str],
    ["ace2", str],
    ["coloring", str],
    ["size", int],
    ["save_chart", _bool_from_str],
]


def _resolve_within(root: Path, rel: str) -> Path:
    """Resolve *rel* against *root*, refusing anything that escapes the root."""
    if not rel:
        raise ValueError("missing path parameter")
    candidate = (root / rel).resolve()
    if root != candidate and root not in candidate.parents:
        raise PermissionError(f"path outside served root: {rel!r}")
    if not candidate.is_file():
        raise FileNotFoundError(f"no such file: {rel!r}")
    return candidate


# ----------------------------------------------------------------------


class ChainsHandler(BaseHTTPRequestHandler):
    server_version = "ae-chains-server/1.0"

    ctx: AppContext = None  # injected by ChainsServer

    # -- response helpers ----------------------------------------------

    def _send(self, body: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK, extra_headers: dict = None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _send_html(self, text: str, status: HTTPStatus = HTTPStatus.OK):
        self._send(text.encode("utf-8"), "text/html; charset=utf-8", status)

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK):
        self._send(json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8", status)

    def _error(self, status: HTTPStatus, message: str, *, json_response: bool):
        if json_response:
            self._send_json({"ERROR": message}, status=status)
        else:
            self._send_html(f"<!doctype html><h1>{int(status)} {status.phrase}</h1><p>{html.escape(message)}</p>", status=status)

    # -- routing --------------------------------------------------------

    def do_GET(self):  # noqa: N802 — http.server API
        parts = urlsplit(self.path)
        route = parts.path
        query = parse_qs(parts.query)
        is_api = route.startswith("/api/")
        try:
            if route == "/":
                self._send_html(index_page.index_page_html())
            elif route == "/healthz":
                self._send(b"ok", "text/plain; charset=utf-8")
            elif route == "/chain":
                self._send_html(chain_page.chain_page_html(
                    self.ctx, subtype_id=self._q(query, "subtype_id"), chain_id=self._q(query, "chain_id")))
            elif route == "/table":
                self._send_html(table_page.table_page_html(
                    self.ctx, subtype_id=self._q(query, "subtype_id"), table_date=self._q(query, "date")))
            elif route == "/api/subtype-data/":
                subtype_id = self._q(query, "subtype_id")
                self._send_json({"tables": index_page.collect_tables_of_subtype(subtype_id), "subtype_id": subtype_id})
            elif route in ("/png", "/pdf"):
                self._serve_image(query, image_type=route[1:])
            elif route == "/ace":
                self._serve_ace(query)
            elif route.startswith("/js/"):
                self._serve_static(route[len("/js/"):])
            else:
                self._error(HTTPStatus.NOT_FOUND, f"no such route: {route}", json_response=is_api)
        except PermissionError as err:
            self._error(HTTPStatus.FORBIDDEN, str(err), json_response=is_api)
        except FileNotFoundError as err:
            self._error(HTTPStatus.NOT_FOUND, str(err), json_response=is_api)
        except (KeyError, ValueError) as err:
            self._error(HTTPStatus.BAD_REQUEST, str(err), json_response=is_api)
        except Exception as err:  # noqa: BLE001
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(err).__name__}: {err}", json_response=is_api)

    # -- endpoints ------------------------------------------------------

    def _serve_image(self, query, image_type):
        args = {k: t(query.get(k, [None])[0]) for k, t in _REQUEST_ARG_TYPES if query.get(k, [None])[0] is not None}
        req_type = args.get("type")
        if req_type == "map":
            src = _resolve_within(self.ctx.root, args["ace"])
            args["ace"] = str(src)
            filename = f'{src.stem}.{image_type}'
        elif req_type == "pc":
            src1 = _resolve_within(self.ctx.root, args["ace1"])
            src2 = _resolve_within(self.ctx.root, args["ace2"])
            args["ace1"], args["ace2"] = str(src1), str(src2)
            filename = f'pc-{src1.stem}-vs-{src2.stem}.{image_type}'
        else:
            self._error(HTTPStatus.IM_A_TEAPOT, f"unsupported image type request: {req_type!r}", json_response=False)
            return
        body = render.get_map(self.ctx, image_type=image_type, **{k: v for k, v in args.items() if k != "type"}, type=req_type)
        if not body:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "rendering produced no output (see server log)", json_response=False)
            return
        self._send(body, MIME[image_type], extra_headers={
            "pid": str(os.getpid()),
            "Content-Disposition": f'inline; filename="{filename}"',
        })

    def _serve_ace(self, query):
        src = _resolve_within(self.ctx.root, self._q(query, "ace"))
        if src.suffix != ".ace":
            raise ValueError(f"not an .ace file: {src.name!r}")
        self._send(src.read_bytes(), MIME["ace"], extra_headers={
            "pid": str(os.getpid()),
            "Content-Disposition": f'inline; filename="{src.name}"',
        })

    def _serve_static(self, rel):
        target = (JS_DIR / rel).resolve()
        if JS_DIR.resolve() not in target.parents or not target.is_file():
            raise FileNotFoundError(f"no such asset: {rel!r}")
        self._send(target.read_bytes(), MIME.get(target.suffix, "application/octet-stream"))

    # -- helpers --------------------------------------------------------

    @staticmethod
    def _q(query, key):
        values = query.get(key)
        if not values:
            raise KeyError(f"missing query parameter: {key!r}")
        return values[0]

    def log_message(self, fmt, *args):
        if getattr(self.server, "quiet", False):
            return
        super().log_message(fmt, *args)


# ----------------------------------------------------------------------


class ChainsServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, ctx: AppContext, host: str = "127.0.0.1", port: int = 8000, *, quiet: bool = False):
        self.ctx = ctx
        self.quiet = quiet
        # AD's page collectors scan relative to cwd — serve from the root by chdir'ing there.
        os.chdir(ctx.root)
        handler = type("BoundChainsHandler", (ChainsHandler,), {"ctx": ctx})
        super().__init__((host, port), handler)

    @property
    def url(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host}:{port}/"


def serve_in_thread(server: ChainsServer) -> threading.Thread:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


# ----------------------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(description="ae WHO-CC incremental-chains web server")
    parser.add_argument("root", help="directory of subtype-assay-rbc-lab chain dirs to serve")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--mapi", default=None, help="clades.mapi coloring file (default: <root>/clades.mapi)")
    parser.add_argument("--map-draw-exe", default=os.environ.get("MAP_DRAW_EXE", "map-draw"),
                        help="map-draw executable (default: $MAP_DRAW_EXE or 'map-draw' on PATH)")
    parser.add_argument("--quiet", action="store_true")
    opts = parser.parse_args(argv)

    root = Path(opts.root).resolve()
    if not root.is_dir():
        parser.error(f"served root is not a directory: {root}")
    ctx = AppContext(root, mapi_file=opts.mapi, map_draw_exe=opts.map_draw_exe)
    server = ChainsServer(ctx, opts.host, opts.port, quiet=opts.quiet)
    print(f"ae chains server listening on {server.url}", file=sys.stderr)
    print(f"  root:      {ctx.root}", file=sys.stderr)
    print(f"  mapi:      {ctx.mapi_file}", file=sys.stderr)
    print(f"  map-draw:  {ctx.map_draw_exe}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()

# ======================================================================
