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


def compose_grid(tree_pdf, map_pdfs: Sequence[os.PathLike], out_pdf, *, captions: Optional[Sequence[str]] = None,
                 page_title: Optional[str] = None, tree_caption: Optional[str] = None, columns: Optional[int] = None,
                 paper_mm: tuple = (297.0, 210.0), margin_mm: float = 6.0, frame: bool = False, sans: bool = False) -> Path:
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
    # Size each map cell to fit BOTH the right panel's width (cols across) and the
    # printable height (rows down, leaving room for a caption+gap per row and the
    # optional page title) so the whole figure stays on one page.
    right_panel_mm = 0.48 * (paper_w - 2.0 * margin_mm)
    title_mm = 9.0 if page_title else 0.0
    # height available for the panels, with a safety margin so the row never spills
    # to a 2nd page (the taller of tree/grid sets the row height)
    avail_h = paper_h - 2.0 * margin_mm - title_mm - 6.0
    cell_by_w = right_panel_mm / cols - 3.0
    # per-row overhead: caption line (if any) + vertical gap; less when unframed/untitled
    row_overhead = 7.0 if any(caps) else 3.0
    cell_by_h = avail_h / rows - row_overhead
    cell_mm = max(10.0, min(cell_by_w, cell_by_h))
    tree_h_frac = round(avail_h / (paper_h - 2.0 * margin_mm), 3)

    work = Path(tempfile.mkdtemp(prefix="tal-grid-"))
    try:
        shutil.copyfile(str(tree_pdf), str(work / "tree.pdf"))
        for i, m in enumerate(maps):
            shutil.copyfile(m, str(work / f"map{i}.pdf"))

        def boxed(i: int) -> str:
            img = rf"\includegraphics[width=\linewidth]{{map{i}.pdf}}"
            # AD draws a thin black border around each map; kateri draws none, so frame here.
            return rf"\setlength{{\fboxsep}}{{0pt}}\setlength{{\fboxrule}}{{0.5pt}}\fbox{{{img}}}" if frame else img

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
            rf"\usepackage[paperwidth={paper_w:.0f}mm,paperheight={paper_h:.0f}mm,margin={margin_mm:.0f}mm]{{geometry}}",
            r"\usepackage{graphicx}",
            (r"\usepackage{helvet}\renewcommand{\familydefault}{\sfdefault}" if sans else "%"),
            r"\setlength{\parindent}{0pt}\pagestyle{empty}",
            r"\begin{document}",
            title_tex + r"\noindent",
            r"\begin{minipage}[t]{0.5\linewidth}\vspace{0pt}\centering",
            rf"\includegraphics[width=\linewidth,height={tree_h_frac}\textheight,keepaspectratio]{{tree.pdf}}{tree_cap_tex}",
            r"\end{minipage}\hfill",
            r"\begin{minipage}[t]{0.48\linewidth}\vspace{0pt}\centering",
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


