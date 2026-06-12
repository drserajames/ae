"""
Lab-name constants used by the report assembler.

Extracted from AD ssm-report's ``map.py`` (sLabDisplayName) and ``stat.py``
(sLabOrder) so that the report-assembly core (report.py) does not have to import
the figure-generation modules, which depend on the not-yet-ported map-draw
subsystem.
"""

# Mapping from internal lab code (upper-case) to the display name used in the
# report. "ALL" is the combined four-lab map.
sLabDisplayName = {
    "CDC": "CDC",
    "CNIC": "CNIC",
    "NIMR": "Crick",
    "NIID": "NIID",
    "MELB": "VIDRL",
    "ALL": "CDC+Crick+NIID+VIDRL",
}

# Canonical lab ordering for signature-page addenda and statistics sections.
sLabOrder = ["CDC", "NIMR", "NIID", "MELB"]

sLabDisplayNameWithAll = {**sLabDisplayName, "all": "All labs"}
