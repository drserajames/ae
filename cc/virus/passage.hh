#pragma once

#include <string>
#include <vector>

#include "ext/fmt.hh"
#include "ext/compare.hh"
#include "utils/string.hh"
#include "utils/messages.hh"

// ======================================================================

namespace ae::virus::passage
{
    // Compound cell-line names, e.g. Crick's "MDCK-MIX2/MDCK1" and its unhyphenated spelling
    // "MDCKMIX2". They are longer than the 5-character limit a plain passage name gets, and
    // "MDCK-MIX"/"MDCKMIX" end in an X that is part of the name rather than an unknown-count
    // marker. THREE places rely on this one list, which is why it lives here and not in the
    // grammar: passage-parse accepts an over-long name only if it is one of these,
    // conversion::apply must not strip their trailing X, and element_t::cell() classifies them.
    inline bool is_compound_cell_name(std::string_view name)
    {
        return name == "MDCK-MIX" || name == "MDCK-SIAT" || name == "MDCK-ATL" || name == "MDCKMIX";
    }

    struct deconstructed_t
    {
        struct element_t
        {
            std::string name{};
            std::string count{}; // if count empty, name did not parsed
            std::string subtype{}; // NIID E4(AM2AL2)
            bool new_lab{false};

            bool operator==(const element_t& rhs) const = default;

            std::string construct(bool add_new_lab_separator) const
            {
                std::string result;
                result.append(name);
                result.append(count);
                result.append(subtype);
                if (!count.empty() && add_new_lab_separator && new_lab)
                    result.append(1, '/');
                return result;
            }

            // Egg tokens. "SPE"/"SPF" = SPF egg, "D" = egg-derived; all three also occur mid-string
            // ("E3/SPE1/E1", "E3SPF1/E1", "E3/D9/SPE1/E6"), where the last element decides.
            // Matches AD's re_egg set (E|D|SPF|SPFCE|SPE|EGG) - see py/ae/semantic/serum_circle.py.
            bool egg() const
            {
                if (name == "E" || name == "SPFCE" || name == "SPE" || name == "SPF" || name == "D")
                    return true;
                // Free text that did not parse: the fallback in passage::parse() stores the whole raw
                // source as the name with an EMPTY count, so this cannot fire on a parsed element (those
                // are <=5 chars and conversion::apply already maps "EGG" -> "E"). GISAID deflines carry
                // "EMBRYONATED HEN EGG" / "10 passages - embryonated chicken eggs; ...", which are eggs
                // by any reading. AD's re_egg matches a bare "EGG" anywhere in the string; "EMBRYON"
                // additionally catches the wording that spells out the substrate without the word egg.
                return count.empty() && (name.find("EGG") != std::string::npos || name.find("EMBRYON") != std::string::npos);
            }
            // Cell lines. "MK" = monkey kidney (conversion::apply maps a bare "M" to "MK"),
            // "QMC" = qualified MDCK cell (CDC/VIDRL, e.g. "QMC2/SIAT1").
            bool cell() const
            {
                return name == "MDCK" || name == "SIAT" || name == "HCK" || name == "SPFCK" || name == "MK" || name == "QMC" || is_compound_cell_name(name);
            }
            // A recognised passage token. An element carrying an unknown count is still usable
            // when its name is one of these ("MDCKX/MDCK" is two knowns, not garbage) - see good().
            bool known() const { return egg() || cell() || name == "OR"; }
            bool good() const { return !name.empty() && (name == "OR" || !count.empty()); }
        };

        std::vector<element_t> elements{};
        std::string date{};

        constexpr deconstructed_t() = default;
        constexpr deconstructed_t(int) : deconstructed_t() {} // to support lexy::fold_inplace in passage-parse.cc
        deconstructed_t(const std::vector<element_t>& a_elements, const std::string& a_date) : elements{a_elements}, date{a_date} {}
        // deconstructed_t(std::string_view not_parsed) : elements{element_t{.name{not_parsed}}} {}

        bool operator==(const deconstructed_t& rhs) const = default;
        auto operator<=>(const deconstructed_t& rhs) const { return construct() <=> rhs.construct(); }

        bool empty() const { return elements.empty(); }
        const element_t& last() const { return elements.back(); }
        bool egg() const { return !empty() && last().egg(); }
        bool cell() const { return !empty() && last().cell(); }

