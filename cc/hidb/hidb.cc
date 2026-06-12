#include <algorithm>
#include <array>
#include <cctype>
#include <cstdlib>
#include <map>
#include <mutex>

#include "hidb/hidb.hh"
#include "ext/simdjson.hh"
#include "ext/fmt.hh"
#include "virus/name-parse.hh"
#include "locdb/v3/locdb.hh"
#include "utils/file.hh"

// ----------------------------------------------------------------------

namespace ae::hidb
{
    // join non-empty parts with a separator
    static std::string join(std::string_view sep, std::initializer_list<std::string_view> parts)
    {
        std::string result;
        for (const auto part : parts) {
            if (!part.empty()) {
                if (!result.empty())
                    result.append(sep);
                result.append(part);
            }
        }
        return result;
    }

    static std::string to_upper(std::string_view src)
    {
        std::string result{src};
        std::transform(result.begin(), result.end(), result.begin(), [](unsigned char c) { return static_cast<char>(std::toupper(c)); });
        return result;
    }
} // namespace ae::hidb

// ----------------------------------------------------------------------
// Antigen

std::string ae::hidb::Antigen::name_without_subtype() const
{
    if (cdc_name())
        return join(" ", {location, isolation});
    else
        return join("/", {host, location, isolation, year});
}

std::string ae::hidb::Antigen::name() const
{
    if (cdc_name())
        return name_without_subtype();
    else
        return join("/", {virus_type, name_without_subtype()});
}

std::string ae::hidb::Antigen::full_name() const
{
    std::string ann;
    for (const auto& a : annotations) {
        if (!ann.empty())
            ann.push_back(' ');
        ann.append(a);
    }
    return join(" ", {name(), ann, reassortant, passage});
}

std::string ae::hidb::Antigen::date(bool compact) const
{
    if (dates.empty())
        return {};
    std::string d = dates.front();
    if (compact)
        d.erase(std::remove(d.begin(), d.end(), '-'), d.end());
    return d;
}

std::string_view ae::hidb::Antigen::country(std::string_view fallback) const
{
    try {
        if (const auto c = ae::locdb::get().country(location); !c.empty())
            return c;
    }
    catch (std::exception&) {
        // locdb not available (LOCDB_V2 unset) -- best effort only
    }
    return fallback;
}

// ----------------------------------------------------------------------
// Serum

std::string ae::hidb::Serum::name_without_subtype() const
{
    return join("/", {host, location, isolation, year});
}

std::string ae::hidb::Serum::name() const
{
    return join("/", {virus_type, name_without_subtype()});
}

std::string ae::hidb::Serum::full_name() const
{
    std::string ann;
    for (const auto& a : annotations) {
        if (!ann.empty())
            ann.push_back(' ');
        ann.append(a);
    }
    return join(" ", {name(), ann, reassortant, serum_id});
}

// ----------------------------------------------------------------------
// Table

std::string ae::hidb::Table::name() const
{
    return join(":", {lab, assay, lineage, rbc, date});
}

// ----------------------------------------------------------------------
// JSON serialisation (hidb-v5), shared by HiDb::save and the maker

namespace ae::hidb
{
    // append a JSON-escaped, double-quoted string
    static void json_string(std::string& out, std::string_view str)
    {
        out.push_back('"');
        for (const char c : str) {
            switch (c) {
                case '"': out.append("\\\""); break;
                case '\\': out.append("\\\\"); break;
                case '\n': out.append("\\n"); break;
                case '\t': out.append("\\t"); break;
                case '\r': out.append("\\r"); break;
                default:
                    if (static_cast<unsigned char>(c) < 0x20)
                        out.append(fmt::format("\\u{:04x}", static_cast<unsigned>(static_cast<unsigned char>(c))));
                    else
                        out.push_back(c);
                    break;
            }
        }
        out.push_back('"');
    }

    static void field_str(std::string& out, bool& first, std::string_view key, std::string_view value)
    {
        if (value.empty())
            return;
        if (!first)
            out.push_back(',');
        first = false;
        json_string(out, key);
        out.push_back(':');
        json_string(out, value);
    }

