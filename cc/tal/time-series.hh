#pragma once

#include <string>
#include <string_view>
#include <vector>

// ======================================================================
// TAL (subsystem #3) — headless time series (date bucketing).
//
// A port of the data side of acmacs-tal's TimeSeries element: shown leaves are
// bucketed by their isolation date into a contiguous run of equal-interval
// slots (year / month / week / day) spanning the observed (or caller-supplied)
// date range. Each slot reports the number of shown leaves whose date falls in
// [first, after_last). The drawing of these as dash columns is Phase B, blocked
// on subsystem #1 — see cc/tal/PORTING.md.
//
// Reuses ae::date date parsing and C++20 <chrono> interval arithmetic, rather
// than porting acmacs-base/time-series wholesale. Leaf dates come from the
// phylo-tree-v3 JSON "d" field (ae::tree::Leaf::date).
// ======================================================================

namespace ae::tree
{
    class Tree;
}

namespace ae::tal
{
    enum class TimeSeriesInterval { year, month, week, day };

    struct TimeSeriesSlot
    {
        std::string first{};       // inclusive start, "YYYY-MM-DD"
        std::string after_last{};  // exclusive end, "YYYY-MM-DD"
        std::size_t count{0};      // shown leaves whose date falls in [first, after_last)
    };

    struct TimeSeries
    {
        std::vector<TimeSeriesSlot> slots{};
        std::size_t dated_leaves{0};    // shown leaves with a parseable date
        std::size_t undated_leaves{0};  // shown leaves with no / unparseable date (excluded)
        std::size_t outside_range{0};   // dated leaves falling in no slot (only when start/end is given)
    };

    // Bucket shown leaves by date. start/end are optional "YYYY-MM-DD" bounds;
    // when empty the range is the min/max observed leaf date. week slots are
    // 7-day intervals aligned to Monday.
    TimeSeries compute_time_series(ae::tree::Tree& tree, TimeSeriesInterval interval, std::string_view start = {}, std::string_view end = {});

} // namespace ae::tal

// ======================================================================
