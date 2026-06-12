#include <filesystem>
#include <string>
#include <string_view>
#include <vector>

#include "ext/fmt.hh"
#include "map-draw/draw.hh"
#include "chart/v3/chart.hh"

// ----------------------------------------------------------------------

int main(int argc, char* const argv[])
{
    int exit_code = 0;
    try {
        std::vector<std::string_view> positional;
        bool label_points = false;
        for (int i = 1; i < argc; ++i) {
            if (const std::string_view arg{argv[i]}; arg == "--labels")
                label_points = true;
            else
                positional.push_back(arg);
        }
        if (positional.size() < 2) {
            fmt::print(stderr, "Usage: {} [--labels] <input.ace> <output.pdf> [image-size-px]\n", argv[0]);
            return 1;
        }
        const double image_size = positional.size() > 2 ? std::stod(std::string{positional[2]}) : 800.0;
        const ae::chart::v3::Chart chart{std::filesystem::path{positional[0]}};
        ae::map_draw::export_pdf(chart, ae::projection_index{0}, std::filesystem::path{positional[1]}, image_size, label_points);
        fmt::print("Wrote {} ({:.0f}x{:.0f}{})\n", positional[1], image_size, image_size, label_points ? ", labelled" : "");
    }
    catch (std::exception& err) {
        fmt::print(stderr, "ERROR: {}\n", err.what());
        exit_code = 2;
    }
    return exit_code;
}

// ----------------------------------------------------------------------
