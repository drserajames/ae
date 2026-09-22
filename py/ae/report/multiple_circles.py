"""Multiple-serum-circles map figures — ae-native replacement for Racmacs' multiple-serum-circles.Rmd.

Per lab this builds, from a pre-styled `styled.ace`, the three PDFs the report's
multiple-serum-circles addenda consume:

  * ``plain.pdf``                       — the by-clade map + title, selected sera restyled,
                                          no circles;
  * ``multiple-serum-circles.pdf``      — adds one theoretical serum circle per selected
                                          serum, each filled with that serum's homologous-
                                          antigen clade colour at ~20% alpha (Racmacs t_col 80);
  * ``multiple-serum-circles-names.pdf`` — the circles map with a small top-left text list of
                                          the circled sera (overlaid via pdflatex).

It works for every subtype: the by-clade front style the report embeds is named per subtype
(H3 ``clades-v10``, H1 ``clades``, B/Vic ``clades-v2``) and is given per lab as
``LabConfig.clade_style``, or auto-detected when the chart carries exactly one
``clades`` / ``clades-vN`` front style. Everything subtype-specific is derived from that one
style: the per-antigen fills colouring the circles, the background references reproducing
the map (its own ``A`` parents minus ``-vaccines*``), the viewport (its resolved ``-reset``
frame — the frame the serum-coverage ``sc-*`` maps use, so the circle maps have the same
zoom as those and as each other, rather than a frame fitted to each lab's circles), and its
clade legend with counts. A clade style, or a ``-clades*`` reference, missing from the chart raises rather
than silently rendering every serum grey.

The map itself is rendered by the **native headless renderer**
(``ae_backend.map_draw.export_styled_map`` / ``export_styled_maps``) — no kateri process, no
socket, Linux-capable — mirroring ``ae.report.map_renderer.NativeRenderer``. The clade
colouring is resolved natively from the chart's own clade **semantic** style
(``c["R"]``) — no dependency on a kateri-baked legacy plot spec — so the antigen colours match
the report's main maps exactly. Serum circles use ae's
``projection().serum_circles(fold)`` theoretical radius — identical to the Rmd's
``2 + max(logtiter[,sr]) - logtiter[homologous_ag, sr]`` for ``fold=2.0``.

The curated per-lab serum selection lives in the report-dir driver (gen-multiple-circles-ae.py),
mirroring the addendum-serum-coverage by-clade config — not greps in this engine.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

import ae_backend
import ae_backend.chart_v3 as cv

from ae import semantic
from . import map_renderer

# ----------------------------------------------------------------------
# Style names built on the chart (background "-mc-*", front "mc-*").

MARK_STYLE = "-mc-mark"
CIRCLES_STYLE = "-mc-circles"
PLAIN_FRONT = "mc-plain"
CIRCLES_FRONT = "mc-circles"

VIEWPORT_STYLE = "-mc-viewport"      # viewport-only style, referenced LAST so an override wins

# The report's by-clade front style: `clades` (H1), `clades-v2` (B/Vic), `clades-v10` (H3), ...
CLADE_FRONT_RE = re.compile(r"^clades(-v\d+)?$")
# Its references carrying the enlarged/labelled vaccine markers, which the Racmacs
# multiple-circles figures do not plot: dropped from the background references.
VACCINES_REF_RE = re.compile(r"^-vaccines")
# Its clade-colouring background reference (`-clades`, `-clades-v10`, ...): must exist.
CLADES_REF_RE = re.compile(r"^-clades(-v\d+)?$")

GREY = "#808080"

TITLE_STYLE = {"offset": [19.0, 12.0], "origin": "tl", "size": 25, "weight": "bold",
               "slant": "normal", "face": "helvetica", "color": "black", "interline": 0.2}


@dataclass
class SerumPick:
    """One curated serum: matched in the chart by a designation substring (and optional
    0-based occurrence when several sera share it). The homologous antigen, circle radius
    and clade colour are derived automatically by ae."""
    match: str
    occurrence: int = 0
    # filled in by resolve():
    serum_no: int = -1
    homologous_no: int = -1
    radius: Optional[float] = None
    color: Optional[str] = None
    designation: str = ""
    label: str = ""                    # designation + passage, for the -names list


@dataclass
class LabConfig:
    """Per-lab configuration for the multiple-serum-circles figures (any subtype): the lab
    directory, title, the curated `SerumPick`s, the report's by-clade front style, an optional
    viewport override, the legend switch, the circle fold, and marker sizing.

    `clade_style` is the front style name the report embeds for this lab (``"clades"`` for H1,
    ``"clades-v2"`` for B/Vic, ``"clades-v10"`` for H3). None auto-detects it, which only works
    when the chart has exactly one ``clades`` / ``clades-vN`` front style; B/Vic and H3 carry
    several versions, so for those it must be given.

    `viewport` None (the default) draws in the clade style's own resolved frame (its ``-reset``
    ``V``) — the frame the serum-coverage ``sc-*`` maps use, so all these maps share one zoom
    (which is also the report by-clade map's). Keep it unless there is a reason not to: a
    per-lab override breaks that. An explicit value overrides it, in
    the ``-reset`` convention: ``[x, y, width]`` (or ``[x, y, width, height]``) where ``x, y`` is
    the top-left ORIGIN of kateri's recentred frame (y down), NOT a map-space centre. Use
    `viewport_from_centre` to convert a map-space centre and width."""
    labdir: str
    title: str
    sera: list[SerumPick]
    clade_style: Optional[str] = None
    viewport: Optional[Sequence[float]] = None
    legend: bool = True                # the clade style's legend (with its counter); False hides it
    fold: float = 2.0
    serum_size: float = 26.0           # selected-serum point size (tuned vs Racmacs srSize 8)
    serum_outline_width: float = 3.0
    circle_outline_width: float = 1.0
    circle_fill_alpha: int = 0x33      # ~20% opaque == Racmacs t_col(col, percent=80)
    names: bool = True


# ----------------------------------------------------------------------

def chart_styles(chart: cv.Chart) -> dict:
    """The chart's semantic styles ``c["R"]`` as JSON. Read this way rather than through
    ``chart.styles()[name]``, which silently ADDS a missing style."""
    return json.loads(chart.export())["c"].get("R", {})


def select_clade_style(styles: dict, requested: Optional[str] = None) -> str:
    """The by-clade front style to reproduce: `requested` if given (it must exist), else the
    chart's single ``^clades(-v\\d+)?$`` front style. Raises naming the candidates otherwise —
    guessing between e.g. B/Vic's ``clades-v1`` .. ``clades-v4`` would be silently wrong."""
    candidates = sorted(name for name in styles if CLADE_FRONT_RE.match(name))
    if requested is not None:
        if requested not in styles:
            raise ValueError(f"clade style {requested!r} not on the chart (clade front styles: {candidates})")
        return requested
    if len(candidates) != 1:
        raise ValueError(f"cannot auto-detect the clade style: {len(candidates)} candidates {candidates}; "
                         f"set LabConfig.clade_style")
    return candidates[0]


def clade_background_references(styles: dict, clade_style: str) -> list[str]:
    """The clade front style's own ``A`` parent references, in order, minus ``-vaccines*``:
    the bare by-clade map (``-reset``, ``-clades…``, ``-new-2``, ``-new-1`` in the report).
    Raises if it has no ``-clades*`` reference or that reference is not on the chart.
    Other undefined references (``-new-1`` on a chart with no previous) are kept, tolerated by
    the renderer exactly as in the report's own map."""
    refs = [m["R"] for m in styles[clade_style].get("A", []) if "R" in m]
    clade_refs = [ref for ref in refs if CLADES_REF_RE.match(ref)]
    if not clade_refs:
        raise ValueError(f"clade style {clade_style!r} has no -clades* reference (references: {refs})")
    if missing := [ref for ref in clade_refs if ref not in styles]:
        raise ValueError(f"clade style {clade_style!r} references {missing}, not on the chart")
    return [ref for ref in refs if not VACCINES_REF_RE.match(ref)]


def resolved_viewport(styles: dict, name: str) -> Optional[list[float]]:
    """The viewport style `name` renders with: last-writer-wins over the same traversal as the
    native renderer's ``resolve()`` (cc/map-draw/styled-draw.cc) — the style's own ``V``, then
    each ``{R: parent}`` reference in order, recursively. None if nothing sets one."""
    viewport = None

    def walk(style_name: str, depth: int) -> None:
        nonlocal viewport
        style = styles.get(style_name)
        if style is None or depth > 32:
            return
        if (v := style.get("V")) is not None:
            viewport = list(v)
        for m in style.get("A", []):
            if "R" in m:
                walk(m["R"], depth + 1)

    walk(name, 0)
    return viewport


def viewport_from_centre(chart: cv.Chart, centre_x: float, centre_y: float, width: float,
                         height: Optional[float] = None) -> list[float]:
    """Convert a map-space centre + width (in the projection's transformed frame, as drawn)
    into the ``-reset`` convention `LabConfig.viewport` takes: the recentred-frame origin
    ``[x, y, width, height]`` (styled-draw.cc §2.2), origin = world_origin + roundedSize/2 −
    hull_centre with roundedSize = ceil(hull_extent + 1) per axis."""
    height = width if height is None else height
    c = json.loads(chart.export())["c"]
    proj = c["P"][0]
    a, b, cc, d = proj.get("t", [1, 0, 0, 1])[:4]
    pts = [(p[0] * a + p[1] * cc, p[0] * b + p[1] * d) for p in proj["l"] if len(p) == 2]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    ox = (centre_x - width / 2) - (min(xs) + max(xs)) / 2 + math.ceil(max(xs) - min(xs) + 1) / 2
    oy = (centre_y - height / 2) - (min(ys) + max(ys)) / 2 + math.ceil(max(ys) - min(ys) + 1) / 2
    return [ox, oy, width, height]


def legacy_fills(ace_path: Path, clade_style: str) -> dict[int, str]:
    """antigen index -> rendered fill hex for `clade_style`, i.e. the Rmd's ``agFill``.

    Resolved natively from the chart's SEMANTIC styles (``c["R"]``) via
    ``Chart.semantic_style_to_legacy`` — the in-process reproduction of kateri's ``setFrom``.
    Previously this read a pre-baked legacy plot spec (``c["p"]``) that only kateri could produce
    (so the report had to launch kateri in ``prestyle`` to bake it); resolving ``c["R"]`` here
    removes that dependency. Verified byte-equal to the old ``c["p"]`` fills across the report's
    charts (0 diffs)."""
    chart = cv.Chart(str(ace_path))
    chart.semantic_style_to_legacy(clade_style)
    data = json.loads(chart.export())["c"]
    p = data.get("p", {})
    idx = p.get("p", [])
    palette = p.get("P", [])
    fills: dict[int, str] = {}
    for ag_no in range(len(data.get("a", []))):
        if ag_no < len(idx) and idx[ag_no] < len(palette):
            if (fill := palette[idx[ag_no]].get("F")):
                fills[ag_no] = fill
    if not fills:
        raise RuntimeError(f"{ace_path}: clade style {clade_style!r} resolved no antigen fills")
    return fills


def resolve_sera(chart: cv.Chart, picks: list[SerumPick], fills: dict[int, str], fold: float) -> list[SerumPick]:
    """Match each pick to a serum, derive its homologous antigen + theoretical circle radius
    + clade colour. Picks that don't match / have no theoretical circle are dropped (warned)."""
    # serum_no -> (radius, homologous antigen no) from ae's theoretical serum circles
    circles: dict[int, tuple[float, int]] = {}
    for cd in chart.projection().serum_circles(fold=fold):
        radius = cd.theoretical()
        if radius is None:
            continue
        homol = next((ag.antigen_no for ag in cd if ag.theoretical is not None), -1)
        circles[cd.serum_no] = (radius, homol)

    designations = [(no, chart.serum(no).designation()) for no, _ in chart.select_all_sera()]
    resolved: list[SerumPick] = []
    for pick in picks:
        needle = pick.match.upper()
        hits = [no for no, des in designations if needle in des.upper()]
        if len(hits) <= pick.occurrence:
            print(f">> multiple_circles: no serum #{pick.occurrence} matching {pick.match!r} "
                  f"(found {len(hits)})", file=sys.stderr)
            continue
        serum_no = hits[pick.occurrence]
        if serum_no not in circles:
            print(f">> multiple_circles: serum {serum_no} {pick.match!r} has no theoretical circle "
                  f"— skipped", file=sys.stderr)
            continue
        radius, homol = circles[serum_no]
        pick.serum_no = serum_no
        pick.homologous_no = homol
        pick.radius = radius
        if (fill := fills.get(homol)) is None:
            print(f">> multiple_circles: WARNING serum {serum_no} {pick.match!r}: homologous antigen {homol} "
                  f"has no clade fill — drawn {GREY}", file=sys.stderr)
            fill = GREY
        pick.color = fill
        serum = chart.serum(serum_no)
        pick.designation = serum.designation()
        # Racmacs sr_names = paste(srNames, srIDs, srPassage): designation already carries
        # name + serum_id; append the passage to complete the -names list line.
        pick.label = f"{pick.designation} {serum.passage()}".strip()
        resolved.append(pick)
        print(f">> multiple_circles: SR {serum_no:3d} {pick.designation:48s} "
              f"homol AG {homol} r={radius:.3f} fill={pick.color}", file=sys.stderr)
    return resolved


def build_styles(chart: cv.Chart, cfg: LabConfig, sera: list[SerumPick], *, clade_style: str,
                 styles: dict) -> None:
    """Build the `-mc-mark` / `-mc-circles` background styles and the `mc-plain` / `mc-circles`
    front styles on the chart, ready for the native renderer's style selection.

    The front styles reference `clade_style`'s background references (minus ``-vaccines*``)
    then the mark (+circles) styles, and take its legend settings. `styles` is the chart's
    ``c["R"]`` as read before any ``mc-*`` style was added (`chart_styles`). No viewport is set
    unless `cfg.viewport` overrides the inherited ``-reset`` frame; the override goes in a
    viewport-only style referenced LAST, because the renderer's viewport is last-writer-wins
    across the traversal and the front style's own ``V`` is read before its parents'."""
    base_references = clade_background_references(styles, clade_style)
    legend_json = styles[clade_style].get("L", {})
    if cfg.viewport is not None:
        chart.styles()[VIEWPORT_STYLE].viewport(*cfg.viewport)

    # Background: restyle the selected sera (black fill, clade outline, fat outline, enlarged).
    mark = chart.styles()[MARK_STYLE]
    mark.priority = 500
    for pick in sera:
        mark.add_modifier(selector={"!i": pick.serum_no}, only="sera", fill="black",
                          outline=pick.color, outline_width=cfg.serum_outline_width,
                          size=cfg.serum_size, raise_=True)

    # Background: one theoretical serum circle per serum, filled with its clade colour @ alpha,
    # black outline (Racmacs geom_circle color="black"). serum_circle.style accumulates a
    # modifier per call into the same style name.
    for pick in sera:
        rgb = pick.color.lstrip("#")[:6]
        fill = f"#{cfg.circle_fill_alpha:02X}{rgb}"
        semantic.serum_circle.style(chart=chart, style_name=CIRCLES_STYLE, fold=cfg.fold,
                                    priority=520, sera=[pick.serum_no], theoretical=True,
                                    circle_style={"outline": "black", "fill": fill,
                                                  "outline_width": cfg.circle_outline_width, "dash": 0})

    # Front styles: the by-clade map + title + per-lab viewport, with mark (+circles).
    for name, extra in [(PLAIN_FRONT, [MARK_STYLE]), (CIRCLES_FRONT, [MARK_STYLE, CIRCLES_STYLE])]:
        style = chart.styles()[name]
        style.priority = 1000
        for ref in base_references + extra + ([VIEWPORT_STYLE] if cfg.viewport is not None else []):
            style.add_modifier(parent=ref)
        style.plot_title.text.text = cfg.title
        _apply_title_style(style.plot_title, TITLE_STYLE)
        if cfg.legend:
            _apply_legend(style.legend, legend_json)
        else:
            style.legend.shown = False


def _apply_legend(legend, lj: dict) -> None:
    """Copy a style's ``L`` JSON onto a SemanticLegend (the keys chart-import.cc reads)."""
    legend.shown = not lj.get("-", False)
    if "C" in lj:
        legend.add_counter = lj["C"]
    if "z" in lj:
        legend.show_rows_with_zero_count = lj["z"]
    if "S" in lj:
        legend.point_size = lj["S"]
    if (box := lj.get("B")):
        if "o" in box:
            legend.box.origin = box["o"]
        if "O" in box:
            legend.box.offset(*box["O"])
    if unsupported := sorted(set(lj) - {"-", "C", "z", "S", "B"}):
        print(f">> multiple_circles: WARNING legend keys {unsupported} not copied", file=sys.stderr)


def _apply_title_style(plot_title, ts: dict) -> None:
    for tkey, skey in [["font_size", "size"], ["font_weight", "weight"], ["font_slant", "slant"],
                       ["font_face", "face"], ["color", "color"], ["interline", "interline"]]:
        if (value := ts.get(skey)) is not None:
            setattr(plot_title.text, tkey, value)
    if (origin := ts.get("origin")) is not None:
        plot_title.box.origin = origin
    if (offset := ts.get("offset")):
        plot_title.box.offset(*offset)


def names_lines(sera: list[SerumPick]) -> list[str]:
    """The circled-serum name list (Racmacs `sr_names[rev(na.omit(srs))]`): designation lines,
    reversed so the last-curated serum is on top, matching the Rmd."""
    return [pick.label for pick in reversed(sera)]


# ----------------------------------------------------------------------
# Native rendering (headless, in-process) — mirrors ae.report.map_renderer.NativeRenderer.

def render_pdfs(chart: cv.Chart, style_names: Sequence[str], out_paths: Sequence[Path], *,
                width: float = 800.0) -> None:
    """Render one PDF per style with the native headless renderer — no kateri process,
    no socket.

    The in-memory styled chart is written to a single short-lived temp ``.ace``, then each
    ``(style_name, output_path)`` pair is rendered from it in one
    ``ae_backend.map_draw.export_styled_maps`` call (chart loaded once). Each style resolves
    its own on-chart ``c["R"]`` named style + ``c["p"]`` base plot-spec — including the
    viewport it inherits from the clade style (or the override set by ``build_styles``) — exactly as kateri's ``set_style`` +
    ``get_pdf(square=True)`` did. The recent map-draw serum-circle fill fix means the
    theoretical circles' translucent (``#AARRGGBB``) clade-colour fills now render natively."""
    fd, tmp_name = tempfile.mkstemp(suffix=".ace", prefix="ae-mc-native-")
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        chart.write(tmp_path)
        jobs = [(name, str(Path(out))) for name, out in zip(style_names, out_paths)]
        ae_backend.map_draw.export_styled_maps(tmp_path, jobs, width, 0)
        for out in out_paths:
            print(f">> multiple_circles: wrote {out}", file=sys.stderr)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


# ----------------------------------------------------------------------
# -names overlay: stamp the circled-serum list onto the circles PDF via pdflatex.

_LATEX_SPECIAL = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
                  "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}


def _latex_escape(text: str) -> str:
    return "".join(_LATEX_SPECIAL.get(ch, ch) for ch in str(text))


def _pdf_page_size_pt(pdf: Path) -> tuple[float, float]:
    out = subprocess.check_output(["pdfinfo", str(pdf)], text=True, stderr=subprocess.DEVNULL)
    for line in out.splitlines():
        if line.startswith("Page size:"):
            w, h = line.split(":", 1)[1].split("x")[:2]
            return float(w.strip()), float(h.strip().split()[0])
    return 595.0, 842.0


def overlay_names(circles_pdf: Path, out_pdf: Path, lines: list[str], *,
                  font_pt: float = 7.0, x_frac: float = 0.024, y_frac: float = 0.115) -> Path:
    """Overlay `lines` (small, top-left, below the map's rendered title) onto `circles_pdf`.
    Positions are fractions of the page (x_frac from left, y_frac from top), matching the
    Rmd's names block just under the title."""
    if not shutil.which("pdflatex"):
        raise RuntimeError("pdflatex not on PATH (needed for the -names overlay)")
    w, h = _pdf_page_size_pt(circles_pdf)
    body = r"\\".join(_latex_escape(s) for s in lines)
    work = Path(tempfile.mkdtemp(prefix="mc-names-"))
    try:
        shutil.copyfile(str(circles_pdf), str(work / "map.pdf"))
        tex = "\n".join([
            r"\documentclass{article}",
            rf"\usepackage[paperwidth={w:.2f}pt,paperheight={h:.2f}pt,margin=0pt]{{geometry}}",
            r"\usepackage{graphicx,tikz}\usepackage[T1]{fontenc}",
            r"\setlength{\parindent}{0pt}\pagestyle{empty}",
            r"\begin{document}\noindent",
            r"\begin{tikzpicture}[remember picture,overlay]",
            r"\node[anchor=north west,inner sep=0pt] at (current page.north west)"
            rf" {{\includegraphics[width={w:.2f}pt,height={h:.2f}pt]{{map.pdf}}}};",
            rf"\node[anchor=north west,align=left,inner sep=0pt,font=\fontsize{{{font_pt:.1f}}}{{{font_pt*1.25:.1f}}}\selectfont,"
            rf"xshift={x_frac*w:.2f}pt,yshift={-y_frac*h:.2f}pt] at (current page.north west) {{{body}}};",
            r"\end{tikzpicture}",
            r"\end{document}",
        ])
        (work / "names.tex").write_text(tex, encoding="utf-8")
        # tikz remember-picture/overlay needs two passes to resolve `current page` anchors.
        for _ in range(2):
            proc = subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "names.tex"],
                                  cwd=str(work), capture_output=True, text=True)
        if proc.returncode != 0 or not (work / "names.pdf").exists():
            raise RuntimeError(f"pdflatex failed on -names overlay:\n{proc.stdout[-1500:]}")
        shutil.copyfile(str(work / "names.pdf"), str(out_pdf))
        return out_pdf
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ----------------------------------------------------------------------

