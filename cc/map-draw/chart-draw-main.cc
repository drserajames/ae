#include <filesystem>
#include <string>

#include "ext/fmt.hh"
#include "map-draw/draw.hh"
#include "chart/v3/chart.hh"

// ----------------------------------------------------------------------

int main(int argc, char* const argv[])
{
    int exit_code = 0;
    try {
        if (argc < 3) {
            fmt::print(stderr, "Usage: {} <input.ace> <output.pdf> [image-size-px]\n", argv[0]);
            return 1;
        }
        const double image_size = argc > 3 ? std::stod(argv[3]) : 800.0;
        const ae::chart::v3::Chart chart{std::filesystem::path{argv[1]}};
        ae::map_draw::export_pdf(chart, ae::projection_index{0}, std::filesystem::path{argv[2]}, image_size);
        fmt::print("Wrote {} ({:.0f}x{:.0f})\n", argv[2], image_size, image_size);
    }
    catch (std::exception& err) {
        fmt::print(stderr, "ERROR: {}\n", err.what());
        exit_code = 2;
    }
    return exit_code;
}

// ----------------------------------------------------------------------
