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
  3. compose tree (left) + map(s) (right) onto one landscape page — either a plain
     stack (`compose_side_by_side`, via `pdfjam`) or, when captions / a page title /
     an explicit column count are wanted, an R×C captioned grid (`compose_grid`, via
     `pdflatex`).

The resulting PDF is exactly what `py/ae/report`'s `signature_page` page type embeds
via an explicit `image:` path, so this slots into the seasonal report unchanged.

Verifiable here: steps 1 and 3 (tree render + composition). Step 2's kateri path is
wired to the kateri.py socket protocol but needs the `kateri` executable on PATH.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
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
    """Raised on a signature-page construction error."""
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


_LATEX_SPECIAL = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
    "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}


def _latex_escape(text: str) -> str:
    return "".join(_LATEX_SPECIAL.get(ch, ch) for ch in str(text))


def _pdf_aspect(pdf, default: float = 0.7) -> float:
    """width/height of a PDF's first page (for sizing the tree panel). Uses pdfinfo."""
    pdfinfo = shutil.which("pdfinfo") or "/Library/TeX/texbin/pdfinfo"
    try:
        out = subprocess.check_output([pdfinfo, str(pdf)], text=True, stderr=subprocess.DEVNULL)
        for line in out.splitlines():
            if line.startswith("Page size:"):
                w, h = line.split(":", 1)[1].split("x")[:2]
                return float(w.strip()) / float(h.strip().split()[0])
    except Exception:
        pass
    return default