def generate_lab(report_dir: Path, cfg: LabConfig, *, width: float = 800.0,
                 persist_chart: Optional[bool] = None) -> dict[str, Path]:
    """Full per-lab pipeline, for any subtype: load styled.ace, pick the clade style
    (`cfg.clade_style` or auto-detected), resolve curated sera and their clade fills, build
    styles (serum-coverage frame + clade legend unless overridden), render plain + circles
    natively, overlay the -names list. Returns the written PDF paths.

    `persist_chart` also saves the styled-plus-`mc-*` chart these maps were drawn from, as
    `<lab>/styled-multiple-circles.ace`. Like the serum-coverage `sc-*` styles, `mc-plain` /
    `mc-circles` and the `CI<fold>` attributes are added to an in-memory copy of `styled.ace`
    and never written back, so nothing on disk reproduces these maps. None (the default)
    takes it from `AE_REPORT_PERSIST_RENDER_CHART`, off unless set — an ordinary run writes
    exactly the files it wrote before. See `map_renderer.write_render_chart`."""
    lab_path = Path(report_dir) / cfg.labdir
    ace = lab_path / "styled.ace"
    if not ace.exists():
        raise FileNotFoundError(f"{ace} not found")

    chart = cv.Chart(str(ace))
    styles = chart_styles(chart)
    clade_style = select_clade_style(styles, cfg.clade_style)
    clade_background_references(styles, clade_style)   # raises now on a missing -clades* style
    viewport = list(cfg.viewport) if cfg.viewport is not None else resolved_viewport(styles, clade_style)
    print(f">> multiple_circles: {cfg.labdir}: clade style {clade_style!r}, viewport {viewport}"
          f"{' (override)' if cfg.viewport is not None else ''}", file=sys.stderr)
    # The renderer draws each circle from the serum's CIn semantic attribute (the radius); set
    # it for folds 2.0/3.0 exactly as the serum-coverage path does before styling.
    semantic.serum_circle.attributes(chart)
    fills = legacy_fills(ace, clade_style)
    sera = resolve_sera(chart, cfg.sera, fills, cfg.fold)
    if not sera:
        raise RuntimeError(f"{cfg.labdir}: no curated sera resolved")
    build_styles(chart, cfg, sera, clade_style=clade_style, styles=styles)

    if map_renderer.persist_render_chart_selected() if persist_chart is None else persist_chart:
        map_renderer.write_render_chart(chart, lab_path / "styled-multiple-circles.ace")

    plain_pdf = lab_path / "plain.pdf"
    circles_pdf = lab_path / "multiple-serum-circles.pdf"
    render_pdfs(chart, [PLAIN_FRONT, CIRCLES_FRONT], [plain_pdf, circles_pdf], width=width)

    out = {"plain": plain_pdf, "circles": circles_pdf}
    if cfg.names:
        names_pdf = lab_path / "multiple-serum-circles-names.pdf"
        overlay_names(circles_pdf, names_pdf, names_lines(sera))
        out["names"] = names_pdf
    return out
