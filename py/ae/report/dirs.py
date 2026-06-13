# Ported from vcm (ssm-report tooling) 2026-0119-tc2/py/vcm/v2/dirs.py — Phase 1 engine/library tier.
# working-dir conventions + lab_title/lab_of_dir. See py/ae/report/MIGRATION.md.
import sys, os
from pathlib import Path
from typing import Any, Optional
import ae.report.modules

# ======================================================================

class VcmDirs (ae.report.modules.Modules):

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
        if dir_name is None:
            dir_name = self.main_dir().stem
        if dir_name in self.sNewNameToOldName:
            return dir_name
        else:
            return None

    def title_lab(self):
        return self.sLabTitle[self.lab_from_main_dir()]

    def lab_from_main_dir(self) -> str:
        return self.main_dir().stem.split("-")[-1]

    def tc_ssm_dir_name(self) -> str:
        return self.tc_ssm_dir_path().name

    def tc_ssm_dir_path(self) -> Path:
        cwd = self.main_dir()
        if (len(cwd.parts) - cwd.parts.index("ssm")) >= 3:
            return cwd.parents[len(cwd.parts) - cwd.parts.index("ssm") - 3]
        else:
            return cwd

    def subtype_dir_name(self) -> str:
        return self.sNewNameToOldName[self.main_dir().stem]

    def main_dir(self) -> Path:
        return Path(self.main_module().__file__).resolve().parent

    def whocc_table_dir(self) -> Path:
        return Path(os.environ["WHOCC_TABLES_DIR"], self.subtype_dir_name()).resolve()

    def find_previous_chart(self, current_name: Optional[str] = None, number_of_previous: int = 1) -> Optional[Path]:
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
        else:
            raise NotImplementedError(f"previous_dir: \"{previous_dir}\" current_name: \"{current_name}\"")

    # ----------------------------------------------------------------------

    @classmethod
    def downloaded_raw_filename(cls) -> Path:
        return Path("downloaded.raw.ace")

    @classmethod
    def downloaded_filename(cls) -> Path:
        return Path("downloaded.ace")

    @classmethod
    def prestyled_filename(cls) -> Path:
        return Path("prestyled.ace")

    @classmethod
    def adjusted_filename(cls) -> Path:
        return Path("adjusted.ace")

    @classmethod
    def link_adjusted(cls):
        if not (adj := cls.adjusted_filename()).exists():
            adj.symlink_to(cls.prestyled_filename())

    @classmethod
    def styled_filename(cls) -> Path:
        return Path("styled.ace")

    @classmethod
    def filenames_for_populating_with_seqdb(cls) -> list[Path]:
        return [cls.downloaded_filename(), cls.prestyled_filename(), cls.adjusted_filename()]

# ----------------------------------------------------------------------

def lab_title(lab: str):
    return VcmDirs.sLabTitle[lab.lower()]

def lab_of_dir(dir: Path) -> str:
    return dir.name.split("-")[-1]

# ======================================================================