        enum class with_date { no, yes };

        std::string construct(with_date wd = with_date::yes) const
        {
            std::string result;
            for (const auto& elt : elements)
                result.append(elt.construct(true));
            if (wd == with_date::yes && !date.empty())
                result.append(fmt::format(" ({})", date));
            return result;
        }

        auto& uppercase()
        {
            for (auto& elt : elements) {
                string::uppercase_in_place(elt.name);
                string::uppercase_in_place(elt.count);
            }
            return *this;
        }

        bool good() const
        {
            // An unknown count is only evidence of garbage when the NAME is unrecognised too.
            // "MDCKX/MDCK" and "PX/MDCK" are real passages with the counts not recorded, whereas
            // "N/A, MDCK1" is two unrecognised single letters and must still be rejected.
            const auto unrecognised = [](const auto& elt) { return !elt.good() || (elt.count[0] == '?' && !elt.known()); };
            return !elements.empty() && elements.front().good() && std::count_if(std::begin(elements), std::end(elements), unrecognised) < 2;
        }
    };

    // ----------------------------------------------------------------------

    class parse_settings
    {
      public:
        enum class tracing { no, yes };

        parse_settings(tracing a_trace = tracing::no) : tracing_{a_trace} {}

        constexpr bool trace() const { return tracing_ == tracing::yes; }

      private:
        tracing tracing_{tracing::no};
    };

    deconstructed_t parse(std::string_view source, const parse_settings& settings, Messages& messages, const MessageLocation& location);

    inline deconstructed_t parse(std::string_view source, parse_settings::tracing tracing = parse_settings::tracing::no)
    {
        Messages messages;
        return parse(source, parse_settings{tracing}, messages, MessageLocation{});
    }

    inline bool is_good(std::string_view source)
    {
        return parse(source).good();
    }

} // namespace ae::virus::passage

// ----------------------------------------------------------------------

namespace ae::virus
{
    class Passage
    {
      public:
        enum class parse { no, yes };

        Passage() = default;
        Passage(const Passage&) = default;
        Passage(Passage&&) = default;
        explicit Passage(std::string_view src, parse pars = parse::yes, passage::parse_settings::tracing tracing = passage::parse_settings::tracing::no)
        {
            if (!src.empty()) {
                if (pars == parse::yes)
                    deconstructed_ = passage::parse(src, tracing);
                else
                    deconstructed_.elements.push_back(passage::deconstructed_t::element_t{.name{std::string{src}}}); // g++-11 wants std::string{src}
            }
        }

        Passage& operator=(const Passage&) = default;
        Passage& operator=(Passage&&) = default;

        bool operator==(const Passage& rhs) const = default;
        auto operator<=>(const Passage& rhs) const { return static_cast<std::string>(*this) <=> static_cast<std::string>(rhs); }

        bool good() const { return deconstructed_.good(); }
        bool empty() const { return deconstructed_.empty(); }
        bool is_egg() const { return deconstructed_.egg(); }
        bool is_cell() const { return deconstructed_.cell(); }
        std::string without_date() const { return deconstructed_.construct(passage::deconstructed_t::with_date::no); }
        operator std::string() const { return deconstructed_.construct(); }
        std::string to_string() const { return deconstructed_.construct(); }
        size_t size() const { return deconstructed_.construct().size(); }
        size_t number_of_elements() const { return deconstructed_.elements.size(); }

        // std::string_view last_number() const; // E2/E3 -> 3, X? -> ?
        // std::string_view last_type() const; // MDCK3/SITA1 -> SIAT

        std::string_view passage_type() const
        {
            using namespace std::string_view_literals;
            if (is_egg())
                return "egg"sv;
            else
                return "cell"sv;
        }

        // size_t find(std::string_view look_for) const { return get().find(look_for); }
        // bool search(const std::regex& re) const { return std::regex_search(get(), re); }


      private:
        passage::deconstructed_t deconstructed_{};
    };
} // namespace ae::virus

template <> struct fmt::formatter<ae::virus::Passage> : public fmt::formatter<std::string>
{
    template <typename FormatContext> auto format(const ae::virus::Passage& ts, FormatContext& ctx) const { return fmt::formatter<std::string>::format(static_cast<std::string>(ts), ctx); }
};

// ======================================================================
