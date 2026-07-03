"""Map rendering + chart access for the chains web app.

Replaces AD's ``chart.py`` (which drove the in-process ``acmacs.ChartDraw``). Here the
drawing is delegated to the standalone **map-draw** CLI — the headless C++ Cairo renderer
that reproduces AD ChartDraw — invoked as a subprocess, mirroring how the chain engine
shells out to ``chart-relax-grid``. Chart *reads* (for the table page's per-chart date)
go through ``ae_backend.chart_v3``.

AD's pre-render + cache behaviour is preserved: rendered images live in a ``png/`` dir next
to the source ``.ace`` and are only regenerated when the source is newer than the cache
(``older_than``). ``reorient-master.ace`` is auto-detected by map-draw itself.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

from ..utils import older_than

# ae_backend is imported lazily so this module imports fine without the native extension.


def _import_backend():
    import ae_backend  # noqa: PLC0415 — intentional lazy import

    return ae_backend


# ======================================================================
# chart access (read-only)
# ======================================================================


def get_chart(filename: Path):
    ae_backend = _import_backend()
    return ae_backend.chart_v3.Chart(str(filename))


def chart_date(filename: Path) -> str:
    try:
        return get_chart(filename).info().date()
    except Exception as err:  # keep the table page resilient to odd charts
        print(f"> WARNING: cannot read date from {filename}: {err}", file=sys.stderr)
        return ""


# ======================================================================
# rendering (delegated to the map-draw CLI, with a png/ cache)
# ======================================================================


def get_map(ctx, *, coloring: str, size: int, ace: str = None, ace1: str = None, ace2: str = None,
            image_type: str = "png", save_chart: bool = False, type: str = "map") -> bytes:
    """Render (or serve from cache) a map or procrustes-comparison image; return its bytes."""
    if type == "map":
        ace_filename = Path(ace)
        output_filename = png_dir(ace_filename).joinpath(
            f"{ace_filename.stem}.{encode_for_filename(coloring)}.{size}.{image_type}")
        reorient_master = find_reorient_master(ace_filename.parent)
        if older_than(output_filename, ace_filename, reorient_master, ctx.mapi_file):
            _run_map_draw(ctx, output_filename, [str(ace_filename)], coloring=coloring, size=int(size))
    elif type == "pc":
        ace1_filename = Path(ace1)
        ace2_filename = Path(ace2)
        output_filename = png_dir(ace1_filename).joinpath(
            f"pc-{ace1_filename.stem}-vs-{ace2_filename.stem}.{encode_for_filename(coloring)}.{size}.{image_type}")
        if older_than(output_filename, ace1_filename, ace2_filename, ctx.mapi_file):
            _run_map_draw(ctx, output_filename, [str(ace1_filename)], coloring=coloring, size=int(size),
                          procrustes=str(ace2_filename))
    else:
        return b""
    if output_filename.exists():
        return output_filename.open("rb").read()
    return b""


def _run_map_draw(ctx, output: Path, inputs: list[str], *, coloring: str, size: int, procrustes: str = None):
    """Build and run the map-draw command line.

    map-draw auto-detects ``reorient-master.ace`` next to (or above) the input, applies
    vaccine marks itself, and picks the backend from the output extension (.png / .pdf).
    """
    cmd = [ctx.map_draw_exe, "--size", str(size)]
    if ctx.mapi_file and coloring:
        cmd += ["--mapi", str(ctx.mapi_file), "--coloring", coloring]
    if procrustes:
        cmd += ["--procrustes", procrustes]
    cmd += [*inputs, str(output)]
    print(f">>> map-draw: {' '.join(cmd)}", file=sys.stderr)
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError:
        print(f"> ERROR: map-draw executable not found: {ctx.map_draw_exe!r} "
              f"(set MAP_DRAW_EXE or --map-draw-exe)", file=sys.stderr)
    except subprocess.CalledProcessError as err:
        print(f"> ERROR: map-draw failed ({err.returncode}) for {output}:\n{err.stderr}", file=sys.stderr)


# ======================================================================
# path helpers (ported verbatim from AD chart.py)
# ======================================================================


def png_dir(ace: Path) -> Path:
    pd = ace.parent.joinpath("png")
    pd.mkdir(exist_ok=True)
    return pd


sReEncoder = re.compile(r"[\(\)\[\]/\"']")


def encode_for_filename(name: str) -> str:
    return sReEncoder.sub("-", name)


sReorientMasterName = "reorient-master.ace"


def find_reorient_master(ace_dir: Path):
    reorient_master_filename = ace_dir.joinpath(sReorientMasterName)
    if not reorient_master_filename.exists():
        reorient_master_filename = ace_dir.parent.joinpath(sReorientMasterName)
        if not reorient_master_filename.exists():
            reorient_master_filename = None
    return reorient_master_filename


# ======================================================================
