"""
ae.utils.format_table — render a table (list of rows, or list of dicts) as aligned text.

`format_table` computes per-column widths and formats each cell through a `Formatter`
(overridable per cell type), joining columns with a separator. `ValueFormatter` subclasses
(`Centered`, `RightAligned`) wrap individual values to control their alignment.
"""
import math

# ----------------------------------------------------------------------

class Formatter:
    """Default cell formatter for `format_table`: right-justifies ints and fixed-point
    floats, left-justifies everything else. Subclass and override `fmt` to customise."""

    # do not call it format because str has format method
    def fmt(self, row_no: int, field_no: int, field, width: int):
        """Format one cell to `width` characters: delegate to the field's own `fmt(width)`
        if it has one, else format an int/float/str by type."""
        if hasattr(field, "fmt"):
            return field.fmt(width)
        elif isinstance(field, int):
            return f"{field:{width}d}"
        elif isinstance(field, float):
            return f"{field:{width}.16f}"
        else:
            return f"{str(field):{width}s}"

class ValueFormatter:
    """Wraps a single cell value with a natural `width()`; base for per-cell alignment
    formatters like `Centered` / `RightAligned`."""

    def __init__(self, value):
        """Wrap `value`."""
        self.value = value

    def width(self) -> int:
        """Display width of the value (length of its string form)."""
        return len(str(self.value))

class Centered (ValueFormatter):
    """A cell value centred within its column width."""

    def fmt(self, width: int, **args) -> str:
        """Centre the value in `width` characters."""
        return f"{str(self.value):^{width}s}"

class RightAligned (ValueFormatter):
    """A cell value right-justified within its column width."""

    def fmt(self, width: int, **args) -> str:
        """Right-justify the value in `width` characters."""
        return f"{str(self.value):>{width}s}"

# ----------------------------------------------------------------------

def format_table(table: list, field_sep: str =" ", formatter: Formatter = None) -> str:
    """formatter is an instance of class derived from Formatter, it may override fmt method.
    """
    if not table:
        return ""
    if isinstance(table[0], list):
        return format_list_of_lists(table, field_sep=field_sep, formatter=formatter)
    else:
        return format_list_of_dicts(table, field_sep=field_sep, formatter=formatter)

# ----------------------------------------------------------------------

def format_list_of_lists(table: list, field_sep: str =" ", formatter: Formatter = None) -> str:
    """Format a list-of-rows table as aligned text: compute per-column widths, then format
    each cell with `formatter` (default `Formatter`), joining columns with `field_sep`."""

    def calculate_width(field):
        """Display width of a cell: the field's own `width()` if it has one, a padded width
        for floats, else the length of its string form."""
        if hasattr(field, "width"):
            return field.width()
        elif isinstance(field, float) and not math.isnan(field):
            return len(str(int(col))) + 17
        else:
            return len(str(field))

    if not formatter:
        formatter = Formatter()
    widths = [0] * len(table[0])
    for row in table:
        for col_no, col in enumerate(row):
            widths[col_no] = max(widths[col_no], calculate_width(col))
    return "\n".join(field_sep.join(formatter.fmt(row_no=row_no, field_no=field_no, field=field, width=widths[field_no]) for field_no, field in enumerate(row)) for row_no, row in enumerate(table))

# ----------------------------------------------------------------------
