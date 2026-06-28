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

The map itself is rendered by **kateri** over its unix socket (one session per lab); the
clade colouring reuses the chart's own ``clades-v10`` semantic style and legacy plot-spec
fills, so the antigen colours match the report's main maps exactly. Serum circles use ae's
``projection().serum_circles(fold)`` theoretical radius — identical to the Rmd's
``2 + max(logtiter[,sr]) - logtiter[homologous_ag, sr]`` for ``fold=2.0``.

The curated per-lab serum selection lives in the report-dir driver (gen-multiple-circles-ae.py),
mirroring the addendum-serum-coverage by-clade config — not greps in this engine.
"""

from __future__ import annotations

import asyncio
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

import ae_backend.chart_v3 as cv

from ae import semantic
from ae.utils import kateri as K

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
    labdir: str
    title: str
    viewport: Sequence[float]          # [center_x, center_y, width] for kateri
    sera: list[SerumPick]
    fold: float = 2.0
    serum_size: float = 26.0           # selected-serum point size (tuned vs Racmacs srSize 8)
    serum_outline_width: float = 3.0
    circle_outline_width: float = 1.0
    circle_fill_alpha: int = 0x33      # ~20% opaque == Racmacs t_col(col, percent=80)
    names: bool = True


# ----------------------------------------------------------------------

def legacy_fills(ace_path: Path) -> dict[int, str]:
    """antigen index -> rendered fill hex, read from the chart's legacy plot spec ("p").
    This is the exact colour kateri draws with `clades-v10` (the legacy spec was exported
    from that style), i.e. the Rmd's `agFill`."""
    data = json.loads(subprocess.check_output(["decat", str(ace_path)]))["c"]
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
    front styles on the chart, ready for kateri `set_style`."""
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
# kateri rendering (one session per lab) — adapted from ae.tal.signature_page.

def _kateri_app_bundle(exe: str) -> Optional[Path]:
    resolved = Path(exe).resolve()
    for parent in (resolved, *resolved.parents):
        if parent.suffix == ".app":
            return parent
    return None


def render_pdfs(chart: cv.Chart, style_names: Sequence[str], out_paths: Sequence[Path], *,
                width: float = 800.0, connect_timeout: float = 90.0, map_timeout: float = 90.0) -> None:
    """Render one PDF per style in a single kateri session (chart sent once)."""
    exe = shutil.which("kateri")
    if not exe:
        raise RuntimeError("kateri not on PATH — install kateri (github.com/drserajames/kateri)")
    app_bundle = _kateri_app_bundle(exe)

    async def _run() -> None:
        socket_dir = tempfile.mkdtemp(prefix="kateri-mc-")
        socket_name = os.path.join(socket_dir, "kateri.sock")
        K.communicator.reset()
        server = await asyncio.start_unix_server(K.communicator.connected, socket_name)
        direct = None
        try:
            if app_bundle is not None:
                opener = await asyncio.create_subprocess_exec(
                    "open", "-n", "-a", str(app_bundle), "--args", "--socket", socket_name, "--headless")
                await opener.wait()
            else:
                direct = await asyncio.create_subprocess_exec(exe, "--socket", socket_name, "--headless")
            waited = 0.0
            while not K.communicator.is_connected():
                if waited >= connect_timeout:
                    raise RuntimeError(f"kateri did not connect within {connect_timeout:.0f}s")
                await asyncio.sleep(0.1)
                waited += 0.1
            K.communicator.send_chart(chart)
            for name, out in zip(style_names, out_paths):
                pdf = await asyncio.wait_for(K.communicator.get_pdf(style=name, width=width, square=True),
                                             timeout=map_timeout)
                Path(out).write_bytes(pdf)
                print(f">> multiple_circles: wrote {out}", file=sys.stderr)
            K.communicator.quit()
        finally:
            server.close()
            if direct is not None and direct.returncode is None:
                direct.terminate()
            elif app_bundle is not None:
                subprocess.run(["pkill", "-f", socket_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            shutil.rmtree(socket_dir, ignore_errors=True)

    asyncio.run(_run())


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
    """Overlay `lines` (small, top-left, below the kateri-drawn title) onto `circles_pdf`.
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

def generate_lab(report_dir: Path, cfg: LabConfig, *, width: float = 800.0) -> dict[str, Path]:
    """Full per-lab pipeline: load styled.ace, resolve curated sera, build styles, render
    plain + circles via kateri, overlay the -names list. Returns the written PDF paths."""
    lab_path = Path(report_dir) / cfg.labdir
    ace = lab_path / "styled.ace"
    if not ace.exists():
        raise FileNotFoundError(f"{ace} not found")

    chart = cv.Chart(str(ace))
    # kateri draws each circle from the serum's CIn semantic attribute (the radius); set it
    # for folds 2.0/3.0 exactly as the serum-coverage path does before styling.
    semantic.serum_circle.attributes(chart)
    fills = legacy_fills(ace)
    sera = resolve_sera(chart, cfg.sera, fills, cfg.fold)
    if not sera:
        raise RuntimeError(f"{cfg.labdir}: no curated sera resolved")
    build_styles(chart, cfg, sera)

    plain_pdf = lab_path / "plain.pdf"
    circles_pdf = lab_path / "multiple-serum-circles.pdf"
    render_pdfs(chart, [PLAIN_FRONT, CIRCLES_FRONT], [plain_pdf, circles_pdf], width=width)

    out = {"plain": plain_pdf, "circles": circles_pdf}
    if cfg.names:
        names_pdf = lab_path / "multiple-serum-circles-names.pdf"
        overlay_names(circles_pdf, names_pdf, names_lines(sera))
        out["names"] = names_pdf
    return out
