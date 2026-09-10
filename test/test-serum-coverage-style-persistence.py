#!/usr/bin/env python3
# Tests for serum-circle / serum-coverage STYLE PERSISTENCE (P2 milestones F/G).
#
# The report's `sc-*` / `-sci-*` / `-sco-*` styles are built on an in-memory chart by
# `ae.report.chart_modifier.ChartModifier.add_serum_coverage_styles` and, before this change,
# were never written to any `.ace` — so the ~1850 kateri golden PDFs a report run produces had
# no chart on disk that reproduced them, and the most geometry-heavy part of the native
# renderer could not be pixel-compared at all. `map_renderer.write_render_chart` saves that
# chart verbatim; this test proves the property that makes a later fidelity run meaningful:
#
#   a persisted chart, re-loaded from disk, renders the SAME maps as the in-memory one.
#
# It checks, on the committed synthetic-free test chart `test/chart1.ace`:
#   1. the whole exported chart JSON is identical after write -> read -> write (so the `c["R"]`
#      styles AND the sera's `CI<fold>` semantic attributes, which carry the circle radii,
#      survive the round trip);
#   2. every `sc-*` front style renders PIXEL-IDENTICALLY from the persisted file and from a
#      re-serialisation of the reloaded chart (`ae_backend.map_draw.export_styled_map`).
#      Compared as rasters, not as PDF bytes: Cairo stamps `/CreationDate` into every PDF it
#      writes, so two renders of the SAME chart a second apart already differ in bytes. This
#      step needs `pdftoppm` (poppler) and is skipped with a warning if it is absent;
#   3. the optional serum-circle geometry that the report does not currently use — `angles`
#      and `radius_lines` — also round-trips, and each serum keeps its own radius-line colour;
#   4. `persist_render_chart_selected()` is OFF unless `AE_REPORT_PERSIST_RENDER_CHART` says
#      otherwise, i.e. an ordinary report run writes exactly the files it wrote before.
#
# No WHO data: the only input is the in-repo test chart, and all output goes to a temp dir.
#
# Run (from the ae worktree root):
#   PYTHONPATH="$PWD/build:$PWD/py" \
#   arch -arm64 /opt/homebrew/bin/python3.14 test/test-serum-coverage-style-persistence.py

import faulthandler
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

faulthandler.enable()
# build-py314 is compiled with libc++ FAST hardening: a latent C++ UB traps as SIGTRAP with no
# Python traceback unless faulthandler is told about it explicitly (see CLAUDE.md).
faulthandler.register(signal.SIGTRAP)

import ae_backend

from ae import semantic
from ae.report import map_renderer
from ae.report.chart_modifier import ChartModifier

CHART = Path(__file__).resolve().parent / "chart1.ace"
FOLD = 2.0

failures: list[str] = []


