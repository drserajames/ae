"""Compose a TAL phylogenetic tree + antigenic map(s) into one signature-page PDF.

This is the ae-native form of acmacs-tal's `AntigenicMaps` signature page. Because
in ae the two halves are produced by separate tools — the **tree** by the `tal-draw`
binary (subsystem #3) and **antigenic maps** by **kateri** (a separate Dart app, the
"antigenic map viewer and pdf generator") — the signature page is assembled at the
**PDF level** rather than on one shared Cairo surface:

  1. render the tree to a PDF via `tal-draw` (optionally highlighting vaccine/reference
     strains, e.g. from hidb, as node-mods);
  2. obtain the antigenic-map PDF(s): either pre-rendered (`maps=`) or rendered on the
     fly from a chart via kateri (`chart=`, requires the `kateri` executable);
  3. compose tree (left) + map(s) (right) onto one landscape page with `pdfjam`.

The resulting PDF is exactly what `py/ae/report`'s `signature_page` page type embeds
via an explicit `image:` path, so this slots into the seasonal report unchanged.

Verifiable here: steps 1 and 3 (tree render + composition). Step 2's kateri path is
wired to the kateri.py socket protocol but needs the `kateri` executable on PATH.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Sequence

# repo root: .../ae  (this file is py/ae/tal/signature_page.py)
REPO_ROOT = Path(__file__).resolve().parents[3]
TAL_DRAW = REPO_ROOT / "build" / "tal-draw"

# Default highlight style for marked (e.g. vaccine/reference) strains.
DEFAULT_MARK_STYLE = {"edge_color": "#e31a1c", "label_color": "#e31a1c", "label_scale": 1.4}


class SignaturePageError(RuntimeError):
    pass


def _require(exe: str, hint: str) -> str:
    if os.path.isabs(exe):
        if os.path.exists(exe) and os.access(exe, os.X_OK):
            return exe
        found = None
    else:
        found = shutil.which(exe)
    if not found:
        raise SignaturePageError(f"{exe} not found — {hint}")
    return found


# ----------------------------------------------------------------------


def _settings_with_marks(settings: Optional[str], mark: Sequence[str], mark_style: Optional[dict], tmpdir: Path) -> str:
    """Write a temp tal-draw settings file = (the given settings, or {}) plus a node-mod
    that highlights the `mark` seq_ids. This is how hidb-identified vaccine/reference
    strains get emphasised on the tree."""
    config = json.loads(Path(settings).read_text()) if settings else {}
    config.setdefault("labels", True)
    config.setdefault("nodes", []).append({"select": {"seq_id": list(mark)}, "apply": dict(mark_style or DEFAULT_MARK_STYLE)})
    path = tmpdir / "tree-settings.json"
    # ensure_ascii=False: write non-ASCII (e.g. em-dashes in titles) as UTF-8 rather than
    # \uXXXX escapes, which tal-draw's rjson reader passes through literally.
    path.write_text(json.dumps(config, indent=1, ensure_ascii=False), encoding="utf-8")
    return str(path)


def render_tree_pdf(tree, out_pdf, *, size: int = 1000, settings: Optional[str] = None, mark: Optional[Sequence[str]] = None,
                    mark_style: Optional[dict] = None, tal_draw_args: Sequence[str] = (), _tmpdir: Optional[Path] = None) -> Path:
    """Render `tree` to `out_pdf` using the tal-draw binary."""
    tal = _require(str(TAL_DRAW), "build tal-draw (see CLAUDE.md → 'Building natively for arm64')")
    args = list(tal_draw_args)
    settings_path = settings
    if mark:
        tmpdir = _tmpdir or Path(tempfile.mkdtemp(prefix="tal-sig-"))
        settings_path = _settings_with_marks(settings, mark, mark_style, tmpdir)
    if settings_path:
        args.append(f"--settings={settings_path}")
    subprocess.run([tal, *args, str(tree), str(out_pdf), str(int(size))], check=True)
    return Path(out_pdf)


def compose_side_by_side(tree_pdf, map_pdfs: Sequence[os.PathLike], out_pdf, *, frame: bool = False, landscape: bool = True) -> Path:
    """Compose the tree (left) and antigenic map(s) (right, stacked) onto one page."""
    maps = [str(m) for m in map_pdfs]
    if not maps:  # tree only
        shutil.copyfile(str(tree_pdf), str(out_pdf))
        return Path(out_pdf)
    pdfjam = _require("pdfjam", "install MacTeX / TeX Live (provides pdfjam)")
    if len(maps) == 1:
        map_panel = maps[0]
    else:  # stack the maps vertically into a single right-hand panel first
        fd, map_panel = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        subprocess.run([pdfjam, "--quiet", *maps, "--nup", f"1x{len(maps)}", "--outfile", map_panel], check=True)
    cmd = [pdfjam, "--quiet", str(tree_pdf), str(map_panel), "--nup", "2x1", "--frame", "true" if frame else "false", "--outfile", str(out_pdf)]
    if landscape:
        cmd.insert(-2, "--landscape")
    subprocess.run(cmd, check=True)
    return Path(out_pdf)


def render_map_via_kateri(chart, out_pdf, *, style: str = "-", width: float = 800.0) -> Path:
    """Render an antigenic map for `chart` to `out_pdf` using kateri over its unix socket.

    Requires the `kateri` executable on PATH. Faithful to py/ae/utils/kateri.py's
    protocol (start kateri --socket, run a unix-socket server, send CHRT, request a PDF),
    but not runnable where kateri is absent — pass a pre-rendered PDF via `maps=` instead.
    """
    import asyncio

    _require("kateri", "install kateri (github.com/drserajames/kateri) or pass a pre-rendered map via --map")
    import ae_backend  # noqa: F401 — needed to load the chart
    from ae.utils import kateri as K

    async def _run() -> bytes:
        socket_dir = tempfile.mkdtemp(prefix="kateri-sock-")
        socket_name = os.path.join(socket_dir, "kateri.sock")
        server = await asyncio.start_unix_server(K.communicator.connected, socket_name)
        proc = await asyncio.create_subprocess_exec(K.KATERI_EXE, "--socket", socket_name)
        try:
            for _ in range(600):  # wait up to ~60s for kateri to connect
                if K.communicator.is_connected():
                    break
                await asyncio.sleep(0.1)
            else:
                raise SignaturePageError("kateri did not connect to the socket within 60s")
            K.communicator.send_chart(ae_backend.chart_v3.Chart(str(chart)))
            pdf_bytes = await K.communicator.get_pdf(style=style, width=width)
            K.communicator.quit()
            return pdf_bytes
        finally:
            server.close()
            if proc.returncode is None:
                proc.terminate()
            shutil.rmtree(socket_dir, ignore_errors=True)

    Path(out_pdf).write_bytes(asyncio.run(_run()))
    return Path(out_pdf)


def make_signature_page(tree, output, *, maps: Sequence[os.PathLike] = (), chart=None, size: int = 1000,
                        settings: Optional[str] = None, mark: Optional[Sequence[str]] = None, mark_style: Optional[dict] = None,
                        style: str = "-", map_width: float = 800.0, tal_draw_args: Sequence[str] = (), frame: bool = False,
                        keep_temp: bool = False) -> Path:
    """Render the tree, obtain the map(s), and compose them into `output`."""
    tmpdir = Path(tempfile.mkdtemp(prefix="tal-sig-"))
    try:
        tree_pdf = render_tree_pdf(tree, tmpdir / "tree.pdf", size=size, settings=settings, mark=mark, mark_style=mark_style,
                                   tal_draw_args=tal_draw_args, _tmpdir=tmpdir)
        map_pdfs = [Path(m) for m in maps]
        if chart:
            map_pdfs.append(render_map_via_kateri(chart, tmpdir / "map.pdf", style=style, width=map_width))
        compose_side_by_side(tree_pdf, map_pdfs, output, frame=frame)
        return Path(output)
    finally:
        if not keep_temp:
            shutil.rmtree(tmpdir, ignore_errors=True)
