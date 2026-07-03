"""
ae.semantic.name_generator — build short antigen labels (abbreviated location/year + passage).
"""
import ae_backend

# ======================================================================

class NameGenerator:
    """Generates abbreviated antigen labels using the location database."""

    def __init__(self):
        """Open the location database."""
        self.locdb = ae_backend.locdb_v3.locdb()

    def location_isolation_year2_passaga_type(self, antigen):
        """Label `<abbrev-location>/<isolation>/<2-digit-year>-<passage-type>` for an
        antigen (falls back to the full name if it doesn't parse)."""
        if name_parsing_result := ae_backend.virus.name_parse(antigen.name()):
            name = f"{self.locdb.abbreviation(name_parsing_result.parts.location)}/{name_parsing_result.parts.isolation}/{name_parsing_result.parts.year[2:]}"
        else:
            name = antigen.name()
        return f"{name}-{self.passage_type(antigen)}"

    def location_year2_passaga_type(self, antigen):
        """Label `<abbrev-location>/<2-digit-year>-<passage-type>` for an antigen (no
        isolation; falls back to the full name if it doesn't parse)."""
        if name_parsing_result := ae_backend.virus.name_parse(antigen.name()):
            name = f"{self.locdb.abbreviation(name_parsing_result.parts.location)}/{name_parsing_result.parts.year[2:]}"
        else:
            name = antigen.name()
        return f"{name}-{self.passage_type(antigen)}"

    def passage_type(self, antigen):
        """Passage-type suffix: `<reassortant>-egg` for a reassortant, else the passage type
        (egg / cell / …)."""
        if reassortant := antigen.reassortant():
            return f"{reassortant}-egg"
        else:
            return antigen.passage().passage_type()
