#include <vector>
#include <stack>
#include <cctype>
#include <stdexcept>
#include <string_view>

#include "ext/from_chars.hh"
#include "utils/timeit.hh"
#include "tree/newick.hh"
#include "tree/tree.hh"

// https://en.wikipedia.org/wiki/Newick_format

// ======================================================================
//
// Hand-written iterative Newick scanner.
//
// The tree is built with an explicit parent stack (tree_builder_t::parents), so
// parsing uses O(1) C++ call-stack regardless of how deep/unbalanced the tree is.
// This replaces an earlier lexy recursive-descent grammar whose real C++ recursion
// was capped at max_recursion_depth=1000: deeper "caterpillar" trees (common after
// ladderizing real influenza trees with thousands of leaves) made the parse abort,
// load_newick() return nullptr, and ae::tree::load() then segfault dereferencing it.
//
// ======================================================================

namespace ae::tree::newick
{
    class invalid_input : public std::runtime_error
    {
      public:
        using std::runtime_error::runtime_error;
    };

    struct tree_builder_t
    {
        tree_builder_t(Tree& a_tree) : tree{a_tree} {}
        tree_builder_t(Tree& a_tree, node_index_t join_at) : tree{a_tree} { parents.push(join_at); }

        void subtree_begin() const
        {
            if (parents.empty())
                parents.push(tree.root_index());
            else
                parents.push(tree.add_inode(parents.top()).first);
            max_nesting_level = std::max(max_nesting_level, parents.size());
        }

        void subtree_end(std::string_view name, double edge) const
        {
            auto& inode = tree.inode(parents.top());
            inode.edge = EdgeLength{edge};
            inode.name = name;
            parents.pop();
        }

        void leaf(std::string_view name, double edge) const
        {
            tree.add_leaf(parents.top(), name, EdgeLength{edge});
            ++leaves;
        }

        Tree& tree;
        mutable std::stack<node_index_t> parents{};
        mutable size_t leaves{0};
        mutable size_t max_nesting_level{0};
    };

    // ----------------------------------------------------------------------

    // Characters that terminate a name token (Newick delimiters). Whitespace also
    // terminates a name but is tested separately so multibyte UTF-8 name bytes pass.
    inline bool is_name_delimiter(char c)
    {
        switch (c) {
            case '(':
            case ')':
            case ',':
            case ':':
            case ';':
                return true;
            default:
                return std::isspace(static_cast<unsigned char>(c)) != 0;
        }
    }

    inline bool is_number_char(char c)
    {
        switch (c) {
            case '-':
            case '+':
            case '.':
            case 'e':
            case 'E':
                return true;
            default:
                return c >= '0' && c <= '9';
        }
    }

    // Iterative scanner: drives tree_builder_t hooks; the builder's parent stack is
    // the only "recursion" state, so call-stack usage is constant.
    inline void parse(std::string_view source, const tree_builder_t& builder)
    {
        const char* p = source.data();
        const char* const end = p + source.size();
        const size_t initial_depth = builder.parents.size(); // >0 for load_join_newick

        const auto skip_ws = [&p, end]() {
            while (p != end && std::isspace(static_cast<unsigned char>(*p)) != 0)
                ++p;
        };

        const auto read_name = [&p, end, &skip_ws]() -> std::string_view {
            skip_ws();
            const char* const begin = p;
            while (p != end && !is_name_delimiter(*p))
                ++p;
            return std::string_view{begin, static_cast<size_t>(p - begin)};
        };

        const auto read_edge = [&p, end, &skip_ws]() -> double {
            skip_ws();
            if (p != end && *p == ':') {
                ++p;
                skip_ws();
                const char* const begin = p;
                while (p != end && is_number_char(*p))
                    ++p;
                if (p != begin)
                    return ae::from_chars<double>(begin, p);
            }
            return 0.0;
        };

        skip_ws();
        if (p == end || *p != '(')
            throw invalid_input{"newick must start with '('"};

        bool done = false;
        while (p != end && !done) {
            skip_ws();
            if (p == end)
                break;
            switch (*p) {
                case '(':
                    ++p;
                    builder.subtree_begin();
                    break;
                case ',':
                    ++p;
                    break;
                case ')': {
                    ++p;
                    if (builder.parents.size() <= initial_depth)
                        throw invalid_input{"unbalanced ')' in newick"};
                    const auto name = read_name();
                    const auto edge = read_edge();
                    builder.subtree_end(name, edge);
                    break;
                }
                case ';':
                    ++p;
                    done = true;
                    break;
                default: {
                    const auto name = read_name();
                    if (name.empty()) // an unhandled delimiter: avoid spinning forever
                        throw invalid_input{fmt::format("unexpected character '{}' in newick", *p)};
                    const auto edge = read_edge();
                    builder.leaf(name, edge);
                    break;
                }
            }
        }

        if (!done)
            throw invalid_input{"newick missing terminating ';'"};
        if (builder.parents.size() != initial_depth)
            throw invalid_input{"unbalanced '(' in newick"};
    }

} // namespace ae::tree::newick

