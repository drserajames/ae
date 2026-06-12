#include "py/module.hh"
#include "hidb/hidb.hh"
#include "hidb/hidb-maker.hh"
#include "chart/v3/chart.hh"

// ======================================================================

void ae::py::hidb(pybind11::module_& mdl)
{
    using namespace pybind11::literals;
    using namespace ae::hidb;

    auto submodule = mdl.def_submodule("hidb", "historical influenza database (hidb-5)");

    submodule.def("set_dir", &set_dir, "dir"_a, "set the directory holding hidb5.{h1,h3,b}.json.xz (overrides $HIDB_V5)");
    submodule.def("hidb", &get, "virus_type"_a, pybind11::return_value_policy::reference, "load (and cache) the hidb for a virus type, e.g. \"A(H3N2)\", \"H3\", \"B\"");

    // build a hidb from chart files and write it out (convenience over HidbMaker)
    submodule.def(
        "make",
        [](const std::vector<std::string>& chart_files, const std::string& output, bool stop_on_error) {
            HidbMaker maker;
            std::vector<std::string> errors;
            for (const auto& file : chart_files) {
                try {
                    maker.add(ae::chart::v3::Chart{std::filesystem::path{file}});
                }
                catch (std::exception& err) {
                    if (stop_on_error)
                        throw;
                    errors.push_back(file + ": " + err.what());
                }
            }
            maker.save(output);
            return errors; // files that could not be added (when stop_on_error is False)
        },
        "chart_files"_a, "output"_a, "stop_on_error"_a = false,
        "build a hidb from chart files, write it to output; returns the list of files that failed (unless stop_on_error)");

    // ----------------------------------------------------------------------

    pybind11::class_<Antigen>(submodule, "HidbAntigen")                            //
        .def("name", &Antigen::name)                                              //
        .def("name_without_subtype", &Antigen::name_without_subtype)              //
        .def("full_name", &Antigen::full_name)                                    //
        .def("date", &Antigen::date, "compact"_a = false)                         //
        .def("country", &Antigen::country, "fallback"_a = "UNKNOWN")              //
        .def("cdc_name", &Antigen::cdc_name)                                      //
        .def("number_of_tables", [](const Antigen& ag) { return ag.tables.size(); }) //
        .def_readonly("virus_type", &Antigen::virus_type)                         //
        .def_readonly("host", &Antigen::host)                                     //
        .def_readonly("location", &Antigen::location)                             //
        .def_readonly("isolation", &Antigen::isolation)                           //
        .def_readonly("year", &Antigen::year)                                     //
        .def_readonly("lineage", &Antigen::lineage)                               //
        .def_readonly("passage", &Antigen::passage)                               //
        .def_readonly("reassortant", &Antigen::reassortant)                       //
        .def_readonly("annotations", &Antigen::annotations)                       //
        .def_readonly("dates", &Antigen::dates)                                   //
        .def_readonly("lab_ids", &Antigen::lab_ids)                               //
        .def_readonly("tables", &Antigen::tables)                                 //
        ;

    pybind11::class_<Serum>(submodule, "HidbSerum")                               //
        .def("name", &Serum::name)                                               //
        .def("name_without_subtype", &Serum::name_without_subtype)               //
        .def("full_name", &Serum::full_name)                                     //
        .def("number_of_tables", [](const Serum& sr) { return sr.tables.size(); }) //
        .def_readonly("virus_type", &Serum::virus_type)                          //
        .def_readonly("host", &Serum::host)                                      //
        .def_readonly("location", &Serum::location)                             //
        .def_readonly("isolation", &Serum::isolation)                           //
        .def_readonly("year", &Serum::year)                                     //
        .def_readonly("lineage", &Serum::lineage)                               //
        .def_readonly("passage", &Serum::passage)                               //
        .def_readonly("reassortant", &Serum::reassortant)                       //
        .def_readonly("serum_id", &Serum::serum_id)                             //
        .def_readonly("serum_species", &Serum::serum_species)                   //
        .def_readonly("annotations", &Serum::annotations)                       //
        .def_readonly("tables", &Serum::tables)                                 //
        .def_readonly("homologous_antigens", &Serum::homologous_antigens)       //
        ;

    pybind11::class_<Table>(submodule, "HidbTable")                              //
        .def("name", &Table::name)                                              //
        .def("number_of_antigens", [](const Table& t) { return t.antigens.size(); }) //
        .def("number_of_sera", [](const Table& t) { return t.sera.size(); })    //
        .def_readonly("virus_type", &Table::virus_type)                         //
        .def_readonly("assay", &Table::assay)                                   //
        .def_readonly("date", &Table::date)                                     //
        .def_readonly("lineage", &Table::lineage)                               //
        .def_readonly("lab", &Table::lab)                                       //
        .def_readonly("rbc", &Table::rbc)                                       //
        .def_readonly("antigens", &Table::antigens)                             //
        .def_readonly("sera", &Table::sera)                                     //
        ;

    pybind11::class_<HiDb>(submodule, "HiDb")                                                                      //
        .def(pybind11::init<const std::filesystem::path&>(), "filename"_a)                                         //
        .def("virus_type", &HiDb::virus_type)                                                                     //
        .def("number_of_antigens", &HiDb::number_of_antigens)                                                     //
        .def("number_of_sera", &HiDb::number_of_sera)                                                             //
        .def("number_of_tables", &HiDb::number_of_tables)                                                         //
        .def("antigen", &HiDb::antigen, "index"_a, pybind11::return_value_policy::reference_internal)             //
        .def("serum", &HiDb::serum, "index"_a, pybind11::return_value_policy::reference_internal)                 //
        .def("table", &HiDb::table, "index"_a, pybind11::return_value_policy::reference_internal)                 //
        .def("find_antigens", &HiDb::find_antigens, "name"_a)                                                     //
        .def("find_sera", &HiDb::find_sera, "name"_a)                                                             //
        .def("find_antigens_by_labid", &HiDb::find_antigens_by_labid, "labid"_a)                                  //
        .def("reference_antigens", &HiDb::reference_antigens, "table_index"_a)                                    //
        .def("most_recent_table", &HiDb::most_recent_table, "table_indexes"_a)                                    //
        .def("oldest_table", &HiDb::oldest_table, "table_indexes"_a)                                              //
        .def("save", &HiDb::save, "filename"_a, "write the loaded hidb back to JSON (compression by extension)")  //
        ;

    pybind11::class_<HidbMaker>(submodule, "HidbMaker")                                                            //
        .def(pybind11::init<>())                                                                                   //
        .def("add", [](HidbMaker& maker, const std::string& chart_file) { maker.add(ae::chart::v3::Chart{std::filesystem::path{chart_file}}); }, "chart_file"_a) //
        .def("number_of_antigens", &HidbMaker::number_of_antigens)                                                 //
        .def("number_of_sera", &HidbMaker::number_of_sera)                                                         //
        .def("number_of_tables", &HidbMaker::number_of_tables)                                                     //
        .def("json", &HidbMaker::json)                                                                             //
        .def("save", &HidbMaker::save, "filename"_a)                                                               //
        ;
}

// ======================================================================
