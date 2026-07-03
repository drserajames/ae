"""
ae.whocc.data_fix — base class for per-table WHO CC data corrections.

During xlsx→torg conversion each field (lab, assay, subtype, rbc, lineage, and every
antigen / serum / titer) is passed through a `DataFix`. The base methods are identity
pass-throughs; a per-directory `ae-whocc-data-fix.py` subclasses `DataFix` and overrides
the relevant ones (using the `fix_antigen_serum_field` / `remove_antigen_serum_annotations`
helpers) to correct known data errors for that lab/subtype table.
"""
import re
import ae_backend

# ======================================================================

class DataFix:
    "Base class for lab/subtype specific datafixer in modules located in ${WHOCC_TABLES_DIR}/subype-assy-lab"

    def __init__(self, extractor: ae_backend.whocc.xlsx.Extractor):
        """Bind the fixer to the table's `Extractor`."""
        self.extractor = extractor

    def lab(self, lab):
        """Return the lab unchanged — override to correct it."""
        return lab

    def assay(self, assay):
        """Return the assay unchanged — override to correct it."""
        return assay

    def subtype(self, subtype):
        """Return the subtype unchanged — override to correct it."""
        return subtype

    def rbc(self, rbc):
        """Return the RBC species unchanged — override to correct it."""
        return rbc

    def lineage(self, lineage):
        """Return the lineage unchanged — override to correct it."""
        return lineage

    # ----------------------------------------------------------------------

    def antigen(self, antigen: dict, antigen_no: int):
        """Return the antigen dict unchanged — override to fix its name/passage/etc."""
        return antigen

    def serum(self, serum: dict, serum_no: int):
        """Return the serum dict unchanged — override to fix it."""
        return serum

    def titer(self, titer: str, antigen_no: int, serum_no: int):
        """Return the titer string unchanged — override to fix it."""
        return titer

    # ----------------------------------------------------------------------

    # table: list of lists of two elements: regex, re.sub replacement pattern
    #   e.g. [[re.compile(r"/IRE/(87733/(?:20)?19|84630/(?:20)?18)", re.I), r"/IRELAND/\g<1>"]]
    # ag_sr: "AG" or "SR"
    #   e.g. serum["name"] = self.fix_antigen_serum_field(source=serum["name"], field_name="name", ag_sr="SR", no=serum_no, table=self.sReSerumName)

    def fix_antigen_serum_field(self, source: str, field_name: str, ag_sr: str, no: str, table: list):
        """Apply a list of `(regex, replacement)` substitutions to a field value, logging any
        change. Helper for override methods (`ag_sr` is "AG"/"SR", `no` the point index)."""
        fixed = source
        for rex, replacement in table:
            # print(f"rex: {rex} repl: {replacement}")
            fixed = rex.sub(replacement, fixed)
        if fixed != source:
            print(f">>> {ag_sr} {no:3d} {field_name} \"{fixed}\" <- \"{source}\"")
        return fixed

    def remove_antigen_serum_annotations(self, source: dict, ag_sr: str, no: str, pattern: re.Pattern):
        """Clear an antigen/serum entry's `annotations` when they match `pattern`, logging
        the removal. Helper for override methods."""
        if (annotations := source.get("annotations")) and pattern.match(annotations):
            source["annotations"] = ""
            print(f">>> {ag_sr} {no:3d} annotations removed: \"{annotations}\"")
        return source

# ======================================================================
