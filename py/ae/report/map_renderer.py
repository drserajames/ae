# P2 milestone J — pluggable map-render backend for the report's per-map PDF step.
"""
ae.report.map_renderer — select how the report renders each antigenic-map PDF.

The report's map step is exactly "pick an on-chart named style -> get a PDF". This module
abstracts that step behind a small `MapRenderer` seam with two interchangeable backends that
consume the SAME on-chart styling the report already bakes (`c["R"]` named styles + `c["p"]`
base plot-spec):

  - `KateriRenderer` — drive the kateri app over its Unix socket (`set_style` +
    `get_pdf`). This is the previous behaviour, now opt-in via the env var.
  - `NativeRenderer` — call `ae_backend.map_draw.export_styled_map` in-process: no
    subprocess, no socket, Linux-capable, and (P2's payoff) no kateri launch per map.

The backend is chosen by the env var `AE_REPORT_MAP_RENDERER`:

    AE_REPORT_MAP_RENDERER=native   (default / unset)  -> NativeRenderer
    AE_REPORT_MAP_RENDERER=kateri                      -> KateriRenderer

Native is the default report figure renderer (headless, in-process, Linux-capable) after P2
sign-off. This only affects the report's batch map-PDF step; kateri remains the interactive
viewer (drag/Relax/GUI) and the fallback here via `AE_REPORT_MAP_RENDERER=kateri`.
"""
import os
import sys
import json
import math
import tempfile
from pathlib import Path

import ae_backend.chart_v3

from ae.utils import kateri

# ======================================================================

ENV_VAR = "AE_REPORT_MAP_RENDERER"
DEFAULT_BACKEND = "native"

# Opt-in: also save the chart that was handed to the renderer, next to the maps it produced.
# See persist_render_chart_selected() / write_render_chart() at the bottom of this module.
ENV_VAR_PERSIST_RENDER_CHART = "AE_REPORT_PERSIST_RENDER_CHART"

# ----------------------------------------------------------------------

class MapRenderer:
    """Interface for the report's per-map PDF render step: given the styled chart, a named
    style, and an output path, write the map PDF. Backends take the SAME inputs so they are
    drop-in for each other."""

    backend_name = "?"

    async def export_pdf(self, chart: ae_backend.chart_v3.Chart, style_name: str, output_filename: Path, width: float = 800.0):
        """Render the map for `style_name` (a name in the chart's `c["R"]` block) to
        `output_filename` as a PDF, at page `width` points."""
        raise NotImplementedError("override in a MapRenderer backend")

    async def export_pdfs(self, chart: ae_backend.chart_v3.Chart, jobs: list[tuple[str, Path]], width: float = 800.0):
        """Render several `(style_name, output_filename)` pairs from the SAME `chart`. The
        default is a plain sequential loop over `export_pdf` (so any backend works and kateri
        keeps its request/result ordering); backends that can amortise per-call setup across
        the whole set (e.g. the native renderer loading the chart once) override this."""
        for style_name, output_filename in jobs:
            await self.export_pdf(chart=chart, style_name=style_name, output_filename=output_filename, width=width)

# ----------------------------------------------------------------------

class KateriRenderer(MapRenderer):
    """Default backend: request the PDF from a connected kateri over its socket. `chart` is
    ignored here because the report has already sent it to kateri (via the `style` command)
    before requesting PDFs — this backend only selects the style and collects the bytes,
    exactly as the report's map step did before the seam was introduced."""

    backend_name = "kateri"

    async def export_pdf(self, chart: ae_backend.chart_v3.Chart, style_name: str, output_filename: Path, width: float = 800.0):
        """Ask kateri for the PDF of `style_name` and write it to `output_filename`."""
        data = await kateri.communicator.get_pdf(style=style_name, width=width)
        print(f">>> [map_renderer.kateri] writing pdf to {output_filename}", file=sys.stderr)
        Path(output_filename).write_bytes(data)

# ----------------------------------------------------------------------

