#include "ext/fmt.hh"
#include "ext/range-v3.hh"
#include "utils/messages.hh"
#include "virus/passage.hh"

static size_t passage_parsing_test(bool verbose);
static size_t passage_classification_test(bool verbose);

// ======================================================================

int main(int argc, const char* const* argv)
{
    const bool verbose{argc > 1 && std::string_view{argv[1]} == "-v"};
    try {
        return static_cast<int>(passage_parsing_test(verbose) + passage_classification_test(verbose));
    }
    catch (std::exception& err) {
        fmt::print("> {}\n", err.what());
        return 1967;
    }
}

// ----------------------------------------------------------------------

struct D
{
    std::string_view raw_name;
    std::string_view expected;
};

size_t passage_parsing_test(bool verbose)
{
    const std::array data{
        D{"C1", "MDCK1"},                                                                                                       //
        D{"MDCK1", "MDCK1"},                                                                                                    //
        D{"MDCK1/SIAT1", "MDCK1/SIAT1"},                                                                                        //
        D{"MDCK1,SIAT1", "MDCK1/SIAT1"},                                                                                        //
        D{"MDCK1, SIAT1", "MDCK1/SIAT1"},                                                                                       //
        D{"Mdck1, Siat1", "MDCK1/SIAT1"},                                                                                       //
        D{"MDCKX,MDCK1", "MDCK?/MDCK1"},                                                                                        //
        D{"MDCKX, MDCK1", "MDCK?/MDCK1"},                                                                                       //
        D{"Passage-C1", "MDCK1"},                                                                                               //
        D{"SIAT-1/MDCK1", "SIAT1/MDCK1"},                                                                                       //
        D{"C2+C1", "MDCK2/MDCK1"},                                                                                              //
        D{"MDCK 2 +1", "MDCK2/MDCK1"},                                                                                          //
        D{"MDCKx\\MDCK2", "MDCK?/MDCK2"},                                                                                       //
        D{"X1", "X1"},                                                                                                          //
        D{"X", "X?"},                                                                                                           //
        D{"X/MDCK1", "X?/MDCK1"},                                                                                               //
        D{"E2 (2012-11-01)", "E2 (2012-11-01)"},                                                                                //
        D{"passage details: MDCKX, MDCK2", "MDCK?/MDCK2"},                                                                      //
        D{"Original", "OR"},                                                                                                    //
        D{"Original Specimen", "OR"},                                                                                           //
        D{"Original Sample", "OR"},                                                                                             //
        D{"passage: Original", "OR"},                                                                                           //
        D{"passage details: original specimen", "OR"},                                                                          //
        D{"CS", "OR"},                                                                                                          //
        D{"Clinical Specimen", "OR"},                                                                                           //
        D{"10 passages - embryonated chicken eggs; Passage Line 5", "10 PASSAGES - EMBRYONATED CHICKEN EGGS; PASSAGE LINE 5"}, //
        D{"embryonated hen egg", "EMBRYONATED HEN EGG"},                                                                       //
        D{"MDCK1/MK2", "MDCK1/MK2"},                                                                                           //
        D{"E3/SPE1", "E3/SPE1"},                                                                                               //
        D{"E3/SPE1/E1", "E3/SPE1/E1"},                                                                                         //
        D{"M1", "MK1"},                                                                                                        //
    };

    size_t errors = 0;
    ae::virus::passage::parse_settings settings{ae::virus::passage::parse_settings::tracing::no};
    for (const auto [no, entry] : ranges::views::enumerate(data)) {
        try {
            ae::Messages messages;
            const auto result = ae::virus::passage::parse(entry.raw_name, settings, messages, ae::MessageLocation{"test", no}).construct();
            // if (verbose)
            //     fmt::print(">>>  \"{}\"\n", entry.raw_name);
            if (result != entry.expected) {
                fmt::print("> {:60s} <-- \"{}\"  expected: \"{}\"\n", fmt::format("\"{}\"", result), entry.raw_name, entry.expected);
                ++errors;
                if (!messages.empty())
                    fmt::print("{}", messages.report());
            }
            else if (verbose)
                fmt::print("  {:60s} <-- \"{}\"\n", fmt::format("\"{}\"", result), entry.raw_name);
        }
        catch (std::exception& err) {
            fmt::print("> {}: {}\n", entry.raw_name, err.what());
            throw;
        }
    }
    // fmt::print("{}\n", messages.report());
    if (errors)
        fmt::print("> {} errors found", errors);
    return errors;

} // passage_parsing_test