    template <typename Range> static void json_string_array(std::string& out, const Range& values)
    {
        out.push_back('[');
        bool inner_first = true;
        for (const auto& v : values) {
            if (!inner_first)
                out.push_back(',');
            inner_first = false;
            json_string(out, v);
        }
        out.push_back(']');
    }

    template <typename Range> static void field_str_array(std::string& out, bool& first, std::string_view key, const Range& values)
    {
        if (values.empty())
            return;
        if (!first)
            out.push_back(',');
        first = false;
        json_string(out, key);
        out.push_back(':');
        json_string_array(out, values);
    }

    static void field_index_array(std::string& out, bool& first, std::string_view key, const std::vector<size_t>& values)
    {
        if (values.empty())
            return;
        if (!first)
            out.push_back(',');
        first = false;
        json_string(out, key);
        out.append(":[");
        bool inner_first = true;
        for (const auto v : values) {
            if (!inner_first)
                out.push_back(',');
            inner_first = false;
            out.append(fmt::format("{}", v));
        }
        out.push_back(']');
    }
} // namespace ae::hidb

std::string ae::hidb::to_json(const std::vector<Antigen>& antigens, const std::vector<Serum>& sera, const std::vector<Table>& tables)
{
    std::string out;
    out.reserve(antigens.size() * 80 + sera.size() * 80 + tables.size() * 200);
    out.append("{\"  version\":\"hidb-v5\",\n \"a\":[");

    bool list_first = true;
    for (const auto& ag : antigens) {
        if (!list_first)
            out.append(",\n  ");
        list_first = false;
        out.push_back('{');
        bool first = true;
        // antigen virus type falls back to its first table's virus type (cdc names have none)
        std::string_view vt = ag.virus_type;
        if (vt.empty() && !ag.tables.empty())
            vt = tables.at(ag.tables.front()).virus_type;
        field_str(out, first, "V", vt);
        field_str(out, first, "H", ag.host);
        field_str(out, first, "O", ag.location);
        field_str(out, first, "i", ag.isolation);
        field_str(out, first, "y", ag.year);
        field_str(out, first, "L", ag.lineage);
        field_str(out, first, "P", ag.passage);
        field_str(out, first, "R", ag.reassortant);
        field_str_array(out, first, "a", ag.annotations);
        field_str_array(out, first, "D", ag.dates);
        field_str_array(out, first, "l", ag.lab_ids);
        field_index_array(out, first, "T", ag.tables);
        out.push_back('}');
    }
    out.append("],\n \"s\":[");

    list_first = true;
    for (const auto& sr : sera) {
        if (!list_first)
            out.append(",\n  ");
        list_first = false;
        out.push_back('{');
        bool first = true;
        field_str(out, first, "V", sr.virus_type);
        field_str(out, first, "H", sr.host);
        field_str(out, first, "O", sr.location);
        field_str(out, first, "i", sr.isolation);
        field_str(out, first, "y", sr.year);
        field_str(out, first, "L", sr.lineage);
        field_str(out, first, "P", sr.passage);
        field_str(out, first, "R", sr.reassortant);
        field_str(out, first, "I", sr.serum_id);
        field_str(out, first, "s", sr.serum_species);
        field_str_array(out, first, "a", sr.annotations);
        field_index_array(out, first, "T", sr.tables);
        field_index_array(out, first, "h", sr.homologous_antigens);
        out.push_back('}');
    }
    out.append("],\n \"t\":[");

    list_first = true;
    for (const auto& tb : tables) {
        if (!list_first)
            out.append(",\n  ");
        list_first = false;
        out.push_back('{');
        bool first = true;
        field_str(out, first, "v", (tb.virus.empty() || tb.virus == "influenza") ? std::string_view{} : std::string_view{tb.virus});
        field_str(out, first, "V", tb.virus_type);
        field_str(out, first, "A", tb.assay);
        field_str(out, first, "D", tb.date);
        field_str(out, first, "l", tb.lab);
        field_str(out, first, "r", tb.rbc);
        field_str(out, first, "L", tb.lineage);
        field_index_array(out, first, "a", tb.antigens);
        field_index_array(out, first, "s", tb.sera);
        // titers: list of lists of strings (always emitted)
        if (!first)
            out.push_back(',');
        first = false;
        out.append("\"t\":[");
        bool row_first = true;
        for (const auto& row : tb.titers) {
            if (!row_first)
                out.push_back(',');
            row_first = false;
            json_string_array(out, row);
        }
        out.push_back(']');
        out.push_back('}');
    }
    out.append("]}\n");
    return out;
}

