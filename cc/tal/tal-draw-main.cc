#include <filesystem>
#include <string>
#include <string_view>
#include <vector>

#include "ext/fmt.hh"
#include "tal/draw-tree.hh"
#include "tree/tree.hh"

// ----------------------------------------------------------------------
// tal-draw — Phase B M1 CLI for the TAL port: render a phylogenetic tree
// (Newick or phylo-tree-v3 JSON) to a PDF. Mirrors chart-draw (subsystem #1);
// Cairo is linked only into this target. See cc/tal/PORTING.md.

int main(int argc, char* const argv[])
{
    int exit_code = 0;
    try {
        std::vector<std::string_view> positional;
        bool labels = false;
        for (int i = 1; i < argc; ++i) {
            const std::string_view arg{argv[i]};
            if (arg == "--labels")
                labels = true;
            else
                positional.push_back(arg);
        }
        if (positional.size() < 2) {
            fmt::print(stderr, "Usage: {} [--labels] <tree.newick|tree.json[.xz]> <output.pdf> [image-size-px]\n", argv[0]);
            return 1;
        }
        const double image_size = positional.size() > 2 ? std::stod(std::string{positional[2]}) : 1000.0;
        const auto tree = ae::tree::load(std::filesystem::path{positional[0]});
        ae::tal::export_tree_pdf(*tree, std::filesystem::path{positional[1]}, image_size, labels);
        fmt::print("Wrote {} ({:.0f}x{:.0f}, {} leaves{})\n", positional[1], image_size, image_size, tree->number_of_leaves(), labels ? ", labelled" : "");
    }
    catch (std::exception& err) {
        fmt::print(stderr, "ERROR: {}\n", err.what());
        exit_code = 2;
    }
    return exit_code;
}

// ----------------------------------------------------------------------
