#include <functional>

#include "tree/tree.hh"
#include "tree/aa-transitions.hh"
#include "py/module.hh"

// ======================================================================

namespace ae::tree
{
    struct Node_Ref
    {
        node_index_t node_index;
        Tree& tree;

        std::string name() const
        {
            return tree.node(node_index).visit([](const auto* node) { return node->name; });
        }
        void set_name(std::string_view new_name)
        {
            tree.node(node_index).visit([new_name](auto* node) { node->name = new_name; });
        }
        double edge() const
        {
            return tree.node(node_index).visit([](const auto* node) -> double { return node->edge.get(); });
        }
        double cumulative_edge() const
        {
            return tree.node(node_index).visit([](const auto* node) -> double { return node->cumulative_edge.get(); });
        }
        node_index_base_t node_id() const
        {
            return tree.node(node_index).visit([](const auto* node) -> node_index_base_t { return node->node_id_.get(); });
        }

        Node_Ref parent() const { return Node_Ref{tree.parent(node_index), tree}; }

        size_t number_of_children() const
        {
            return tree.node(node_index).visit([](const Inode* inode) { return inode->children.size(); }, [](const Leaf*) { return 0ul; });
        }

        Node_Ref first_leaf() const { return Node_Ref{tree.first_leaf(node_index), tree}; }
        Node_Ref first_immediate_child_leaf() const { return Node_Ref{tree.first_immediate_child_leaf(node_index), tree}; }

    };

    struct Nodes_Iterator
    {
        const Nodes& nodes;
        size_t index{0};

        Node_Ref next()
        {
            if (index == nodes.nodes.size())
                throw pybind11::stop_iteration();
            return {nodes.nodes[index++], nodes.tree};
        }
    };

    inline void export_subtree(const Node_Ref& root, const std::filesystem::path& filename, size_t indent)
    {
        export_subtree(root.tree, root.node_index, filename, indent);
    }

    inline void load_subtree(const std::filesystem::path& filename, const Node_Ref& join_node)
    {
        load_subtree(filename, join_node.tree, join_node.node_index);
    }


} // namespace ae::tree

// ======================================================================

