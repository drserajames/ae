#!/usr/bin/env python3
"""Local WYSIWYG editor for the curated MRCA aa-transition labels on a tal-draw tree.

Pipeline per render:
  .tal  --(ae.tal.settings_v3.load_tal)-->  tal-draw schema (+ mrca_label_sidecar + image_size)
        --(build/tal-draw --settings=)-->    tree.pdf  +  labels.json  (the geometry sidecar)
        --(pdftoppm -png)-->                 backdrop.png

The browser (editor.html) shows backdrop.png as a backdrop and overlays each curated label as a
draggable box (read from labels.json, all in PDF device units). Dragging a label and hitting Save
posts the new offsets here; we patch the matching `draw-aa-transitions` `per-node` entry in the
*source* .tal (surgically, preserving its relaxed-JSON formatting/comments) with
  "label": {"offset": [x, y]}  +  "pinned": true
and re-render. A pinned label is then placed at exactly that offset by tal-draw (box top-left =
node + offset*page) and reserved as a fixed obstacle; the un-pinned labels still auto-place around it.

  offset.x = (box.x0 - anchor.x) / page.width      # exact inverse of the renderer's pinned formula
  offset.y = (box.y0 - anchor.y) / page.height      # +y is DOWN (PDF device units)

Run:
  python3 server.py --tal <path/to/x.tal> --tree <path/to/x.tjz> [--out DIR] [--image-size N]
                    [-D name[=value] ...] [--dpi 150] [--port 8753]
The --tal it patches may live anywhere (e.g. an ssm run's tree/<sub>.tal). Outputs go to --out
(default: a temp dir), never into the repo.
"""
import argparse
import http.server
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

EDITOR_DIR = Path(__file__).resolve().parent
REPO = EDITOR_DIR.parents[2]          # cc/tal/label-editor -> cc/tal -> cc -> ae-tree
TAL_DRAW = REPO / "build" / "tal-draw"
sys.path.insert(0, str(REPO / "py"))  # for ae.tal.settings_v3 (pure-Python, no ae_backend needed)


def _num(x: float) -> str:
    """Compact JSON number: trim trailing zeros but keep it a valid literal."""
    s = f"{float(x):.6f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-", "-0") else "0"


# ---------------------------------------------------------------- render

