"""
ae.sequences.source.ncbi — read NCBI influenza sequence dumps into (metadata, sequence).

`reader` pairs NCBI's `influenza.fna.xz` (FASTA sequences) with `influenza_na.dat.xz`
(tab-separated metadata), keyed by GenBank accession. Iterating a `reader` yields
`(metadata, sequence)` for HA (segment 4) records only, with names and dates parsed via
ae.sequences.source.parse. Consumed by the seqdb-population pipeline.
"""
import sys, re, io, pprint
from pathlib import Path

import ae_backend
from .parse import Context, parse_name, parse_date
from ...utils.timeit import timeit

# ======================================================================

class Error (RuntimeError):
    """Raised on an unrecoverable NCBI-read error."""
    pass

# ----------------------------------------------------------------------

class reader:
    """Reader over a directory of NCBI influenza dumps (`influenza.fna.xz` +
    `influenza_na.dat.xz`). Iterate it to get `(metadata, sequence)` tuples for HA records."""

    def __init__(self, ncbi_dir: Path):
        """Locate the `.fna.xz`/`.na.dat.xz` files under `ncbi_dir`; reading is deferred
        until iteration."""
        self.messages = []
        self.unrecognized_locations = set()
        self.na_dat_filename = ncbi_dir.joinpath("influenza_na.dat.xz")
        self.fna_filename = ncbi_dir.joinpath("influenza.fna.xz")

    def __iter__(self):
        """Read the metadata table, then stream the FASTA file, yielding `(metadata,
        sequence)` for each record whose GenBank id has HA metadata. The metadata dict may
        carry an "excluded" key marking records for downstream exclusion."""
        self.reader_ = ae_backend.raw_sequence.FastaReader(self.fna_filename)
        self.na_dat = self.read_influenza_na_dat(self.na_dat_filename)
        for en in self.reader_:
            self.context = Context(self, filename=self.fna_filename, line_no=en.line_no)
            if metadata := self.read_fna_name(en.raw_name, context=self.context):
                yield metadata, en.sequence # metadata may contain "excluded" key to manually exclude the sequence

    def get_and_clear_messages(self):
        """Return the accumulated parse messages and reset the buffer."""
        messages = self.messages
        self.messages = []
        return messages

    # ----------------------------------------------------------------------

    def read_fna_name(self, name: str, context: Context):
        """Map a FASTA `|`-delimited defline (5 fields) to its metadata via the GenBank
        accession (field 4). None if the record has no HA metadata (wrong segment) or the
        defline is malformed."""
        fields = name.split("|")
        if len(fields) == 5:
            # print(f">>>> {fields[3]}", file=sys.stderr)
            if metadata := self.na_dat.get(fields[3]):
                return metadata
            # if not found, it most probably means wrong segment (not HA)
        else:
            print(f">> [ncbi] invalid fna name: \"{name}\"", file=sys.stderr)
        return None

    # ----------------------------------------------------------------------

    def read_influenza_na_dat(self, filename: Path):
        """Read the whole `influenza_na.dat` table into a dict keyed by sample id, one entry
        per parsed HA row."""
        raw_data = ae_backend.read_file(filename)
        metadata = {entry["sample_id_by_sample_provider"]: entry for entry in (self.read_influenza_na_dat_entry(filename=filename, line_no=line_no, line=line) for line_no, line in enumerate(io.StringIO(raw_data), start=1)) if entry}
        # print(f">>> {len(metadata)} rows read from {filename}", file=sys.stderr)
        return metadata

        # print(f"{filename}: {len(data)}")

    def read_influenza_na_dat_entry(self, filename: Path, line_no: int, line: str):
        """Parse one tab-separated metadata row (11 fields). Returns a metadata dict for
        segment-4 (HA) rows with an extractable virus name — with name and date parsed via
        ae.sequences.source.parse — else None."""
        context = Context(self, filename=filename, line_no=line_no)
        fields = line.split("\t")
        if len(fields) != 11:
            print(f">> invalid number of fields ({len(fields)}) @@ {filename}:{line_no}", file=sys.stderr)
            return None
        if len(fields) == 11 and fields[2] == "4" and (name := self.extract_name(fields[7])): # interested in segment 4 (HA) only
            # genbank_accession, host, segment_no, subtype, country, date, sequence_length, virus_name, age, gender, completeness
            # print(f">>>> id \"{fields[0]}\"", file=sys.stderr)
            metadata = {
                "sample_id_by_sample_provider": fields[0],
                # "host": fields[1],
                # "gisaid_segment_number": fields[2],
                "type_subtype": self.parse_subtype(fields[3]),
                "country": self.parse_country(fields[4]),
                # "date": fields[5],
                # "sequence_length": fields[6],
                # "name": name,
                # "age": fields[8],
                # "gender": fields[9],
                # "completeness": fields[10],
                "line_no": line_no,
            }
            parse_name(name, metadata=metadata, context=context)
            if metadata.get("extra") == "(MIXED)":
                del metadata["extra"]
            if date := parse_date(fields[5], metadata=metadata, context=context):
                metadata["date"] = date
            # print(f">>>> metadata {metadata}", file=sys.stderr)
            return metadata
        else:
            return None

    sReSubtypeFixMixedH = re.compile(r"^\s*mixed\s*[\.,]\s*H", re.I)

    def parse_subtype(self, subtype):
        """Normalise NCBI's subtype text to ae form (e.g. `H3` → `A(H3)`); blanks out
        N-only / MIXED-only subtypes and strips `,MIXED` qualifiers (`A(H1,MIXED)` →
        `A(H1)`)."""
        subtype = subtype.upper()
        if subtype[:1] == "H":
            subtype = f"A({subtype})"
        elif mm_mixed_h := self.sReSubtypeFixMixedH.match(subtype):
            subtype = f"A(H{mm_mixed_h.end()})"
        elif subtype == "MIXED" or subtype[:1] == "N" or subtype[:7] == "MIXED,N":
            subtype = ""
        if ",MIXED" in subtype: # A(H1,MIXED) -> A(H1)
            subtype = subtype.replace(",MIXED", "")
        if "MIXED" in subtype:
            print(f">> not fixed subtype: {subtype}")
        return subtype

    def parse_country(self, country):
        """Return the country field unchanged (placeholder hook for country normalisation)."""
        return country

    def extract_name(self, name):
        """Pull the parenthesised strain name out of an `Influenza A/B virus (NAME)` title,
        or None if it doesn't match that shape."""
        try:
            if name[:17].upper() in ["INFLUENZA A VIRUS", "INFLUENZA B VIRUS"] and (paren := name.index("(")) in [17, 18] and name[-1] == ")":
                return name[paren+1:-1]
        except ValueError:
            pass
        return None

# ----------------------------------------------------------------------
