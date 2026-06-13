#include <filesystem>
#include <string>
#include <string_view>
#include <vector>

#include "ext/fmt.hh"
#include "geo/geographic-map.hh"

// ----------------------------------------------------------------------

int main(int argc, char* const argv[])
{
    int exit_code = 0;
    try {
        std::vector<std::string_view> positional;
        for (int i = 1; i < argc; ++i)
            positional.push_back(std::string_view{argv[i]});
        if (positional.empty()) {
            fmt::print(stderr, "Usage: {} <output.pdf> [image-width-px]\n", argv[0]);
            return 1;
        }
        const double image_width = positional.size() > 1 ? std::stod(std::string{positional[1]}) : 1000.0;
        ae::geo::export_geographic_pdf(std::filesystem::path{positional[0]}, image_width);
        fmt::print("Wrote {} (world map, width {:.0f})\n", positional[0], image_width);
    }
    catch (std::exception& err) {
        fmt::print(stderr, "ERROR: {}\n", err.what());
        exit_code = 2;
    }
    return exit_code;
}

// ----------------------------------------------------------------------