def compose_grid(tree_pdf, map_pdfs: Sequence[os.PathLike], out_pdf, *, captions: Optional[Sequence[str]] = None,
                 page_title: Optional[str] = None, tree_caption: Optional[str] = None, columns: Optional[int] = None,
                 paper_mm: tuple = (297.0, 210.0), margin_mm: float = 6.0, frame: bool = False, sans: bool = False,
                 auto_width: bool = False) -> Path:
    """Compose the tree (left) and an R×C grid of antigenic maps (right) onto one landscape
    page via `pdflatex`. The richer counterpart to `compose_side_by_side`: optional per-map
    captions, a page title, and a real grid (vs a 1×N stack).

    `frame=True` draws a thin black box around each map (matching AD's per-map border, since
    kateri draws no border itself). `sans=True` typesets text in Helvetica to match AD.
    For the section-map signature page, titles are drawn *inside* each map (kateri), so
    `captions` is omitted — no text appears between maps.

    `columns` defaults to ceil(sqrt(n)). If `pdflatex` isn't available it falls back to
    `compose_side_by_side` (which drops the captions/title but still composes the page).
    """
    maps = [str(m) for m in map_pdfs]
    if not maps:  # tree only
        shutil.copyfile(str(tree_pdf), str(out_pdf))
        return Path(out_pdf)
    pdflatex = shutil.which("pdflatex")
    if not pdflatex:  # no LaTeX → degrade gracefully to the pdfjam stack (no captions)
        return compose_side_by_side(tree_pdf, map_pdfs, out_pdf)

    caps = list(captions or [])
    caps += [""] * (len(maps) - len(caps))  # pad to one caption per map
    cols = columns if (columns and columns > 0) else max(1, math.ceil(math.sqrt(len(maps))))
    rows = math.ceil(len(maps) / cols)
    paper_w, paper_h = paper_mm
    title_mm = 9.0 if page_title else 0.0
    # Vertical headroom for the minipage[t] baseline + inter-row glue (else the grid spills to
    # a 2nd page). Square maps are height-bounded to the cell, so auto_width can pack tighter
    # (bigger cells → wider grid → page aspect closer to AD) than the fixed-paper path.
    avail_h = paper_h - 2.0 * margin_mm - title_mm - (10.0 if auto_width else 6.0)
    row_overhead = 7.0 if any(caps) else (1.5 if auto_width else 3.0)
    col_gap_mm, panel_gap_mm = 2.0, 5.0
    if auto_width:
        # AD-like: fix the page HEIGHT, give each map a fixed square cell (rows fill the
        # height), the tree its natural width (its aspect × height), and let the page WIDTH
        # grow with the number of map columns — so 2-col B/Vic is narrow, 4-col H3 is wide.
        cell_mm = max(20.0, avail_h / rows - row_overhead)
        # Page HEIGHT = the tightly-packed map grid + margins + a small spill guard. The grid is
        # composed below (auto_width branch) as a \vtop{\offinterlineskip ...} with NO inter-row
        # baselineskip glue, so N rows pack into ~rows*cell_mm. This matches AD's ~199mm sig page;
        # the earlier \par-separated minipage stack carried ~20mm of baselineskip glue -> a ~217mm
        # (~9% too tall) page. PAD=4mm is the minimum keeping every subtype on ONE page (the h3
        # 4-col/10-map 3-row grid is the tightest — verified by sweep). => ~202mm, +1.5% vs AD.
        sig_rowgap_mm = 1.5  # vertical gap between map rows (\vskip in the tight grid below)
        grid_h_mm = rows * cell_mm + (rows - 1) * sig_rowgap_mm
        # Size the tree to the GRID height. NB: sizing it to the FULL text height (taller than the
        # grid, to squeeze out the last ~3% of vertical fill) widens the tree column enough to push
        # the page to a 2nd page (verified: spills h1-cdc). Grid height is the single-page-safe max.
        tree_w_mm = _pdf_aspect(tree_pdf) * grid_h_mm
        grid_w_mm = cols * cell_mm + (cols - 1) * col_gap_mm
        paper_w = 2.0 * margin_mm + tree_w_mm + panel_gap_mm + grid_w_mm
        tree_w_frac = tree_w_mm / (paper_w - 2.0 * margin_mm)
        paper_h = grid_h_mm + 2.0 * margin_mm + 4.0
    else:
        # Fixed paper: size each cell to fit both the right panel's width and the height.
        right_panel_mm = 0.48 * (paper_w - 2.0 * margin_mm)
        cell_mm = max(10.0, min(right_panel_mm / cols - 3.0, avail_h / rows - row_overhead))
        tree_w_frac = 0.5
    # Auto-width sig page: tree matches the (tight) grid height (single-page safe); otherwise avail_h.
    tree_h_frac = round((grid_h_mm if auto_width else avail_h) / (paper_h - 2.0 * margin_mm), 3)
    grid_panel_frac = round((cols * cell_mm + cols * col_gap_mm + 2.0) / (paper_w - 2.0 * margin_mm), 3)

    work = Path(tempfile.mkdtemp(prefix="tal-grid-"))
    try:
        shutil.copyfile(str(tree_pdf), str(work / "tree.pdf"))
        for i, m in enumerate(maps):
            shutil.copyfile(m, str(work / f"map{i}.pdf"))

        def boxed(i: int) -> str:
            """LaTeX for one grid cell: the i-th map PDF bounded to the cell
            (keepaspectratio), optionally framed with a thin black border."""
            # Bound the map by BOTH the cell width and height (keepaspectratio): kateri's
            # auto-fit maps aren't always square, so a width-only fit would make a tall map
            # overflow the cell and spill the grid to a 2nd page.
            img = rf"\includegraphics[width={cell_mm:.1f}mm,height={cell_mm:.1f}mm,keepaspectratio]{{map{i}.pdf}}"
            # AD draws a thin black border around each map; kateri draws none, so frame here.
            return rf"\setlength{{\fboxsep}}{{0pt}}\setlength{{\fboxrule}}{{0.5pt}}\fbox{{{img}}}" if frame else img

        if auto_width:
            # Tight grid: each row an \hbox of framed maps; rows stacked in a
            # \vtop{\offinterlineskip ...} so there is NO inter-row baselineskip glue (the cause of
            # the over-tall page). Section-map sig pages carry no per-map captions.
            row_tex = []
            for r in range(rows):
                imgs = [boxed(i) for i in range(r * cols, min((r + 1) * cols, len(maps)))]
                row_tex.append(r"\hbox{" + r"\hspace{2mm}".join(imgs) + r"}")
            grid = r"\vtop{\offinterlineskip" + "".join(
                "\n" + rt + (rf"\vskip{sig_rowgap_mm:.1f}mm" if k < len(row_tex) - 1 else "")
                for k, rt in enumerate(row_tex)) + r"}"
        else:
            cells = []
            for i in range(len(maps)):
                cap = caps[i] if i < len(caps) else ""
                cap_tex = rf"\\[1pt]{{\footnotesize {_latex_escape(cap)}}}" if cap else ""
                cells.append(
                    rf"\begin{{minipage}}[t]{{{cell_mm:.1f}mm}}\centering{boxed(i)}{cap_tex}\end{{minipage}}%"
                )
                cells.append(r"\hspace{2mm}")
                if (i + 1) % cols == 0:  # row break
                    cells.append(r"\par\vspace{2mm}")
            grid = "\n".join(cells)

        title_tex = rf"{{\large\bfseries {_latex_escape(page_title)}\par}}\vspace{{2mm}}" + "\n" if page_title else ""
        tree_cap_tex = rf"\\[1pt]{{\footnotesize {_latex_escape(tree_caption)}}}" if tree_caption else ""

        tex = "\n".join([
            r"\documentclass{article}",
            rf"\usepackage[paperwidth={paper_w:.0f}mm,paperheight={paper_h:.0f}mm,margin={margin_mm:.0f}mm,"
            r"headheight=0pt,headsep=0pt,footskip=0pt]{geometry}",
            r"\usepackage{graphicx}",
            (r"\usepackage{helvet}\renewcommand{\familydefault}{\sfdefault}" if sans else "%"),
            r"\setlength{\parindent}{0pt}\pagestyle{empty}",
            r"\begin{document}",
            title_tex + r"\noindent",
            rf"\begin{{minipage}}[t]{{{tree_w_frac:.3f}\linewidth}}\vspace{{0pt}}\centering",
            rf"\includegraphics[width=\linewidth,height={tree_h_frac}\textheight,keepaspectratio]{{tree.pdf}}{tree_cap_tex}",
            r"\end{minipage}\hfill",
            rf"\begin{{minipage}}[t]{{{grid_panel_frac:.3f}\linewidth}}\vspace{{0pt}}\centering",
            grid,
            r"\end{minipage}",
            r"\end{document}",
        ])
        (work / "sig.tex").write_text(tex, encoding="utf-8")
        proc = subprocess.run([pdflatex, "-interaction=nonstopmode", "-halt-on-error", "sig.tex"],
                              cwd=str(work), capture_output=True, text=True)
        if proc.returncode != 0 or not (work / "sig.pdf").exists():
            raise SignaturePageError(f"pdflatex failed composing the signature page:\n{proc.stdout[-1500:]}")
        shutil.copyfile(str(work / "sig.pdf"), str(out_pdf))
        return Path(out_pdf)
    finally:
        shutil.rmtree(work, ignore_errors=True)


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
        K.communicator.reset()  # singleton reused across sessions — clear stale writer so the connect-wait works
        server = await asyncio.start_unix_server(K.communicator.connected, socket_name)
        direct = None
        try:
            if app_bundle is not None:  # macOS GUI app — launch via `open` for an Aqua session
                opener = await asyncio.create_subprocess_exec("open", "-n", "-a", str(app_bundle), "--args", "--socket", socket_name, "--headless")
                await opener.wait()
            else:  # non-bundle / non-macOS build — launch directly
                direct = await asyncio.create_subprocess_exec(exe, "--socket", socket_name, "--headless")
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


