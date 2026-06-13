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

# Highlight styles. Explicit --mark and vaccines are red; hidb reference antigens blue.
DEFAULT_MARK_STYLE = {"edge_color": "#e31a1c", "label_color": "#e31a1c", "label_scale": 1.4}
REFERENCE_MARK_STYLE = {"edge_color": "#1f78b4", "label_color": "#1f78b4", "label_scale": 1.3}


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


def _kateri_app_bundle(kateri_exe: str) -> Optional[Path]:
    """Resolve the .app bundle containing the kateri executable (the on-PATH `kateri`
    is a symlink into kateri.app/Contents/MacOS/kateri)."""
    resolved = Path(kateri_exe).resolve()
    for parent in (resolved, *resolved.parents):
        if parent.suffix == ".app":
            return parent
    return None


def render_map_via_kateri(chart, out_pdf, *, style: str = "-", width: float = 800.0, connect_timeout: float = 60.0) -> Path:
    """Render an antigenic map for `chart` to `out_pdf` using kateri over its unix socket.

    Requires the `kateri` executable on PATH. Implements py/ae/utils/kateri.py's protocol:
    run a unix-socket server, launch kateri (which connects back as a client and sends
    HELO), send the chart, request a PDF. kateri is a Flutter GUI app and connects only
    after its window builds, so on macOS it is launched via `open` (which gives it a GUI
    session) rather than as a bare subprocess.
    """
    import asyncio

    exe = _require("kateri", "install kateri (github.com/drserajames/kateri) or pass a pre-rendered map via --map")
    try:
        import ae_backend  # needed to load/export the chart
        from ae.utils import kateri as K
    except ImportError as err:
        raise SignaturePageError(
            f"the --chart/kateri path needs ae_backend ({err}); run under the Python that can import it "
            "(e.g. the arm64 python3.10 with PYTHONPATH=build), or pass a pre-rendered map via --map") from err

    app_bundle = _kateri_app_bundle(exe)

    async def _run() -> bytes:
        socket_dir = tempfile.mkdtemp(prefix="kateri-sock-")
        socket_name = os.path.join(socket_dir, "kateri.sock")
        server = await asyncio.start_unix_server(K.communicator.connected, socket_name)
        direct = None
        try:
            if app_bundle is not None:  # macOS GUI app — launch via `open` for an Aqua session
                opener = await asyncio.create_subprocess_exec("open", "-n", "-a", str(app_bundle), "--args", "--socket", socket_name)
                await opener.wait()
            else:  # non-bundle / non-macOS build — launch directly
                direct = await asyncio.create_subprocess_exec(exe, "--socket", socket_name)
            waited = 0.0
            while not K.communicator.is_connected():
                if waited >= connect_timeout:
                    raise SignaturePageError(f"kateri did not connect to the socket within {connect_timeout:.0f}s")
                await asyncio.sleep(0.1)
                waited += 0.1
            K.communicator.send_chart(ae_backend.chart_v3.Chart(str(chart)))
            pdf_bytes = await K.communicator.get_pdf(style=style, width=width)
            K.communicator.quit()  # tells kateri to exit
            return pdf_bytes
        finally:
            server.close()
            if direct is not None and direct.returncode is None:
                direct.terminate()
            shutil.rmtree(socket_dir, ignore_errors=True)

    Path(out_pdf).write_bytes(asyncio.run(_run()))
    return Path(out_pdf)


