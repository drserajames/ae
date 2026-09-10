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

The map itself is rendered by the **native headless renderer**
(``ae_backend.map_draw.export_styled_map`` / ``export_styled_maps``) — no kateri process, no
socket, Linux-capable — mirroring ``ae.report.map_renderer.NativeRenderer``. The clade
colouring is resolved natively from the chart's own ``clades-v10`` **semantic** style
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

# References reproducing the report's by-clade map. Like the report's `clades-v10` front
# style but WITHOUT `-vaccines-v10`: the Racmacs multiple-circles figures plot the bare
# clade-coloured map (no enlarged/labelled vaccine markers).
BASE_REFERENCES = ["-reset", "-clades-v10", "-new-2", "-new-1"]

# The semantic style whose per-antigen fills colour the circles (== the report's by-clade map).
CLADE_LEGACY_STYLE = "clades-v10"

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
    """Per-lab configuration for the multiple-serum-circles figures: the lab directory,
    title, square viewport, the curated `SerumPick`s, the circle fold, and marker sizing."""
    labdir: str
    title: str
    viewport: Sequence[float]          # [center_x, center_y, width] — square map viewport
    sera: list[SerumPick]
    fold: float = 2.0
    serum_size: float = 26.0           # selected-serum point size (tuned vs Racmacs srSize 8)
    serum_outline_width: float = 3.0
    circle_outline_width: float = 1.0
    circle_fill_alpha: int = 0x33      # ~20% opaque == Racmacs t_col(col, percent=80)
    names: bool = True


# ----------------------------------------------------------------------

def legacy_fills(ace_path: Path) -> dict[int, str]:
    """antigen index -> rendered fill hex for the ``clades-v10`` style, i.e. the Rmd's ``agFill``.

    Resolved natively from the chart's SEMANTIC styles (``c["R"]``) via
    ``Chart.semantic_style_to_legacy`` — the in-process reproduction of kateri's ``setFrom``.
    Previously this read a pre-baked legacy plot spec (``c["p"]``) that only kateri could produce
    (so the report had to launch kateri in ``prestyle`` to bake it); resolving ``c["R"]`` here
    removes that dependency. Verified byte-equal to the old ``c["p"]`` fills across the report's
    charts (0 diffs)."""
    chart = cv.Chart(str(ace_path))
    chart.semantic_style_to_legacy(CLADE_LEGACY_STYLE)
    data = json.loads(chart.export())["c"]
    p = data.get("p", {})
    idx = p.get("p", [])
    palette = p.get("P", [])
    fills: dict[int, str] = {}
    for ag_no in range(len(data.get("a", []))):
        if ag_no < len(idx) and idx[ag_no] < len(palette):
            if (fill := palette[idx[ag_no]].get("F")):
                fills[ag_no] = fill
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
        pick.color = fills.get(homol, "#808080")
        serum = chart.serum(serum_no)
        pick.designation = serum.designation()
        # Racmacs sr_names = paste(srNames, srIDs, srPassage): designation already carries
        # name + serum_id; append the passage to complete the -names list line.
        pick.label = f"{pick.designation} {serum.passage()}".strip()
        resolved.append(pick)
        print(f">> multiple_circles: SR {serum_no:3d} {pick.designation:48s} "
              f"homol AG {homol} r={radius:.3f} fill={pick.color}", file=sys.stderr)
    return resolved


def build_styles(chart: cv.Chart, cfg: LabConfig, sera: list[SerumPick]) -> None:
    """Build the `-mc-mark` / `-mc-circles` background styles and the `mc-plain` / `mc-circles`
    front styles on the chart, ready for the native renderer's style selection."""
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
        for ref in BASE_REFERENCES + extra:
            style.add_modifier(parent=ref)
        style.plot_title.text.text = cfg.title
        _apply_title_style(style.plot_title, TITLE_STYLE)
        style.legend.shown = False
        style.viewport(*cfg.viewport)


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
    per-lab square viewport set by ``build_styles`` — exactly as kateri's ``set_style`` +
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
    """Full per-lab pipeline: load styled.ace, resolve curated sera, build styles, render
    plain + circles natively, overlay the -names list. Returns the written PDF paths.

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
    # The renderer draws each circle from the serum's CIn semantic attribute (the radius); set
    # it for folds 2.0/3.0 exactly as the serum-coverage path does before styling.
    semantic.serum_circle.attributes(chart)
    fills = legacy_fills(ace)
    sera = resolve_sera(chart, cfg.sera, fills, cfg.fold)
    if not sera:
        raise RuntimeError(f"{cfg.labdir}: no curated sera resolved")
    build_styles(chart, cfg, sera)

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
