#include "utils/log.hh"
#include "chart/v3/projections.hh"
#include "chart/v3/randomizer.hh"
#include "chart/v3/stress.hh"

// ----------------------------------------------------------------------

double ae::chart::v3::Projection::stress(const Chart& chart, recalculate_stress recalculate) const
{
    switch (recalculate) {
      case recalculate_stress::yes:
          return stress_recalculate(chart);
      case recalculate_stress::if_necessary:
          if (stress_.has_value())
              return *stress_;
          else
              return stress_recalculate(chart);
      // case recalculate_stress::no:
      //     if (stress_.has_value())
      //         return *stress_;
      //     else
      //         return InvalidStress;
    }
    throw std::runtime_error{"Projection::stress: internal"};

} // ae::chart::v3::Projection::stress

// ----------------------------------------------------------------------

double ae::chart::v3::Projection::stress_recalculate(const Chart& chart) const
{
    stress_ = stress_factory(chart, *this, optimization_options{}.mult).value(layout());
    AD_DEBUG("stress_recalculate {}", *stress_);
    return *stress_;

} // ae::chart::v3::Projection::stress_recalculate

// ----------------------------------------------------------------------

void ae::chart::v3::Projection::randomize_layout(LayoutRandomizer& randomizer)
{
    for (const auto point_no : layout().number_of_points())
        layout().update(point_no, randomizer.get(layout().number_of_dimensions()));

} // ae::chart::v3::Projection::randomize_layout

// ----------------------------------------------------------------------

void ae::chart::v3::Projection::randomize_layout(const point_indexes& to_randomize, LayoutRandomizer& randomizer)
{
    for (const auto point_no : to_randomize)
        layout().update(point_no, randomizer.get(layout().number_of_dimensions()));

} // ae::chart::v3::Projection::randomize_layout

// ----------------------------------------------------------------------

ae::point_indexes ae::chart::v3::Projection::non_nan_points() const
{
    const auto& layt = layout();
    point_indexes non_nan;
    for (const auto point_no : layt.number_of_points()) {
        if (layt.point_has_coordinates(point_no))
            non_nan.insert(point_no);
    }
    return non_nan;

} // ae::chart::v3::Projection::non_nan_points

// ----------------------------------------------------------------------

// A point with no coordinates cannot take part in the optimisation, and the engines reject NaN
// outright ("MinCGCreate: X contains infinite or NaN values!"). DisconnectedPointsHandler already
// zeroes-and-restores the points a projection LISTS as disconnected, but a chart can carry a NaN
// point that is not on that list, and a single one of those aborts the whole relax.
//
// Report-pipeline charts do carry them. Over the 16 February-2026 ssm maps: 8 had NaN points that
// were all properly listed -- up to 162 of them, relaxing fine -- and 3 had 1-2 unlisted ones,
// which failed. AD disconnects such a point rather than failing, so do the same: the stress then
// excludes it and its coordinates stay NaN afterwards.
//
// This cannot change a relax that currently succeeds: it only ever adds points that have no
// coordinates, and any projection containing one of those throws today.
ae::point_indexes ae::chart::v3::Projection::disconnect_points_without_coordinates()
{
    const auto& layt = layout();
    point_indexes newly_disconnected;
    for (const auto point_no : layt.number_of_points()) {
        if (!layt.point_has_coordinates(point_no) && !disconnected_.contains(point_no)) {
            disconnected_.insert(point_no);
            newly_disconnected.insert(point_no);
        }
    }
    return newly_disconnected;

} // ae::chart::v3::Projection::disconnect_points_without_coordinates

// ----------------------------------------------------------------------

ae::chart::v3::optimization_status ae::chart::v3::Projection::relax(const Chart& chart, const optimization_options& options)
{
    disconnect_points_without_coordinates();
    const auto status = optimize(chart, *this, options);
    stress_ = status.final_stress;
    if (transformation_.number_of_dimensions != layout_.number_of_dimensions())
        transformation_.reset(layout_.number_of_dimensions());
    return status;

} // ae::chart::v3::Projection::relax

// ----------------------------------------------------------------------

void ae::chart::v3::Projection::remove_points(const point_indexes& points, antigen_index number_of_antigens)
{
    layout_.remove(points);
    stress_ = std::nullopt;
    if (!forced_column_bases_.empty()) {
        for (const auto no : points) {
            if (no.get() > number_of_antigens.get())
                forced_column_bases_.remove(serum_index{no - number_of_antigens.get()});
        }
    }
    remove_and_renumber(disconnected_, points);
    remove_and_renumber(unmovable_, points);
    remove_and_renumber(unmovable_in_the_last_dimension_, points);
    if (!avidity_adjusts_->empty()) {
        for (const auto no : points) {
            if (no.get() < number_of_antigens.get())
                avidity_adjusts_.get().erase(std::next(avidity_adjusts_->begin(), no.get()));
        }
    }

} // ae::chart::v3::Projection::remove_points

// ----------------------------------------------------------------------

void ae::chart::v3::Projections::sort(const Chart& chart)
{
    // projections with NaN stress are at the end
    std::sort(data_.begin(), data_.end(), [&chart](const auto& p1, const auto& p2) {
        const auto s1 = p1.stress(chart), s2 = p2.stress(chart);
        if (std::isnan(s1))
            return false;
        else if (std::isnan(s2))
            return true;
        else
            return s1 < s2;
    });

} // ae::chart::v3::Projections::sort

// ----------------------------------------------------------------------