def render_section_maps_via_kateri(chart, style_names: Sequence[str], out_dir, *, width: float = 800.0,
                                   connect_timeout: float = 90.0) -> list:
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
        server = await asyncio.start_unix_server(K.communicator.connected, socket_name)
        direct = None
        try:
            if app_bundle is not None:
                opener = await asyncio.create_subprocess_exec("open", "-n", "-a", str(app_bundle), "--args", "--socket", socket_name)
                await opener.wait()
            else:
                direct = await asyncio.create_subprocess_exec(exe, "--socket", socket_name)
            waited = 0.0
            while not K.communicator.is_connected():
                if waited >= connect_timeout:
                    raise SignaturePageError(f"kateri did not connect within {connect_timeout:.0f}s")
                await asyncio.sleep(0.1)
                waited += 0.1
            K.communicator.send_chart(chart)
            paths = []
            for i, name in enumerate(style_names):
                pdf_bytes = await K.communicator.get_pdf(style=name, width=width)
                out = out_dir / f"map-{i:02d}.pdf"
                out.write_bytes(pdf_bytes)
                paths.append(out)
            K.communicator.quit()
            return paths
        finally:
            server.close()
            if direct is not None and direct.returncode is None:
                direct.terminate()
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
      * `drop_dash_bars` — AD's sig page disables the aa `dash-bar-aa-at` columns
        (the `155E/156N…` colour bar), so drop them;
      * `clades_before_time_series` — AD draws the clades column to the LEFT of the
        time-series matrix on the sig page (tree-only puts it right);
      * `matches_chart_seq_ids` — leaves whose antigen is in the chart, drawn as
        AD's grey `matches-chart-antigen` dash-bar.
    """
    from ae.tal.settings_v3 import load_tal

    schema, warnings = load_tal(str(tal_path), defines or {})
    for warning in warnings:
        print(f"  [tal] {warning}", file=sys.stderr)
    if title is not None:
        schema["title"] = title
    if show_legend is not None:
        schema["legend"] = {"show": show_legend}
    if drop_dash_bars:
        schema.pop("dash_bars", None)  # remove the aa colour bar (AD's sig page has none)
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


def make_section_signature_page(tree, chart, tal, output, *, size: Optional[int] = None, map_width: float = 800.0,
                                viewport: Optional[Sequence[float]] = None, page_title: Optional[str] = None,
                                tree_caption: Optional[str] = None, defines: Optional[dict] = None,
                                serum_circles: bool = False, serum_circle_fold: float = 2.0,
                                keep_temp: bool = False) -> Path:
    """Build a faithful signature page: the TAL tree (rendered from `tal`) on the
    left, and on the right one antigenic map per *shown* hz-section of `tal`, each
    highlighting that section's antigens (coloured by date) and sera over a greyed
    base map — AD's section<->map coupling, reproduced via kateri + a PDF grid.

    `tree`/`chart` are file paths; `tal` is the acmacs-tal `.tal` settings holding
    the hz-sections and time-series window. Needs ae_backend (run under the arm64
    Python with PYTHONPATH=build) and the kateri executable on PATH."""
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
        sections = SM.parse_sections(tal)
        if not sections:
            raise SignaturePageError(f"no shown hz-sections found in {tal}")
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
        vp = list(viewport) if viewport else (reset_vp or SM.viewport_from_layout(chart_obj))
        styled = SM.build_section_styles(chart_obj, sections, match, scale, vp,
                                         available_styles=available_styles, vaccine_marks=vaccine_marks,
                                         serum_circles=serum_circles, serum_circle_fold=serum_circle_fold)
        for s in styled:
            print(f"  [sigp] {s['name']}: {s['n_antigens']} antigens, {s['n_sera']} sera :: {s['title']}", file=_sys.stderr)

        map_pdfs = render_section_maps_via_kateri(chart_obj, [s["name"] for s in styled], tmpdir / "maps", width=map_width)

        # Pass 2: the final tree settings with AD sig-page overrides — title top-left,
        # no aa-at-pos legend, no aa colour-bar dash columns, clades left of the matrix,
        # and the grey matches-chart-antigen dash-bar for leaves whose antigen is in the chart.
        matched_seq_ids = [leaf_names[i] for i in sorted(match.leaf_to_ag)]
        tree_settings, _ = _tal_to_settings(tal, tmpdir, defines, title=page_title, show_legend=False,
                                            drop_dash_bars=True, clades_before_time_series=True,
                                            matches_chart_seq_ids=matched_seq_ids, section_prefixes=section_prefixes)
        tree_pdf = render_tree_pdf(tree, tmpdir / "tree.pdf", size=size or tal_size or 1000, settings=tree_settings)

        # AD lays the section maps out 3 rows high -> columns = ceil(n / 3).
        # No captions (titles are inside each map), a black frame per map, sans text;
        # the page title is drawn by the tree (above), not the composite.
        columns = math.ceil(len(map_pdfs) / 3)
        compose_grid(tree_pdf, map_pdfs, output, captions=None,
                     page_title=None, tree_caption=tree_caption, columns=columns, frame=True, sans=True)
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