// ----------------------------------------------------------------------

// ----------------------------------------------------------------------

struct CD
{
    std::string_view raw_name;
    bool egg;
    bool cell;
};

// egg/cell classification (Passage::is_egg / is_cell -> deconstructed_t::last().egg()/cell()).
// This is what chart select_antigens(passage_is(...)) and hence semantic.vaccine.find() rely on.
size_t passage_classification_test(bool verbose)
{
    const std::array data{
        // --- the cases this test was added for: "MK" (monkey kidney) and "SPE" (SPF egg) ---
        CD{"MDCK1/MK2", false, true},  // Crick B/Vic
        CD{"E3/SPE1", true, false},    // Crick B/Vic
        CD{"E3/SPE1/E1", true, false}, // VIDRL - last element E1, egg before and after
        CD{"MK1", false, true},        //
        CD{"SPE4/SPE3", true, false},  // NIID - SPE in both elements
        CD{"M1", false, true},         // conversion::apply maps bare "M" -> "MK"
        // --- QMC (cell), SPF and D (egg) ---
        CD{"QMC2", false, true},       // CDC/VIDRL qualified MDCK cell
        CD{"QMC2/SIAT1", false, true}, // CDC
        CD{"QMC2/HCK1", false, true},  // NIID
        CD{"QMC1/QMC9", false, true},  //
        CD{"SPF2", true, false},       // CDC, standalone SPF egg
        CD{"E3SPF10", true, false},    // CDC, E-prefixed, no separator
        CD{"E3SPF1/E1", true, false},  // last element E1 - egg before and after
        CD{"E3/D1", true, false},      // VIDRL
        CD{"E3/D8/D1", true, false},   // NIID
        CD{"E3/D9/SPE1/E6", true, false}, // NIID, D and SPE in one string
        CD{"SPFCK1", false, true},     // SPFCK stays CELL despite the new SPF egg token
        CD{"SPFCE2", true, false},     // and SPFCE stays egg
        // --- regressions: the token lists that were already there ---
        CD{"MDCK1", false, true},       //
        CD{"MDCK1/SIAT1", false, true}, //
        CD{"SIAT2", false, true},       //
        CD{"HCK1", false, true},        //
        CD{"MDCK1/HCK2", false, true},  // NIID
        CD{"SPFCK1", false, true},      //
        CD{"E3", true, false},          //
        CD{"E3/E1/E1", true, false},    // CNIC
        CD{"E4", true, false},          // NIID
        CD{"SPFCE2", true, false},      //
        CD{"C1", false, true},          // conversion "C" -> "MDCK"
        CD{"EGG3", true, false},        // conversion "EGG" -> "E"
        // --- neither egg nor cell ---
        CD{"OR", false, false},   //
        CD{"CS", false, false},   //
        CD{"VW10131161", false, false}, // VIDRL internal id, not a passage - still neither
        CD{"NULL1", false, false},      // placeholder - still neither
        CD{"", false, false},     // empty passage
    };

    size_t errors = 0;
    for (const auto& entry : data) {
        const ae::virus::Passage passage{entry.raw_name};
        const auto egg = passage.is_egg(), cell = passage.is_cell();
        if (egg != entry.egg || cell != entry.cell) {
            fmt::print("> \"{}\" -> \"{}\"  egg={} cell={}  expected: egg={} cell={}\n", entry.raw_name, passage.to_string(), egg, cell, entry.egg, entry.cell);
            ++errors;
        }
        else if (verbose)
            fmt::print("  {:30s} -> {:20s} egg={:5} cell={:5}\n", fmt::format("\"{}\"", entry.raw_name), fmt::format("\"{}\"", passage.to_string()), egg, cell);
    }
    if (errors)
        fmt::print("> {} classification errors found\n", errors);
    return errors;

} // passage_classification_test

// ----------------------------------------------------------------------
