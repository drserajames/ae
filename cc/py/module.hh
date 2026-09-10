#pragma once

#include "ext/pybind11.hh"

// ======================================================================

namespace ae::py
{
    void sequences(pybind11::module_& mdl);
    void tree(pybind11::module_& mdl);
    void virus(pybind11::module_& mdl);
    void whocc(pybind11::module_& mdl);
    void locdb_v3(pybind11::module_& mdl);
    void chart_v3(pybind11::module_& mdl);
    void chart_v3_antigens(pybind11::module_& chart_v3_submodule);
    void chart_v3_plot_spec(pybind11::module_& chart_v3_submodule);
    void chart_v3_tests(pybind11::module_& chart_v3_submodule);
    void chart_v2(pybind11::module_& mdl);
    void utils(pybind11::module_& mdl);
    void tal(pybind11::module_& mdl); // --- tal (subsystem #3) ---
    void hidb(pybind11::module_& mdl); // --- hidb (subsystem #2) ---
    void map_draw(pybind11::module_& mdl); // --- map-draw (subsystem #1, revived) ---
    void sig_page(pybind11::module_& mdl); // --- sigp-vector: fully-vector single-canvas signature-page compositor ---

} // namespace acmacs_py

// ======================================================================
