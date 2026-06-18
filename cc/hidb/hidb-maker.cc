#include <algorithm>

#include "hidb/hidb-maker.hh"
#include "ext/fmt.hh"
#include "utils/file.hh"
#include "chart/v3/chart.hh"
#include "virus/name-parse.hh"

// ----------------------------------------------------------------------

namespace ae::hidb
{
    namespace
    {
        constexpr char KSEP = '\x1f'; // unit separator -- cannot appear in field values

        std::string join_space(const std::vector<std::string>& parts)
        {
            std::string result;
            for (const auto& p : parts) {
                if (!result.empty())
                    result.push_back(' ');
                result.append(p);
            }
            return result;
        }

        // first character of a lineage, uppercase (matches AD update_lineage)
        std::string lineage_initial(std::string_view lineage)
        {
            if (lineage.empty())
                return {};
            return std::string{lineage.substr(0, 1)};
        }

        // split a name into virus_type/host/location/isolation/year with the same
        // cdc fallbacks AD uses; reassortant/passage/annotations come from the chart
        struct name_fields
        {
            std::string virus_type, host, location, isolation, year;
        };

        name_fields split_name(std::string_view name)
        {
            name_fields nf;
            const auto parts = ae::virus::name::parse(name);
            if (!parts.location.empty()) {
                nf.virus_type = parts.subtype;
                nf.host = parts.host;
                nf.location = parts.location;
                nf.isolation = parts.isolation;
                nf.year = parts.year;
                return nf;
            }
            // cdc name with location ("AB 1234" / "AB-1234")
            if (name.size() > 3 && (name[2] == ' ' || name[2] == '-')) {
                nf.location = std::string{name.substr(0, 2)};
                nf.isolation = std::string{name.substr(3)};
            }
            else {
                // cdc name without location (some FRA tables miss location data)
                nf.location = "cdc-name-without-location";
                nf.isolation = std::string{name};
            }
            return nf;
        }
    } // namespace
} // namespace ae::hidb

// ----------------------------------------------------------------------

void ae::hidb::HidbMaker::add(const ae::chart::v3::Chart& chart)
{
    const auto& info = chart.info();

    // --- table ---
    Table tb;
    tb.virus = std::string{static_cast<std::string_view>(info.virus())};
    tb.virus_type = std::string{*info.type_subtype()};
    tb.assay = std::string{static_cast<std::string_view>(info.assay())};
    tb.date = std::string{static_cast<std::string_view>(info.date())};
    tb.lab = std::string{static_cast<std::string_view>(info.lab())};
    tb.rbc = std::string{static_cast<std::string_view>(info.rbc_species())};
    tb.lineage = lineage_initial(static_cast<std::string_view>(chart.lineage()));

    const std::string table_key = fmt::format("{}{}{}{}{}{}{}{}{}{}{}{}{}{}{}", tb.virus, KSEP, tb.virus_type, KSEP, /*subset*/ "", KSEP, tb.lineage,
                                              KSEP, tb.assay, KSEP, tb.lab, KSEP, tb.rbc, KSEP, tb.date);
    if (tables_.find(table_key) != tables_.end())
        throw error{"table already in hidb: " + tb.name()};

    // titers in source order (full grid, including any distinct antigens/sera)
    const auto n_ag = chart.antigens().size().get();
    const auto n_sr = chart.sera().size().get();
    tb.titers.resize(n_ag);
    for (size_t ag_no = 0; ag_no < n_ag; ++ag_no) {
        tb.titers[ag_no].resize(n_sr);
        for (size_t sr_no = 0; sr_no < n_sr; ++sr_no)
            tb.titers[ag_no][sr_no] = std::string{static_cast<std::string_view>(chart.titers().titer(ae::antigen_index{ag_no}, ae::serum_index{sr_no}))};
    }

    auto [table_it, inserted] = tables_.emplace(table_key, TbData{.tb = std::move(tb), .antigen_keys = {}, .serum_keys = {}});
    TbData& table_data = table_it->second;

    // --- antigens ---
    std::vector<std::string> source_ag_keys(n_ag); // key per source antigen ("" if distinct/skipped)
    for (size_t ag_no = 0; ag_no < n_ag; ++ag_no) {
        const auto& source = chart.antigens()[ae::antigen_index{ag_no}];
        if (source.annotations().distinct())
            continue;
        const auto nf = split_name(*source.name());
        const std::string annotations = join_space(source.annotations().get());
        const std::string reassortant{*source.reassortant()};
        const std::string passage = static_cast<std::string>(source.passage());
        const std::string ag_key = fmt::format("{}{}{}{}{}{}{}{}{}{}{}{}{}", nf.location, KSEP, nf.isolation, KSEP, nf.year, KSEP, nf.host, KSEP,
                                               annotations, KSEP, reassortant, KSEP, passage);
        source_ag_keys[ag_no] = ag_key;

        auto [it, ins] = antigens_.try_emplace(ag_key);
        AgData& data = it->second;
        if (ins) {
            data.ag.virus_type = nf.virus_type;
            data.ag.host = nf.host;
            data.ag.location = nf.location;
            data.ag.isolation = nf.isolation;
            data.ag.year = nf.year;
            data.ag.passage = passage;
            data.ag.reassortant = reassortant;
            data.ag.annotations.assign(source.annotations().get().begin(), source.annotations().get().end());
        }
        if (const auto lin = lineage_initial(static_cast<std::string_view>(source.lineage())); !lin.empty() && data.ag.lineage.empty())
            data.ag.lineage = lin;
        if (const std::string date{static_cast<std::string_view>(source.date())}; !date.empty())
            data.dates.insert(date);
        for (const auto& lab_id : source.lab_ids())
            data.lab_ids.insert(std::string{lab_id});
        data.table_keys.insert(table_key);
        table_data.antigen_keys.insert(ag_key);
    }

    // --- sera ---
    for (size_t sr_no = 0; sr_no < n_sr; ++sr_no) {
        const auto& source = chart.sera()[ae::serum_index{sr_no}];
        if (source.annotations().distinct())
            continue;
        const auto nf = split_name(*source.name());
        const std::string annotations = join_space(source.annotations().get());
        const std::string reassortant{*source.reassortant()};
        const std::string serum_id{static_cast<std::string_view>(source.serum_id())};
        const std::string sr_key = fmt::format("{}{}{}{}{}{}{}{}{}{}{}{}{}", nf.location, KSEP, nf.isolation, KSEP, nf.year, KSEP, nf.host, KSEP,
                                               annotations, KSEP, reassortant, KSEP, serum_id);

        auto [it, ins] = sera_.try_emplace(sr_key);
        SrData& data = it->second;
        if (ins) {
            data.sr.virus_type = nf.virus_type;
            data.sr.host = nf.host;
            data.sr.location = nf.location;
            data.sr.isolation = nf.isolation;
            data.sr.year = nf.year;
            data.sr.passage = static_cast<std::string>(source.passage());
            data.sr.reassortant = reassortant;
            data.sr.serum_id = serum_id;
            data.sr.serum_species = std::string{static_cast<std::string_view>(source.serum_species())};
            data.sr.annotations.assign(source.annotations().get().begin(), source.annotations().get().end());
        }
        if (const auto lin = lineage_initial(static_cast<std::string_view>(source.lineage())); !lin.empty() && data.sr.lineage.empty())
            data.sr.lineage = lin;
        data.table_keys.insert(table_key);
        table_data.serum_keys.insert(sr_key);

        // homologous antigens of this serum, mapped to global antigen keys
        for (const auto ag_index : chart.antigens().homologous(source)) {
            if (const auto idx = ag_index.get(); idx < source_ag_keys.size() && !source_ag_keys[idx].empty())
                data.homologous_keys.insert(source_ag_keys[idx]);
        }
    }
}