def check(condition: bool, what: str, detail: str = ""):
    print(f"{'ok  ' if condition else 'FAIL'}  {what}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures.append(what)


def raster_digest(pdf: Path) -> str:
    """SHA-256 of `pdf` rasterised at 72 dpi. PDF bytes cannot be compared directly: Cairo
    writes a `/CreationDate` into every file, so even two renders of the same chart differ."""
    # style names contain dots ("sc-000-f2.0-e"), so build the stem by hand rather than with
    # Path.with_suffix, which would cut at the first dot from the right.
    stem = str(pdf)[:-len(".pdf")]
    subprocess.run(["pdftoppm", "-png", "-r", "72", "-singlefile", str(pdf), stem],
                   check=True, capture_output=True)
    return hashlib.sha256(Path(stem + ".png").read_bytes()).hexdigest()


class _Modifier(ChartModifier):
    """Minimal concrete ChartModifier: `add_serum_coverage_styles` is inherited unchanged (it
    is the code under test); only the chart/subtype-specific hooks it calls are supplied."""

    def title_lab_subtype(self) -> str:
        return "TESTLAB TEST-SUBTYPE"

    def style_for_legacy_plot_spec(self) -> str:
        return "clades"

    def viewport(self, zoom_variant: str) -> list[float]:
        return [-5.0, -5.0, 10.0]


def styled_chart() -> tuple[ae_backend.chart_v3.Chart, list[str]]:
    """The test chart put through the production serum-coverage styling path, plus the names
    of the styles that produced (background `-sci-*`/`-sco-*` and front `sc-*`)."""
    chart = ae_backend.chart_v3.Chart(str(CHART))
    if chart.number_of_projections() == 0:
        chart.relax(number_of_dimensions=2, number_of_optimizations=10, minimum_column_basis="none")

    modifier = _Modifier(chart=chart)
    # The background styles the `sc-*` front styles reference. In a report run these come from
    # populate_for_prestyle + semantic.pale; here only their names have to resolve.
    modifier.add_reset_style()
    clades = chart.styles()["-clades"]
    clades.priority = modifier.style_priority("-clades")
    clades.add_modifier(only="antigens", fill="green", outline="black")
    semantic.pale.style(chart=chart, priority=modifier.style_priority("-pale"))
    vaccines = chart.styles()["-vaccines"]
    vaccines.priority = modifier.style_priority("-vaccines")
    vaccines.add_modifier(only="antigens", selector={"R": True}, outline="black")

    # This is what the `serum_coverage` command does: the CI<fold> attributes carry the circle
    # radii, then the sc styles reference them.
    semantic.serum_circle.attributes(chart=chart)
    modifier.add_serum_coverage_styles(fold=FOLD)

    names = sorted(json.loads(chart.export())["c"].get("R", {}))
    sc_names = [n for n in names if n.startswith(("sc-", "-sci-", "-sco-"))]
    return chart, sc_names


def test_round_trip(tmp: Path):
    chart, sc_names = styled_chart()
    n_sera = chart.number_of_sera()
    expected = n_sera * 2 * 2 + n_sera  # e/t x (front + background circle) + one coverage each
    check(len(sc_names) == expected, "serum-coverage styles built",
          f"{len(sc_names)} styles for {n_sera} sera (expected {expected})")

    persisted = map_renderer.write_render_chart(chart, tmp / "styled-serum-coverage.ace")
    check(persisted.exists(), "persisted chart written", str(persisted.name))

    reloaded = ae_backend.chart_v3.Chart(str(persisted))
    rewritten = tmp / "reloaded.ace"
    reloaded.write(rewritten)

    before = json.loads(chart.export())["c"]
    after = json.loads(reloaded.export())["c"]
    check(before.get("R") == after.get("R"), "c[\"R\"] styles survive write -> read",
          f"{len(after.get('R', {}))} named styles")
    circle_attrs = [srm.get("T", {}).get(f"CI{int(FOLD)}") for srm in after["s"]]
    check([srm.get("T", {}).get(f"CI{int(FOLD)}") for srm in before["s"]] == circle_attrs,
          f"sera CI{int(FOLD)} radius attributes survive write -> read",
          f"{sum(1 for a in circle_attrs if a)}/{n_sera} sera carry a radius")
    check(before == after, "whole chart JSON identical after write -> read -> write")
    if before != after:
        for key in sorted(set(before) | set(after)):
            if before.get(key) != after.get(key):
                print(f"        differing top-level key: {key}")

    fronts = [n for n in sc_names if n.startswith("sc-")]
    if shutil.which("pdftoppm") is None:
        print("skip  sc-* maps render pixel-identically after reload — pdftoppm (poppler) not found")
        return
    identical = 0
    for style_name in fronts:
        one = tmp / f"persisted.{style_name}.pdf"
        two = tmp / f"reloaded.{style_name}.pdf"
        ae_backend.map_draw.export_styled_map(persisted, one, style_name, 800.0, 0)
        ae_backend.map_draw.export_styled_map(rewritten, two, style_name, 800.0, 0)
        if raster_digest(one) == raster_digest(two):
            identical += 1
        else:
            print(f"        differing render: {style_name}")
    check(bool(fronts) and identical == len(fronts), "sc-* maps render pixel-identically after reload",
          f"{identical}/{len(fronts)} front styles")


def test_angles_and_radius_lines(tmp: Path):
    """The `angles` / `radius_lines` serum-circle geometry is not used by the report today, but
    it is part of what milestones F/G cover, so it must persist too."""
    chart = ae_backend.chart_v3.Chart(str(CHART))
    if chart.number_of_projections() == 0:
        chart.relax(number_of_dimensions=2, number_of_optimizations=10, minimum_column_basis="none")
    semantic.serum_circle.attributes(chart=chart)
    per_passage = {"egg": "red", "cell": "blue", "reassortant": "orange"}
    semantic.serum_circle.style(
        chart=chart, style_name="-angles", sera=list(range(chart.number_of_sera())), fold=FOLD,
        circle_style={"outline": dict(per_passage), "fill": {"egg": "#18FF0000", "cell": "#180000FF", "reassortant": "#18FFA500"},
                      "outline_width": 2.5, "dash": 3, "angles": [0.5, 2.5],
                      "radius_lines": {"outline": dict(per_passage), "outline_width": 1.5, "dash": 2}})

    written = tmp / "angles.ace"
    chart.write(written)
    reloaded = ae_backend.chart_v3.Chart(str(written))
    before = json.loads(chart.export())["c"]["R"]["-angles"]
    after = json.loads(reloaded.export())["c"]["R"]["-angles"]
    check(before == after, "serum-circle angles + radius-lines survive write -> read")
    # each serum's radius line must take ITS OWN passage colour, not the first serum's
    modifiers = after["A"]
    mismatched = [m for m in modifiers if m["CI"].get("r", {}).get("O") != m["CI"]["O"]]
    check(not mismatched, "each serum keeps its own radius-line colour",
          f"{len(modifiers) - len(mismatched)}/{len(modifiers)} modifiers")


def test_opt_in_default():
    saved = os.environ.pop(map_renderer.ENV_VAR_PERSIST_RENDER_CHART, None)
    try:
        check(not map_renderer.persist_render_chart_selected(), "persistence is off by default")
        for value, want in [("1", True), ("yes", True), ("true", True),
                            ("0", False), ("no", False), ("off", False), ("", False)]:
            os.environ[map_renderer.ENV_VAR_PERSIST_RENDER_CHART] = value
            got = map_renderer.persist_render_chart_selected()
            check(got is want, f"{map_renderer.ENV_VAR_PERSIST_RENDER_CHART}={value!r} -> {want}")
    finally:
        os.environ.pop(map_renderer.ENV_VAR_PERSIST_RENDER_CHART, None)
        if saved is not None:
            os.environ[map_renderer.ENV_VAR_PERSIST_RENDER_CHART] = saved


def main() -> int:
    if not CHART.exists():
        print(f"{CHART}: not found", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory(prefix="ae-sc-persist-") as tmp_name:
        tmp = Path(tmp_name)
        test_round_trip(tmp)
        test_angles_and_radius_lines(tmp)
        test_opt_in_default()
    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