void ae::hidb::HiDb::save(const std::filesystem::path& filename) const
{
    ae::file::write(filename, to_json(antigens_, sera_, tables_));
}

// ----------------------------------------------------------------------
// HiDb construction

namespace
{
    using namespace ae::hidb;

    // read an array of strings
    template <typename Value> std::vector<std::string> read_strings(Value value)
    {
        std::vector<std::string> result;
        for (auto elt : value.get_array())
            result.emplace_back(static_cast<std::string_view>(elt));
        return result;
    }

    // read an array of unsigned integers
    template <typename Value> std::vector<size_t> read_indexes(Value value)
    {
        std::vector<size_t> result;
        for (auto elt : value.get_array())
            result.push_back(static_cast<size_t>(static_cast<uint64_t>(elt)));
        return result;
    }

    template <typename Source> void read_antigen(Antigen& target, Source source)
    {
        for (auto field : source.get_object()) {
            const std::string_view key = field.unescaped_key();
            auto value = field.value();
            if (key.size() == 1) {
                switch (key[0]) {
                    case 'V': target.virus_type = static_cast<std::string_view>(value); break;
                    case 'H': target.host = static_cast<std::string_view>(value); break;
                    case 'O': target.location = static_cast<std::string_view>(value); break;
                    case 'i': target.isolation = static_cast<std::string_view>(value); break;
                    case 'y': target.year = static_cast<std::string_view>(value); break;
                    case 'L': target.lineage = static_cast<std::string_view>(value); break;
                    case 'P': target.passage = static_cast<std::string_view>(value); break;
                    case 'R': target.reassortant = static_cast<std::string_view>(value); break;
                    case 'a': target.annotations = read_strings(value); break;
                    case 'D': target.dates = read_strings(value); break;
                    case 'l': target.lab_ids = read_strings(value); break;
                    case 'T': target.tables = read_indexes(value); break;
                    default: break;
                }
            }
        }
    }

    template <typename Source> void read_serum(Serum& target, Source source)
    {
        for (auto field : source.get_object()) {
            const std::string_view key = field.unescaped_key();
            auto value = field.value();
            if (key.size() == 1) {
                switch (key[0]) {
                    case 'V': target.virus_type = static_cast<std::string_view>(value); break;
                    case 'H': target.host = static_cast<std::string_view>(value); break;
                    case 'O': target.location = static_cast<std::string_view>(value); break;
                    case 'i': target.isolation = static_cast<std::string_view>(value); break;
                    case 'y': target.year = static_cast<std::string_view>(value); break;
                    case 'L': target.lineage = static_cast<std::string_view>(value); break;
                    case 'P': target.passage = static_cast<std::string_view>(value); break;
                    case 'R': target.reassortant = static_cast<std::string_view>(value); break;
                    case 'I': target.serum_id = static_cast<std::string_view>(value); break;
                    case 's': target.serum_species = static_cast<std::string_view>(value); break;
                    case 'a': target.annotations = read_strings(value); break;
                    case 'T': target.tables = read_indexes(value); break;
                    case 'h': target.homologous_antigens = read_indexes(value); break;
                    default: break;
                }
            }
        }
    }

    template <typename Source> void read_table(Table& target, Source source)
    {
        for (auto field : source.get_object()) {
            const std::string_view key = field.unescaped_key();
            auto value = field.value();
            if (key.size() == 1) {
                switch (key[0]) {
                    case 'v': target.virus = static_cast<std::string_view>(value); break;
                    case 'V': target.virus_type = static_cast<std::string_view>(value); break;
                    case 'A': target.assay = static_cast<std::string_view>(value); break;
                    case 'D': target.date = static_cast<std::string_view>(value); break;
                    case 'L': target.lineage = static_cast<std::string_view>(value); break;
                    case 'l': target.lab = static_cast<std::string_view>(value); break;
                    case 'r': target.rbc = static_cast<std::string_view>(value); break;
                    case 'a': target.antigens = read_indexes(value); break;
                    case 's': target.sera = read_indexes(value); break;
                    case 't':
                        for (auto row : value.get_array())
                            target.titers.push_back(read_strings(row));
                        break;
                    default: break;
                }
            }
        }
    }
} // namespace