// ----------------------------------------------------------------------

void ae::hidb::HidbMaker::build(std::vector<Antigen>& antigens, std::vector<Serum>& sera, std::vector<Table>& tables) const
{
    // assign sorted indexes (map iteration is ordered by canonical key)
    std::map<std::string, size_t> table_index, antigen_index, serum_index;
    size_t no = 0;
    for (const auto& [key, _] : tables_)
        table_index.emplace(key, no++);
    no = 0;
    for (const auto& [key, _] : antigens_)
        antigen_index.emplace(key, no++);
    no = 0;
    for (const auto& [key, _] : sera_)
        serum_index.emplace(key, no++);

    const auto resolve_sorted = [](const std::set<std::string>& keys, const std::map<std::string, size_t>& index) {
        std::vector<size_t> result;
        result.reserve(keys.size());
        for (const auto& k : keys)
            result.push_back(index.at(k));
        std::sort(result.begin(), result.end());
        return result;
    };

    tables.reserve(tables_.size());
    for (const auto& [key, data] : tables_) {
        Table tb = data.tb;
        tb.antigens = resolve_sorted(data.antigen_keys, antigen_index);
        tb.sera = resolve_sorted(data.serum_keys, serum_index);
        tables.push_back(std::move(tb));
    }

    antigens.reserve(antigens_.size());
    for (const auto& [key, data] : antigens_) {
        Antigen ag = data.ag;
        ag.dates.assign(data.dates.begin(), data.dates.end());
        ag.lab_ids.assign(data.lab_ids.begin(), data.lab_ids.end());
        ag.tables = resolve_sorted(data.table_keys, table_index);
        antigens.push_back(std::move(ag));
    }

    sera.reserve(sera_.size());
    for (const auto& [key, data] : sera_) {
        Serum sr = data.sr;
        sr.tables = resolve_sorted(data.table_keys, table_index);
        sr.homologous_antigens = resolve_sorted(data.homologous_keys, antigen_index);
        sera.push_back(std::move(sr));
    }
}

// ----------------------------------------------------------------------

std::string ae::hidb::HidbMaker::json() const
{
    std::vector<Antigen> antigens;
    std::vector<Serum> sera;
    std::vector<Table> tables;
    build(antigens, sera, tables);
    return to_json(antigens, sera, tables);
}

void ae::hidb::HidbMaker::save(const std::filesystem::path& filename) const
{
    ae::file::write(filename, json());
}
