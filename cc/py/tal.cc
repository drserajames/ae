#include "tal/layout.hh"
#include "tal/clades.hh"
#include "tal/time-series.hh"
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

    // ----------------------------------------------------------------------
    // clade sections

    pybind11::class_<ae::tal::CladeSection>(tal_submodule, "CladeSection")                                                                  //
        .def_readonly("first_node", &ae::tal::CladeSection::first_node, pybind11::doc("node index of the first leaf in the run"))           //
        .def_readonly("last_node", &ae::tal::CladeSection::last_node, pybind11::doc("node index of the last leaf in the run"))              //
        .def_readonly("first_name", &ae::tal::CladeSection::first_name)                                                                     //
        .def_readonly("last_name", &ae::tal::CladeSection::last_name)                                                                        //
        .def_readonly("first_vertical", &ae::tal::CladeSection::first_vertical, pybind11::doc("vertical (row) position of the first leaf")) //
        .def_readonly("last_vertical", &ae::tal::CladeSection::last_vertical, pybind11::doc("vertical (row) position of the last leaf"))    //
        .def_property_readonly("size", &ae::tal::CladeSection::size, pybind11::doc("number of leaf rows spanned by the section"))           //
        ;

    pybind11::class_<ae::tal::Clade>(tal_submodule, "Clade")                                                                  //
        .def_readonly("name", &ae::tal::Clade::name)                                                                          //
        .def_readonly("sections", &ae::tal::Clade::sections, pybind11::doc("vertically-contiguous runs, top-to-bottom"))      //
        .def_property_readonly("number_of_leaves", &ae::tal::Clade::number_of_leaves)                                         //
        ;

    tal_submodule.def("compute_clade_sections", &ae::tal::compute_clade_sections, "tree"_a,
                      pybind11::doc("group shown leaves into per-clade vertically-contiguous sections (headless; reuses leaf clade annotations)"));

    // ----------------------------------------------------------------------
    // time series (date bucketing)

    pybind11::class_<ae::tal::TimeSeriesSlot>(tal_submodule, "TimeSeriesSlot")                                                  //
        .def_readonly("first", &ae::tal::TimeSeriesSlot::first, pybind11::doc("inclusive slot start, YYYY-MM-DD"))              //
        .def_readonly("after_last", &ae::tal::TimeSeriesSlot::after_last, pybind11::doc("exclusive slot end, YYYY-MM-DD"))      //
        .def_readonly("count", &ae::tal::TimeSeriesSlot::count, pybind11::doc("shown leaves with a date in [first, after_last)")) //
        ;

    pybind11::class_<ae::tal::TimeSeries>(tal_submodule, "TimeSeries")                                                  //
        .def_readonly("slots", &ae::tal::TimeSeries::slots, pybind11::doc("contiguous date slots, earliest first"))    //
        .def_readonly("dated_leaves", &ae::tal::TimeSeries::dated_leaves)                                              //
        .def_readonly("undated_leaves", &ae::tal::TimeSeries::undated_leaves)                                          //
        .def_readonly("outside_range", &ae::tal::TimeSeries::outside_range, pybind11::doc("dated leaves in no slot (only when start/end given)")) //
        ;

    tal_submodule.def(
        "compute_time_series",
        [](ae::tree::Tree& tree, std::string_view interval, std::string_view start, std::string_view end) {
            ae::tal::TimeSeriesInterval iv{ae::tal::TimeSeriesInterval::month};
            if (interval == "year")
                iv = ae::tal::TimeSeriesInterval::year;
            else if (interval == "month")
                iv = ae::tal::TimeSeriesInterval::month;
            else if (interval == "week")
                iv = ae::tal::TimeSeriesInterval::week;
            else if (interval == "day")
                iv = ae::tal::TimeSeriesInterval::day;
            else
                throw std::invalid_argument{fmt::format("unknown time-series interval \"{}\", supported: year, month, week, day", interval)};
            return ae::tal::compute_time_series(tree, iv, start, end);
        },
        "tree"_a, "interval"_a = "month", "start"_a = std::string_view{}, "end"_a = std::string_view{},
        pybind11::doc("bucket shown leaves by date into year/month/week/day slots (headless; reuses leaf dates)"));

} // ae::py::tal

// ======================================================================
