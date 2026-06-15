#include <filesystem>
#include <string>
#include <string_view>
#include <vector>

#include "ext/fmt.hh"
#include "tal/draw-tree.hh"
#include "tal/settings.hh"
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
        ae::tal::TreeDrawParameters params;
        std::string_view settings_file;
        for (int i = 1; i < argc; ++i) {
            const std::string_view arg{argv[i]};
            if (arg == "--labels")
                params.labels = true;
            else if (arg == "--labels-overlap")
                params.labels_avoid_collisions = false;
            else if (arg == "--color-by-clade")
                params.color_by_clade = true;
            else if (arg == "--color-by-continent")
                params.color_by_continent = true;
            else if (arg.substr(0, 15) == "--color-by-pos=")
                params.color_by_pos = std::stoi(std::string{arg.substr(15)});
            else if (arg == "--clades")
                params.clades = true;
            else if (arg == "--time-series")
                params.time_series = true;
            else if (arg.substr(0, 11) == "--interval=")
                params.time_series_interval = std::string{arg.substr(11)};
            else if (arg == "--legend")
                params.legend = true;
            else if (arg == "--aa-transitions")
                params.aa_transitions = true;
            else if (arg == "--aa-transitions-compute")
                params.aa_transitions_compute = true;
            else if (arg.substr(0, 11) == "--dash-bar=")
                params.dash_bars.push_back(ae::tal::DashBarAAAt{.pos = std::stoi(std::string{arg.substr(11)})});
            else if (arg.substr(0, 8) == "--title=")
                params.title = std::string{arg.substr(8)};
            else if (arg.substr(0, 24) == "--width-to-height-ratio=")
                params.width_to_height_ratio = std::stod(std::string{arg.substr(24)});
            else if (arg.substr(0, 11) == "--settings=")
                settings_file = arg.substr(11);
            else
                positional.push_back(arg);
        }
        if (positional.size() < 2) {
            fmt::print(stderr,
                       "Usage: {} [--settings=config.json] [--labels] [--color-by-clade] [--clades]\n"
                       "          [--color-by-continent] [--color-by-pos=N]\n"
                       "          [--time-series] [--interval=year|month|week|day] [--legend] [--aa-transitions]\n"
                       "          [--title=TEXT] <tree.newick|tree.json[.xz]> <output.pdf> [image-size-px]\n"
                       "  --settings=FILE loads all draw options (incl. per-clade colour/name overrides) from\n"
                       "  a JSON config; other flags are ignored when it is given (image-size-px still overrides).\n",
                       argv[0]);
            return 1;
        }
        // --settings provides the full declarative config; a positional image-size still wins.
        double image_size = 1000.0;
        if (!settings_file.empty())
            params = ae::tal::load_draw_settings(std::filesystem::path{settings_file}, &image_size);
        if (positional.size() > 2)
            image_size = std::stod(std::string{positional[2]});
        const auto tree = ae::tree::load(std::filesystem::path{positional[0]});
        const std::size_t labels_hidden = ae::tal::export_tree_pdf(*tree, std::filesystem::path{positional[1]}, image_size, params);
        fmt::print("Wrote {} ({:.0f}x{:.0f}, {} leaves{}{}{}{})\n", positional[1], image_size, image_size, tree->number_of_leaves(), params.labels ? ", labelled" : "",
                   params.clades ? ", clades" : "", params.time_series ? ", time-series" : "",
                   labels_hidden > 0 ? fmt::format(", {} labels hidden to avoid overlap", labels_hidden) : std::string{});
    }
    catch (std::exception& err) {
        fmt::print(stderr, "ERROR: {}\n", err.what());
        exit_code = 2;
    }
    return exit_code;
}

// ----------------------------------------------------------------------
