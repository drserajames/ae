#pragma once

#include <string>
#include <string_view>
#include <vector>
#include <filesystem>
#include <stdexcept>
#include <memory>
#include <unordered_map>

// ======================================================================
//
// hidb -- historical influenza database (port of AD hidb-5).
//
// Reads the hidb-v5 JSON format (hidb5.{h1,h3,b}.json.xz) into an in-memory
// model. Unlike AD, which mmaps an optimised binary (.hidb5b) layout, this
// port parses the JSON directly with ae::simdjson and keeps plain in-memory
// vectors -- simpler, and fast enough for the tooling that consumes it.
//
// JSON schema (see ~/AC/eu/AD/sources/hidb-5/doc/hidb5-format.json):
//   "a" antigens, "s" sera, "t" tables. Antigen/serum keys:
//     V virus_type, H host, O location (cdc_abbreviation for cdc names),
//     i isolation (full name for cdc names), y year (empty => cdc name),
//     L lineage, P passage, R reassortant, a annotations, D dates,
//     l lab_ids, T table indices; sera also I serum_id, s serum_species,
//     h homologous-antigen indices. Table keys: V virus_type, A assay,
//     D date, L lineage, l lab, r rbc, a antigen indices, s serum indices,
//     t titers (list of lists).
//
// ======================================================================

namespace ae::hidb
{
    class error : public std::runtime_error
    {
      public:
        using std::runtime_error::runtime_error;
    };

    // ----------------------------------------------------------------------

    class Antigen
    {
      public:
        std::string virus_type;
        std::string host;
        std::string location;
        std::string isolation;
        std::string year;
        std::string lineage;
        std::string passage;
        std::string reassortant;
        std::vector<std::string> annotations;
        std::vector<std::string> dates;
        std::vector<std::string> lab_ids;
        std::vector<size_t> tables;

        // an antigen is "cdc-named" when it has no year; then location holds the
        // cdc abbreviation and isolation holds the raw name (matches AD)
        bool cdc_name() const { return year.empty(); }

        std::string name_without_subtype() const;          // host/location/isolation/year, or "location isolation" for cdc
        std::string name() const;                          // subtype prepended unless cdc-named
        std::string full_name() const;                     // name + annotations + reassortant + passage
        std::string date(bool compact = false) const;      // first isolation date (YYYY-MM-DD, or YYYYMMDD if compact); empty if none
        std::string_view country(std::string_view fallback = "UNKNOWN") const; // via locdb (best effort)
    };

    // ----------------------------------------------------------------------

    class Serum
    {
      public:
        std::string virus_type;
        std::string host;
        std::string location;
        std::string isolation;
        std::string year;
        std::string lineage;
        std::string passage;
        std::string reassortant;
        std::string serum_id;
        std::string serum_species;
        std::vector<std::string> annotations;
        std::vector<size_t> tables;
        std::vector<size_t> homologous_antigens;

        std::string name_without_subtype() const; // host/location/isolation/year
        std::string name() const;                  // subtype prepended
        std::string full_name() const;             // name + annotations + reassortant + serum_id
    };

    // ----------------------------------------------------------------------

    class Table
    {
      public:
        std::string virus;      // "v" -- empty / "influenza" by default
        std::string virus_type;
        std::string assay;
        std::string date;
        std::string lineage;
        std::string lab;
        std::string rbc;
        std::vector<size_t> antigens;
        std::vector<size_t> sera;
        std::vector<std::vector<std::string>> titers;

        std::string name() const; // lab:assay:lineage:rbc:date
    };

    // ----------------------------------------------------------------------
    // serialise a model back to hidb-v5 JSON (shared by HiDb::save and the maker)

    std::string to_json(const std::vector<Antigen>& antigens, const std::vector<Serum>& sera, const std::vector<Table>& tables);

    // ----------------------------------------------------------------------

    class HiDb
    {
      public:
        explicit HiDb(const std::filesystem::path& filename);

        std::string_view virus_type() const { return virus_type_; }

        const std::vector<Antigen>& antigens() const { return antigens_; }
        const std::vector<Serum>& sera() const { return sera_; }
        const std::vector<Table>& tables() const { return tables_; }

        const Antigen& antigen(size_t index) const { return antigens_.at(index); }
        const Serum& serum(size_t index) const { return sera_.at(index); }
        const Table& table(size_t index) const { return tables_.at(index); }

        size_t number_of_antigens() const { return antigens_.size(); }
        size_t number_of_sera() const { return sera_.size(); }
        size_t number_of_tables() const { return tables_.size(); }

        // lookup by name; query parsed into location/isolation/year (with cdc and
        // slash-split fallbacks). returns indices into antigens()/sera().
        std::vector<size_t> find_antigens(std::string_view name) const;
        std::vector<size_t> find_sera(std::string_view name) const;
        std::vector<size_t> find_antigens_by_labid(std::string_view labid) const;

        // antigens in a table whose name matches a serum name in the same table
        std::vector<size_t> reference_antigens(size_t table_index) const;

        // most-recent / oldest table among a set (by table date)
        size_t most_recent_table(const std::vector<size_t>& table_indexes) const;
        size_t oldest_table(const std::vector<size_t>& table_indexes) const;

        // write the loaded model back to hidb-v5 JSON (compression by extension)
        void save(const std::filesystem::path& filename) const;

      private:
        std::string virus_type_;
        std::vector<Antigen> antigens_;
        std::vector<Serum> sera_;
        std::vector<Table> tables_;
        // location (uppercase, as stored) -> antigen / serum indexes, for fast find
        std::unordered_multimap<std::string_view, size_t> antigen_by_location_;
        std::unordered_multimap<std::string_view, size_t> serum_by_location_;

        void build_indexes();
    };

    // ----------------------------------------------------------------------
    // singleton access by virus type, loading from a configured directory.
    //   directory resolution: set_dir() override, else $HIDB_V5.
    //   filename: hidb5.{h1,h3,b}.json.xz chosen from the virus type/subtype.

    void set_dir(const std::filesystem::path& dir);
    const HiDb& get(std::string_view virus_type);

} // namespace ae::hidb
