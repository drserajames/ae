# P2 milestone J — pluggable map-render backend for the report's per-map PDF step.
"""
ae.report.map_renderer — select how the report renders each antigenic-map PDF.

The report's map step is exactly "pick an on-chart named style -> get a PDF". This module
abstracts that step behind a small `MapRenderer` seam with two interchangeable backends that
consume the SAME on-chart styling the report already bakes (`c["R"]` named styles + `c["p"]`
base plot-spec):

  - `KateriRenderer` (default) — drive the kateri app over its Unix socket (`set_style` +
    `get_pdf`). This is exactly the previous behaviour.
  - `NativeRenderer` — call `ae_backend.map_draw.export_styled_map` in-process: no
    subprocess, no socket, Linux-capable, and (P2's payoff) no kateri launch per map.

The backend is chosen by the env var `AE_REPORT_MAP_RENDERER`:

    AE_REPORT_MAP_RENDERER=kateri   (default / unset)  -> KateriRenderer
    AE_REPORT_MAP_RENDERER=native                      -> NativeRenderer

Leaving it unset reproduces the current behaviour EXACTLY. kateri stays the default (and the
interactive drag/relax tool) until native parity is signed off (P2 milestone K).
"""
import os
import sys
import tempfile
from pathlib import Path

import ae_backend.chart_v3

from ae.utils import kateri

# ======================================================================

ENV_VAR = "AE_REPORT_MAP_RENDERER"
DEFAULT_BACKEND = "kateri"

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

# ----------------------------------------------------------------------

_BACKENDS = {
    "kateri": KateriRenderer,
    "native": NativeRenderer,
}

def selected_backend_name() -> str:
    """The backend name from `AE_REPORT_MAP_RENDERER` (default `kateri` when unset/empty)."""
    return (os.environ.get(ENV_VAR) or DEFAULT_BACKEND).strip().lower() or DEFAULT_BACKEND

def get_map_renderer() -> MapRenderer:
    """Instantiate the `MapRenderer` selected by `AE_REPORT_MAP_RENDERER` (default kateri)."""
    name = selected_backend_name()
    try:
        backend = _BACKENDS[name]
    except KeyError:
        raise RuntimeError(f"unknown {ENV_VAR}={name!r}; expected one of {sorted(_BACKENDS)}")
    return backend()

# ======================================================================
