#include <filesystem>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "ext/fmt.hh"
#include "map-draw/draw.hh"
#include "chart/v3/chart.hh"

// ----------------------------------------------------------------------
// map-draw: headless antigenic-map renderer (fidelity port of AD ChartDraw for
// the chains-202105 web app). Output extension selects the backend: .png -> raster,
// otherwise PDF. See cc/map-draw/TODO.md.
//
//   map-draw [options] <input.ace> <output.png|pdf>
//     --size N            canvas size in px (default 800)
//     --mapi FILE         clades.mapi coloring settings file
//     --coloring KEY      mapi coloring block, e.g. clades-A(H3N2)-v1
//     --no-marks          skip recent-layer marks
//     --no-title          skip stress title
//     --no-legend         skip clade legend
//     --labels            label every point with its name (debug)
//     --serum-circles     draw 2-fold serum circles
// ----------------------------------------------------------------------

// Usage text. Printed to stdout for an explicit --help (exit 0) and to stderr on a
// usage error (exit 1). Without this, an unrecognised or misspelt flag (or --help itself)
// fell through to the positional arguments and was used as the *output path* — map-draw
// wrote a file literally named after the flag instead of erroring.
static std::string usage(std::string_view prog)
{
    return fmt::format("Usage: {0} [--size N] [--mapi FILE --coloring KEY] [--reorient-master FILE] [--no-reorient]\n"
                       "       {0}   [--procrustes FILE] [--no-populate] [--vaccines FILE] [--no-vaccines]\n"
                       "       {0}   [--no-marks] [--no-title] [--no-legend] [--labels] [--serum-circles]\n"
                       "       {0}   <input.ace> <output.png|pdf>\n"
                       "\n"
                       "  --size N             canvas size in px (default 800)\n"
                       "  --mapi FILE          clades.mapi coloring settings file\n"
                       "  --coloring KEY       mapi coloring block, e.g. clades-A(H3N2)-v1\n"
                       "  --reorient-master F  reorient against this chart instead of auto-detecting\n"
                       "  --no-reorient        skip reorientation entirely\n"
                       "  --procrustes FILE    draw with procrustes arrows to this secondary chart\n"
                       "  --no-populate        skip seqdb population\n"
                       "  --vaccines FILE      vaccine-strain data file (else auto-detected)\n"
                       "  --no-vaccines        skip vaccine marking\n"
                       "  --no-marks           skip recent-layer marks\n"
                       "  --no-title           skip stress title\n"
                       "  --no-legend          skip clade legend\n"
                       "  --labels             label every point with its name (debug)\n"
                       "  --serum-circles      draw 2-fold serum circles\n"
                       "  --help, -h           show this help\n",
                       prog);
}

