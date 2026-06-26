# Ported from vcm (ssm-report tooling) 2026-0119-tc2/py/vcm/v2/commander.py — Phase 1b engine tier.
# the @command surface (download/populate/prestyle/style/export). See py/ae/report/MIGRATION.md.
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
from .main_loop import command, no_kateri, no_loop, headless
from .chart_modifier import ChartModifier

# ======================================================================

class CommanderBasic:

    def chart_modifier(self, chart: ae_backend.chart_v3.Chart | Path | None = None) -> ChartModifier:
        raise NotImplementedError("override in derived (0do specific)")

    @command
    @no_kateri
    @no_loop
    def download(self):
        self.download_from_chain()

    @command
    def style(self) -> ChartModifier:
        chart_modifier = self.chart_modifier(ae.report.dirs.VcmDirs.adjusted_filename())
        chart_modifier.populate_for_style()
        if kateri.communicator.is_connected():
            kateri.communicator.send_chart(chart_modifier.chart)
            kateri.communicator.set_style(chart_modifier.style_for_style_command())
        return chart_modifier

    @command
    @no_loop
    async def prestyle(self) -> ChartModifier:
        chart_modifier = self.chart_modifier(ae.report.dirs.VcmDirs.downloaded_filename())
        chart_modifier.populate_for_prestyle()
        if kateri.communicator.is_connected():
            kateri.communicator.send_chart(chart_modifier.chart)
            kateri.communicator.export_to_legacy(style=chart_modifier.style_for_legacy_plot_spec())
            chart = await kateri.communicator.get_chart()
            chart.write(ae.report.dirs.VcmDirs.prestyled_filename())
            ae.report.dirs.VcmDirs.link_adjusted()
        return chart_modifier

    @command
    @no_loop
    @headless
    async def populate_export(self):
        self.populate()
        await self.export()

    @command
    @no_kateri
    @no_loop
    def populate_adjusted(self):
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
        chart_modifier = self.style()
        # do not await in parallel because current katteri protocol does not allow matching pdfs request and result
        for style_name in chart_modifier.export_styles():
            await self.export_pdf(style_name=style_name, output_filename=Path(".").resolve().joinpath(f"out.1.{style_name}.pdf"))
        await self.export_mapi_for_signature_pages(chart_modifier=chart_modifier)
        kateri.communicator.export_to_legacy(style=chart_modifier.style_for_legacy_plot_spec())
        chart = await kateri.communicator.get_chart()
        chart.write(ae.report.dirs.VcmDirs.styled_filename())

    @command
    @no_loop
    @headless
    async def export_info(self):
        chart_modifier = self.style()
        for style_name in chart_modifier.export_info_styles():
            await self.export_pdf(style_name=style_name, output_filename=Path(".").resolve().joinpath(f"out.1.{style_name}.pdf"))

    @command
    @no_loop
    @headless
    async def export_mapi_for_signature_pages(self, chart_modifier: Optional[ChartModifier] = None):
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
        # do not await in parallel because current kateri protocol does not allow matching pdfs request and result
        for serum_no, serum in (chart_modifier.chart.select_sera(serum_selector) if serum_selector is not None else chart_modifier.chart.select_all_sera()):
            for et in ["e", "t"]:
                for zoom_variant in chart_modifier.zoom_variants():
                    style_name = f"sc-{serum_no:03d}-f{fold}-{et}{zoom_variant}"
                    await self.export_pdf(style_name=style_name, output_filename=self.serum_coverage_output_dir().joinpath(f"{style_name}.pdf"))
        self.serum_coverage_webpage(chart_modifier=chart_modifier)

    @command
    def serum_coverage_h3_2a2(self):
        return self.serum_coverage(serum_selector=lambda sr: sr.has_clade("3C.2a1b.2a.2"), fold=2.0)

    @command
    @no_loop
    @headless
    async def serum_coverage_export_h3_2a2(self):
        return await self.serum_coverage_export(serum_selector=lambda sr: sr.has_clade("3C.2a1b.2a.2"), fold=2.0)

    # ----------------------------------------------------------------------

    def download_from_chain(self):
        downloader = ae.report.download.Downloader()
        downloader.from_chain(subtype_dir_name=ae.report.dirs.VcmDirs().subtype_dir_name()).populate_from_seqdb().export_downloaded()
        # downloader.orient_to("master.ace")
        return downloader

    def download_from_previous(self, rotate: float | None = None):
        downloader = ae.report.download.Downloader()
        downloader.use_previous(ae.report.dirs.VcmDirs().find_previous_chart(), rotate=rotate).populate_from_seqdb().export_downloaded()
        return downloader

    async def export_pdf(self, style_name: str, output_filename: Path):
        data = await kateri.communicator.get_pdf(style=style_name)
        print(f">>> writing pdf to {output_filename}", file=sys.stderr)
        with output_filename.open("wb") as output:
            output.write(data)
        # if open:
        #     subprocess.call(["open", expected["filename"]])

    def serum_coverage_output_dir(self, check_existance: bool = False) -> Path | None:
        output_dir = Path(f"serum-coverage")
        if check_existance:
            return output_dir if output_dir.exists() else None
        else:
            output_dir.mkdir(exist_ok=True)
            return output_dir

    def serum_coverage_webpage(self, chart_modifier):

        def fold_val(stem: str):
            folds = [mt.group(1) for field in stem.split("-") if (mt := re.match(r"^f([\d\.]+)$", field))]
            if not folds:
                raise RuntimeError(f"cannot infer fold from \"{stem}\"")
            return folds[0]

        def serum_title(stem: str):
            serum_no = int(stem.split("-")[1])
            serum = chart_modifier.chart.serum(serum_no)
            return f"{serum_no} {serum.designation()}"

        if output_dir := self.serum_coverage_output_dir(check_existance=True):
            subtype_lab = ae.report.dirs.VcmDirs().main_dir().stem
            images = sorted(output_dir.glob("*.pdf"))
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
                            for fn_e in sorted(output_dir.glob(f"*-f{fold}-e{zoom}.pdf"))
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
