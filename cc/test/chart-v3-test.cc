#include <cstdlib>
#include <array>

#include <catch2/catch_test_macros.hpp>
#include <catch2/catch_session.hpp>

#include "utils/float.hh"
#include "chart/v3/chart.hh"

// ----------------------------------------------------------------------

TEST_CASE("best stress", "[stress]") {
    const char* ae_root = std::getenv("AE_ROOT");
    REQUIRE(ae_root != nullptr);

    ae::chart::v3::Chart chart{std::filesystem::path{ae_root} / "test" / "chart1.ace"};
    REQUIRE(chart.antigens().size() == ae::antigen_index{22});
    REQUIRE(chart.sera().size() == ae::serum_index{10});
    REQUIRE(chart.number_of_points() == ae::point_index{32});
    REQUIRE(chart.projections().empty());
    REQUIRE(chart.titers().number_of_antigens() == chart.antigens().size());
    REQUIRE(chart.titers().number_of_sera() == chart.sera().size());
    REQUIRE(chart.titers().number_of_non_dont_cares() == 220);
    const std::array expected_column_bases{3.0, 5.0, 4.0, 4.0, 5.0, 6.0, 5.0, 5.0, 6.0, 5.0};
    for (const auto sr_no : chart.sera().size())
        REQUIRE(float_equal(chart.titers().raw_column_basis(sr_no), expected_column_bases[*sr_no]));

    chart.relax(ae::chart::v3::number_of_optimizations_t{1000}, ae::chart::v3::minimum_column_basis{"none"}, ae::number_of_dimensions_t{2}, ae::chart::v3::optimization_options{});
    chart.projections().sort(chart);
    REQUIRE(std::abs(chart.projections().best().stress() - 66.12473) < 10e-4);
}

// ----------------------------------------------------------------------

// Regression: setting a viewport on a semantic style with no other members used to
// serialize as "name": {,"V": [...]} -- a spurious leading comma before the
// first/only member -- which chart.export() (and any downstream json parser) rejects.
TEST_CASE("semantic style export: viewport as sole member", "[styles][export]") {
    const char* ae_root = std::getenv("AE_ROOT");
    REQUIRE(ae_root != nullptr);

    ae::chart::v3::Chart chart{std::filesystem::path{ae_root} / "test" / "chart1.ace"};
    chart.styles().find("empty-style-with-viewport").viewport = ae::draw::v2::Viewport{1.0, 2.0, 3.0, 4.0};

    const auto exported = chart.export_to_json();
    REQUIRE_NOTHROW([&]() { ae::chart::v3::Chart{std::string_view{exported}}; }());

    ae::chart::v3::Chart reloaded{std::string_view{exported}};
    const auto* style = reloaded.styles().find_if_exists("empty-style-with-viewport");
    REQUIRE(style != nullptr);
    REQUIRE(style->viewport.has_value());
    REQUIRE(style->viewport.value() == ae::draw::v2::Viewport{1.0, 2.0, 3.0, 4.0});
    REQUIRE(style->modifiers.empty());
}

// Combination of members must also serialize/round-trip correctly (priority, a
// modifier, legend, and viewport all present on the same style).
TEST_CASE("semantic style export: viewport combined with other members", "[styles][export]") {
    const char* ae_root = std::getenv("AE_ROOT");
    REQUIRE(ae_root != nullptr);

    ae::chart::v3::Chart chart{std::filesystem::path{ae_root} / "test" / "chart1.ace"};
    auto& style = chart.styles().find("combined-style");
    style.priority = 3;
    style.viewport = ae::draw::v2::Viewport{-1.0, -2.0, 5.0, 6.0};
    auto& modifier = style.modifiers.emplace_back();
    modifier.parent = "combined-style";
    modifier.selector.as_object()["C"] = std::string_view{"test-clade"};

    const auto exported = chart.export_to_json();
    REQUIRE_NOTHROW([&]() { ae::chart::v3::Chart{std::string_view{exported}}; }());

    ae::chart::v3::Chart reloaded{std::string_view{exported}};
    const auto* reloaded_style = reloaded.styles().find_if_exists("combined-style");
    REQUIRE(reloaded_style != nullptr);
    REQUIRE(reloaded_style->priority == 3);
    REQUIRE(reloaded_style->viewport.value() == ae::draw::v2::Viewport{-1.0, -2.0, 5.0, 6.0});
    REQUIRE(reloaded_style->modifiers.size() == 1);
}

int main(int argc, const char* const* argv)
{
    return Catch::Session().run( argc, argv );
}

// ----------------------------------------------------------------------