def load_vaccine_names(vaccines_file, subtype: str) -> list:
    """Read the WHO vaccine strain names for `subtype` from acmacs-data's
    semantic_vaccines.py (the modern replacement for AD's vaccines.json). Keys are
    e.g. "A(H1N1)", "A(H3N2)", "BV", "BY"."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_ae_tal_semantic_vaccines", str(vaccines_file))
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)  # imports ae.utils.org — needs py/ on sys.path
    except Exception as err:
        raise SignaturePageError(f"cannot load vaccines file {vaccines_file}: {err}") from err
    table = getattr(module, "sData", {}).get(subtype)
    if table is None:
        raise SignaturePageError(f"subtype {subtype!r} not in {vaccines_file} (keys: {sorted(getattr(module, 'sData', {}))})")
    return [entry["name"] for entry in table if entry.get("name")]


def match_leaves_by_name(tree, names: Sequence[str]) -> list:
    """Return the seq_ids of tree leaves whose strain-name matches one of `names`.

    Leaf seq_ids look like `LOCATION/ISOLATE/YEAR[_PASSAGE]_HASH` with spaces written
    as underscores (e.g. NEW_CALEDONIA/20/1999_E5_AB12CD34); vaccine names use spaces
    (NEW CALEDONIA/20/1999). A leaf matches when its seq_id equals the normalised name
    or starts with it followed by `_` (so all passages of the strain are caught).
    Loads the tree via ae_backend, so run under the Python that can import it.
    """
    try:
        import ae_backend
    except ImportError as err:
        raise SignaturePageError(f"--mark-vaccines needs ae_backend ({err}); run under the arm64 python3.10") from err
    loaded = ae_backend.tree.load(str(tree))
    wanted = {n.strip().upper().replace(" ", "_") for n in names if n.strip()}
    matched = []
    for ref in loaded.select_leaves():
        try:
            seq_id = ref.name()
        except UnicodeDecodeError:
            continue  # a few real-tree leaves carry non-UTF-8 bytes; they're never vaccine/reference names
        upper = seq_id.upper()
        if any(upper == w or upper.startswith(w + "_") for w in wanted):
            matched.append(seq_id)
    return matched


def get_reference_antigen_names(hidb_dir, subtype: str, n_recent_tables: int = 20) -> list:
    """Reference antigen names for `subtype` from hidb — the union of the reference
    antigens of the most recent `n_recent_tables` tables (the current reference panel).
    Needs ae_backend + the hidb DBs (set hidb_dir or $HIDB_V5)."""
    try:
        import ae_backend
    except ImportError as err:
        raise SignaturePageError(f"--mark-reference needs ae_backend ({err}); run under the arm64 python3.10") from err
    if hidb_dir:
        ae_backend.hidb.set_dir(str(hidb_dir))
    db = ae_backend.hidb.hidb(subtype)
    n_tables = db.number_of_tables()
    names = set()
    for table_index in range(max(0, n_tables - max(1, n_recent_tables)), n_tables):
        for antigen_index in db.reference_antigens(table_index):
            # name_without_subtype: tree leaf seq_ids drop the "B/"/"A(H3N2)/" prefix
            names.add(db.antigen(antigen_index).name_without_subtype())
    return sorted(names)


def _settings_with_mark_groups(settings: Optional[str], groups, tmpdir: Path) -> str:
    """Write a temp tal-draw settings file = (the given settings, or {}) plus one node-mod
    per (names, style) group, so different categories (vaccines, references, …) can be
    highlighted in different colours."""
    config = json.loads(Path(settings).read_text()) if settings else {}
    config.setdefault("labels", True)
    nodes = config.setdefault("nodes", [])
    for names, style in groups:
        names = list(names)
        if names:
            nodes.append({"select": {"seq_id": names}, "apply": dict(style)})
    path = tmpdir / "tree-settings.json"
    path.write_text(json.dumps(config, indent=1, ensure_ascii=False), encoding="utf-8")
    return str(path)


def make_signature_page(tree, output, *, maps: Sequence[os.PathLike] = (), chart=None, size: int = 1000,
                        settings: Optional[str] = None, mark: Optional[Sequence[str]] = None, mark_style: Optional[dict] = None,
                        mark_vaccines: Optional[str] = None, vaccines_file=None,
                        mark_reference: Optional[str] = None, hidb_dir=None, reference_tables: int = 20,
                        style: str = "-", map_width: float = 800.0, tal_draw_args: Sequence[str] = (), frame: bool = False,
                        keep_temp: bool = False) -> Path:
    """Render the tree, obtain the map(s), and compose them into `output`."""
    tmpdir = Path(tempfile.mkdtemp(prefix="tal-sig-"))
    try:
        groups = []  # (names, style) — drawn as node-mods, each its own colour
        if mark:
            groups.append((list(mark), dict(mark_style or DEFAULT_MARK_STYLE)))
        if mark_vaccines:
            if not vaccines_file:
                raise SignaturePageError("--mark-vaccines needs --vaccines-file (acmacs-data/semantic_vaccines.py)")
            groups.append((match_leaves_by_name(tree, load_vaccine_names(vaccines_file, mark_vaccines)), dict(DEFAULT_MARK_STYLE)))
        if mark_reference:
            groups.append((match_leaves_by_name(tree, get_reference_antigen_names(hidb_dir, mark_reference, reference_tables)), dict(REFERENCE_MARK_STYLE)))
        merged_settings = _settings_with_mark_groups(settings, groups, tmpdir) if groups else settings
        tree_pdf = render_tree_pdf(tree, tmpdir / "tree.pdf", size=size, settings=merged_settings, mark=None,
                                   tal_draw_args=tal_draw_args, _tmpdir=tmpdir)
        map_pdfs = [Path(m) for m in maps]
        if chart:
            map_pdfs.append(render_map_via_kateri(chart, tmpdir / "map.pdf", style=style, width=map_width))
        compose_side_by_side(tree_pdf, map_pdfs, output, frame=frame)
        return Path(output)
    finally:
        if not keep_temp:
            shutil.rmtree(tmpdir, ignore_errors=True)