def render(tal: Path, tree: Path, outdir: Path, image_size_override, defines, dpi):
    """Translate the .tal, render the PDF + sidecar, rasterise the backdrop PNG.

    Returns (sidecar_dict_augmented, warnings)."""
    from ae.tal.settings_v3 import load_tal
    schema, warnings = load_tal(str(tal), defines or {})
    image_size = int(image_size_override) if image_size_override else int(schema.get("image_size", 1000))
    schema["image_size"] = image_size
    sidecar = outdir / "labels.json"
    schema["mrca_label_sidecar"] = str(sidecar)
    schema_file = outdir / "schema.json"
    schema_file.write_text(json.dumps(schema))

    pdf = outdir / "tree.pdf"
    r = subprocess.run([str(TAL_DRAW), f"--settings={schema_file}", str(tree), str(pdf)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"tal-draw failed:\n{r.stderr or r.stdout}")

    subprocess.run(["pdftoppm", "-png", "-r", str(dpi), "-singlefile", str(pdf), str(outdir / "backdrop")],
                   check=True, capture_output=True)

    data = json.loads(sidecar.read_text()) if sidecar.exists() else {"labels": []}
    data["tal"] = str(tal)
    data["tal_name"] = Path(tal).name
    data["warnings"] = warnings
    data["dpi"] = dpi
    data["rendered_at"] = time.time()
    return data, warnings


# ---------------------------------------------------------------- surgical .tal patch

def _active_pernode_span(lines):
    """Line range [start, end] of the ACTIVE `"per-node": [ ... ]` array (NOT `?per-node`)."""
    start = None
    for i, ln in enumerate(lines):
        if re.match(r'\s*"per-node"\s*:\s*\[', ln):   # anchored: "?per-node" won't match
            start = i
            break
    if start is None:
        raise RuntimeError('no active "per-node" array found in the .tal draw-aa-transitions block')
    depth = 0
    for i in range(start, len(lines)):
        depth += lines[i].count("[") - lines[i].count("]")   # seq_ids/names carry no brackets
        if depth == 0:
            return start, i
    raise RuntimeError('unterminated "per-node" array')


def _patch_entry_line(line: str, ox: float, oy: float, pinned: bool) -> str:
    """Set this per-node entry's label.offset and pinned, editing only those keys."""
    off = f"[{_num(ox)}, {_num(oy)}]"
    if re.search(r'"offset"\s*:\s*\[', line):                       # replace existing offset
        line = re.sub(r'("offset"\s*:\s*)\[[^\]]*\]', lambda m: m.group(1) + off, line, count=1)
    elif re.search(r'"label"\s*:\s*\{', line):                      # add offset into existing label{}
        line = re.sub(r'("label"\s*:\s*\{)', lambda m: m.group(1) + f'"offset": {off}, ', line, count=1)
    else:                                                           # add a label{} after the name
        line = re.sub(r'("\??name"\s*:\s*"[^"]*")(\s*,)?',
                      lambda m: m.group(1) + f', "label": {{"offset": {off}}},', line, count=1)
    pv = "true" if pinned else "false"
    if re.search(r'"pinned"\s*:', line):                            # replace existing pinned
        line = re.sub(r'("pinned"\s*:\s*)(?:true|false)', lambda m: m.group(1) + pv, line, count=1)
    else:                                                           # insert pinned right after the {
        line = re.sub(r'^(\s*\{)', lambda m: m.group(1) + f' "pinned": {pv}, ', line, count=1)
    return line


def _patch_nodetext_line(line: str, ox: float, oy: float) -> str:
    """Set a `nodes` apply.text.offset (the only offset on the line)."""
    off = f"[{_num(ox)}, {_num(oy)}]"
    if re.search(r'"offset"\s*:\s*\[', line):
        return re.sub(r'("offset"\s*:\s*)\[[^\]]*\]', lambda m: m.group(1) + off, line, count=1)
    # no offset yet: add one into the apply.text object, right after its "text": "..."
    return re.sub(r'("text"\s*:\s*"[^"]*")', lambda m: m.group(1) + f', "offset": {off}', line, count=1, flags=0)


def patch_tal(tal_path: Path, edits):
    """Apply edits to the .tal. kind=="mrca" -> active per-node `label.offset`+`pinned`;
    kind=="nodetext" -> the matching `nodes` entry's `apply.text.offset`."""
    text = Path(tal_path).read_text()
    lines = text.split("\n")
    mrca = [e for e in edits if e.get("kind", "mrca") == "mrca"]
    nodetext = [e for e in edits if e.get("kind") == "nodetext"]
    applied = 0

    if mrca:
        start, end = _active_pernode_span(lines)
        for e in mrca:
            first, last = e["first"], e["last"]
            ox, oy = e["offset"]
            pinned = bool(e.get("pinned", True))
            hit = next((i for i in range(start, end + 1)
                        if re.search(r'"\??first"\s*:\s*"%s"' % re.escape(first), lines[i])
                        and re.search(r'"\??last"\s*:\s*"%s"' % re.escape(last), lines[i])), None)
            if hit is None:
                raise RuntimeError(f"no per-node entry for first={first!r} last={last!r}")
            lines[hit] = _patch_entry_line(lines[hit], ox, oy, pinned)
            applied += 1

    for e in nodetext:
        seq_id = e["seq_id"]
        ox, oy = e["offset"]
        hit = next((i for i, ln in enumerate(lines)
                    if '"nodes"' in ln and re.search(r'"seq_id"\s*:\s*"%s"' % re.escape(seq_id), ln)
                    and '"text"' in ln), None)
        if hit is None:
            raise RuntimeError(f"no nodes apply.text entry for seq_id={seq_id!r}")
        lines[hit] = _patch_nodetext_line(lines[hit], ox, oy)
        applied += 1

    Path(tal_path).write_text("\n".join(lines))
    return applied


# ---------------------------------------------------------------- HTTP server

class State:
    def __init__(self, args, outdir):
        self.args = args
        self.outdir = outdir
        self.defines = parse_defines(args.D)
        self.lock = threading.Lock()
        self.data = None
        # persistent PDF target written on Save (default: alongside the .tal as <stem>.pdf)
        self.pdf_out = Path(args.pdf) if args.pdf else (Path(args.tal).parent / (Path(args.tal).stem + ".pdf"))

    def rerender(self):
        with self.lock:
            self.data, _ = render(Path(self.args.tal), Path(self.args.tree), self.outdir,
                                  self.args.image_size, self.defines, self.args.dpi)
            return self.data


def parse_defines(dlist):
    out = {}
    for d in dlist or []:
        if "=" in d:
            k, v = d.split("=", 1)
            out[k] = v
        else:
            out[d] = True
    return out


def make_handler(state: State):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/":
                self._send(200, (EDITOR_DIR / "editor.html").read_bytes(), "text/html; charset=utf-8")
            elif path == "/labels.json":
                self._send(200, json.dumps(state.data))
            elif path == "/backdrop.png":
                png = state.outdir / "backdrop.png"
                if png.exists():
                    self._send(200, png.read_bytes(), "image/png")
                else:
                    self._send(404, json.dumps({"error": "no backdrop"}))
            else:
                self._send(404, json.dumps({"error": "not found"}))

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw or b"{}")
            except Exception as ex:
                self._send(400, json.dumps({"error": f"bad JSON: {ex}"}))
                return
            if self.path.split("?", 1)[0] != "/save":
                self._send(404, json.dumps({"error": "not found"}))
                return
            edits = payload.get("edits", [])
            try:
                n = patch_tal(Path(state.args.tal), edits)
                data = state.rerender()
                data = dict(data)
                data["saved"] = n
                # write the re-rendered PDF (with the new label positions) to the persistent target
                src = state.outdir / "tree.pdf"
                if src.exists() and state.pdf_out:
                    shutil.copy(src, state.pdf_out)
                    data["saved_pdf"] = str(state.pdf_out)
                self._send(200, json.dumps(data))
            except Exception as ex:
                self._send(500, json.dumps({"error": str(ex)}))
    return Handler


