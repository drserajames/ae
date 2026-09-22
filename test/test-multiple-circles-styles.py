#!/usr/bin/env python3
# Tests for ae.report.multiple_circles' subtype-independent style handling.
#
# The multiple-serum-circles figures used to hardcode H3's `clades-v10` / `-clades-v10`, so on
# an H1 or B/Vic chart every circle rendered grey and the run still exited 0; and the per-lab
# viewport never took effect, because the renderer's viewport is last-writer-wins and `-reset`
# was walked after the front style's own `V`. This checks, on the in-repo test chart
# `test/chart1.ace` with synthetic clade styles added in memory:
#   1. the clade style is taken from the config, auto-detected only when unambiguous, and a
#      missing or ambiguous one RAISES (naming the candidates) instead of rendering grey;
#   2. the background references are the clade style's own parents minus `-vaccines*`, and a
#      missing `-clades*` reference raises;
#   3. with no override the circle maps resolve the clade style's `-reset` viewport; an explicit
#      override WINS; and the two frames really render differently (pdftoppm, if present);
#   4. the clade legend (with its counter) is inherited, and `legend=False` hides it.
#
# No WHO data: the only input is the in-repo test chart, and all output goes to a temp dir.
#
# Run (from the ae worktree root):
#   PYTHONPATH="$PWD/build:$PWD/py" \
#   arch -arm64 /opt/homebrew/bin/python3.14 test/test-multiple-circles-styles.py

import faulthandler
import hashlib
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

faulthandler.enable()
faulthandler.register(signal.SIGTRAP)

import ae_backend.chart_v3 as cv

from ae.report import multiple_circles as mc

CHART = Path(__file__).resolve().parent / "chart1.ace"
RESET_VIEWPORT = [-3.0, -2.0, 12.0, 12.0]
OVERRIDE = [1.0, 1.0, 6.0]

failures: list[str] = []