def render_section_maps_via_kateri(chart, style_names: Sequence[str], out_dir, *, width: float = 800.0,
                                   viewport_size: float = 0.0,
                                   connect_timeout: float = 90.0, map_timeout: float = 60.0) -> list:
    """Render one antigenic-map PDF per named style in `chart`, in a single kateri
    session (chart sent once; `set_style`+`pdf` looped). `chart` is an
    `ae_backend.chart_v3.Chart` already carrying the section styles (built by
    `ae.tal.section_maps.build_section_styles`). Returns the PDF paths in order.

    This is the section<->map coupling's renderer: the per-section highlight/colour
    lives in each style, so one kateri session emits the whole map grid."""
    import asyncio

    exe = _require("kateri", "install kateri (github.com/drserajames/kateri) or pass pre-rendered maps via --map")
    try:
        import ae_backend  # noqa: F401  (chart already loaded by caller, but the socket layer needs the module)
        from ae.utils import kateri as K
    except ImportError as err:
        raise SignaturePageError(
            f"the kateri section-maps path needs ae_backend ({err}); run under the Python that can import it "
            "(arm64 python with PYTHONPATH=build)") from err

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    app_bundle = _kateri_app_bundle(exe)

    async def _run() -> list:
        socket_dir = tempfile.mkdtemp(prefix="kateri-sock-")
        socket_name = os.path.join(socket_dir, "kateri.sock")
        K.communicator.reset()  # singleton reused across sessions — clear stale writer so the connect-wait works
        server = await asyncio.start_unix_server(K.communicator.connected, socket_name)
        direct = None
        try:
            if app_bundle is not None:
                opener = await asyncio.create_subprocess_exec("open", "-n", "-a", str(app_bundle), "--args", "--socket", socket_name, "--headless")
                await opener.wait()
            else:
                direct = await asyncio.create_subprocess_exec(exe, "--socket", socket_name, "--headless")
            waited = 0.0
            while not K.communicator.is_connected():
                if waited >= connect_timeout:
                    raise SignaturePageError(f"kateri did not connect within {connect_timeout:.0f}s")
                await asyncio.sleep(0.1)
                waited += 0.1
            K.communicator.send_chart(chart)
            paths = []
            for i, name in enumerate(style_names):
                # Per-map timeout: kateri occasionally stalls mid-session; fail this render
                # fast (the report driver then moves on to the next lab) rather than hang.
                try:
                    pdf_bytes = await asyncio.wait_for(K.communicator.get_pdf(style=name, width=width, square=True, viewport_size=viewport_size or 0.0), timeout=map_timeout)
                except asyncio.TimeoutError:
                    raise SignaturePageError(f"kateri stalled rendering map {i} ({name}) after {map_timeout:.0f}s")
                out = out_dir / f"map-{i:02d}.pdf"
                out.write_bytes(pdf_bytes)
                paths.append(out)
            K.communicator.quit()
            return paths
        finally:
            server.close()
            if direct is not None and direct.returncode is None:
                direct.terminate()
            elif app_bundle is not None:
                # the GUI app was launched detached via `open`, so quit() may not reach a
                # stalled instance; kill the one bound to our (unique) socket so a lingering
                # window can't block the next render (the cascade that fails a driver run).
                subprocess.run(["pkill", "-f", socket_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            shutil.rmtree(socket_dir, ignore_errors=True)

    return asyncio.run(_run())


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


def _tal_program(tal_path) -> str:
    """The settings program to run for `tal_path`: `"tal"` for a single report `.tal`,
    `"tal-default"` for an AD settings stack (`tal -s a -s b …`), where `<sub>.sp.tal`'s
    — or acmacs-tal's builtin — `tal-default` is the entry point and reaches the tree
    `.tal`'s own `tal` program through `tal-modifications`."""
    return "tal" if isinstance(tal_path, (str, Path)) else "tal-default"


def _tal_to_settings(tal_path, tmpdir: Path, defines: Optional[dict] = None,
                     title: Optional[str] = None, show_legend: Optional[bool] = None,
                     drop_dash_bars: bool = False, clades_before_time_series: bool = False,
                     matches_chart_seq_ids: Optional[Sequence[str]] = None,
                     section_prefixes: Optional[dict] = None) -> tuple[str, Optional[int]]:
    """Translate an acmacs-tal settings-v3 `.tal` into a tal-draw settings file.
    Returns (settings_path, image_size_or_None). Mirrors the `--tal` handling in
    the tal-signature-page CLI so the tree panel is rendered from the same config
    AD uses, with sig-page overrides matching AD's `layout-with-maps`:

      * `title` / `show_legend` — title drawn top-left; no aa-at-pos legend;
      * `drop_dash_bars` — drop the aa `dash-bar-aa-at` colour-bar columns.
        **AD's sig page KEEPS them.** They come from the tree `.tal`'s own `tal` program,
        which AD's `tal-modifications` runs after the `<sub>.sp.tal` layout, and they are
        plainly there in every `sp/*.sp.pdf` reference — legend `135K/135A 145N/145G …`,
        drawn between the grey matches-chart bar and the hz-section brackets. The earlier
        "AD's sig page has no colour bar" reading came from rendering ae with only the tree
        `.tal`, which never reaches them.
        They are nonetheless still dropped here, because ae cannot yet PLACE them on a sig
        page: `cc/tal/draw-tree.cc`'s `clades_before_time_series` branch (the AD
        `layout-with-maps` column order) assigns `x_label0/x_clade0/x_ts0/x_grey0/x_hzmark0`
        but no `x_dash0`, so every dash bar renders at x=0, over the tree's left edge —
        while it does subtract `dash_w` from the tree width. Passing False today therefore
        produces a garbled page, not AD's. Closing this is a column slot in that branch
        (between the matrix and the grey bar); once it exists, pass False here;
      * `clades_before_time_series` — AD draws the clades column to the LEFT of the
        time-series matrix on the sig page (tree-only puts it right);
      * `matches_chart_seq_ids` — leaves whose antigen is in the chart, drawn as
        AD's grey `matches-chart-antigen` dash-bar.
    """
    from ae.tal.settings_v3 import load_tal

    # A settings STACK (AD's `tal -s a -s b …`) or a single `.tal`. On a stack the entry
    # program is `tal-default` — the one `sp/<sub>.sp.tal` defines, or, when that file is
    # `{}` (B/Vic, B/Yam), acmacs-tal's builtin one, hence `builtin_programs=True`.
    if isinstance(tal_path, (str, Path)):
        schema, warnings = load_tal(str(tal_path), defines or {})
    else:
        # A signature page always has a chart, and `$chart-present` is what steers AD's
        # builtin `layout` to `layout-with-maps` (tree + columns + maps) instead of
        # `layout-tree-only` — which is the branch a B/Vic page takes, `bvic.sp.tal` being
        # `{}`. Without it the page comes out with the tree-only column order and width.
        schema, warnings = load_tal([str(one) for one in tal_path],
                                    {"chart-present": True, **(defines or {})},
                                    builtin_programs=True)
    for warning in warnings:
        print(f"  [tal] {warning}", file=sys.stderr)
    if title is not None:
        schema["title"] = title
    if show_legend is not None:
        schema["legend"] = {"show": show_legend}
    if drop_dash_bars:
        # NB the old comment here claimed "AD's sig page has none". That is wrong: AD's
        # signature pages do draw the aa-at-position colour-bar columns, between the
        # time-series matrix and the hz-section markers. Dropping them was hiding a second
        # bug — `draw-tree.cc`'s clades_before_time_series branch never assigned `x_dash0`,
        # so had they been kept they would have drawn at x=0 over the tree. Both are fixed;
        # the flag stays for callers that genuinely want a bar-free tree.
        schema.pop("dash_bars", None)
    if clades_before_time_series:
        schema["clades_before_time_series"] = True
        schema["hz_section_labels"] = True  # draw section letters (A/B/C) on the right, like AD
    if matches_chart_seq_ids:
        schema["matches_chart_seq_ids"] = list(matches_chart_seq_ids)
    if section_prefixes and isinstance(schema.get("hz_sections"), list):
        for hs in schema["hz_sections"]:  # AD assigns A/B/C in tree order, not the .tal "L"
            if hs.get("first") in section_prefixes:
                hs["prefix"] = section_prefixes[hs["first"]]
    path = tmpdir / "tree-from-tal.json"
    path.write_text(json.dumps(schema), encoding="utf-8")
    size = int(schema["image_size"]) if "image_size" in schema else None
    return str(path), size


# The sig-map viewport is sourced from ae's own `-reset` style (see
# make_section_signature_page). AD framed each section map with the per-lab `sp.mapi`
# `loc:viewport` that `sp/0do` passes as its first `-s` file; `mapi=` (CLI `--mapi`) reads
# it via `section_maps.viewport_from_mapi`.
#
# Measured 2026-09-11 on this cycle, do NOT reach for `mapi=` to match AD: the `-reset`
# style ALREADY carries AD's zoom — its size is identical to sp.mapi's for every subtype
# (B/Vic 13, H1 15, H3 18) — and it is the only one of the two that is correct in ae's
# frame. sp.mapi's `abs` ORIGIN is in acmacs' own layout frame, so passing it through the
# kateri/ae style-viewport API lands the box several map units off (B/Vic +4.98/+3.23,
# H1 +6.44/+8.21, H3 +3.70/+4.66), pushing the cluster into a corner — the raw-vs-
# transformed frame mismatch of the port audit's §2. Rendered against the AD reference,
# `-reset` reproduces AD's framing (same zoom, same centring) and `mapi=` does not.
# `mapi=` therefore stays for a chart with no `-reset` style, and for verification crops.


def make_section_signature_page(tree, chart, tal, output, *, size: Optional[int] = None, map_width: float = 800.0,
                                viewport: Optional[Sequence[float]] = None, mapi: Optional[os.PathLike] = None,
                                page_title: Optional[str] = None,
                                tree_caption: Optional[str] = None, defines: Optional[dict] = None,
                                serum_circles: bool = False, serum_circle_fold: float = 2.0,
                                native: bool = True, keep_temp: bool = False) -> Path:
    """Build a faithful signature page: the TAL tree (rendered from `tal`) on the
    left, and on the right one antigenic map per *shown* hz-section of `tal`, each
    highlighting that section's antigens (coloured by date) and sera over a greyed
    base map — AD's section<->map coupling.

    Default (`native=True`): the fully-vector single-canvas compositor
    (:func:`make_section_signature_page_native`) — tree + section maps drawn as vectors
    onto ONE Cairo PDF page by ae's own renderers, no kateri, no pdfjam/pdflatex. Pass
    `native=False` to fall back to the legacy kateri section-maps + pdflatex/pdfjam grid
    (needs the `kateri` executable and a TeX install).

    `tree`/`chart` are file paths; `tal` is the acmacs-tal `.tal` settings holding the
    hz-sections and time-series window — a single file, or the whole AD settings **stack**
    as a list (`sp/0do`'s `-s` sequence: `<lab>/sp.mapi`, `<sub>.sp.tal`, `<sub><infix>.tal`,
    `sp.tal`, optionally `spc.tal`, `<page>.sp.tal`). `mapi` is a `sp.mapi` file whose
    `loc:viewport` frames every section map AD's way (overridden by an explicit `viewport`).
    Needs ae_backend (run under the arm64 Python with PYTHONPATH=build); the native path
    additionally needs the `tal-draw` binary built."""
    if viewport is None and mapi is not None:
        from ae.tal import section_maps as _SM
        viewport = _SM.viewport_from_mapi(mapi)
    if native:
        return make_section_signature_page_native(
            tree, chart, tal, output, size=size, map_width=map_width, viewport=viewport,
            page_title=page_title, tree_caption=tree_caption, defines=defines, serum_circles=serum_circles,
            serum_circle_fold=serum_circle_fold, keep_temp=keep_temp)
    import sys as _sys

    _sys.path.insert(0, str(REPO_ROOT / "build"))
    try:
        import ae_backend
    except ImportError as err:
        raise SignaturePageError(
            f"section signature pages need ae_backend ({err}); run under the arm64 Python with PYTHONPATH=build") from err
    from ae.tal import section_maps as SM

    tmpdir = Path(tempfile.mkdtemp(prefix="tal-sigsec-"))
    try:
        # The `.tal`'s own `hz-sections` when it still specifies them; otherwise AD's
        # fallback — sections derived from the tree's clade annotations via the `clades`
        # block (see SM.compute_sections). Every report `.tal` from 2026-0805-tc1 on takes
        # the fallback: they define `hz-sections` but no longer run the `hz` sub-program,
        # so every entry is "show": false and AD sections from `clades` instead.
        sections = SM.sections_for(tal, tree, program=_tal_program(tal))
        if not sections:
            raise SignaturePageError(
                f"no shown hz-sections in {tal} and no clade-derived sections from {tree}")
        window = SM.parse_time_series(tal)
        scale = SM.DateColorScale(*window) if window else None
        if scale is None:
            print("  [sigp] no time-series window in .tal; antigens won't be date-coloured", file=_sys.stderr)

        # Pass 1: a basic translation just to get draw-order leaf names from tal-draw
        # (matches the rendered tree's order; avoids the libc++-hardening trap of
        # Python tree-leaf iteration on 3.14).
        names_settings, tal_size = _tal_to_settings(tal, tmpdir, defines)
        chart_obj = ae_backend.chart_v3.Chart(str(chart))
        leaf_names = SM.leaf_names_from_taldraw(tree, names_settings, TAL_DRAW, tmpdir)
        match = SM.match_leaf_names(leaf_names, chart_obj)
        section_prefixes = SM.assign_prefixes(sections, match)  # A/B/C in tree order (AD set_prefix)
        reset_vp, available_styles = SM.report_styles_from_ace(chart)
        vaccine_marks = SM.vaccine_marks_from_ace(chart)
        # Framing (Sarah's decision, 2026-07-03): frame every section map with the SAME
        # viewport as the MAIN-REPORT clade maps — the chart's `-reset` style viewport — so a
        # sig-page map is centred/zoomed IDENTICALLY to that lab's main map. This is a
        # deliberate divergence from AD's sig framing, which used the per-lab sp.mapi
        # `loc:viewport` (off-centre from the cloud); we drop it for internal consistency
        # between the report's main maps and its signature-page maps.
        #   `reset_vp` = the chart's `-reset` V ([x, y, size, size]), read by
        # report_styles_from_ace above — the exact list the main clade maps carry as their
        # style viewport. build_section_styles stores it via `style.viewport(*vp)`, the same
        # call/mechanism the `-reset` style uses, so the sig style's viewport is byte-identical
        # to the main map's (no corner->centre conversion needed — the stored `-reset` V is
        # already in kateri's style-viewport convention). An explicit `viewport` arg overrides;
        # if a chart has no `-reset` style (not ae.report-styled) fall back to kateri auto-fit.
        vp = list(viewport) if viewport else (list(reset_vp) if reset_vp else None)
        print(f"  [sigp] viewport: {('explicit ' if viewport else 'main -reset ') + str([round(x, 2) for x in vp]) if vp else 'kateri auto-fit'}", file=_sys.stderr)
        styled = SM.build_section_styles(chart_obj, sections, match, scale, vp,
                                         available_styles=available_styles, vaccine_marks=vaccine_marks,
                                         serum_circles=serum_circles, serum_circle_fold=serum_circle_fold,
                                         spc_tal=tal)
        for s in styled:
            print(f"  [sigp] {s['name']}: {s['n_antigens']} antigens, {s['n_sera']} sera :: {s['title']}", file=_sys.stderr)

        # viewport_size=0: the explicit per-style viewport (above) frames each map, so kateri
        # must NOT also auto-fit/centre at a square size (that's what shifted the cluster).
        map_pdfs = render_section_maps_via_kateri(chart_obj, [s["name"] for s in styled], tmpdir / "maps",
                                                  width=map_width, viewport_size=0.0)

        # Pass 2: the final tree settings with AD sig-page overrides — title top-left,
        # no aa-at-pos legend, clades left of the matrix,
        # and the grey matches-chart-antigen dash-bar for leaves whose antigen is in the chart.
        matched_seq_ids = [leaf_names[i] for i in sorted(match.leaf_to_ag)]
        tree_settings, _ = _tal_to_settings(tal, tmpdir, defines, title=page_title, show_legend=False,
                                            drop_dash_bars=False, clades_before_time_series=True,
                                            matches_chart_seq_ids=matched_seq_ids, section_prefixes=section_prefixes)
        tree_pdf = render_tree_pdf(tree, tmpdir / "tree.pdf", size=size or tal_size or 1000, settings=tree_settings)

        # AD lays the section maps out 3 rows high -> columns = ceil(n / 3).
        # No captions (titles are inside each map), a black frame per map, sans text;
        # the page title is drawn by the tree (above), not the composite.
        columns = math.ceil(len(map_pdfs) / 3)
        # margin_mm=2 (vs the 6mm default): the composed page height is grid_h + 2*margin + 4,
        # while the available text height (=grid_h + 4) is INDEPENDENT of margin, so shrinking the
        # margin raises the tree's fill fraction of the page (tree height is locked to grid_h)
        # WITHOUT eating into the 4mm single-page spill guard. Closes most of the AD tree-height
        # gap (the residual is tal-draw's own canvas fill, owned by the tree subsystem).
        compose_grid(tree_pdf, map_pdfs, output, captions=None,
                     page_title=None, tree_caption=tree_caption, columns=columns, frame=True, sans=True,
                     auto_width=True, margin_mm=2.0)
        return Path(output)
    finally:
        if not keep_temp:
            shutil.rmtree(tmpdir, ignore_errors=True)


def make_signature_page(tree, output, *, maps: Sequence[os.PathLike] = (), chart=None, size: int = 1000,
                        settings: Optional[str] = None, mark: Optional[Sequence[str]] = None, mark_style: Optional[dict] = None,
                        mark_vaccines: Optional[str] = None, vaccines_file=None,
                        mark_reference: Optional[str] = None, hidb_dir=None, reference_tables: int = 20,
                        style: str = "-", map_width: float = 800.0, tal_draw_args: Sequence[str] = (), frame: bool = False,
                        captions: Optional[Sequence[str]] = None, page_title: Optional[str] = None,
                        tree_caption: Optional[str] = None, columns: Optional[int] = None,
                        keep_temp: bool = False) -> Path:
    """Render the tree, obtain the map(s), and compose them into `output`.

    The composition uses the captioned grid layout (`compose_grid`, via pdflatex) when any of
    `captions`/`page_title`/`tree_caption`/`columns` is given; otherwise the plain side-by-side
    stack (`compose_side_by_side`, via pdfjam).
    """
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
        if captions or page_title or tree_caption or columns:
            compose_grid(tree_pdf, map_pdfs, output, captions=captions, page_title=page_title,
                         tree_caption=tree_caption, columns=columns)
        else:
            compose_side_by_side(tree_pdf, map_pdfs, output, frame=frame)
        return Path(output)
    finally:
        if not keep_temp:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ======================================================================
# Fully-vector single-canvas signature page (sigp-vector): native map + tree
# rendered as VECTORS onto ONE Cairo PDF page — no PNG tiles, no kateri, no pdfjam.
# ======================================================================
#
# The kateri/pdfjam form above renders the section maps with kateri and stitches the
# tree + map PDFs with pdflatex/pdfjam. A prior prototype painted per-renderer PNG
# tiles onto one Cairo page. This form draws BOTH halves as vectors onto one shared
# cairo_pdf_surface: the section maps via ae's native `export_styled_map_into` and the
# tree via `export_tree_into`, each targeting a computed device sub-rectangle of the
# page (`ae_backend.tal.SigPageCanvas`). No raster tiles, no pdfjam/pdflatex, no kateri.
# See cc/tal/SIG-PAGE-COMPOSITOR.md.

_MM2PT = 72.0 / 25.4  # PDF points per millimetre (the compositor works in PDF points)
_CAPTION_FONT_PT = 8.0  # tree caption: \footnotesize of compose_grid's 10pt article class


def _sig_page_layout(n_maps: int, tree_aspect: float, *, margin_mm: float = 2.0,
                     paper_h_mm: float = 210.0) -> tuple[float, float, tuple, list]:
    """Auto-width signature-page geometry (a device-space port of `compose_grid`'s
    ``auto_width`` branch). Returns ``(page_w_mm, page_h_mm, tree_rect_mm, cell_rects_mm)``
    with every rect ``(x, y, w, h)`` in mm from the page top-left. The maps fill a
    ``rows x cols`` grid **row-major** — left to right, then down (``cols = ceil(n / 3)``,
    AD lays the maps 3 rows high) — which is `compose_grid`'s fill order: its auto_width
    branch builds row *r* from ``range(r * cols, (r + 1) * cols)``. Cells are sized so the
    grid (and the tree) are ``grid_h`` tall and the page width grows with the column count."""
    cols = max(1, math.ceil(n_maps / 3))            # AD lays the maps 3 rows high
    rows = math.ceil(n_maps / cols) if n_maps else 1
    avail_h = paper_h_mm - 2.0 * margin_mm - 10.0
    row_gap, col_gap, panel_gap = 1.5, 2.0, 5.0
    cell = max(20.0, avail_h / rows - 1.5)
    grid_h = rows * cell + (rows - 1) * row_gap
    tree_w = tree_aspect * grid_h
    grid_w = cols * cell + (cols - 1) * col_gap
    # Round the PAGE to whole mm, exactly as compose_grid emits the LaTeX paper size
    # (`paperwidth={paper_w:.0f}mm,paperheight={paper_h:.0f}mm`). The tree/cell rects keep
    # their exact fractional-mm positions (LaTeX likewise places content by fractions inside
    # the rounded paper). Matching the paper size to the mm makes the page ASPECT — and hence
    # the scale pdfpages applies when it fits the sig page onto the report's A4 pages — identical
    # to the LaTeX baseline, so composited text lands at the same absolute size in the report.
    page_w = round(2.0 * margin_mm + tree_w + panel_gap + grid_w)
    page_h = round(grid_h + 2.0 * margin_mm + 4.0)   # +4 = single-page spill guard (matches compose_grid)
    tree_rect = (margin_mm, margin_mm, tree_w, grid_h)
    grid_left = margin_mm + tree_w + panel_gap
    cells = []
    for i in range(n_maps):
        r, c = divmod(i, cols)                       # row-major = compose_grid's row r = range(r*cols, (r+1)*cols)
        cells.append((grid_left + c * (cell + col_gap), margin_mm + r * (cell + row_gap), cell, cell))
    return page_w, page_h, tree_rect, cells


def make_section_signature_page_native(tree, chart, tal, output, *, size: Optional[int] = None,
                                       map_width: float = 800.0,
                                       viewport: Optional[Sequence[float]] = None,
                                       mapi: Optional[os.PathLike] = None,
                                       page_title: Optional[str] = None, tree_caption: Optional[str] = None,
                                       defines: Optional[dict] = None,
                                       serum_circles: bool = False, serum_circle_fold: float = 2.0,
                                       keep_temp: bool = False) -> Path:
    """Fully-vector single-canvas form of :func:`make_section_signature_page`: identical
    section<->map coupling, but the section maps AND the tree are drawn as vectors onto ONE
    Cairo PDF page (``ae_backend.tal.SigPageCanvas``) — the maps via ae's native styled
    renderer (no kateri) and the tree via the native tree renderer (no separate tal-draw
    PDF, no pdfjam/pdflatex). Produces the same page layout (tree left, ``ceil(n/3)``-column
    map grid right, per-map frame, optional ``tree_caption`` under the tree). Needs ae_backend
    on PYTHONPATH and the ``tal-draw`` binary."""
    import sys as _sys

    _sys.path.insert(0, str(REPO_ROOT / "build"))
    try:
        import ae_backend
    except ImportError as err:
        raise SignaturePageError(
            f"native signature pages need ae_backend ({err}); run under the arm64 Python with PYTHONPATH=build") from err
    if not hasattr(ae_backend.tal, "SigPageCanvas"):
        raise SignaturePageError("ae_backend.tal.SigPageCanvas missing — rebuild ae (cc/tal/sig-page.cc + meson)")
    from ae.tal import section_maps as SM

    if viewport is None and mapi is not None:
        viewport = SM.viewport_from_mapi(mapi)

    tmpdir = Path(tempfile.mkdtemp(prefix="tal-sigsec-vec-"))
    try:
        # The `.tal`'s own `hz-sections` when it still specifies them; otherwise AD's
        # fallback — sections derived from the tree's clade annotations via the `clades`
        # block (see SM.compute_sections). Every report `.tal` from 2026-0805-tc1 on takes
        # the fallback: they define `hz-sections` but no longer run the `hz` sub-program,
        # so every entry is "show": false and AD sections from `clades` instead.
        sections = SM.sections_for(tal, tree, program=_tal_program(tal))
        if not sections:
            raise SignaturePageError(
                f"no shown hz-sections in {tal} and no clade-derived sections from {tree}")
        window = SM.parse_time_series(tal)
        scale = SM.DateColorScale(*window) if window else None
        if scale is None:
            print("  [sigp] no time-series window in .tal; antigens won't be date-coloured", file=_sys.stderr)

        # Pass 1: draw-order leaf names (matches the rendered tree order) + section prefixes.
        names_settings, tal_size = _tal_to_settings(tal, tmpdir, defines)
        chart_obj = ae_backend.chart_v3.Chart(str(chart))
        leaf_names = SM.leaf_names_from_taldraw(tree, names_settings, TAL_DRAW, tmpdir)
        match = SM.match_leaf_names(leaf_names, chart_obj)
        section_prefixes = SM.assign_prefixes(sections, match)  # A/B/C in tree order
        reset_vp, available_styles = SM.report_styles_from_ace(chart)
        vaccine_marks = SM.vaccine_marks_from_ace(chart)
        vp = list(viewport) if viewport else (list(reset_vp) if reset_vp else None)
        print(f"  [sigp] viewport: {('explicit ' if viewport else 'main -reset ') + str([round(x, 2) for x in vp]) if vp else 'native auto-fit'}", file=_sys.stderr)
        styled = SM.build_section_styles(chart_obj, sections, match, scale, vp,
                                         available_styles=available_styles, vaccine_marks=vaccine_marks,
                                         serum_circles=serum_circles, serum_circle_fold=serum_circle_fold,
                                         spc_tal=tal)
        for s in styled:
            print(f"  [sigp] {s['name']}: {s['n_antigens']} antigens, {s['n_sera']} sera :: {s['title']}", file=_sys.stderr)

        # Write the chart carrying the section styles once; SigPageCanvas.render_maps loads it once
        # and renders every section style into its cell as a vector (the kateri replacement — the
        # section<->map coupling lives entirely in the styles).
        styled_ace = tmpdir / "sig-styled.ace"
        chart_obj.write(str(styled_ace))

        # Pass 2: final tree settings with AD sig-page overrides (title top-left, no aa-at-pos
        # legend, clades left of the matrix, grey matches-chart dash-bar). The tree page aspect = its width_to_height_ratio (draw-tree.cc) — read it
        # from the settings to size the tree panel BEFORE rendering (no probe render needed).
        matched_seq_ids = [leaf_names[i] for i in sorted(match.leaf_to_ag)]
        tree_settings, _ = _tal_to_settings(tal, tmpdir, defines, title=page_title, show_legend=False,
                                            drop_dash_bars=False, clades_before_time_series=True,
                                            matches_chart_seq_ids=matched_seq_ids, section_prefixes=section_prefixes)
        tree_schema = json.loads(Path(tree_settings).read_text())
        tree_aspect = float(tree_schema.get("width_to_height_ratio", 1.0)) or 1.0

        # Geometry (mm), matching compose_grid auto_width (margin 2 mm); rects → PDF points.
        page_w_mm, page_h_mm, tree_rect, cells = _sig_page_layout(len(styled), tree_aspect, margin_mm=2.0)
        page_w_pt, page_h_pt = page_w_mm * _MM2PT, page_h_mm * _MM2PT
        tx, ty, tw, th = (v * _MM2PT for v in tree_rect)

        canvas = ae_backend.tal.SigPageCanvas(str(output), page_w_pt, page_h_pt)
        # Section maps: one job per style, framed, in device points; `cells` are already in
        # compose_grid's row-major fill order (left to right, then down) — see _sig_page_layout.
        jobs = [(styled[i]["name"], cells[i][0] * _MM2PT, cells[i][1] * _MM2PT,
                 cells[i][2] * _MM2PT, cells[i][3] * _MM2PT, True) for i in range(len(styled))]
        canvas.render_maps(str(styled_ace), 0, float(map_width), jobs)
        # Tree: render at the SAME internal image_size the pdfjam/LaTeX baseline uses
        # (`size or tal_size or 1000`, exactly compose_grid's tree render size) and let
        # export_tree_into letterbox-scale it into the panel — reproducing LaTeX's
        # `keepaspectratio` cell fit. The tree renderer clamps fonts/line widths to ABSOLUTE
        # device bounds (draw-tree.cc: font_size clamp [3,14], line_width clamp [0.2,3],
        # title_fs clamp [8,26], …), so it does NOT scale linearly with image_size: rendering
        # at the small panel height (~th) and placing it 1:1 makes those clamped glyphs/lines
        # proportionally LARGER than the baseline (which renders at 1000 and optically scales
        # DOWN), drifting text size AND label spacing vs report/addendum-4.pdf. Vector content
        # scales losslessly, so letterboxing the 1000-render introduces no blur. Because the
        # tree page aspect == width_to_height_ratio == the panel aspect (tw = tree_aspect*grid_h),
        # the fit scale is th/image_size in both axes → the tree still fills the panel exactly.
        canvas.render_tree(str(tree), tree_settings, float(size or tal_size or 1000), tx, ty, tw, th)
        if tree_caption:
            # compose_grid puts the caption directly under the tree image, \centering and
            # \footnotesize (8pt in the 10pt article class), in Helvetica (sans=True). The native
            # page has the same vertical structure — the tree fills the panel and everything below
            # it is compose_grid's spill guard (~6mm, the band the LaTeX caption line occupies) —
            # so centre the caption in that band. It needs no layout change: as in compose_grid the
            # tree is height-bounded to grid_h whether or not a caption is present.
            canvas.draw_caption(tree_caption, tx, ty + th, tw, page_h_pt - (ty + th), _CAPTION_FONT_PT)
        canvas.finish()
        return Path(output)
    finally:
        if not keep_temp:
            shutil.rmtree(tmpdir, ignore_errors=True)
