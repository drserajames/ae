# Ported from vcm (ssm-report tooling) 2026-0119-tc2/py/vcm/v2/dirs.py — Phase 1 engine/library tier.
# working-dir conventions + lab_title/lab_of_dir. See py/ae/report/MIGRATION.md.
"""
ae.report.dirs — working-directory conventions for the seasonal (ssm/VCM) report.

`VcmDirs` (a `Modules` subclass) resolves the per-lab/subtype report layout from the
driver script's own location: which `<subtype>-<assay>-…-<lab>` directory the run is
in, the enclosing `ssm` report tree, the matching WHO CC table directory, and the
canonical `.ace` filename for each pipeline stage (downloaded → prestyled → adjusted →
styled). It also locates the corresponding chart in a previous report, for incremental
merges. Ported from the vcm ssm-report tooling (see py/ae/report/MIGRATION.md).
"""
import sys, os
from pathlib import Path
from typing import Any, Optional
import ae.report.modules

# ======================================================================

class VcmDirs (ae.report.modules.Modules):
    """Per-run report directory resolver. The driver script's own file location fixes the
    "main dir" (a `<subtype>-<assay>-…-<lab>` directory under an `ssm` report tree); the
    methods here map that to lab titles, WHO CC table dirs, previous-report charts, and the
    canonical per-stage `.ace` filenames. `sNewNameToOldName` maps the current short dir
    names to the legacy subtype-assay-rbc-lab names used on disk for tables and merges."""

    sNewNameToOldName = {
        "h1-cdc": "h1pdm-hi-turkey-cdc",
        "h1-cnic": "h1pdm-hi-turkey-cnic",
        "h1-crick": "h1pdm-hi-turkey-crick",
        "h1-niid": "h1pdm-hi-turkey-niid",
        "h1-vidrl": "h1pdm-hi-turkey-vidrl",
        "h3-hi-guinea-pig-cdc": "h3-hi-guinea-pig-cdc",
        "h3-hi-guinea-pig-crick": "h3-hi-guinea-pig-crick",
        "h3-hi-guinea-pig-cnic": "h3-hi-guinea-pig-cnic",
        "h3-hi-guinea-pig-niid": "h3-hi-guinea-pig-niid",
        "h3-hi-guinea-pig-vidrl": "h3-hi-guinea-pig-vidrl",
        "h3-hint-cdc": "h3-hint-cdc",
        "h3-neut-cnic": "h3-pn-cnic",
        "h3-neut-crick": "h3-prn-crick",
        "h3-neut-niid": "h3-fra-niid",
        "h3-neut-vidrl": "h3-fra-vidrl",
        "bvic-cdc": "bvic-hi-turkey-cdc",
        "bvic-cnic": "bvic-hi-turkey-cnic",
        "bvic-crick": "bvic-hi-turkey-crick",
        "bvic-niid": "bvic-hi-chicken-niid",
        "bvic-vidrl": "bvic-hi-turkey-vidrl",
        "byam-cdc": "byam-hi-turkey-cdc",
        "byam-crick": "byam-hi-turkey-crick",
        "byam-niid": "byam-hi-chicken-niid",
        "byam-vidrl": "byam-hi-turkey-vidrl",
    }

    sLabTitle = {"cdc": "CDC", "cnic": "CNIC", "crick": "Crick", "niid": "NIID", "vidrl": "VIDRL", "all": "All labs"}

    def standard_vcm_chart_dir(self, dir_name: Optional[str] = None) -> Optional[str]:
        """Return `dir_name` (default: the main dir's stem) if it names a recognised VCM
        chart directory — i.e. is a key of `sNewNameToOldName` — otherwise None."""
        if dir_name is None:
            dir_name = self.main_dir().stem
        if dir_name in self.sNewNameToOldName:
            return dir_name
        else:
            return None

    def title_lab(self):
        """Human-readable lab name (e.g. "CDC") for the lab of the current main dir."""
        return self.sLabTitle[self.lab_from_main_dir()]

    def lab_from_main_dir(self) -> str:
        """Lab code parsed from the trailing `-<lab>` segment of the main dir name."""
        return self.main_dir().stem.split("-")[-1]

    def tc_ssm_dir_name(self) -> str:
        """Name of the enclosing report (target-cycle `ssm`) directory."""
        return self.tc_ssm_dir_path().name

    def tc_ssm_dir_path(self) -> Path:
        """Path of the enclosing report directory: three levels above the `ssm` component
        of the main dir, or the main dir itself if the layout is shallower than that."""
        cwd = self.main_dir()
        if (len(cwd.parts) - cwd.parts.index("ssm")) >= 3:
            return cwd.parents[len(cwd.parts) - cwd.parts.index("ssm") - 3]
        else:
            return cwd

    def subtype_dir_name(self) -> str:
        """Legacy (old-scheme) subtype-assay-rbc-lab directory name for the current main
        dir, via `sNewNameToOldName` — used to locate WHO CC tables and previous merges."""
        return self.sNewNameToOldName[self.main_dir().stem]

    def main_dir(self) -> Path:
        """Directory containing the driver (`__main__`) script — the report run's working
        directory."""
        return Path(self.main_module().__file__).resolve().parent

    def whocc_table_dir(self) -> Path:
        """Path to this subtype-assay's WHO CC tables under `$WHOCC_TABLES_DIR`."""
        return Path(os.environ["WHOCC_TABLES_DIR"], self.subtype_dir_name()).resolve()

    def find_previous_chart(self, current_name: Optional[str] = None, number_of_previous: int = 1) -> Optional[Path]:
        """Locate this chart in an earlier report, `number_of_previous` reports back, for
        incremental merging. Looks under that report's `merges/<old-name>.ace` (or a
        per-dir `styled.ace`). Returns the resolved path, or None when the earlier report
        exists but has no chart for this dir (not an error — callers filter None out).
        Raises NotImplementedError if the previous directory does not exist at all."""
        if current_name is None:
            current_name = self.standard_vcm_chart_dir()
        previous_dir = self.tc_ssm_dir_path()
        for p_no in range(number_of_previous):
            previous_dir = previous_dir.joinpath("previous")
        if previous_dir.joinpath("merges").is_dir():
            prev_ace = previous_dir.joinpath("merges", f"{self.sNewNameToOldName[current_name]}.ace")
            if prev_ace.exists():
                print(f">>>> previous chart: {prev_ace.resolve()}", file=sys.stderr)
                return prev_ace.resolve()
            else:
                print(f">> no previous chart for {current_name} in {previous_dir}", file=sys.stderr)
                return None
                # raise RuntimeError(f"cannot find previous merge in {previous_dir} -> {previous_dir.resolve()}")
        elif (prev_ace := previous_dir.joinpath(current_name, "styled.ace")).exists():
            return prev_ace.resolve()
        elif previous_dir.is_dir():
            # the previous report exists but has no chart for this dir (e.g. this lab/subtype
            # wasn't in that earlier report — common for the 2-back chart). Not an error:
            # previous_charts() filters None out ("eliminate not found").
            print(f">> no previous chart for {current_name} in {previous_dir}", file=sys.stderr)
            return None
        else:
            raise NotImplementedError(f"previous_dir does not exist: \"{previous_dir.resolve()}\" current_name: \"{current_name}\"")

    # ----------------------------------------------------------------------

    @classmethod
    def downloaded_raw_filename(cls) -> Path:
        """Filename of the raw as-downloaded chart (`downloaded.raw.ace`)."""
        return Path("downloaded.raw.ace")

    @classmethod
    def downloaded_filename(cls) -> Path:
        """Filename of the downloaded chart (`downloaded.ace`)."""
        return Path("downloaded.ace")

    @classmethod
    def prestyled_filename(cls) -> Path:
        """Filename of the pre-styled chart (`prestyled.ace`)."""
        return Path("prestyled.ace")

    @classmethod
    def adjusted_filename(cls) -> Path:
        """Filename of the manually-adjusted chart (`adjusted.ace`)."""
        return Path("adjusted.ace")

    @classmethod
    def link_adjusted(cls):
        """Create `adjusted.ace` as a symlink to `prestyled.ace` if it does not yet exist,
        so an un-adjusted run still has an `adjusted.ace` for the next stage."""
        if not (adj := cls.adjusted_filename()).exists():
            adj.symlink_to(cls.prestyled_filename())

    @classmethod
    def styled_filename(cls) -> Path:
        """Filename of the final styled chart (`styled.ace`)."""
        return Path("styled.ace")

    @classmethod
    def filenames_for_populating_with_seqdb(cls) -> list[Path]:
        """The chart files whose sequences should be (re)populated from seqdb: the
        downloaded, prestyled and adjusted charts."""
        return [cls.downloaded_filename(), cls.prestyled_filename(), cls.adjusted_filename()]

# ----------------------------------------------------------------------

def lab_title(lab: str):
    """Human-readable title for a lab code (e.g. "cdc" → "CDC"). Case-insensitive."""
    return VcmDirs.sLabTitle[lab.lower()]

def lab_of_dir(dir: Path) -> str:
    """Lab code parsed from the trailing `-<lab>` segment of a report directory name."""
    return dir.name.split("-")[-1]

# ======================================================================
