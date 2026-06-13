#pragma once

#include <filesystem>

#include "tal/draw-tree.hh"

// ======================================================================
// TAL (subsystem #3) — Phase C: settings DSL (declarative JSON config).
//
// A bounded first slice of the acmacs-tal settings layer: instead of porting the
// full settings-v3 mod pipeline (node selection + if/then + ~71 KB of built-in
// commands), tal-draw can read a single declarative JSON file describing the
// drawing. It maps straight onto TreeDrawParameters and adds what CLI flags
// cannot express — notably per-clade colour / display-name overrides.
//
// Schema (all keys optional):
//   {
//     "image_size": 1000,
//     "title": "A(H3N2) HA",
//     "labels": true,
//     "color_by_clade": true,
//     "clades":         { "show": true },
//     "time_series":    { "show": true, "interval": "year", "start": "", "end": "" },
//     "legend":         { "show": true },
//     "aa_transitions": { "show": true },
//     "clade_styles": [ { "name": "3C.2a1b", "color": "#1f77b4", "display_name": "2a1b" } ]
//   }
// ======================================================================

namespace ae::tal
{
    // Load a tal-draw JSON settings file into draw parameters. If image_size is
    // non-null and the file has an "image_size" key, it is written there.
    // Throws std::runtime_error / rjson parse errors on malformed input.
    TreeDrawParameters load_draw_settings(const std::filesystem::path& file, double* image_size = nullptr);

} // namespace ae::tal

// ======================================================================
