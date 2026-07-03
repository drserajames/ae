"""
ae.sequences.source.parse — shared parsing helpers for sequence-source readers.

Sequence readers (e.g. ae.sequences.source.ncbi / .fasta) turn a raw FASTA name and
assorted fields into a normalised `metadata` dict via `parse_name` / `parse_date` /
`parse_passage`, which delegate to the `ae_backend.virus` parsers. A `Context` carries the
current reader, filename and line number, accumulates parse `Message`s, and applies any
per-directory `ae.py` preprocessor hooks (`preprocess_virus_name` / `_date` / `_passage`).
"""
import sys
from pathlib import Path
from dataclasses import dataclass

import ae.utils.load_module
import ae_backend

# ======================================================================

@dataclass
class Message:
    """One parse diagnostic — either a hand-built (field/value/message) note or a wrapped
    backend `ae_backend.Message` (`message_raw`), tagged with the source filename/line."""
    field: str = None
    value: str = None
    message: str = None
    message_raw: ae_backend.Message = None
    filename: Path = None
    line_no: int = None

    def report(self):
        """Format this message as a one-line human-readable string, including the
        `file:line` location when known."""
        if self.filename:
            mloc = f" @@ {self.filename}:{self.line_no}"
        else:
            mloc = ""
        if self.message_raw:
            if self.field or self.value:
                fv = f"{self.field}[{self.value}]"
            else:
                fv = ""
            return f"{self.message_raw.type_short()} {fv}: [{self.message_raw.type}] {self.message_raw.type_subtype} {self.message_raw.value} -- {self.message_raw.context}{mloc}"
        else:
            return f"  {self.field}[{self.value}]: {self.message}{mloc}"

    def type_matches(self, types: str): # types: lowercase
        """True if this message's short type code is in `types` (a lowercase string), or if
        `types` contains "a" (match-all)."""
        return "a" in types or (self.message_raw and self.message_raw.type_short().lower() in types)

    def type_subtype(self):
        """The backend message's type/subtype string, or None for a hand-built message."""
        if self.message_raw:
            return self.message_raw.type_subtype
        else:
            return None

# ======================================================================

class Context:
    """Per-line parsing context: the owning reader plus the current `filename`/`line_no`.
    Collects `Message`s onto the reader and dispatches to optional per-directory `ae.py`
    preprocessor hooks that sit next to the input file."""

    def __init__(self, reader, filename: Path, line_no: int):
        """Bind the context to `reader` at `filename:line_no`."""
        self.reader = reader
        self.filename = filename
        self.line_no = line_no

    def message(self, field: str = None, value: str = None, message: str = None, message_raw: ae_backend.Message = None):
        """Append a `Message` — hand-built from `field`/`value`/`message`, or wrapping a
        backend `message_raw` — to the reader's message list, tagged with this location."""
        self.reader.messages.append(Message(field=field, value=value, message=message, message_raw=message_raw, filename=self.filename, line_no=self.line_no))

    def messages_from_backend(self, messages: ae_backend.Messages):
        """Append every message from a backend `ae_backend.Messages` collection to the reader."""
        for raw_message in messages:
            self.reader.messages.append(Message(message_raw=raw_message))
            # print(f">>> messages_from_backend\n{self.reader.messages[-1].report()}")

    def unrecognized_locations(self, unrecognized_locations: set):
        """Merge a set of unrecognised location strings into the reader's running set."""
        self.reader.unrecognized_locations |= unrecognized_locations

    def preprocess_virus_name(self, name, metadata: dict):
        """Run the input directory's `ae.py` `preprocess_virus_name(name, metadata)` hook if
        present, else return `name` unchanged — lets a data dir massage names before parsing."""
        if (directory_module := ae.utils.load_module.load(self.filename.parent.joinpath("ae.py"))) and (preprocessor := getattr(directory_module, "preprocess_virus_name", None)):
            return preprocessor(name, metadata)
        else:
            return name

    def preprocess_date(self, date, metadata: dict):
        """Run the input directory's `ae.py` `preprocess_date(date, metadata)` hook if
        present, else return `date` unchanged."""
        if (directory_module := ae.utils.load_module.load(self.filename.parent.joinpath("ae.py"))) and (preprocessor := getattr(directory_module, "preprocess_date", None)):
            return preprocessor(date, metadata)
        else:
            return date

    def preprocess_passage(self, passage, metadata: dict):
        """Run the input directory's `ae.py` `preprocess_passage(passage, metadata)` hook if
        present, else return `passage` unchanged."""
        if (directory_module := ae.utils.load_module.load(self.filename.parent.joinpath("ae.py"))) and (preprocessor := getattr(directory_module, "preprocess_passage", None)):
            return preprocessor(passage, metadata)
        else:
            return passage

    def file_line(self):
        """`filename:line_no` location string."""
        return f"{self.filename}:{self.line_no}"

