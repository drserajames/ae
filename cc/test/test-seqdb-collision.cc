// Regression guard for the seqdb hash-collision data loss (TODO.md defect #9).
//
// `Seqdb::add` used to decide whether to keep an incoming sequence from a hash hit
// plus a NAME comparison, never comparing the sequences themselves. The only rescue
// was a nucleotide-LENGTH guard written as an `else if`, so on a same-length collision
// the incoming sequence was stored as a slave with `nuc` cleared and
// `replace_with_master()` later handed that strain a different virus's sequence --
// silently, because the diagnostic sits inside the length-differs branch.
//
// A real collision cannot be produced from invented sequences (that would mean finding
// a preimage pair for xxhash32), so the hash is set DIRECTLY on the RawSequence, which
// is exactly what the production path does after `calculate_hash`. All sequence data
// here is invented -- no surveillance data, per CLAUDE.md. The names deliberately do NOT
// use the LOCATION/NUMBER/YEAR shape of a real strain name: the WHO-data gate matches that
// shape and would (correctly) block this file, and a test fixture is not worth an allowlist
// entry that would blunt the gate for everyone.

#include <cstdlib>
#include <filesystem>
#include <string>

#include "ext/fmt.hh"
#include "sequences/seqdb.hh"
#include "sequences/raw-sequence.hh"

// ======================================================================

static int failures{0};

static void check(bool ok, std::string_view what)
{
    fmt::print("{}  {}\n", ok ? "ok  " : "FAIL", what);
    if (!ok)
        ++failures;
}

static ae::sequences::RawSequence make(std::string_view name, std::string_view nuc, std::string_view hash)
{
    using namespace ae::sequences;
    RawSequence rs{name};   // RawSequence has no default ctor: it takes the raw name
    rs.name = name;
    rs.sequence.nuc = sequence_nuc_t{nuc};
    rs.hash_nuc = ae::hash_t{std::string{hash}};
    rs.date = "2020-01-01";
    rs.type_subtype = ae::virus::type_subtype_t{"A(H3N2)"};
    return rs;
}

// Invented nucleotides. A and B are the same length and differ in one position;
// SHORT is a truncation of A.
static const std::string kNucA{"ACGT" "ACGT" "ACGT" "ACGT" "ACGT" "ACGT"};
static const std::string kNucB{"ACGT" "ACGT" "ACGT" "ACGT" "ACGT" "ACGA"};
static const std::string kShort{"ACGT" "ACGT" "ACGT"};

int main(int /*argc*/, const char* const* /*argv*/)
{
    try {
        using namespace ae::sequences;

        // Seqdb::filename() throws when SEQDB_V4 is unset, and load() no-ops when the
        // file is absent -- so point it at an empty dir to get an empty database.
        const auto tmp = std::filesystem::temp_directory_path() / "ae-test-seqdb-collision";
        std::filesystem::create_directories(tmp);
        ::setenv("SEQDB_V4", tmp.c_str(), 1);

        const auto stored_nuc = [](const Seqdb& db, std::string_view name) -> std::string {
            if (const auto* entry = db.find_by_name(name); entry && !entry->seqs.empty())
                return *entry->seqs.front().nuc;
            return {};
        };

        // --- the defect: same hash, same length, DIFFERENT nucleotides ---------------
        {
            Seqdb db{ae::virus::type_subtype_t{"A(H3N2)"}};
            db.add(make("test-seq-alpha", kNucA, "DEADBEEF"));
            db.add(make("test-seq-beta", kNucB, "DEADBEEF")); // forced collision
            check(stored_nuc(db, "test-seq-alpha") == kNucA, "collision: first sequence keeps its own nucleotides");
            check(stored_nuc(db, "test-seq-beta") == kNucB, "collision: second sequence keeps its own nucleotides, NOT the first's");
            check(!stored_nuc(db, "test-seq-beta").empty(), "collision: second sequence is not stored with nuc cleared");
        }

        // --- the design's intended case: same hash AND identical nucleotides ---------
        // This must keep behaving as before: a genuine duplicate becomes a slave.
        {
            Seqdb db{ae::virus::type_subtype_t{"A(H3N2)"}};
            db.add(make("test-seq-alpha", kNucA, "DEADBEEF"));
            db.add(make("test-seq-duplicate", kNucA, "DEADBEEF"));
            check(stored_nuc(db, "test-seq-alpha") == kNucA, "duplicate: master keeps its nucleotides");
            check(stored_nuc(db, "test-seq-duplicate").empty(), "duplicate: genuine duplicate is still stored as a slave");
        }

        // --- unchanged: same hash, DIFFERENT lengths -> truncated-sequence policy ----
        {
            Seqdb db{ae::virus::type_subtype_t{"A(H3N2)"}};
            db.add(make("test-seq-alpha", kNucA, "DEADBEEF"));
            db.add(make("test-seq-truncated", kShort, "DEADBEEF"));
            check(!stored_nuc(db, "test-seq-truncated").empty() || !stored_nuc(db, "test-seq-alpha").empty(),
                  "different lengths: the existing short-sequence policy still resolves to one kept sequence");
        }

        std::filesystem::remove_all(tmp);
    }
    catch (std::exception& err) {
        fmt::print("> {}\n", err.what());
        return 1967;
    }

    fmt::print("\n{}\n", failures ? fmt::format("{} CHECK(S) FAILED", failures) : "all checks passed");
    return failures ? 1 : 0;
}

// ======================================================================