class NativeRenderer(MapRenderer):
    """Headless in-process backend: render the styled chart with the native C++ renderer
    (`ae_backend.map_draw.export_styled_map`), which resolves the same `c["R"]` named style +
    `c["p"]` base plot-spec kateri consumes. No kateri process, no socket. `export_styled_map`
    reads a chart from an `.ace` file, so the report's in-memory styled chart is written to a
    short-lived temp `.ace` for each render."""

    backend_name = "native"

    async def export_pdf(self, chart: ae_backend.chart_v3.Chart, style_name: str, output_filename: Path, width: float = 800.0):
        """Write the styled chart to a temp `.ace` and render `style_name` natively to
        `output_filename`."""
        if chart is None:
            raise RuntimeError(
                f"{self.__class__.__name__} needs the in-memory styled chart, but none was "
                f"passed to export_pdf (style {style_name!r}). The native backend renders from "
                f"the chart directly rather than from a kateri session.")
        fd, tmp_name = tempfile.mkstemp(suffix=".ace", prefix="ae-report-native-")
        os.close(fd)
        tmp_path = Path(tmp_name)
        try:
            chart.write(tmp_path)
            print(f">>> [map_renderer.native] rendering style {style_name!r} -> {output_filename}", file=sys.stderr)
            ae_backend.map_draw.export_styled_map(tmp_path, Path(output_filename), style_name, width, 0)
        finally:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass

    async def export_pdfs(self, chart: ae_backend.chart_v3.Chart, jobs: list[tuple[str, Path]], width: float = 800.0):
        """Batch render: write the ~12 MB styled chart to a temp `.ace` ONCE, then render
        every `(style_name, output_filename)` in a single native call that loads the chart
        once (`ae_backend.map_draw.export_styled_maps`). Each map is byte-identical to the
        per-call `export_pdf` path — the only difference is the chart is loaded once instead
        of once per style."""
        if chart is None:
            raise RuntimeError(
                f"{self.__class__.__name__} needs the in-memory styled chart, but none was "
                f"passed to export_pdfs. The native backend renders from the chart directly "
                f"rather than from a kateri session.")
        if not jobs:
            return
        fd, tmp_name = tempfile.mkstemp(suffix=".ace", prefix="ae-report-native-")
        os.close(fd)
        tmp_path = Path(tmp_name)
        try:
            chart.write(tmp_path)
            native_jobs = [(style_name, str(Path(output_filename))) for style_name, output_filename in jobs]
            for style_name, output_filename in jobs:
                print(f">>> [map_renderer.native] (batch) rendering style {style_name!r} -> {output_filename}", file=sys.stderr)
            ae_backend.map_draw.export_styled_maps(tmp_path, native_jobs, width, 0)
        finally:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass

# ----------------------------------------------------------------------

_BACKENDS = {
    "kateri": KateriRenderer,
    "native": NativeRenderer,
}

def selected_backend_name() -> str:
    """The backend name from `AE_REPORT_MAP_RENDERER` (default `native` when unset/empty)."""
    return (os.environ.get(ENV_VAR) or DEFAULT_BACKEND).strip().lower() or DEFAULT_BACKEND

def get_map_renderer() -> MapRenderer:
    """Instantiate the `MapRenderer` selected by `AE_REPORT_MAP_RENDERER` (default native;
    kateri is the opt-in fallback via `AE_REPORT_MAP_RENDERER=kateri`)."""
    name = selected_backend_name()
    try:
        backend = _BACKENDS[name]
    except KeyError:
        raise RuntimeError(f"unknown {ENV_VAR}={name!r}; expected one of {sorted(_BACKENDS)}")
    return backend()

def native_selected() -> bool:
    """True when `AE_REPORT_MAP_RENDERER=native` — the report's finalising steps (write
    `styled.ace`, compute the signature-page mapi viewport) must run kateri-free. When False
    (default) the report keeps its exact previous kateri behaviour."""
    return selected_backend_name() == "native"