def free_port(preferred):
    for p in [preferred, 0]:
        try:
            s = socket.socket()
            s.bind(("127.0.0.1", p))
            port = s.getsockname()[1]
            s.close()
            return port
        except OSError:
            continue
    return preferred


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tal", required=True, help="source .tal to render AND patch on Save")
    ap.add_argument("--tree", required=True, help="tree file (.tjz / .newick / .json) to render")
    ap.add_argument("--out", help="output dir for pdf/png/sidecar (default: temp dir, kept)")
    ap.add_argument("--image-size", type=int, default=0, help="page height in device units (default: from .tal/1000)")
    ap.add_argument("--pdf", help="persistent PDF written on Save (default: <tal-dir>/<tal-stem>.pdf)")
    ap.add_argument("-D", action="append", default=[], help="settings define: name or name=value")
    ap.add_argument("--dpi", type=int, default=150, help="backdrop rasterisation DPI (default 150)")
    ap.add_argument("--port", type=int, default=8753)
    ap.add_argument("--no-open", action="store_true", help="do not auto-open a browser")
    args = ap.parse_args()

    if not TAL_DRAW.exists():
        sys.exit(f"tal-draw not found at {TAL_DRAW} — build it first (see ae-tree/ae/CLAUDE.md)")
    outdir = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="tal-label-editor-"))
    outdir.mkdir(parents=True, exist_ok=True)

    state = State(args, outdir)
    print(f"Rendering {args.tal} on {args.tree} ...")
    data = state.rerender()
    print(f"  {len(data['labels'])} labels; working outputs in {outdir}")
    print(f"  Save writes the PDF to: {state.pdf_out}")
    for w in data.get("warnings", [])[:8]:
        print(f"  warning: {w}")

    port = free_port(args.port)
    httpd = http.server.HTTPServer(("127.0.0.1", port), make_handler(state))
    url = f"http://127.0.0.1:{port}/"
    print(f"\n  Editor: {url}\n  Patches: {args.tal}\n  (Ctrl-C to stop)\n")
    if not args.no_open:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