ae::hidb::HiDb::HiDb(const std::filesystem::path& filename)
{
    ae::simdjson::Parser parser{filename};
    for (auto field : parser.doc().get_object()) {
        const std::string_view key = field.unescaped_key();
        if (key == "a") {
            for (auto en : field.value().get_array())
                read_antigen(antigens_.emplace_back(), en);
        }
        else if (key == "s") {
            for (auto en : field.value().get_array())
                read_serum(sera_.emplace_back(), en);
        }
        else if (key == "t") {
            for (auto en : field.value().get_array())
                read_table(tables_.emplace_back(), en);
        }
        else if (key == "  version") {
            if (const std::string_view ver = field.value(); ver != "hidb-v5")
                throw error{"hidb: unsupported version: \"" + std::string{ver} + "\""};
        }
        // ignore "_" and any other keys
    }

    if (!antigens_.empty())
        virus_type_ = antigens_.front().virus_type;
    else if (!tables_.empty())
        virus_type_ = tables_.front().virus_type;

    build_indexes();
}

void ae::hidb::HiDb::build_indexes()
{
    antigen_by_location_.reserve(antigens_.size());
    for (size_t no = 0; no < antigens_.size(); ++no)
        antigen_by_location_.emplace(std::string_view{antigens_[no].location}, no);
    serum_by_location_.reserve(sera_.size());
    for (size_t no = 0; no < sera_.size(); ++no)
        serum_by_location_.emplace(std::string_view{sera_[no].location}, no);
}

// ----------------------------------------------------------------------
// find

namespace
{
    // split a query name into (location, isolation, year) using the ae virus name
    // parser, with cdc-name and slash-split fallbacks (mirrors AD Antigens::find)
    struct query_parts
    {
        std::string location;
        std::string isolation;
        std::string year;
    };

    query_parts parse_query(std::string_view name)
    {
        query_parts qp;
        const auto parts = ae::virus::name::parse(name);
        if (!parts.location.empty()) {
            qp.location = parts.location;
            qp.isolation = parts.isolation;
            qp.year = parts.year;
            return qp;
        }
        // cdc name? "AB 1234..."
        if (name.size() > 3 && name[2] == ' ') {
            qp.location = std::string{name.substr(0, 2)};
            qp.isolation = std::string{name.substr(3)};
            return qp;
        }
        // slash split
        std::vector<std::string_view> split;
        size_t start = 0;
        while (start <= name.size()) {
            const auto pos = name.find('/', start);
            if (pos == std::string_view::npos) {
                split.push_back(name.substr(start));
                break;
            }
            split.push_back(name.substr(start, pos - start));
            start = pos + 1;
        }
        switch (split.size()) {
            case 1: qp.location = std::string{split[0]}; break;
            case 2: qp.location = std::string{split[0]}; qp.isolation = std::string{split[1]}; break;
            case 3: qp.location = std::string{split[1]}; qp.isolation = std::string{split[2]}; break;
            default: break;
        }
        return qp;
    }
} // namespace

std::vector<size_t> ae::hidb::HiDb::find_antigens(std::string_view name) const
{
    const auto qp = parse_query(name);
    const auto loc = to_upper(qp.location);
    const auto iso = to_upper(qp.isolation);
    std::vector<size_t> result;
    const auto range = antigen_by_location_.equal_range(std::string_view{loc});
    for (auto it = range.first; it != range.second; ++it) {
        const auto& ag = antigens_[it->second];
        if (!iso.empty() && to_upper(ag.isolation) != iso)
            continue;
        if (!qp.year.empty() && ag.year != qp.year)
            continue;
        result.push_back(it->second);
    }
    std::sort(result.begin(), result.end());
    return result;
}

std::vector<size_t> ae::hidb::HiDb::find_sera(std::string_view name) const
{
    const auto qp = parse_query(name);
    const auto loc = to_upper(qp.location);
    const auto iso = to_upper(qp.isolation);
    std::vector<size_t> result;
    const auto range = serum_by_location_.equal_range(std::string_view{loc});
    for (auto it = range.first; it != range.second; ++it) {
        const auto& sr = sera_[it->second];
        if (!iso.empty() && to_upper(sr.isolation) != iso)
            continue;
        if (!qp.year.empty() && sr.year != qp.year)
            continue;
        result.push_back(it->second);
    }
    std::sort(result.begin(), result.end());
    return result;
}