# ======================================================================
# Native, kateri-free replacements for the `export` command's finalising steps.
#
# The per-map PDF step already has a native backend (NativeRenderer, above). But
# CommanderBasic.export finishes with two more kateri round-trips that the two functions
# below replace so an `export` run needs NO kateri process at all:
#
#   1. write_styled_ace()          <- kateri export_to_legacy(style) + get_chart() + write
#   2. sig_page_viewport() (mapi)  <- kateri set_style(style) + get_viewport()
# ----------------------------------------------------------------------

def write_styled_ace(chart: ae_backend.chart_v3.Chart, filename: Path):
    """Native replacement for `export`'s trailing `kateri.export_to_legacy(style) +
    get_chart() + write(styled.ace)`.

    kateri's `export_to_legacy` runs `plotSpecLegacy().setFrom(currentPlotSpec)`
    (map-viewer-data.dart `exportCurrentPlotStyleToLegacy`) — it bakes the *named* semantic
    style (`c["R"][style_for_legacy_plot_spec()]`) into the legacy per-point plot spec
    (`c["p"]` = per-point palette index + palette). `get_chart` then returns the whole chart
    (semantic attributes + `c["R"]` styles + `c["P"]` projections + the freshly-baked
    `c["p"]`).

    Everything except that fresh `c["p"]` bake is already present on the in-memory styled
    chart, so a plain `chart.write()` reproduces the semantic attributes, all `c["R"]` named
    styles and the `c["P"]` projections byte-for-byte. The `c["p"]` legacy plot spec carried
    on the chart is the one baked by the *earlier* `prestyle` step — which bakes the SAME
    `style_for_legacy_plot_spec()` style (see CommanderBasic.prestyle / .export) — so its
    per-antigen clade fills are identical to what a fresh kateri bake would produce (verified
    against the kateri-written styled.ace: the only differences are colour-string
    normalisation, e.g. `#6D9BC2`->`#6d9bc2` and `#CCCCCC`->`gray80`). The one consumer of
    this legacy plot spec, `multiple_circles.legacy_fills`, reads only those per-antigen
    fills, so it is served identically.

    Residual (honest gap): this relies on the in-memory chart already carrying a `c["p"]`
    baked from `style_for_legacy_plot_spec()` (which the standard download->prestyle->adjust
    pipeline guarantees). It does NOT itself re-run the semantic->legacy bake, because that
    logic (`setFrom`) lives only in kateri; a native `Chart.semantic_style_to_legacy` binding
    (stubbed out in cc/chart/v3/chart.hh) would be needed to bake it in-process."""
    print(f">>> [map_renderer.native] writing styled chart -> {filename}", file=sys.stderr)
    chart.write(Path(filename))

def persist_render_chart_selected() -> bool:
    """True when `AE_REPORT_PERSIST_RENDER_CHART` is set to a truthy value.

    Off by default, so an ordinary report run writes exactly the files it wrote before.
    Turn it on for a **reference-generation** run: see `write_render_chart`."""
    value = (os.environ.get(ENV_VAR_PERSIST_RENDER_CHART) or "").strip().lower()
    return value not in ("", "0", "no", "false", "off")