int main(int argc, char* const argv[])
{
    int exit_code = 0;
    try {
        std::vector<std::string_view> positional;
        ae::map_draw::DrawSettings settings;
        bool no_reorient = false;
        std::optional<std::filesystem::path> reorient_master;
        std::optional<std::filesystem::path> secondary_ace;
        for (int i = 1; i < argc; ++i) {
            const std::string_view arg{argv[i]};
            if (arg == "--size" && i + 1 < argc)
                settings.image_size = std::stod(std::string{argv[++i]});
            else if (arg == "--mapi" && i + 1 < argc)
                settings.mapi = std::filesystem::path{argv[++i]};
            else if (arg == "--coloring" && i + 1 < argc)
                settings.coloring_key = std::string{argv[++i]};
            else if (arg == "--reorient-master" && i + 1 < argc)
                reorient_master = std::filesystem::path{argv[++i]};
            else if (arg == "--procrustes" && i + 1 < argc)
                secondary_ace = std::filesystem::path{argv[++i]};
            else if (arg == "--no-reorient")
                no_reorient = true;
            else if (arg == "--no-populate")
                settings.populate_seqdb = false;
            else if (arg == "--vaccines" && i + 1 < argc)
                settings.vaccines_file = std::filesystem::path{argv[++i]};
            else if (arg == "--no-vaccines")
                settings.mark_vaccines = false;
            else if (arg == "--no-marks")
                settings.mark_recent_layer = false;
            else if (arg == "--no-title")
                settings.draw_title = false;
            else if (arg == "--no-legend")
                settings.draw_legend = false;
            else if (arg == "--labels")
                settings.label_points = true;
            else if (arg == "--serum-circles")
                settings.draw_serum_circles = true;
            else if (arg == "--help" || arg == "-h") {
                fmt::print("{}", usage(argv[0]));
                return 0;
            }
            else if (arg.size() > 1 && arg[0] == '-') {
                // Never treat an option-looking argument as a path: an unknown (or
                // value-less) flag used to become the output filename.
                fmt::print(stderr, "ERROR: unrecognised or incomplete option: {}\n{}", arg, usage(argv[0]));
                return 1;
            }
            else
                positional.push_back(arg);
        }
        if (positional.size() < 2) {
            fmt::print(stderr, "{}", usage(argv[0]));
            return 1;
        }
        // Resolve the vaccine-strain data file (acmacs-data/semantic_vaccines.py) at runtime,
        // if not given explicitly. Never committed into ae — found via the acmacs-data dir that
        // ae-env.sh already points several data vars at ($ACMACS_DATA / $SEQDB_V4 / $LOCDB_V2).
        if (!settings.vaccines_file) {
            std::vector<std::filesystem::path> candidates;
            if (const char* p = std::getenv("ACMACS_DATA"))
                candidates.emplace_back(std::filesystem::path{p} / "semantic_vaccines.py");
            if (const char* p = std::getenv("SEQDB_V4"))
                candidates.emplace_back(std::filesystem::path{p} / "semantic_vaccines.py");
            if (const char* p = std::getenv("LOCDB_V2"))
                candidates.emplace_back(std::filesystem::path{p}.parent_path() / "semantic_vaccines.py");
            for (const auto& cand : candidates) {
                if (std::filesystem::exists(cand)) {
                    settings.vaccines_file = cand;
                    break;
                }
            }
        }

        // Procrustes mode (make_pc): --procrustes <secondary.ace> draws the primary chart
        // with arrows to the secondary. Frames on the primary's own layout (no reorient).
        if (secondary_ace) {
            const ae::chart::v3::Chart primary{std::filesystem::path{positional[0]}};
            const ae::chart::v3::Chart secondary{*secondary_ace};
            ae::map_draw::export_procrustes(primary, ae::projection_index{0}, secondary, ae::projection_index{0}, std::filesystem::path{positional[1]}, settings);
            fmt::print("Wrote {} (procrustes, {:.0f}x{:.0f})\n", positional[1], settings.image_size, settings.image_size);
            return 0;
        }

        // Reorient master: use --reorient-master if given, else auto-detect like AD's
        // find_reorient_master (reorient-master.ace in the ace dir, then its parent).
        if (!no_reorient) {
            if (reorient_master)
                settings.reorient_master = reorient_master;
            else {
                const std::filesystem::path ace{positional[0]};
                for (const auto& dir : {ace.parent_path(), ace.parent_path().parent_path()}) {
                    const auto cand = dir / "reorient-master.ace";
                    if (std::filesystem::exists(cand)) {
                        settings.reorient_master = cand;
                        break;
                    }
                }
            }
        }
        const ae::chart::v3::Chart chart{std::filesystem::path{positional[0]}};
        ae::map_draw::export_map(chart, ae::projection_index{0}, std::filesystem::path{positional[1]}, settings);
        fmt::print("Wrote {} ({:.0f}x{:.0f})\n", positional[1], settings.image_size, settings.image_size);
    }
    catch (std::exception& err) {
        fmt::print(stderr, "ERROR: {}\n", err.what());
        exit_code = 2;
    }
    return exit_code;
}

// ----------------------------------------------------------------------