# ======================================================================

def parse_name(name: str, metadata: dict, context: Context):
    """Parse a virus `name` and populate `metadata` in place (name, host, continent,
    country, date, reassortant, extra). The name is first run through the directory's
    `preprocess_virus_name` hook; a `<no-parse>…` prefix stores the remainder verbatim and a
    `<exclude>…` prefix marks the record excluded. Otherwise `ae_backend.virus.name_parse`
    does the work; parse failures fall back to the upper-cased name and record `Message`s
    and unrecognised locations on the context. `new_only` fields are left as-is if already set."""

    def set_metadata(key: str, value: str, new_only: bool = False):
        """Set `metadata[key] = value` when `value` is truthy; if `new_only`, leave an
        already-set key untouched."""
        if value and (not new_only or not metadata.get(key)):
            metadata[key] = value

    preprocessed_name = context.preprocess_virus_name(name, metadata)
    if preprocessed_name[:10] == "<no-parse>":
        metadata["name"] = preprocessed_name[10:].upper()
    elif preprocessed_name[:9] == "<exclude>":
        metadata["excluded"] = preprocessed_name
        metadata["name"] = preprocessed_name
    else:
        result = ae_backend.virus.name_parse(preprocessed_name, type_subtype=metadata.get("type_subtype", ""), year_hint=metadata.get("date", "")[:4], filename=context.filename, line_no=context.line_no)
        if result.good():
            metadata["name"] = result.parts.host_location_isolation_year()
        else:
            metadata["name"] = preprocessed_name.upper()
            if preprocessed_name != name:
                value = f"{preprocessed_name} (original: {name})"
            else:
                value = name
            for message in result.messages:
                context.message(field="name", value=value, message_raw=message)
            context.unrecognized_locations(result.messages.unrecognized_locations())
        set_metadata("host", result.parts.host)
        set_metadata("continent", result.parts.continent)
        set_metadata("country", result.parts.country)
        set_metadata("date", result.parts.year, new_only=True)
        set_metadata("reassortant", result.parts.reassortant, new_only=True)
        set_metadata("extra", result.parts.extra, new_only=True)

# ----------------------------------------------------------------------

def parse_date(date: str, metadata: dict, context: Context):
    """Parse a `date` string to a normalised date via `ae_backend.date_format` (incomplete
    dates allowed; month-first for CDC). Runs the `preprocess_date` hook first; `"???"` maps
    to empty. On failure, records a `Message` and returns the original string unchanged."""
    preprocessed_date = context.preprocess_date(date, metadata)
    if not preprocessed_date:
        return preprocessed_date
    elif date == "???":
        return ""
    try:
        return ae_backend.date_format(preprocessed_date, allow_incomplete=True, throw_on_error=True, month_first=metadata.get("lab") == "CDC")
    except Exception as err:
        if date != preprocessed_date:
            value = f"{preprocessed_date} (original: {date})"
        else:
            value = date
        context.message(field="date", value=value, message=str(err))
        print(f">> date not parsed: {value}", file=sys.stderr)
        return date

# ----------------------------------------------------------------------

def parse_passage(passage: str, metadata: dict, context: Context):
    """Parse a `passage` string via `ae_backend.virus.passage_parse`, returning the
    normalised passage, or the upper-cased input if it does not parse. Runs the
    `preprocess_passage` hook first."""
    preprocessed_passage = context.preprocess_passage(passage, metadata)
    result = ae_backend.virus.passage_parse(preprocessed_passage)
    if result.good():
        return result.passage()
    else:
        return passage.upper()

# ======================================================================
