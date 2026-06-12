#pragma once

#include <filesystem>
#include <map>
#include <set>
#include <string>
#include <vector>

#include "hidb/hidb.hh"

// ======================================================================
//
// HidbMaker -- build a hidb from a set of charts (port of AD HidbMaker).
//
// For each chart: add one Table (deduplicated; exact duplicates rejected) and
// each non-DISTINCT antigen/serum to a global, de-duplicated, ordered set,
// accumulating dates / lab ids / lineage and linking antigen<->table and
// serum<->table. A serum's homologous antigens (computed via the chart) are
// recorded as global antigen indexes. `json()` / `save()` then emit hidb-v5.
//
// Faithful to AD: a table's "a"/"s" index lists are sorted by global index,
// while its "t" titers stay in the source chart's antigen/serum order.
//
// ======================================================================

namespace ae::chart::v3
{
    class Chart;
}

namespace ae::hidb
{
    class HidbMaker
    {
      public:
        HidbMaker() = default;

        // add a chart; throws ae::hidb::error if its table is already present
        void add(const ae::chart::v3::Chart& chart);

        std::string json() const;
        void save(const std::filesystem::path& filename) const;

        size_t number_of_antigens() const { return antigens_.size(); }
        size_t number_of_sera() const { return sera_.size(); }
        size_t number_of_tables() const { return tables_.size(); }

      private:
        struct AgData
        {
            Antigen ag;                       // fixed scalar fields + annotations
            std::set<std::string> dates;      // accumulated across charts
            std::set<std::string> lab_ids;    //
            std::set<std::string> table_keys; // tables this antigen is in
        };
        struct SrData
        {
            Serum sr;
            std::set<std::string> table_keys;
            std::set<std::string> homologous_keys; // antigen keys
        };
        struct TbData
        {
            Table tb;
            std::set<std::string> antigen_keys;
            std::set<std::string> serum_keys;
        };

        // ordered by canonical key string (matches AD's field-order operator<)
        std::map<std::string, TbData> tables_;
        std::map<std::string, AgData> antigens_;
        std::map<std::string, SrData> sera_;

        void build(std::vector<Antigen>& antigens, std::vector<Serum>& sera, std::vector<Table>& tables) const;
    };

} // namespace ae::hidb