std::vector<size_t> ae::hidb::HiDb::find_antigens_by_labid(std::string_view labid) const
{
    std::vector<std::string> candidates;
    if (labid.find('#') == std::string_view::npos) {
        candidates.push_back("CDC#" + std::string{labid});
        candidates.push_back("MELB#" + std::string{labid});
        candidates.push_back("NIID#" + std::string{labid});
    }
    else
        candidates.emplace_back(labid);

    std::vector<size_t> result;
    for (size_t no = 0; no < antigens_.size(); ++no) {
        const auto& ids = antigens_[no].lab_ids;
        for (const auto& cand : candidates) {
            if (std::find(ids.begin(), ids.end(), cand) != ids.end()) {
                result.push_back(no);
                break;
            }
        }
    }
    return result;
}

// ----------------------------------------------------------------------
// reference antigens: antigens in a table whose name() matches a serum name() in
// the same table (mirrors AD Table::reference_antigens)

std::vector<size_t> ae::hidb::HiDb::reference_antigens(size_t table_index) const
{
    const auto& tbl = tables_.at(table_index);
    std::vector<std::string> serum_names;
    serum_names.reserve(tbl.sera.size());
    for (const auto sr_no : tbl.sera)
        serum_names.push_back(sera_.at(sr_no).name());

    std::vector<size_t> result;
    for (const auto ag_no : tbl.antigens) {
        if (std::find(serum_names.begin(), serum_names.end(), antigens_.at(ag_no).name()) != serum_names.end())
            result.push_back(ag_no);
    }
    return result;
}

// ----------------------------------------------------------------------

size_t ae::hidb::HiDb::most_recent_table(const std::vector<size_t>& table_indexes) const
{
    size_t best = table_indexes.front();
    for (const auto idx : table_indexes) {
        if (tables_.at(idx).date > tables_.at(best).date)
            best = idx;
    }
    return best;
}

size_t ae::hidb::HiDb::oldest_table(const std::vector<size_t>& table_indexes) const
{
    size_t best = table_indexes.front();
    for (const auto idx : table_indexes) {
        if (tables_.at(idx).date < tables_.at(best).date)
            best = idx;
    }
    return best;
}

// ----------------------------------------------------------------------
// singleton access

namespace ae::hidb
{
    static std::filesystem::path sDir;
    static std::mutex sMutex;
    static std::map<std::string, std::unique_ptr<HiDb>, std::less<>> sCache;

    // map a virus type/subtype to the hidb file suffix
    static std::string_view file_suffix(std::string_view virus_type)
    {
        if (virus_type.find("H1") != std::string_view::npos)
            return "h1";
        if (virus_type.find("H3") != std::string_view::npos)
            return "h3";
        if (!virus_type.empty() && (virus_type[0] == 'B' || virus_type[0] == 'b'))
            return "b";
        throw error{"hidb: cannot determine hidb file for virus type \"" + std::string{virus_type} + "\""};
    }
} // namespace ae::hidb

void ae::hidb::set_dir(const std::filesystem::path& dir)
{
    std::lock_guard guard{sMutex};
    sDir = dir;
}

const ae::hidb::HiDb& ae::hidb::get(std::string_view virus_type)
{
    const auto suffix = file_suffix(virus_type);
    std::lock_guard guard{sMutex};

    if (const auto found = sCache.find(suffix); found != sCache.end())
        return *found->second;

    std::filesystem::path dir = sDir;
    if (dir.empty()) {
        if (const char* env = std::getenv("HIDB_V5"); env && *env)
            dir = env;
        else
            throw error{"hidb: directory not set (call hidb.set_dir() or set $HIDB_V5)"};
    }

    const auto filename = dir / ("hidb5." + std::string{suffix} + ".json.xz");
    auto db = std::make_unique<HiDb>(filename);
    const auto& ref = *db;
    sCache.emplace(std::string{suffix}, std::move(db));
    return ref;
}
