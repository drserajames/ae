# Ported from vcm (ssm-report tooling) py/vcm/v2/commander.py — Phase 1b engine tier.
# the @command surface (download/populate/prestyle/style/export). See py/ae/report/MIGRATION.md.
"""
ae.report.commander — the `@command` surface driven by the report main loop.

`CommanderBasic` gathers the report subcommands a driver script exposes on the CLI /
interactive loop (see ae.report.main_loop): the pipeline `download` → `populate` →
`prestyle` → (manual adjust) → `style` → `export`, plus serum-coverage map generation. The
styling commands drive kateri over its socket; the export commands run headless and write
PDFs / `.ace` outputs. Subclasses supply the subtype-specific `chart_modifier`. Ported from
the vcm ssm-report tooling.
"""
import sys
import re
import json
import datetime
from pathlib import Path
from typing import Optional, Callable

import ae_backend.chart_v3
from ae.utils import kateri
from ae import semantic

import ae.report.download
import ae.report.dirs
from .main_loop import command, no_kateri, no_loop, headless, interactive_kateri
from .chart_modifier import ChartModifier
from . import map_renderer
from .map_renderer import get_map_renderer

# ======================================================================

class CommanderBasic:
    """Base command surface for the report driver. Each `@command` method is a subcommand
    invoked from the CLI / loop, together covering download → populate → prestyle → adjust
    → style → export and serum-coverage generation. Subclasses provide `chart_modifier`."""

    def chart_modifier(self, chart: ae_backend.chart_v3.Chart | Path | None = None) -> ChartModifier:
        """Return the subtype-specific `ChartModifier` for a chart — override per 0do. Raises
        NotImplementedError in the base."""
        raise NotImplementedError("override in derived (0do specific)")

    @command
    @no_kateri
    @no_loop
    def download(self):
        """`download` command: fetch this dir's chart from the incremental chain (no kateri,
        single-shot)."""
        self.download_from_chain()

    @command
    def style(self) -> ChartModifier:
        """`style` command: build the full styles on the adjusted chart and, if kateri is
        connected, send it and select the style-command style. Returns the ChartModifier."""
        chart_modifier = self.chart_modifier(ae.report.dirs.VcmDirs.adjusted_filename())
        chart_modifier.populate_for_style()
        if kateri.communicator.is_connected():
            kateri.communicator.send_chart(chart_modifier.chart)
            kateri.communicator.set_style(chart_modifier.style_for_style_command())
        return chart_modifier

    @command
    @interactive_kateri
    @no_loop
    async def prestyle(self) -> ChartModifier:
        """`prestyle` command: build prestyles on the downloaded chart, write `prestyled.ace`
        and link `adjusted.ace`; on an interactive run, show the prestyled map in kateri.

        Single-shot as it has always been (`@no_loop`): the window comes up with the map on it
        and goes away with the command — unlike `style`, prestyle does not hold it open. It is
        the operator's look at the map before choosing the rotations / outlier moves that
        follow (`chart-rotate`, `adjust/0do`).

        `prestyled.ace` is written natively and unconditionally *before* kateri is touched, so
        a scripted run (which gets no kateri — `@interactive_kateri`) produces exactly the same
        files. The `get_viewport` await is only a round-trip: it makes kateri actually take and
        draw the chart before `@no_loop` tears the app down, which a fire-and-forget
        `send_chart` would not.

        The kateri round-trip this command used to make was a different thing: it baked the
        legacy plot spec (`c["p"]`) via `export_to_legacy` + `get_chart` and only then wrote
        the chart. Nothing consumes `c["p"]` any more — `multiple_circles` resolves clade fills
        from the semantic styles (`c["R"]`) directly — so the bake stays gone; only the display
        is kept."""
        chart_modifier = self.chart_modifier(ae.report.dirs.VcmDirs.downloaded_filename())
        chart_modifier.populate_for_prestyle()
        chart_modifier.chart.write(ae.report.dirs.VcmDirs.prestyled_filename())
        ae.report.dirs.VcmDirs.link_adjusted()
        if kateri.communicator.is_connected():
            kateri.communicator.send_chart(chart_modifier.chart)
            kateri.communicator.set_style(chart_modifier.style_for_legacy_plot_spec())
            await kateri.communicator.get_viewport()   # round-trip: ensure the map is drawn
        return chart_modifier

    @command
    @no_loop
    @headless
    async def populate_export(self):
        """`populate_export` command: populate charts from seqdb then run the full export
        (headless)."""
        self.populate()
        await self.export()

    @command
    @no_kateri
    @no_loop
    def populate_adjusted(self):
        """`populate_adjusted` command: repopulate just `adjusted.ace` from seqdb (no kateri)."""
        if (fn := ae.report.dirs.VcmDirs.adjusted_filename()).exists():
            print(f">>> populating {fn}", file=sys.stderr)
            chart = ae_backend.chart_v3.Chart(fn)
            chart.populate_from_seqdb()
            chart.write(fn)

    @command
    @no_kateri
    @no_loop
    def populate(self):
        "populate from seqdb (when seqdb was updated)"
        for fn in ae.report.dirs.VcmDirs.filenames_for_populating_with_seqdb():
            if fn.exists():
                print(f">>> populating {fn}", file=sys.stderr)
                chart = ae_backend.chart_v3.Chart(fn)
                chart.populate_from_seqdb()
                chart.write(fn)

    @command
    @no_loop
    @headless
    async def export(self):
        """`export` command: style the chart, export each main-map PDF (`out.1.<style>.pdf`),
        write the signature-page mapi, and save the legacy-exported `styled.ace` (headless)."""
        chart_modifier = self.style()
        # Render the lab's full style set from the one styled chart. The native backend loads
        # the chart once for the whole set (P2 batch); kateri renders them sequentially (its
        # protocol does not allow matching pdf requests to results out of order).
        jobs = [(style_name, Path(".").resolve().joinpath(f"out.1.{style_name}.pdf")) for style_name in chart_modifier.export_styles()]
        await self.export_pdfs(jobs=jobs, chart=chart_modifier.chart)
        await self.export_mapi_for_signature_pages(chart_modifier=chart_modifier)
        # Finalise styled.ace. With AE_REPORT_MAP_RENDERER=native the whole export runs
        # kateri-free: serialise the in-memory styled chart directly (see
        # map_renderer.write_styled_ace for why this is equivalent to the kateri bake).
        # Unset/default keeps the exact previous kateri path.
        if map_renderer.native_selected():
            map_renderer.write_styled_ace(chart_modifier.chart, ae.report.dirs.VcmDirs.styled_filename())
        else:
            kateri.communicator.export_to_legacy(style=chart_modifier.style_for_legacy_plot_spec())
            chart = await kateri.communicator.get_chart()
            chart.write(ae.report.dirs.VcmDirs.styled_filename())

    @command
    @no_loop
    @headless
    async def export_info(self):
        """`export_info` command: style the chart and export the info-map PDFs (headless)."""
        chart_modifier = self.style()
        jobs = [(style_name, Path(".").resolve().joinpath(f"out.1.{style_name}.pdf")) for style_name in chart_modifier.export_info_styles()]
        await self.export_pdfs(jobs=jobs, chart=chart_modifier.chart)

    @command
    @no_loop
    @headless
    async def export_mapi_for_signature_pages(self, chart_modifier: Optional[ChartModifier] = None):
        """`export_mapi_for_signature_pages` command: write `sp.mapi` (viewport + vaccine
        markers) for the signature pages, styling the chart first if none is supplied
        (headless)."""
        if chart_modifier is None:
            self.populate()
            chart_modifier = self.style()
        await chart_modifier.export_mapi_for_signature_pages(filename=Path("sp.mapi"), style="clades")

    @command
    def serum_coverage(self, serum_selector: Callable | None = None, fold: float = 2.0):
        "serum_selector: lambda sr: sr.no < 5"
        chart_modifier = self.chart_modifier(ae.report.dirs.VcmDirs.adjusted_filename())
        chart_modifier.populate_for_prestyle()
        semantic.pale.style(chart=chart_modifier.chart, priority=chart_modifier.style_priority("-pale"))
        semantic.serum_circle.attributes(chart=chart_modifier.chart)
        chart_modifier.add_serum_coverage_styles(serum_selector=serum_selector, fold=fold)
        if kateri.communicator.is_connected():
            kateri.communicator.send_chart(chart_modifier.chart)
            kateri.communicator.set_style(f"sc-000-f{fold}-e")
        print(f">>>> chart_modifier {chart_modifier}", file=sys.stderr)
        return chart_modifier

    @command
    @no_loop
    @headless
    async def serum_coverage_export(self, serum_selector: Callable | None = None, fold: float = 2.0):
        "serum_selector: lambda sr: sr.no < 5"
        chart_modifier = self.serum_coverage(serum_selector=serum_selector, fold=fold)
        print(f">>>> chart_modifier {chart_modifier}", file=sys.stderr)
        # Batch-render the serum-coverage style set from the one chart (native loads it once);
        # kateri renders them sequentially (its protocol needs pdf requests/results in order).
        jobs = []
        for serum_no, serum in (chart_modifier.chart.select_sera(serum_selector) if serum_selector is not None else chart_modifier.chart.select_all_sera()):
            for et in ["e", "t"]:
                for zoom_variant in chart_modifier.zoom_variants():
                    style_name = f"sc-{serum_no:03d}-f{fold}-{et}{zoom_variant}"
                    jobs.append((style_name, self.serum_coverage_output_dir().joinpath(f"{style_name}.pdf")))
        # Clean the output dir so it reflects only THIS run's maps. Serum-coverage PDFs
        # otherwise accumulate across runs: a shrunk chart (fewer sera) or a serum_selector
        # (e.g. h1-cdc's single-serum export) leaves maps for sera this run won't regenerate —
        # clutter that also names sera outside the current chart (the SIGTRAP source, cf. the
        # bounds-check on chart.serum()). serum_coverage_export is authoritative for the dir:
        # remove any existing sc-*.pdf not in this run's job set, plus the derived
        # gridage/index/coverage web artifacts (regenerated by serum_coverage_webpage below).
        output_dir = self.serum_coverage_output_dir()
        wanted = {out.name for _, out in jobs}
        stale = [p for p in sorted(output_dir.glob("sc-*.pdf")) if p.name not in wanted]
        for p in stale:
            p.unlink()
        for aux in (*output_dir.glob("gridage-*.json"), *output_dir.glob("index-*.html"), output_dir.joinpath("coverage.html")):
            if aux.exists():
                aux.unlink()
        if stale:
            print(f">>> serum_coverage_export: cleaned {len(stale)} stale serum-coverage map(s) from {output_dir}", file=sys.stderr)
        await self.export_pdfs(jobs=jobs, chart=chart_modifier.chart)
        self.serum_coverage_webpage(chart_modifier=chart_modifier)

    @command
    def serum_coverage_h3_2a2(self):
        """`serum_coverage_h3_2a2` command: serum coverage restricted to sera of H3 clade
        3C.2a1b.2a.2."""
        return self.serum_coverage(serum_selector=lambda sr: sr.has_clade("3C.2a1b.2a.2"), fold=2.0)

    @command
    @no_loop
    @headless
    async def serum_coverage_export_h3_2a2(self):
        """`serum_coverage_export_h3_2a2` command: export serum-coverage maps for H3 clade
        3C.2a1b.2a.2 sera."""
        return await self.serum_coverage_export(serum_selector=lambda sr: sr.has_clade("3C.2a1b.2a.2"), fold=2.0)

    # ----------------------------------------------------------------------

    def download_from_chain(self):
        """Download this dir's chart from the incremental chain, populate it from seqdb and
        write `downloaded.ace`. Returns the Downloader."""
        downloader = ae.report.download.Downloader()
        downloader.from_chain(subtype_dir_name=ae.report.dirs.VcmDirs().subtype_dir_name()).populate_from_seqdb().export_downloaded()
        # downloader.orient_to("master.ace")
        return downloader

    def download_from_previous(self, rotate: float | None = None):
        """Seed this dir's chart from the previous report's chart (optionally rotated),
        populate from seqdb and write `downloaded.ace`. Returns the Downloader."""
        downloader = ae.report.download.Downloader()
        downloader.use_previous(ae.report.dirs.VcmDirs().find_previous_chart(), rotate=rotate).populate_from_seqdb().export_downloaded()
        return downloader

    async def export_pdf(self, style_name: str, output_filename: Path, chart: Optional[ae_backend.chart_v3.Chart] = None):
        """Render the map for `style_name` to `output_filename`, via the map-render backend
        selected by `AE_REPORT_MAP_RENDERER` (default kateri; `native` = in-process C++
        `export_styled_map`). `chart` is the styled chart; it is required by the native
        backend and ignored by the kateri backend (which already holds the chart from the
        `style` command)."""
        await get_map_renderer().export_pdf(chart=chart, style_name=style_name, output_filename=output_filename)

    async def export_pdfs(self, jobs: list[tuple[str, Path]], chart: Optional[ae_backend.chart_v3.Chart] = None):
        """Render several `(style_name, output_filename)` pairs from the one styled `chart`,
        via the selected map-render backend. The native backend loads the chart once for the
        whole set (P2 batch); kateri falls back to a sequential per-style loop. Equivalent to
        calling `export_pdf` for each pair, but amortises the per-set setup."""
        await get_map_renderer().export_pdfs(chart=chart, jobs=jobs)

    def serum_coverage_output_dir(self, check_existance: bool = False) -> Path | None:
        """The `serum-coverage/` output directory. With `check_existance`, return it only if
        it already exists (else None); otherwise create it and return it."""
        output_dir = Path(f"serum-coverage")
        if check_existance:
            return output_dir if output_dir.exists() else None
        else:
            output_dir.mkdir(exist_ok=True)
            return output_dir

    def serum_coverage_webpage(self, chart_modifier):
        """Write the per-fold/zoom `gridage-*.json` + `index-*.html` serum-coverage web pages
        that lay the empirical/theoretical map PDFs in the output dir side by side."""

        def fold_val(stem: str):
            """Extract the fold value from a `…-f<fold>-…` filename stem; raises if absent."""
            folds = [mt.group(1) for field in stem.split("-") if (mt := re.match(r"^f([\d\.]+)$", field))]
            if not folds:
                raise RuntimeError(f"cannot infer fold from \"{stem}\"")
            return folds[0]

        num_sera = chart_modifier.chart.number_of_sera()

        def serum_no_of(stem: str):
            """Serum index encoded in a serum-coverage map stem (`sc-<serum_no>-…`), or None
            if it is not a valid `sc-NNN-…` stem."""
            fields = stem.split("-")
            if len(fields) < 2 or not fields[1].isdigit():
                return None
            return int(fields[1])

        def is_current_serum(stem: str) -> bool:
            """Whether a stem names a serum that exists in the current chart. Stale PDFs left
            in the output dir by a previous run of a larger chart (more sera) name serum
            indexes that no longer exist here — they must be skipped, otherwise `chart.serum()`
            is called out of range (a hard SIGTRAP under libc++ hardening) and the generated
            page would reference maps for nonexistent sera."""
            no = serum_no_of(stem)
            return no is not None and 0 <= no < num_sera

        def serum_title(stem: str):
            """`<serum_no> <designation>` title for a serum-coverage map from its stem."""
            serum_no = serum_no_of(stem)
            serum = chart_modifier.chart.serum(serum_no)
            return f"{serum_no} {serum.designation()}"

        if output_dir := self.serum_coverage_output_dir(check_existance=True):
            subtype_lab = ae.report.dirs.VcmDirs().main_dir().stem
            all_images = sorted(output_dir.glob("*.pdf"))
            images = [img for img in all_images if is_current_serum(img.stem)]
            if stale := [img.name for img in all_images if not is_current_serum(img.stem)]:
                print(f">> serum_coverage_webpage: skipping {len(stale)} stale/foreign map(s) not matching the "
                      f"current chart's {num_sera} sera: {stale[0]} … {stale[-1]}", file=sys.stderr)
            if not images:
                return
            zoom_variants = [""] + (["-zoom"] if any("-zoom" in img.stem for img in images) else [])
            fold_variants = set(fold_val(img.stem) for img in images)
            for zoom in zoom_variants:
                for fold in fold_variants:
                    fold_s = f"{int(2 ** float(fold))}-fold"
                    gridage = {
                        "title": {
                            "short": f"Serum Coverage {subtype_lab}",
                            "long": f"Serum Coverage {fold_s} {zoom} {subtype_lab}",
                            "date": datetime.date.today().strftime("%Y-%m-%d"),
                        },
                        "page": [
                            {
                                "title": serum_title(fn_e.stem),
                                "columns": [[{"T": "title", "text": "Empirical"}, {"T": "pdf", "file": fn_e.name}],
                                            [{"T": "title", "text": "Theoretical"}, {"T": "pdf", "file": fn_e.name.replace("-e", "-t")}]]
                            }
                            for fn_e in sorted(output_dir.glob(f"*-f{fold}-e{zoom}.pdf")) if is_current_serum(fn_e.stem)
                        ]
                    }
                    filename_infix = f"f{fold}{zoom}"
                    gridage_filename = f"gridage-{filename_infix}.json"
                    with output_dir.joinpath(gridage_filename).open("w", encoding="ascii") as out_gridage:
                        json.dump(gridage, out_gridage, indent=2)
                    with output_dir.joinpath(f"index-{filename_infix}.html").open("w", encoding="ascii") as out_index_html:
                        out_index_html.write(sSerumCoverageIndexHtml % {"subtype_lab": subtype_lab, "gridage_file": gridage_filename})

# ======================================================================

sSerumCoverageIndexHtml = """<!DOCTYPE html>
<html>
    <head>
        <meta charset="utf-8" />
        <title>Serum Coverage %(subtype_lab)s</title>
        <link rel="stylesheet" type="text/css" href="/js/acd/who/gridage/v1/gridage.css">
        <script src="/js/acd/who/gridage/v1/gridage.js"></script>
        <script>gridage_file = "%(gridage_file)s"</script>
        <style>
         h1 { color: #0000A0; }
         body {
             height: 100%%;
             padding: 1em 0 0 1em;
             margin: 0;
         }
        </style>
    </head>
    <body>
    </body>
</html>
"""

# ======================================================================