def write_render_chart(chart: ae_backend.chart_v3.Chart, filename: Path) -> Path:
    """Save the chart that was handed to the map renderer, so the maps it produced can be
    re-rendered (and pixel-compared) later.

    Several report map families are drawn from a chart that is styled **in memory** and then
    thrown away — `serum_coverage_export` (the `sc-*` / `-sci-*` / `-sco-*` serum-circle and
    serum-coverage styles) and `multiple_circles.generate_lab` (`mc-plain` / `mc-circles`).
    Those styles therefore appear in NO `.ace` on disk: `styled.ace` is written by a different
    command, from a differently-styled chart (`export` -> `populate_for_style`), and it neither
    carries the `sc-*`/`mc-*` styles nor the per-serum `CI<fold>` semantic attributes the
    circle radii come from. The consequence for P2 is that ~1850 kateri golden PDFs per report
    run have no chart that reproduces them, so the most geometry-heavy part of the native
    renderer (milestones F/G: empirical vs theoretical radius, fold, dash, angle radius-lines,
    within/outside coverage restyle) cannot be pixel-verified at all.

    This writes that chart out verbatim — the SAME object the renderer consumed, so the file
    is a faithful record and not a reconstruction. Both backends are served: the native one
    renders from a serialisation of this chart already (`NativeRenderer.export_pdfs` writes it
    to a temp `.ace`), and the kateri one is sent the same bytes over the socket
    (`kateri.communicator.send_chart`). A write -> read -> render round trip is exact: the
    `c["R"]` styles (including `CI`/`SC` modifier blocks with angles and radius-lines) and the
    sera's `CI<fold>` attributes all survive, and the re-rendered maps are pixel-identical —
    see `test/test-serum-coverage-style-persistence.py`. (Pixel, not byte: Cairo stamps a
    `/CreationDate` into every PDF, so even two renders of the same chart differ in bytes.)

    Opt-in via `AE_REPORT_PERSIST_RENDER_CHART` (or an explicit `persist_chart=True` at the
    call site). It only ever ADDS a file, but a report chart is ~1 MB per lab, so it is off by
    default and turned on for reference-generation runs. See
    `tools/p2-fidelity/SERUM-COVERAGE-REFERENCE-PASS.md`."""
    filename = Path(filename)
    filename.parent.mkdir(parents=True, exist_ok=True)
    print(f">>> [map_renderer] persisting render chart -> {filename}", file=sys.stderr)
    chart.write(filename)
    return filename

def sig_page_viewport(chart: ae_backend.chart_v3.Chart, used_viewport) -> list[float]:
    """Native replacement for the `kateri.set_style(style) + get_viewport()` round-trip in
    `ChartModifier.export_mapi_for_signature_pages`.

    kateri returns three things and the report combines them into the sig-page viewport:
      * `used`          = the style's own viewport `[x, y, size]` (the report set this via
                          `self.viewport()`), passed in here as `used_viewport`;
      * `native`        = the projection viewport AFTER kateri's roundAndRecenter, i.e. a box
                          whose width/height are `ceil(hull_span + 1)` of the TRANSFORMED
                          layout (viewport.dart roundAndRecenter);
      * `native_center` = the centre of the transformed-layout hull BEFORE rounding
                          (viewport.dart `layoutCenter2`).
    The report then computes (commander/chart_modifier):
        x = -native_w/2 + used_x + native_center_x
        y = -native_h/2 + used_y + native_center_y
        size = used_size
    which this function reproduces from the transformed layout (raw layout `c["P"][0]["l"]`
    put through the projection transformation `c["P"][0]["t"]`, convention
    `tx = x*a + y*c`, `ty = x*b + y*d` per cc/chart/v3/transformation.hh). Verified to
    reproduce kateri's `sp.mapi` viewport to full float precision across H1/H3/B labs."""
    ux, uy, us = float(used_viewport[0]), float(used_viewport[1]), float(used_viewport[2])
    data = json.loads(chart.export())["c"]
    projections = data.get("P", [])
    if not projections:
        return [ux, uy, us]
    proj = projections[0]
    layout = proj.get("l", [])
    a, b, c, d = proj.get("t", [1.0, 0.0, 0.0, 1.0])[:4]
    xs: list[float] = []
    ys: list[float] = []
    for co in layout:
        if co and len(co) >= 2 and co[0] is not None and co[1] is not None and co[0] == co[0] and co[1] == co[1]:
            x, y = co[0], co[1]
            xs.append(x * a + y * c)
            ys.append(x * b + y * d)
    if not xs:
        return [ux, uy, us]
    cx = (min(xs) + max(xs)) / 2.0
    cy = (min(ys) + max(ys)) / 2.0
    rw = math.ceil((max(xs) - min(xs)) + 1.0)
    rh = math.ceil((max(ys) - min(ys)) + 1.0)
    return [cx - rw / 2.0 + ux, cy - rh / 2.0 + uy, us]

# ======================================================================
