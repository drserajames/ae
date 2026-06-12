#include "tal/layout.hh"
#include "tree/tree.hh"
#include "py/module.hh"

// ======================================================================

void ae::py::tal(pybind11::module_& mdl)
{
    using namespace pybind11::literals;

    auto tal_submodule = mdl.def_submodule("tal", "phylogenetic tree drawing (TAL) — headless layout, port in progress (see cc/tal/PORTING.md)");

    pybind11::class_<ae::tal::NodeLayout>(tal_submodule, "NodeLayout")                                                                 //
        .def_readonly("node", &ae::tal::NodeLayout::node, pybind11::doc("tree node index (positive: leaf, <=0: inode)"))               //
        .def_readonly("name", &ae::tal::NodeLayout::name, pybind11::doc("leaf name; empty for inodes"))                                //
        .def_readonly("x", &ae::tal::NodeLayout::x, pybind11::doc("horizontal position = cumulative edge length from root"))           //
        .def_readonly("y", &ae::tal::NodeLayout::y, pybind11::doc("vertical position = cumulative vertical offset (leaf row)"))        //
        ;

    pybind11::class_<ae::tal::TreeLayout>(tal_submodule, "TreeLayout")                                                                          //
        .def_readonly("height", &ae::tal::TreeLayout::height, pybind11::doc("vertical extent = sum of shown-leaf vertical offsets"))            //
        .def_readonly("max_cumulative", &ae::tal::TreeLayout::max_cumulative, pybind11::doc("horizontal extent = max cumulative edge of leaves")) //
        .def_readonly("leaves", &ae::tal::TreeLayout::leaves, pybind11::doc("shown leaves, top-to-bottom order"))                               //
        .def_readonly("inodes", &ae::tal::TreeLayout::inodes, pybind11::doc("shown inodes, post-order"))                                        //
        ;

    tal_submodule.def("compute_layout", &ae::tal::compute_layout, "tree"_a,
                      pybind11::doc("compute per-node vertical/horizontal positions for tree drawing (headless; reuses cumulative edges)"));

} // ae::py::tal

// ======================================================================
