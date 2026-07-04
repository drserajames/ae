#pragma once

#include <optional>
#include <string>
#include <string_view>
#include <utility>

#include "utils/log.hh"          // AD_WARNING
#include "chart/v3/titers.hh"    // ae::chart::v3::sd_denominator

// ----------------------------------------------------------------------
// Shared resolution of the across-layer titer-merge SD gate (lispmds rule 5:
// a cell whose across-layer log2 titers have SD > sd_limit becomes "*").
//
// This is the SINGLE SOURCE OF TRUTH for the context-dependent defaults used by
// both chart_v3.merge (cc/py/chart-v3-antigens.cc) and Chart.set_titers_from_layers
// (cc/py/chart-v3.cc), so the two entry points can never drift apart. See
// doc/merge-types.org for the full description of the defaults matrix.
// ----------------------------------------------------------------------

namespace ae::py
{
    // Parse the sd_denominator string ("population" / "sample") used by the SD gate.
    inline ae::chart::v3::sd_denominator parse_sd_denominator(std::string_view denom)
    {
        using namespace ae::chart::v3;
        if (denom == "population")
            return sd_denominator::population;
        else if (denom == "sample")
            return sd_denominator::sample;
        AD_WARNING("unrecognized sd_denominator \"{}\" (expected \"population\" or \"sample\"), using \"population\"", denom);
        return sd_denominator::population;
    }

    // Resolve the two optional Python kwargs (sd_limit, sd_denominator) into the concrete
    // (double sd_limit, sd_denominator) pair the C++ merge/set_from_layers path consumes:
    //   neither supplied       -> threshold 1.0, population (n) denominator = legacy AD parity
    //   sd_limit supplied only -> sample (n-1, Racmacs) denominator
    //   explicit sd_denominator always wins; sd_limit == NaN disables the gate (denominator moot).
    inline std::pair<double, ae::chart::v3::sd_denominator> resolve_sd_gate(std::optional<double> sd_limit, const std::optional<std::string>& sd_denominator_arg)
    {
        using namespace ae::chart::v3;
        const bool limit_supplied = sd_limit.has_value();
        const auto denom = sd_denominator_arg
                               ? parse_sd_denominator(*sd_denominator_arg)                        // explicit wins
                               : (limit_supplied ? sd_denominator::sample                         // tuning → sample
                                                 : sd_denominator::population);                   // hands-off → AD
        return {sd_limit.value_or(1.0), denom};
    }

} // namespace ae::py

// ----------------------------------------------------------------------
