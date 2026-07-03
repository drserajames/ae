"""
ae.utils.json — JSON dump/load with a compact, wide-line pretty-printer.

Produces AD-style `.ace`-friendly JSON: nested objects/arrays are indented, but "simple"
small ones — and anything whose multi-line form fits under a width limit — collapse onto a
single line. At the top level it prepends an Emacs `js-indent-level` marker. `loads` is
just `json.loads`.
"""
import json
from pathlib import Path

# ======================================================================

loads = json.loads

# ----------------------------------------------------------------------

def _json_simple(d):
    r = True
    if isinstance(d, dict):
        r = not any(isinstance(v, (list, tuple, set, dict)) for v in d.values()) and len(d) < 17
    elif isinstance(d, (tuple, list)):
        r = not any(isinstance(v, (list, tuple, set, dict)) for v in d)
    return r

# ----------------------------------------------------------------------

def dumps(data: dict, separators=[',', ': '], indent=None, compact=True, sort_keys=False, simple=_json_simple, one_line_max_width=200, object_fields_sorting_key=None):
    """Serialize `data` to a JSON string. With `compact` and an `indent`, use the wide-line
    pretty-printer (`_json_dumps`); otherwise fall back to stdlib `json.dumps`. Strips a
    leading `_` key and, when indenting, prepends the Emacs indent-level marker."""
    # module_logger.info('json.dumps: {!r}'.format(data))
    if isinstance(data, dict):
        data.pop("_", None)
    if indent is not None and compact:
        result = _json_dumps(data, indent=indent, indent_increment=indent, simple=simple, one_line_max_width=one_line_max_width, object_fields_sorting_key=object_fields_sorting_key)
    else:
        result = json.dumps(data, separators=separators, indent=indent, sort_keys=sort_keys)
        if indent and isinstance(data, dict):
            result = "{{{:<{}s}\"_\":\"-*- js-indent-level: {} -*-\",".format("", indent - 1, indent) + result[1:]
    return result

# ----------------------------------------------------------------------

class JSONEncoder (json.JSONEncoder):
    """`json.JSONEncoder` that serialises `Path` objects as their string form."""

    def default(self, o):
        """Encode a `Path` as its string form; defer other types to the base encoder."""
        if isinstance(o, Path):
            r = str(o)
        # elif hasattr(o, "json"):
        #     r = o.json()
        else:
            # r = "<" + str(type(o)) + " : " + repr(o) + ">"
            super().default(o)
        return r

# ----------------------------------------------------------------------

def _json_dumps(data, indent=2, indent_increment=None, simple=_json_simple, toplevel=True, one_line_max_width=200, object_fields_sorting_key=None):
    """More compact dumper with wide lines."""

    def end(symbol, indent):
        """The closing `symbol` (`}` / `]`) indented to the enclosing level."""
        if indent > indent_increment:
            r = "{:{}s}{}".format("", indent - indent_increment, symbol)
        else:
            r = symbol
        return r

    def make_one_line(data):
        """Serialise `data` compactly on a single line (object keys sorted)."""
        if isinstance(data, set):
            s = json.dumps(sorted(data, key=object_fields_sorting_key), cls=JSONEncoder)
        elif isinstance(data, dict):
            s = "{"
            for no, k in enumerate(sorted(data, key=object_fields_sorting_key), start=1):
                comma = ", " if no < len(data) else ""
                s += "{}: {}{}".format(json.dumps(k, cls=JSONEncoder), _json_dumps(data[k], indent=0, indent_increment=None, simple=simple, toplevel=False, object_fields_sorting_key=object_fields_sorting_key), comma)
            s += "}"
        else:
            s = json.dumps(data, sort_keys=True, ensure_ascii=False, cls=JSONEncoder)
        return s

    def make_object(data):
        """Serialise a dict as indented multi-line output (with the top-level indent marker
        when `toplevel`), recursing into values."""
        if toplevel:
            r = ["{{{:<{}s}\"_\":\"-*- js-indent-level: {} -*-\",".format("", indent_increment - 1, indent_increment)]
        else:
            r = ["{"]
        for no, k in enumerate(sorted(data, key=object_fields_sorting_key), start=1):
            comma = "," if no < len(data) else ""
            r.append("{:{}s}{}: {}{}".format("", indent, json.dumps(k, cls=JSONEncoder), _json_dumps(data[k], indent + indent_increment, indent_increment, simple=simple, toplevel=False, object_fields_sorting_key=object_fields_sorting_key), comma))
        r.append(end("}", indent))
        return r

    # --------------------------------------------------

    if indent_increment is None:
        indent_increment = indent
    if indent == 0 or simple(data):
        s = make_one_line(data)
    else:
        r = []
        if isinstance(data, dict):
            r.extend(make_object(data))
        elif isinstance(data, (tuple, list)):
            r.append("[")
            for no, v in enumerate(data, start=1):
                comma = "," if no < len(data) else ""
                r.append("{:{}s}{}{}".format("", indent, _json_dumps(v, indent + indent_increment, indent_increment, simple=simple, toplevel=False, object_fields_sorting_key=object_fields_sorting_key), comma))
            r.append(end("]", indent))
        else:
            raise ValueError("Cannot serialize: {!r}".format(data))
        s = "\n".join(r)
        if "\n" in s and len(s) < one_line_max_width:
            s = make_one_line(data)
    return s

# ======================================================================
