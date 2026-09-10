#include <filesystem>
#include <tuple>
#include <vector>

#include <pybind11/stl.h>
#include <pybind11/stl/filesystem.h>

#include "tal/sig-page.hh"
#include "py/module.hh"

// ======================================================================
// Python binding for the fully-vector single-canvas signature-page compositor (sigp-vector).
// Exposes ae_backend.tal.SigPageCanvas — one Cairo PDF page onto which the section maps and the
// tree are drawn as VECTORS (no PNG tiles, no pdfjam/pdflatex, no kateri). See cc/tal/sig-page.hh
// and SIG-PAGE-COMPOSITOR.md.
// ======================================================================

void ae::py::sig_page(pybind11::module_& mdl)
{
    using namespace pybind11::literals;

    // Attach to the existing `tal` submodule (module.cc calls ae::py::tal(mdl) before ae::py::sig_page(mdl)).
    auto tal = mdl.def_submodule("tal");

    // A map job passed from Python as a tuple (style, x, y, w, h, frame) in device points.
    using JobTuple = std::tuple<std::string, double, double, double, double, bool>;

    pybind11::class_<ae::tal::SigPageCanvas>(tal, "SigPageCanvas",
        "One Cairo PDF page onto which a signature page's tree + section maps are drawn as vectors "
        "(no PNG tiles, no pdfjam/pdflatex, no kateri). Construct with the page size (device points), "
        "render the maps + tree into their sub-rects, then finish().")
        .def(pybind11::init<const std::filesystem::path&, double, double>(), "output"_a, "page_w"_a, "page_h"_a,
             pybind11::doc("Create the page: a cairo_pdf_surface of page_w x page_h device points, written to `output`, white background."))
        .def(
            "render_maps",
            [](ae::tal::SigPageCanvas& self, const std::filesystem::path& ace, unsigned projection_no, double width, const std::vector<JobTuple>& jobs) {
                std::vector<ae::tal::SigMapJob> sig_jobs;
                sig_jobs.reserve(jobs.size());
                for (const auto& [style, x, y, w, h, frame] : jobs)
                    sig_jobs.push_back(ae::tal::SigMapJob{.style = style, .x = x, .y = y, .w = w, .h = h, .frame = frame});
                self.render_maps(ace, projection_no, width, sig_jobs);
            },
            "ace"_a, "projection_no"_a, "width"_a, "jobs"_a,
            pybind11::doc("Render each job's styled map into its device rect as a vector, loading the chart `ace` once. "
                          "`jobs` is a list of (style_name, x, y, w, h, frame); `frame`=True strokes a 1px black border."))
        .def("render_tree", &ae::tal::SigPageCanvas::render_tree, "tree"_a, "settings"_a, "image_size"_a, "x"_a, "y"_a, "w"_a, "h"_a,
             pybind11::doc("Render `tree` (tal-draw settings file `settings`, height `image_size`) into the device rect (x, y, w, h) as a vector."))
        .def("finish", &ae::tal::SigPageCanvas::finish, pybind11::doc("Finalise (cairo_show_page) and write the PDF. Idempotent; also called on destruction."));
}

// ----------------------------------------------------------------------