// ----------------------------------------------------------------------

std::shared_ptr<ae::tree::Tree> ae::tree::load_newick(const std::string& source)
{
    try {
        auto tree = std::make_shared<Tree>();
        newick::tree_builder_t tree_builder{*tree};
        newick::parse(source, tree_builder);
        // fmt::print(">>>> {} leaves in the tree read from newick, max nesting level: {}\n", tree_builder.leaves, tree_builder.max_nesting_level);
        return tree;
    }
    catch (newick::invalid_input& err) {
        fmt::print(">> newick parsing error: {}\n", err.what());
        return nullptr;
    }

} // ae::tree::load_newick

// ----------------------------------------------------------------------

void ae::tree::load_join_newick(const std::string& source, Tree& tree, node_index_t join_at)
{
    try {
        newick::tree_builder_t tree_builder{tree, join_at};
        newick::parse(source, tree_builder);
        // fmt::print(">>>> {} leaves in the tree read from newick, max nesting level: {}\n", tree_builder.leaves, tree_builder.max_nesting_level);
    }
    catch (newick::invalid_input& err) {
        fmt::print(">> newick parsing error: {}\n", err.what());
    }

} // ae::tree::load_join_newick

// ----------------------------------------------------------------------

std::string ae::tree::export_newick(const Tree& tree, const Inode& root, size_t indent)
{
    Timeit ti{"tree::export_newick", std::chrono::milliseconds{100}};

    fmt::memory_buffer text;
    std::vector<bool> commas{false};
    commas.reserve(tree.depth());
    size_t current_indent = 0;

    const auto format_prefix = [&text, &current_indent, indent]() {
        if (indent)
            fmt::format_to(std::back_inserter(text), "\n{:{}s}", " ", current_indent);
    };

    const auto format_comma = [&text, &commas, format_prefix]() {
        if (commas.back()) {
            fmt::format_to(std::back_inserter(text), ",");
            format_prefix();
        }
        else
            commas.back() = true;
    };

    const auto format_edge = [&text](auto edge) {
        if (edge != 0.0)
            fmt::format_to(std::back_inserter(text), ":{:.10g}", *edge);
    };

    const auto format_inode_pre = [&text, &commas, format_comma, &current_indent, indent, format_prefix](const Inode*) {
        format_comma();
        fmt::format_to(std::back_inserter(text), "(");
        current_indent += indent;
        format_prefix();
        commas.push_back(false);
    };

    const auto format_inode_post = [&text, &commas, format_edge, &current_indent, indent, format_prefix](const Inode* inode) {
        commas.pop_back();
        if (current_indent >= indent)
            current_indent -= indent;
        format_prefix();
        fmt::format_to(std::back_inserter(text), "){}", inode->name);
        format_edge(inode->edge);
    };

    const auto format_leaf = [&text, format_comma, format_edge](const Leaf* leaf) {
        format_comma();
        fmt::format_to(std::back_inserter(text), "{}", leaf->name);
        format_edge(leaf->edge);
    };

    const auto format_leaf_post = [](const Leaf* leaf) {
        fmt::print("> export_newick format_leaf_post \"{}\"\n", leaf->name);
    };

    bool within_subtree = false;
    for (const auto ref : tree.visit(tree_visiting::all_pre_post)) {
        if (ref.pre()) {
            if (!within_subtree && root.node_id_ == ref.node_id())
                within_subtree = true;
            if (within_subtree)
                ref.visit(format_inode_pre, format_leaf);
        }
        else if (within_subtree) {
            ref.visit(format_inode_post, format_leaf_post);
            if (root.node_id_ == ref.node_id())
                within_subtree = false;
        }
    }
    fmt::format_to(std::back_inserter(text), ";");

    return fmt::to_string(text);

} // ae::tree::export_newick

// ----------------------------------------------------------------------
