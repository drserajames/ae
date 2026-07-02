"""Chain configuration base class (ported from acmacs_py.chain202105.chain_setup).

A per-lab driver defines `class ChainSetup (ChainSetupDefault)` overriding chains() and
source_dir(). See the sample driver referenced in the ae.whocc.chains docstring.
"""

from .error import KnownError

# ----------------------------------------------------------------------
#
# Sample driver (create <chain_dir>/Setup.py):
#
#   from pathlib import Path
#   from ae.whocc.chains import ChainSetupDefault, IndividualTableMapChain, IncrementalChain
#
#   class ChainSetup (ChainSetupDefault):
#
#       def chains(self):
#           tables = self.collect_individual_tables()
#           minimum_column_basis = "none"
#           return [IndividualTableMapChain(tables[1:], minimum_column_basis=minimum_column_basis),
#                   IncrementalChain(tables, name="f-20210524", minimum_column_basis=minimum_column_basis)]
#
#       def collect_individual_tables(self):
#           return sorted(self.source_dir().glob("*.ace"))
#
#       def source_dir(self):
#           return Path("/syn/eu/ac/whocc-tables/h3-hint-cdc")
#
#       def combine_cheating_assays(self):
#           return True
#
# ----------------------------------------------------------------------

class ChainSetupDefault:

    def __init__(self):
        pass

    def chains(self):
        raise KnownError("override ChainSetup.chains() in Setup.py")

    def number_of_optimizations(self):
        return 1000

    def number_of_dimensions(self):
        return 2

    def reorient_to(self):
        return None

    def projections_to_keep(self):
        return 10

    def disconnect_having_few_titers(self):
        return True

    def combine_cheating_assays(self):
        return False

    def ignore_tables_with_too_few_sera(self):
        "do not signal an error if a table has too few antigens or sera, just do not make individual map, but do make a merge"
        return True

    def individual_table_preprocess(self, source, output_directory):
        "e.g. remove antigens/sera of wrong lineage. return source if not preprocessing required. generate and return preprocessed chart filename in output_directory, if preprocessing required."
        return source

# ======================================================================
