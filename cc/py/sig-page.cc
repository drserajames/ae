#include <filesystem>
#include <tuple>
#include <vector>

#include "tal/sig-page.hh"
#include "py/module.hh"

// ======================================================================
// Python binding for the single-canvas signature-page compositor (subsystem #3).
// Exposes ae_backend.tal.compose_sig_page(output, page_w, page_h, tiles) where each
// tile is (png_path, x, y, w, h, frame). See cc/tal/sig-page.hh + SIG-PAGE-COMPOSITOR.md.
// ======================================================================

void ae::py::sig_page(pybind11::module_& mdl)
{
    using namespace pybind11::literals;

    // Attach to the existing `tal` submodule if present, else create it. (module.cc calls
    // ae::py::tal(mdl) before ae::py::sig_page(mdl), so the submodule already exists.)
    auto tal = mdl.def_submodule("tal");

    using TileTuple = std::tuple<std::filesystem::path, double, double, double, double, bool>;

    tal.def(
        "compose_sig_page",
        [](const std::filesystem::path& output, double page_w, double page_h, const std::vector<TileTuple>& tiles) {
            std::vector<ae::tal::SigTile> sig_tiles;
            sig_tiles.reserve(tiles.size());
            for (const auto& [png, x, y, w, h, frame] : tiles)
                sig_tiles.push_back(ae::tal::SigTile{.png = png, .x = x, .y = y, .w = w, .h = h, .frame = frame});
            ae::tal::compose_sig_page(output, page_w, page_h, sig_tiles);
        },
        "output"_a, "page_w"_a, "page_h"_a, "tiles"_a,
        pybind11::doc("Paint PNG tiles onto ONE Cairo PDF page (single-canvas signature-page compositor). "
                      "`tiles` is a list of (png_path, x, y, w, h, frame) in device px; each PNG is scaled "
                      "into its rectangle, `frame`=True strokes a 1px black border. No pdfjam/pdflatex/kateri."));
}

// ----------------------------------------------------------------------
