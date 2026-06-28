#include <algorithm>
#include <chrono>
#include <utility>

#include "tal/time-series.hh"
#include "tree/tree.hh"
#include "ext/date.hh"

// ======================================================================

namespace ae::tal
{
    // Generate contiguous [first, after_last) slot boundaries covering [first_day, last_day].
    static std::vector<std::pair<std::chrono::sys_days, std::chrono::sys_days>> generate_slots(TimeSeriesInterval interval, std::chrono::sys_days first_day,
                                                                                               std::chrono::sys_days last_day)
    {
        using namespace std::chrono;
        std::vector<std::pair<sys_days, sys_days>> bounds;
        switch (interval) {
            case TimeSeriesInterval::year: {
                const year first_y{year_month_day{first_day}.year()};
                const year last_y{year_month_day{last_day}.year()};
                for (year y = first_y; y <= last_y; ++y)
                    bounds.emplace_back(sys_days{y / January / 1}, sys_days{(y + years{1}) / January / 1});
                break;
            }
            case TimeSeriesInterval::month: {
                const year_month_day first_ymd{first_day}, last_ymd{last_day};
                const year_month last_ym{last_ymd.year() / last_ymd.month()};
                for (year_month ym{first_ymd.year() / first_ymd.month()}; ym <= last_ym; ym += months{1})
                    bounds.emplace_back(sys_days{ym / 1}, sys_days{(ym + months{1}) / 1});
                break;
            }
            case TimeSeriesInterval::week: {
                const sys_days monday{first_day - (weekday{first_day} - Monday)}; // align to the Monday on/before first_day
                for (sys_days s = monday; s <= last_day; s += days{7})
                    bounds.emplace_back(s, s + days{7});
                break;
            }
            case TimeSeriesInterval::day: {
                for (sys_days s = first_day; s <= last_day; s += days{1})
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
    // AD's time_series::make treats an explicit `end` as the EXCLUSIVE upper bound (the last
    // slot is the interval before `end`), so end "2026-03" yields a last month of Feb 2026.
    // generate_slots() below is inclusive of the month/year containing range_last, so step the
    // explicit end back one day to drop the `end` interval. The auto case (no end) keeps the
    // max leaf date, which must stay inclusive so the most-recent month is shown.
    const sys_days range_last{end.empty()
                                  ? *std::max_element(dates.begin(), dates.end())
                                  : sys_days{ae::date::from_string(end, ae::date::allow_incomplete::yes, ae::date::throw_on_error::yes)} - days{1}};

    const auto bounds = generate_slots(interval, range_first, range_last);
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
