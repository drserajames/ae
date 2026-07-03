"""
ae.utils.time_series — iterate calendar periods (week / month / year) over a date range.

`TimeSeriesRange` partitions a half-open date interval into consecutive week, month or
year buckets and yields their start dates (or start/end pairs, or formatted labels). Used
to build the time-series columns of report figures. Week buckets are normalised to Mondays.
"""
import sys, calendar
from typing import Optional, Generator

from . import datetime

# ======================================================================

class TimeSeriesRange:
    """A half-open date range `[first, after_last)` partitioned into `period`-sized buckets
    (`"week"`, `"month"` or `"year"`). Week ranges snap `first` back to its Monday."""

    def __init__(self, first: str|datetime.date, after_last: Optional[str|datetime.date] = None, last_inclusive: Optional[str|datetime.date] = None, period: str = "month"):
        """Build the range. Pass exactly one of `after_last` (exclusive end) or
        `last_inclusive` (inclusive end, converted to the exclusive bound). Dates may be
        `date`s or strings (parsed by ae.utils.datetime). Raises ValueError for an invalid
        `period` or if neither end bound is given."""
        if period not in ["week", "month", "year"]:
            raise ValueError(f"TimeSeriesRange: invalid period: \"{period}\"")
        self.period = period
        self._first = datetime.parse_date(first)
        if self.period == "week":
            self._first -= datetime.timedelta(days=calendar.weekday(year=self._first.year, month=self._first.month, day=self._first.day)) # monday to monday
        if after_last is not None:
            self._after_last = datetime.parse_date(after_last)
        elif last_inclusive is not None:
            self._after_last = self.next(datetime.parse_date(last_inclusive))
        else:
            raise ValueError("either after_last or last_inclusive must be passed")

    def next(self, date: datetime.date) -> datetime.date:
        """The start of the period one step after `date`."""
        match self.period:
            case "year":
                return date.replace(year=date.year + 1)
            case "month":
                if date.month == 12:
                    return date.replace(year=date.year + 1, month=1)
                else:
                    return date.replace(month=date.month + 1)
            case "week":
                return date + datetime.timedelta(days=7)
        raise ValueError(f"TimeSeriesRange: invalid period: \"{self.period}\"")

    def previous(self, date: datetime.date) -> datetime.date:
        """The start of the period one step before `date`."""
        match self.period:
            case "year":
                return date.replace(year=date.year - 1)
            case "month":
                if date.month == 1:
                    return date.replace(year=date.year - 1, month=12)
                else:
                    return date.replace(month=date.month - 1)
            case "week":
                return date - datetime.timedelta(days=7)
        raise ValueError(f"TimeSeriesRange: invalid period: \"{self.period}\"")

    def range_begin(self) -> Generator[datetime.date, None, None]:
        """Yield each period's start date across the range."""
        current = self._first
        while current < self._after_last:
            yield current
            current = self.next(current)

    def range_begin_str(self) -> Generator[str, None, None]:
        """Yield each period's start date formatted per `name_format_style()`."""
        fmt = self.name_format_style()
        current = self._first
        while current < self._after_last:
            yield current.strftime(fmt)
            current = self.next(current)

    def range_begin_end(self) -> Generator[list[datetime.date], None, None]:
        """Yield `[start, next_start]` (the half-open bounds) for each period in the range."""
        current = self._first
        while current < self._after_last:
            nx = self.next(current)
            yield [current, nx]
            current = nx

    def front(self) -> datetime.date:
        """First period's start date."""
        return self._first

    def back(self) -> datetime.date:
        """Last period's start date (the period immediately before `after_last`)."""
        return self.previous(self._after_last)

    def after_last(self) -> datetime.date:
        """Exclusive end of the range (start of the first period past the end)."""
        return self._after_last

    def front_YMD(self) -> str:
        """`front()` as a `YYYY-MM-DD` string."""
        return self._first.strftime("%Y-%m-%d")

    def back_YMD(self) -> str:
        """`back()` as a `YYYY-MM-DD` string."""
        return self.previous(self._after_last).strftime("%Y-%m-%d")

    def after_last_YMD(self) -> str:
        """`after_last()` as a `YYYY-MM-DD` string."""
        return self._after_last.strftime("%Y-%m-%d")

    def __str__(self):
        """Compact `TimeSeries[<front>, <back>]` representation."""
        return f"TimeSeries[{self.front_YMD()}, {self.back_YMD()}]"

    def name_format_style(self) -> str:
        """strftime format for this period's labels: `%Y` (year), `%Y-%m` (month) or
        `%Y-%m-%d` (week)."""
        if self.period == "year":
            return "%Y"
        elif self.period == "month":
            return "%Y-%m"
        elif self.period == "week":
            return "%Y-%m-%d"
        else:
            raise ValueError(f"TimeSeriesRange: uknown period: \"{self.period}\"")

# ======================================================================