def check(condition: bool, what: str, detail: str = ""):
    print(f"{'ok  ' if condition else 'FAIL'}  {what}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures.append(what)


def raises(fn, needle: str) -> tuple[bool, str]:
    try:
        fn()
    except (ValueError, RuntimeError) as err:
        return needle in str(err), str(err)
    return False, "did not raise"


def add_clade_styles(chart: cv.Chart, versions: list[str], *, with_background: bool = True) -> None:
    """Report-like styles: `-reset` (viewport), per version a `-clades<v>` background colouring
    every antigen with a legend row, and a `clades<v>` front style referencing
    [-reset, -clades<v>, -new-1, -vaccines<v>] with a counted legend."""
    reset = chart.styles()["-reset"]
    reset.priority = 90000
    reset.viewport(*RESET_VIEWPORT)
    for v in versions:
        if with_background:
            bg = chart.styles()[f"-clades{v}"]
            bg.priority = 200
            bg.add_modifier(selector={}, only="antigens", fill="#FF0000", legend="all antigens")
        front = chart.styles()[f"clades{v}"]
        front.priority = 100
        for ref in ["-reset", f"-clades{v}", "-new-1", f"-vaccines{v}"]:
            front.add_modifier(parent=ref)
        front.legend.shown = True
        front.legend.add_counter = True


def staged(tmp: Path, name: str, versions: list[str], **kw) -> Path:
    """A report dir `tmp/<name>/` holding `styled.ace` = chart1 + synthetic clade styles."""
    # One relaxed layout shared by every lab dir, so renders differ only by their styles.
    relaxed = tmp / "relaxed.ace"
    if not relaxed.exists():
        chart = cv.Chart(str(CHART))
        if chart.number_of_projections() == 0:
            chart.relax(number_of_dimensions=2, number_of_optimizations=10, minimum_column_basis="none")
        chart.write(relaxed)
    chart = cv.Chart(str(relaxed))
    add_clade_styles(chart, versions, **kw)
    (tmp / name).mkdir(parents=True, exist_ok=True)
    chart.write(tmp / name / "styled.ace")
    return tmp


def lab(name: str, **kw) -> mc.LabConfig:
    return mc.LabConfig(labdir=name, title="test", sera=[mc.SerumPick(match="")], names=False, **kw)


def persisted_styles(report_dir: Path, name: str) -> dict:
    return mc.chart_styles(cv.Chart(str(report_dir / name / "styled-multiple-circles.ace")))


def raster_digest(pdf: Path) -> str:
    stem = str(pdf)[:-len(".pdf")]
    subprocess.run(["pdftoppm", "-png", "-r", "72", "-singlefile", str(pdf), stem], check=True, capture_output=True)
    return hashlib.sha256(Path(stem + ".png").read_bytes()).hexdigest()


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="ae-test-mc-"))
    try:
        # ---- 1. clade style selection ----
        one = mc.chart_styles(cv.Chart(str(staged(tmp, "one", [""]) / "one" / "styled.ace")))
        check(mc.select_clade_style(one, None) == "clades", "single clade style auto-detected")
        ok, msg = raises(lambda: mc.select_clade_style(one, "clades-v10"), "not on the chart")
        check(ok, "missing requested clade style raises", msg)

        many = mc.chart_styles(cv.Chart(str(staged(tmp, "many", ["-v1", "-v2"]) / "many" / "styled.ace")))
        ok, msg = raises(lambda: mc.select_clade_style(many, None), "clades-v1")
        check(ok and "clades-v2" in msg, "ambiguous auto-detect raises naming the candidates", msg)
        check(mc.select_clade_style(many, "clades-v2") == "clades-v2", "explicit clade style chosen")

        # ---- 2. background references ----
        refs = mc.clade_background_references(many, "clades-v2")
        check(refs == ["-reset", "-clades-v2", "-new-1"], "references = own parents minus -vaccines*", str(refs))
        nobg = mc.chart_styles(cv.Chart(str(staged(tmp, "nobg", [""], with_background=False) / "nobg" / "styled.ace")))
        ok, msg = raises(lambda: mc.clade_background_references(nobg, "clades"), "not on the chart")
        check(ok, "missing -clades* background reference raises", msg)
        ok, msg = raises(lambda: mc.generate_lab(tmp, lab("nobg")), "not on the chart")
        check(ok, "generate_lab raises on a missing background style (no grey render)", msg)
        ok, msg = raises(lambda: mc.generate_lab(tmp, lab("many")), "cannot auto-detect")
        check(ok, "generate_lab raises on an ambiguous clade style", msg)

        # ---- 3. viewport ----
        check(mc.resolved_viewport(one, "clades") == RESET_VIEWPORT, "clade style resolves the -reset viewport",
              str(mc.resolved_viewport(one, "clades")))

        staged(tmp, "dflt", [""])
        mc.generate_lab(tmp, lab("dflt"), persist_chart=True)
        dflt = persisted_styles(tmp, "dflt")
        for front in (mc.PLAIN_FRONT, mc.CIRCLES_FRONT):
            check(mc.resolved_viewport(dflt, front) == RESET_VIEWPORT, f"{front}: default = -reset frame (serum-coverage frame)",
                  str(mc.resolved_viewport(dflt, front)))
        check(mc.VIEWPORT_STYLE not in dflt, "no viewport style without an override")

        staged(tmp, "ovr", [""])
        mc.generate_lab(tmp, lab("ovr", viewport=OVERRIDE), persist_chart=True)
        ovr = persisted_styles(tmp, "ovr")
        expected = OVERRIDE + [OVERRIDE[2]]
        for front in (mc.PLAIN_FRONT, mc.CIRCLES_FRONT):
            check(mc.resolved_viewport(ovr, front) == expected, f"{front}: explicit override wins",
                  str(mc.resolved_viewport(ovr, front)))
            parents = [m["R"] for m in ovr[front].get("A", []) if "R" in m]
            check(parents[-1] == mc.VIEWPORT_STYLE, f"{front}: override style referenced last", str(parents))
        if shutil.which("pdftoppm"):
            staged(tmp, "dflt2", [""])
            mc.generate_lab(tmp, lab("dflt2"))
            check(raster_digest(tmp / "dflt" / "plain.pdf") == raster_digest(tmp / "dflt2" / "plain.pdf"),
                  "control: same config renders identically")
            check(raster_digest(tmp / "dflt" / "plain.pdf") != raster_digest(tmp / "ovr" / "plain.pdf"),
                  "override changes the rendered frame")
        else:
            print("WARN  pdftoppm not on PATH — rendered-frame comparison skipped")

        # ---- 4. legend ----
        check(dflt[mc.PLAIN_FRONT].get("L", {}).get("C") is True and not dflt[mc.PLAIN_FRONT]["L"].get("-", False),
              "legend inherited, shown with counter", str(dflt[mc.PLAIN_FRONT].get("L")))
        staged(tmp, "nolg", [""])
        mc.generate_lab(tmp, lab("nolg", legend=False), persist_chart=True)
        check(persisted_styles(tmp, "nolg")[mc.PLAIN_FRONT].get("L", {}).get("-") is True, "legend=False hides it")
        if shutil.which("pdftotext"):
            text = subprocess.run(["pdftotext", str(tmp / "dflt" / "plain.pdf"), "-"], capture_output=True, text=True).stdout
            check("all antigens" in text, "legend row rendered in plain.pdf")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{'FAILED: ' + ', '.join(failures) if failures else 'all ok'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
