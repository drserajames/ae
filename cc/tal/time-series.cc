#include <algorithm>
#include <chrono>
#include <utility>

#include "tal/time-series.hh"
#include "tree/tree.hh"
#include "ext/date.hh"

// ======================================================================

namespace ae::tal
{
    // Generate contiguous slot boundaries over the half-open range [first_day, after_last),
    // exactly as acmacs-base time_series::make does (AD cc/time-series.cc:53):
    //
    //     for (auto current = detail::first(param.first, param.intervl); current < param.after_last; )
    //
    // i.e. a slot is emitted iff its own START lies before `after_last`; `after_last` is the
    // first instant NOT covered. The exclusion happens HERE and nowhere else — callers pass
    // the settings `end` through unchanged (see compute_time_series below). Applying it twice
    // (stepping `end` back a day *and* stopping the loop early) silently dropped the last slot.
    static std::vector<std::pair<std::chrono::sys_days, std::chrono::sys_days>> generate_slots(TimeSeriesInterval interval, std::chrono::sys_days first_day,
                                                                                               std::chrono::sys_days after_last)
    {
        using namespace std::chrono;
        std::vector<std::pair<sys_days, sys_days>> bounds;
        switch (interval) {
            case TimeSeriesInterval::year: {
                // AD detail::first() snaps the range start to the beginning of its year/month.
                for (year y{year_month_day{first_day}.year()}; sys_days{y / January / 1} < after_last; ++y)
                    bounds.emplace_back(sys_days{y / January / 1}, sys_days{(y + years{1}) / January / 1});
                break;
            }
            case TimeSeriesInterval::month: {
                const year_month_day first_ymd{first_day};
                for (year_month ym{first_ymd.year() / first_ymd.month()}; sys_days{ym / 1} < after_last; ym += months{1})
                    bounds.emplace_back(sys_days{ym / 1}, sys_days{(ym + months{1}) / 1});
                break;
            }
            case TimeSeriesInterval::week: {
                const sys_days monday{first_day - (weekday{first_day} - Monday)}; // align to the Monday on/before first_day
                for (sys_days s = monday; s < after_last; s += days{7})
                    bounds.emplace_back(s, s + days{7});
                break;
            }
            case TimeSeriesInterval::day: {
                for (sys_days s = first_day; s < after_last; s += days{1})
                    bounds.emplace_back(s, s + days{1});
                break;
            }
        }
        return bounds;
    }

} // namespace ae::tal

// ----------------------------------------------------------------------

ae::tal::TimeSeries ae::tal::compute_time_series(ae::tree::Tree& tree, TimeSeriesInterval interval, std::string_view start, std::string_view end)
{
    using namespace ae::tree;
    using namespace std::chrono;

    // Collect parsed dates of shown leaves (iterative pre-order, shown-only).
    std::vector<sys_days> dates;
    std::size_t undated{0};

    struct Frame
    {
        node_index_t index;
        std::size_t cursor;
    };
    std::vector<Frame> stack;
    stack.push_back({Tree::root_index(), 0});
    while (!stack.empty()) {
        Frame& frame = stack.back();
        const Inode& inode = tree.inode(frame.index);
        if (frame.cursor < inode.children.size()) {
            const node_index_t child = inode.children[frame.cursor++];
            if (is_leaf(child)) {
                const Leaf& leaf = tree.leaf(child);
                if (leaf.shown) {
                    if (leaf.date.empty()) {
                        ++undated;
                    }
                    else if (const auto ymd = ae::date::from_string(leaf.date, ae::date::allow_incomplete::yes, ae::date::throw_on_error::no); ymd.ok()) {
                        dates.push_back(sys_days{ymd});
                    }
                    else {
                        ++undated;
                    }
                }
            }
            else if (tree.inode(child).shown) {
                stack.push_back({child, 0});
            }
        }
        else {
            stack.pop_back();
        }
    }

    TimeSeries result;
    result.undated_leaves = undated;
    result.dated_leaves = dates.size();
    if (dates.empty())
        return result;

    const sys_days range_first{start.empty() ? *std::min_element(dates.begin(), dates.end())
                                              : sys_days{ae::date::from_string(start, ae::date::allow_incomplete::yes, ae::date::throw_on_error::yes)}};
    // AD keeps the settings `end` as `after_last` UNCHANGED (acmacs-base time-series.cc:90,
    // parameters::update) and excludes it once, on generate_slots' loop condition. So
    // end "2026-10" draws through September 2026, and end "2026-03" through February 2026.
    //
    // With no `end`, AD's suggest_start_end returns one interval past the bucket holding the
    // latest observed date, so that bucket IS drawn. `max leaf date + 1 day` is the same thing
    // without the interval arithmetic: the containing bucket starts on or before the max date
    // (so it is emitted), and the next one starts after it (so it is not).
    const sys_days after_last{end.empty()
                                  ? *std::max_element(dates.begin(), dates.end()) + days{1}
                                  : sys_days{ae::date::from_string(end, ae::date::allow_incomplete::yes, ae::date::throw_on_error::yes)}};

    const auto bounds = generate_slots(interval, range_first, after_last);
    // fmt::runtime: ae's year_month_day formatter delegates to sys_days at runtime,
    // so the "%Y-%m-%d" chrono spec cannot pass fmt's consteval format-string check.
    const auto ymd_str = [](sys_days day) { return fmt::format(fmt::runtime("{:%Y-%m-%d}"), year_month_day{day}); };
    for (const auto& [slot_first, slot_after_last] : bounds)
        result.slots.push_back(TimeSeriesSlot{.first = ymd_str(slot_first), .after_last = ymd_str(slot_after_last), .count = 0});

    for (const sys_days date : dates) {
        bool placed{false};
        for (std::size_t slot = 0; slot < bounds.size(); ++slot) {
            if (date >= bounds[slot].first && date < bounds[slot].second) {
                ++result.slots[slot].count;
                placed = true;
                break;
            }
        }
        if (!placed)
            ++result.outside_range;
    }

    return result;

} // ae::tal::compute_time_series

// ======================================================================