void ae::py::tree(pybind11::module_& mdl)
{
    using namespace std::string_view_literals;
    using namespace pybind11::literals;
    using namespace ae::tree;

    // ----------------------------------------------------------------------

    auto tree_submodule = mdl.def_submodule("tree", "tree manipulation");

    pybind11::class_<Tree, std::shared_ptr<Tree>>(tree_submodule, "Tree") //
        .def(
            "populate_with_sequences", [](Tree& tree, std::string_view subtype) { tree.populate_with_sequences(virus::type_subtype_t{subtype}); }, "subtype"_a) //
        .def(
            "populate_with_duplicates", [](Tree& tree, std::string_view subtype) { tree.populate_with_duplicates(virus::type_subtype_t{subtype}); }, "subtype"_a) //
        .def(
            "set_clades",                                                                                                                                          //
            [](Tree& tree, std::string_view clades_json_file) { tree.set_clades(std::filesystem::path{clades_json_file}); }, "clades_json"_a)                      //
        .def("select_all", &Tree::select_all)                                                                                                                      //
        .def("select_leaves", &Tree::select_leaves)                                                                                                                //
        .def("select_inodes", &Tree::select_inodes)                                                                                                                //
        .def("select_inodes_with_just_one_child", &Tree::select_inodes_with_just_one_child, pybind11::doc("inodes with just one child are problematic for raxml")) //
        .def(
            "remove",
            [](Tree& tree, std::vector<Node_Ref>& nodes) {
                std::vector<node_index_t> indexes(nodes.size());
                std::transform(std::begin(nodes), std::end(nodes), std::begin(indexes), [&tree](const auto& ref) {
                    if (&ref.tree != &tree)
                        throw std::invalid_argument{"nodes are not from the passed tree"};
                    return ref.node_index;
                });
                tree.remove(indexes);
            },
            "nodes"_a) //
        .def(
            "ladderize",
            [](Tree& tree, std::string_view method) {
                Tree::ladderize_method lm{Tree::ladderize_method::none};
                if (method == "number-of-leaves"sv)
                    lm = Tree::ladderize_method::number_of_leaves;
                else if (method == "max-edge-length")
                    lm = Tree::ladderize_method::max_edge_length;
                else if (method == "none")
                    lm = Tree::ladderize_method::none;
                else
                    throw std::invalid_argument{fmt::format("unknow ladderization method \"{}\", supported: \"number-of-leaves\", \"max-edge-length\", \"none\"", method)};
                tree.ladderize(lm);
            },
            "method"_a = "number-of-leaves")                                                                                              //
        .def("remove_leaves_isolated_before", &Tree::remove_leaves_isolated_before, "date"_a, "important"_a = std::vector<std::string>{}) //
        .def("number_of_leaves", &Tree::number_of_leaves)                                                                                 //
        .def(
            "fix_names_by_seqdb", [](Tree& tree, std::string_view subtype) { return tree.fix_names_by_seqdb(virus::type_subtype_t{subtype}); }, "subtype"_a,
            pybind11::doc("fix names not found in the current seqdb using hash, returns list of messages"))                                       //
        .def("set_raxml_ancestral_state_reconstruction_data", &Tree::set_raxml_ancestral_state_reconstruction_data, "asr_tree"_a, "asr_states"_a) //
        ;

    pybind11::class_<Nodes>(tree_submodule, "Nodes")                                                       //
        .def("sort_by_cumulative", &Nodes::sort_by_cumulative)                                             //
        .def("filter_by_cumulative_more_than", &Nodes::filter_by_cumulative_more_than, "min_cumulative"_a) //
        .def("filter_seq_id", &Nodes::filter_seq_id, "seq_ids"_a)                                          //
        .def("remove", &Nodes::remove)                                                                     //
        .def("__len__", [](const Nodes& nodes) { return nodes.nodes.size(); })                             //
        .def(
            "__iter__", [](const Nodes& nodes) { return Nodes_Iterator{nodes}; }, pybind11::keep_alive<0, 1>()) //
        .def("__getitem__",
             [](const Nodes& nodes, size_t index) {
                 if (index >= nodes.nodes.size())
                     throw std::out_of_range(fmt::format("index {} is out of range for Nodes, max index allowed: {}", index, nodes.nodes.size() - 1));
                 return Node_Ref{nodes.nodes[index], nodes.tree};
             }) //
        ;

    pybind11::class_<Nodes_Iterator>(tree_submodule, "Nodes_Iterator")             //
        .def("__iter__", [](Nodes_Iterator& it) -> Nodes_Iterator& { return it; }) //
        .def("__next__", &Nodes_Iterator::next)                                    //
        ;

    pybind11::class_<Node_Ref>(tree_submodule, "Node_Ref")                        //
        .def("name", &Node_Ref::name)                                             //
        .def("name", &Node_Ref::set_name)                                         //
        .def("edge", &Node_Ref::edge)                                             //
        .def("cumulative_edge", &Node_Ref::cumulative_edge)                       //
        .def("node_id", &Node_Ref::node_id)                                       //
        .def("parent", &Node_Ref::parent)                                         //
        .def("first_leaf", &Node_Ref::first_leaf)                                 //
        .def("first_immediate_child_leaf", &Node_Ref::first_immediate_child_leaf) //
        .def("number_of_children", &Node_Ref::number_of_children)                 //
        .def(
            "add_leaf",
            [](Node_Ref& parent, std::string_view name, double edge) {
                if (ae::tree::is_leaf(parent.node_index))
                    throw std::invalid_argument{"cannot add leaf to leaf (as parent)"};
                parent.tree.add_leaf(parent.node_index, name, EdgeLength{edge});
            },
            "name"_a, "edge"_a = 0.0, pybind11::doc("insert leaf into the tree as a child of self")) //
        .def(
            "add_sibling_leaf", [](Node_Ref& leaf, std::string_view name, double edge) { leaf.tree.add_leaf(leaf.tree.parent(leaf.node_index), name, EdgeLength{edge}); }, "name"_a, "edge"_a = 0.0,
            pybind11::doc("insert leaf into the tree as a child of the parent of self")) //
        ;

    tree_submodule.def("load", &load, "filename"_a);
    tree_submodule.def("load_subtree", pybind11::overload_cast<const std::filesystem::path&, const Node_Ref&>(&load_subtree), "filename"_a, "join_node"_a);
    tree_submodule.def("export", &export_tree, "tree"_a, "filename"_a, "indent"_a = 0);
    tree_submodule.def("export_subtree", pybind11::overload_cast<const Node_Ref&, const std::filesystem::path&, size_t>(&export_subtree), "root_node"_a, "filename"_a, "indent"_a = 0);

    // Mirrors acmacs-tal `Tree::report_first_last_leaves()` (AD cc/tree.cc, the `tal
    // --first-last-leaves N` report), so ae's transition labels can be diffed against AD's
    // AS DATA, keyed on each inode's (first leaf, last leaf) pair rather than on a node id
    // (AD's "vertical.horizontal" node_id has no ae equivalent).
    // Returns one tuple per inode with >= min_number_of_leaves leaves, in pre-order:
    //   (level, number_of_leaves, first_leaf_name, last_leaf_name, transitions)
    // `transitions` is AD's AA_Transitions::display(): space-joined "{left}{pos}{right}",
    // entries with an empty left or right omitted.
    tree_submodule.def(
        "report_first_last_leaves",
        [](Tree& tree, size_t min_number_of_leaves, bool aa) {
            tree.update_number_of_leaves_in_subtree();
            std::vector<std::tuple<size_t, size_t, std::string, std::string, std::string>> result;
            const auto last_leaf = [&tree](node_index_t index) {
                while (!is_leaf(index))
                    index = tree.inode(index).children.back();
                return index;
            };
            const auto display = [](const transitions_t& transitions) {
                fmt::memory_buffer out;
                bool first{true};
                for (const auto& tr : transitions.transitions) {
                    if (tr.left == ' ' || tr.right == ' ')
                        continue;
                    fmt::format_to(std::back_inserter(out), "{}{}{}{}", first ? "" : " ", tr.left, tr.pos, tr.right);
                    first = false;
                }
                return fmt::to_string(out);
            };
            const std::function<void(node_index_t, size_t)> walk = [&](node_index_t index, size_t level) {
                const Inode& node = tree.inode(index);
                if (node.number_of_leaves() >= min_number_of_leaves)
                    result.emplace_back(level, node.number_of_leaves(), tree.leaf(tree.first_leaf(index)).name, tree.leaf(last_leaf(index)).name,
                                        display(aa ? node.aa_transitions : node.nuc_transitions));
                for (const auto child : node.children) {
                    if (!is_leaf(child))
                        walk(child, level + 1);
                }
            };
            walk(Tree::root_index(), 0);
            return result;
        },
        "tree"_a, "min_number_of_leaves"_a = 20, "aa"_a = true);

    tree_submodule.def(
        "set_aa_nuc_transition_labels",
        [](Tree& tree, std::string_view method_str, bool set_aa_labels, bool set_nuc_labels, double non_common_tolerance, bool reset_labels) {
            aa_nuc_transition_method method{aa_nuc_transition_method::consensus};
            if (method_str == "consensus")
                method = aa_nuc_transition_method::consensus;
            else if (method_str == "eu-20200915" || method_str == "eu_20200915" || method_str == "eu-20200915-low-mem")
                method = aa_nuc_transition_method::eu_20200915; // the per-pos (low-mem) and full forms give identical labels
            else
                throw std::invalid_argument{AD_FORMAT("Unrecognized aa/nuc transition method: \"{}\"", method_str)};
            set_aa_nuc_transition_labels(
                tree, AANucTransitionSettings{.set_aa_labels = set_aa_labels, .set_nuc_labels = set_nuc_labels, .method = method, .reset_labels = reset_labels, .non_common_tolerance = non_common_tolerance});
        },
        "tree"_a, "method"_a = "consensus", "set_aa_labels"_a = true, "set_nuc_labels"_a = false, "non_common_tolerance"_a = 0.6, "reset_labels"_a = true);

    // ----------------------------------------------------------------------
}

// ======================================================================
