# Ported from vcm (ssm-report tooling) 2026-0119-tc2/py/vcm/v2/download.py — Phase 1 engine/library tier.
# chart download/relax/orient/merge (ae_backend.chart_v3). See py/ae/report/MIGRATION.md.
"""
ae.report.download — fetch and prepare the source chart for a report directory.

`Downloader` pulls the per-dir source chart — the latest (or a pinned / exactly-reproduced)
incremental from the antigenic chain over ssh, or a seed from the previous report — then
populates it from seqdb and can merge, relax, grid-test, orient and write `downloaded.ace`.
Its methods return `self` for chaining, and `self.updated` tracks whether the chart changed.
Ported from the vcm ssm-report tooling.
"""
import sys, os, subprocess
from pathlib import Path
from typing import Callable
from ae.utils.open_file import backup
from ae.utils.timeit import timeit

import ae_backend.chart_v3
import ae.chart

import ae.report.dirs

MaybeCallable = Callable | None
Chart = ae_backend.chart_v3.Chart

# ======================================================================

class Downloader:
    """Fetches and prepares the per-dir source chart. Chain the builder methods (each returns
    `self`): typically `from_chain(...).populate_from_seqdb().export_downloaded()`.
    `self.updated` records whether the chart actually changed, gating the later steps."""

    CHAIN_ROOT = Path("/syn/eu/ac/results/chains-202105")

    # ----------------------------------------------------------------------

    def from_chain(self, subtype_dir_name: str, chain_name: str | None = None):
        """Download this subtype's chart from the incremental chain over ssh into
        `downloaded.raw.ace`, skipping the transfer when the sha1 already matches. Honours
        `$VCM_CHAIN_REPRODUCE` (fetch the chain file whose sha1 matches this dir's recorded
        one, reconstructing an earlier report's exact chart) and `$VCM_CHAIN_INCREMENTAL`
        (pin to an older chain point by filename substring)."""
        subtype_dir: Path = self.CHAIN_ROOT.joinpath(subtype_dir_name)
        local_ace_file = ae.report.dirs.VcmDirs.downloaded_raw_filename()
        local_sha1_filename = local_ace_file.with_suffix(".sha1")

        # Reproduce mode ($VCM_CHAIN_REPRODUCE): fetch the chain file whose sha1 matches this dir's
        # recorded downloaded.raw.sha1 — i.e. reconstruct the *exact* chart an earlier report used,
        # regardless of how far the chain has since advanced. Searches newest chain dir first.
        repro_sha1 = self._local_sha1(local_sha1_filename) if os.environ.get("VCM_CHAIN_REPRODUCE") else None
        if repro_sha1:
            cmd = (f"for d in $(ls -1dt {subtype_dir}/f-*); do for f in $d/*.incremental.ace; do "
                   f"[ \"$(sha1sum \"$f\" | cut -d' ' -f1)\" = {repro_sha1} ] && {{ echo \"$f\"; exit 0; }}; done; done")
            remote_ace_file = subprocess.check_output(["ssh", "o", cmd]).decode("ascii").strip()
            if not remote_ace_file:
                raise RuntimeError(f"reproduce: no chain file with sha1 {repro_sha1} under {subtype_dir}")
        else:
            if chain_name is None:
                chain_dir = subprocess.check_output(["ssh", "o", f"ls -1d {subtype_dir}/f-* | tail -n 1"]).decode("ascii").strip()
            else:
                chain_dir = subtype_dir.joinpath(chain_name)
            # By default take the latest incremental in the chain. To reproduce a historical report,
            # pin to an older chain point via $VCM_CHAIN_INCREMENTAL (a substring of the incremental
            # filename, e.g. the data-cutoff date "20260129") — the latest *matching* file is used.
            pin = os.environ.get("VCM_CHAIN_INCREMENTAL", "").strip()
            glob = f"*{pin}*.incremental.ace" if pin else "*.incremental.ace"
            remote_ace_file = subprocess.check_output(["ssh", "o", f"ls -1 {chain_dir}/{glob} | tail -n 1"]).decode("ascii").strip()
        ace_remote_sha1 = self._remote_sha1(remote_ace_file)
        if not local_ace_file.exists() or not (ace_local_sha1 := self._local_sha1(local_sha1_filename)) or ace_local_sha1 != ace_remote_sha1:
            backup(local_ace_file)
            print(f">>> {local_ace_file} <-- {remote_ace_file}   {ace_remote_sha1}", file=sys.stderr)
            subprocess.check_call(f"ssh o cat '{remote_ace_file}' | decat | brotli -Z -v -f -o '{local_ace_file}'", shell=True)
            local_ace_file.chmod(0o644)
            local_sha1_filename.open("w", encoding="ascii").write(ace_remote_sha1)

            self.chart = Chart(local_ace_file)
            self.chart.write(local_ace_file)
            self.updated = True
        else:
            print(f">>> up to date: {local_ace_file} -- {remote_ace_file}   {ace_remote_sha1}", file=sys.stderr)
            self.chart = Chart(local_ace_file)
            self.updated = False
        return self

    def _local_sha1(self, filename: Path) -> str | None:
        if not filename.exists():
            return None
        return filename.open().read().strip()

    def _remote_sha1(self, filename: str) -> str:
        return subprocess.check_output(["ssh", "o", f"sha1sum '{filename}'"]).decode("ascii").split()[0]

    # ----------------------------------------------------------------------

    def use_previous(self, previous: Path, rotate: float | None = None):
        """Seed the chart from the `previous` report's chart (optionally rotating its
        projection), populate from seqdb and export — but only when `downloaded.ace` does not
        already exist."""
        if not ae.report.dirs.VcmDirs.downloaded_filename().exists():
            self.chart = Chart(previous)
            self.updated = True
            if rotate is not None:
                self.chart.projection(0).transformation().rotate(rotate)
            self.populate_from_seqdb()
            self.export_downloaded()
            self.updated = True
        else:
            self.chart = Chart(local_ace_file)
            self.updated = False
        return self

    # ----------------------------------------------------------------------

    def orient_to(self, orient_to: str | Path | Chart):
        """Orient the chart's projection to a master chart (a path or a `Chart`)."""
        if isinstance(orient_to, Chart):
            master = orient_to
        else:
            master = Chart(orient_to)
        self.chart.orient_to(master)
        return self

    def populate_from_seqdb(self, even_if_not_updated: bool = False):
        """Populate the chart's sequences from seqdb — only when the chart changed, unless
        `even_if_not_updated`."""
        if even_if_not_updated or self.updated:
            with timeit(f"populating from seqdb"):
                self.chart.populate_from_seqdb()
                self.updated = True
        return self

    def export_downloaded(self, even_if_not_updated: bool = False):
        """Write the chart to `downloaded.ace` — only when it changed, unless
        `even_if_not_updated`."""
        if even_if_not_updated or self.updated:
            self.chart.write(ae.report.dirs.VcmDirs.downloaded_filename())
        return self

    # ----------------------------------------------------------------------

    def merge(self, sources: list[Path], remove_antigens: MaybeCallable = None, remove_sera: MaybeCallable = None, match: str = "strict", merge_type: str = "simple", report: bool = True):
        """Merge `sources` into the chart (combining cheating assays, keeping duplicates
        distinct), optionally removing the selected antigens/sera afterwards."""
        self.chart = ae.chart.merge(sources=sources, match=match, merge_type=merge_type, combine_cheating_assays=True, duplicates_distinct=True, report=False)
        if remove_antigens is not None or remove_sera is not None:
            self.chart.remove_antigens_sera(antigens=self.chart.select_antigens(remove_antigens) if remove_antigens else None, sera=self.chart.select_sera(remove_sera) if remove_sera else None)
        self.updated = True
        if report:
            print(ae.chart.info(self.chart, show_projections=True, show_forced_column_bases=True, show_sources=False))
        return self

    def is_the_same_as(self, filename: Path):
        """Whether `filename`'s chart matches the current one in antigen, serum, titer-layer
        and source counts (clears `updated` when it does)."""
        if not filename.exists():
            return False
        downloaded_chart = Chart(filename)
        the_same = downloaded_chart.number_of_antigens() == self.chart.number_of_antigens() and \
            downloaded_chart.number_of_sera() == self.chart.number_of_sera() and \
            downloaded_chart.titers().number_of_layers() == self.chart.titers().number_of_layers() and \
            downloaded_chart.info().number_of_sources() == self.chart.info().number_of_sources()
        if the_same:
            self.updated = False
        return the_same

    def relax(self, number_of_optimizations: int, relax_type: str = "scratch", minimum_column_basis: str = "none", grid: bool = True, disconnect_antigens: MaybeCallable = None, disconnect_sera: MaybeCallable = None, report: bool = True):
        """disconnect egg ag/sr, relax"""
        match relax_type:
            case "scratch":
                self.chart.relax(number_of_dimensions=2, number_of_optimizations=number_of_optimizations, minimum_column_basis=minimum_column_basis,
                            disconnect_antigens=self.chart.select_antigens(disconnect_antigens) if disconnect_antigens else None,
                            disconnect_sera=self.chart.select_sera(disconnect_sera) if disconnect_sera else None)
            case "incremental":
                if disconnect_antigens is not None or disconnect_sera is not None:
                    raise ValueError("cannot handle disconnect_antigens/disconnect_sera for incremental relax")
                self.chart.relax_incremental(number_of_optimizations=number_of_optimizations)
            case _: raise ValueError(f"unsupported relax_type: \"{relax_type}\"")
        self.chart.keep_projections(1)
        self.updated = True
        if report:
            print(ae.chart.info(self.chart, show_projections=True, show_forced_column_bases=True, show_sources=False))
        if grid:
            self.grid(report=report)
        return self

    def grid(self, report: bool = True):
        """Run the grid test and, if any trapped/hemisphering points are found, move them
        (marking the chart updated)."""
        if (grid_test := self.chart.grid_test()).count_trapped_hemisphering():
            for en in grid_test.trapped_hemisphering():
                print(en)
            grid_test.apply(self.chart.projection(0))
            self.updated = True
            if report:
                print(ae.chart.info(self.chart, show_projections=True, show_forced_column_bases=True, show_sources=False))
        return self

    def connect_freeze_relax(self, number_of_optimizations: int, report: bool = True):
        """connect disconnected, relax with previously connected frozen"""
        self.chart.projection(0).connect_all_disconnected()
        self.chart.relax_incremental(projection_no=0, number_of_optimizations=number_of_optimizations, remove_source_projection=True, unmovable_non_nan_points=True)
        self.chart.keep_projections(1)
        if report:
            print(ae.chart.info(self.chart, show_projections=True, show_forced_column_bases=True, show_sources=False))
        self.updated = True
        return self

    def remove_styles(self):
        """Remove all plot styles from the chart."""
        self.chart.styles().remove()
        return self

# ======================================================================
