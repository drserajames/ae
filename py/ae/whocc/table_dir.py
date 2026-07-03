"""
ae.whocc.table_dir — on-disk locations for WHO CC assay tables and their derivatives.

Given a `whocc.xlsx.Extractor` (which exposes an assay table's virus type/lineage, assay,
RBC species and lab), these helpers build the canonical paths under `$WHOCC_TABLES_DIR`:
the per-`<subtype>-<assay>-<lab>` output directory, the `<...>-<date>` filename stem, and
the xlsx / torg / ace / data-fix pathnames beneath it. Mirrors the whocc-tables layout.
"""
import os, sys
from pathlib import Path
import ae_backend

# ======================================================================

WHOCC_TABLES_DIR = Path(os.environ.get("WHOCC_TABLES_DIR"))
if not WHOCC_TABLES_DIR:
    raise RuntimeError(f"""WHOCC_TABLES_DIR env var not set""")

# ======================================================================

def subtype_assay_lab_output_dir(extractor: ae_backend.whocc.xlsx.Extractor):
    """Output directory for this table's lab/subtype/assay:
    `$WHOCC_TABLES_DIR/<virus_type_lineage>-<assay_low_rbc>-<lab_low>`."""
    print(extractor.format_assay_data(">>>> virus_type_lineage:{virus_type_lineage} assay_low_rbc:{assay_low_rbc} lab_low:{lab_low}"), file=sys.stderr)
    return WHOCC_TABLES_DIR.joinpath(extractor.format_assay_data("{virus_type_lineage}-{assay_low_rbc}-{lab_low}"))

def subtype_assay_lab_stem(extractor: ae_backend.whocc.xlsx.Extractor):
    """Filename stem for this table (no extension):
    `<virus_type_lineage>-<assay_low_rbc>-<lab_low>-<YYYYMMDD>`."""
    return extractor.format_assay_data("{virus_type_lineage}-{assay_low_rbc}-{lab_low}-{table_date:%Y%m%d}")

# ----------------------------------------------------------------------

def subtype_assay_lab_torg_pathname(extractor: ae_backend.whocc.xlsx.Extractor, torg_dir: Path = None):
    """Path of this table's `.torg` file (under `<output_dir>/torg`, or `torg_dir` if
    given). Raises RuntimeError if that directory does not exist."""
    if not torg_dir:
        torg_dir = subtype_assay_lab_output_dir(extractor=extractor).joinpath("torg")
    if not torg_dir.exists():
        raise RuntimeError(f"""Torg output dir "{torg_dir}" does not exist""")
    return torg_dir.joinpath(subtype_assay_lab_stem(extractor=extractor) + ".torg")

def subtype_assay_lab_xlsx_pathname(extractor: ae_backend.whocc.xlsx.Extractor, xlsx_dir: Path = None):
    """Path of this table's `.xlsx` file (under `<output_dir>/xlsx`, or `xlsx_dir` if
    given). Raises RuntimeError if that directory does not exist."""
    if not xlsx_dir:
        xlsx_dir = subtype_assay_lab_output_dir(extractor=extractor).joinpath("xlsx")
    if not xlsx_dir.exists():
        raise RuntimeError(f"""Xlsx output dir "{xlsx_dir}" does not exist""")
    return xlsx_dir.joinpath(subtype_assay_lab_stem(extractor=extractor) + ".xlsx")

# ----------------------------------------------------------------------

def subtype_assay_lab_ace_pathname(extractor: ae_backend.whocc.xlsx.Extractor, prn_read: bool = False, ace_dir: Path = None):
    """Return `[ace_path, prn_read_ace_path]` for this table's `.ace` output. The second
    element is None unless `prn_read` is set, in which case it points into the `prn-read/`
    subdirectory (used for PRN/neut tables read a second way). `ace_dir` overrides the
    default output directory. Raises RuntimeError if a required directory is missing."""
    if not ace_dir:
        output_dir = subtype_assay_lab_output_dir(extractor=extractor)
    else:
        output_dir = ace_dir
    if not output_dir.exists():
        raise RuntimeError(f"""ace output dir "{output_dir}" does not exist""")
    if prn_read:
        if ace_dir:
            prn_read_dir = ace_dir
        else:
            prn_read_dir = output_dir.joinpath("prn-read")
            if not prn_read_dir.exists():
                raise RuntimeError(f"""prn_read_dir "{prn_read_dir}" does not exist""")
    ace_filename = subtype_assay_lab_stem(extractor=extractor) + ".ace"
    return [
        output_dir.joinpath(ace_filename),
        prn_read_dir.joinpath(ace_filename) if prn_read else None
    ]

# ----------------------------------------------------------------------

def subtype_assay_lab_data_fix_pathname(extractor: ae_backend.whocc.xlsx.Extractor):
    """Path of this table's per-directory `ae-whocc-data-fix.py` fix-up script."""
    return subtype_assay_lab_output_dir(extractor).joinpath("ae-whocc-data-fix.py")

# ----------------------------------------------------------------------

def detect_pathname():
    """Path of the top-level `ae-whocc-detect.py` detection script under `$WHOCC_TABLES_DIR`."""
    return WHOCC_TABLES_DIR.joinpath("ae-whocc-detect.py")

# ======================================================================
