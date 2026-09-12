#include "tree/aa-transitions.hh"
#include "tree/tree.hh"
#include "utils/timeit.hh"

// ======================================================================

namespace ae::tree
{
    static void remove_aa_transition_labels(Tree& tree);
    static void remove_nuc_transition_labels(Tree& tree);
    static void set_aa_nuc_transition_labels_consensus(Tree& tree, const AANucTransitionSettings& settings);
    static void set_aa_nuc_transition_labels_eu_20200915(Tree& tree, const AANucTransitionSettings& settings);
}

// ----------------------------------------------------------------------

void ae::tree::set_aa_nuc_transition_labels(Tree& tree, const AANucTransitionSettings& settings)
{
    if (settings.reset_labels) {
        if (settings.set_aa_labels)
            remove_aa_transition_labels(tree);
        if (settings.set_nuc_labels)
            remove_nuc_transition_labels(tree);
    }
    switch (settings.method) {
        case aa_nuc_transition_method::consensus:
            set_aa_nuc_transition_labels_consensus(tree, settings);
            break;
        case aa_nuc_transition_method::eu_20200915:
            set_aa_nuc_transition_labels_eu_20200915(tree, settings);
            break;
    }

} // ae::tree::set_aa_nuc_transition_labels

// ----------------------------------------------------------------------

void ae::tree::remove_aa_transition_labels(Tree& tree)
{
    for (auto ref : tree.visit(tree_visiting::inodes))
        ref.inode()->aa_transitions.clear();

} // ae::tree::remove_aa_transition_labels

// ----------------------------------------------------------------------

void ae::tree::remove_nuc_transition_labels(Tree& tree)
{
    for (auto ref : tree.visit(tree_visiting::inodes))
        ref.inode()->nuc_transitions.clear();

} // ae::tree::remove_nuc_transition_labels

// ----------------------------------------------------------------------

namespace ae::tree
{
    enum class aa_nuc_e { aa, nuc };

    template <aa_nuc_e aa_nuc> class set_aa_nuc_transition_labels_consensus_t
    {
      public:
        set_aa_nuc_transition_labels_consensus_t(Tree& tree, sequences::pos0_t longest_seq, const Leaf& root_leaf, const AANucTransitionSettings& settings)
            : tree_{tree}, longest_seq_{longest_seq}, root_leaf_{root_leaf}, settings_{settings}
        {
        }

        void for_pos(sequences::pos0_t pos)
        {
            update_common(pos);

            //     // AD_DEBUG(parameters.debug, "eu-20200915 set aa transitions =============================================================");
            set_transitions(pos);
            //     // AD_DEBUG(parameters.debug, "eu-20200915 update aa transitions ================================================================================");

            //     // AD_DEBUG("update aa transitions");
            //     // const Timeit ti{"update aa transitions"};
            //     update_aa_transitions_eu_20200915_stage_3(tree, pos, root_sequence, parameters);
        }

        sequences::pos0_t seq_size(const Leaf& leaf) const
        {
            if constexpr (aa_nuc == aa_nuc_e::aa)
                return leaf.aa.size();
            else
                return leaf.nuc.size();
        }

        char seq_at(const Leaf& leaf, sequences::pos0_t pos) const
        {
            if constexpr (aa_nuc == aa_nuc_e::aa)
                return leaf.aa[pos];
            else
                return leaf.nuc[pos];
        }

        void update_common(sequences::pos0_t pos)
        {
            for (auto ref : tree_.visit(tree_visiting::inodes))
                ref.inode()->reset_common_aa();

            // unsigned max_count{0};
            for (auto ref : tree_.visit(tree_visiting::inodes_post)) {
                auto& node = *ref.inode();
                for (const auto child_id : node.children) {
                    if (is_leaf(child_id)) {
                        if (auto& child = tree_.leaf(child_id); child.shown) {
                            if (seq_size(child) > pos)
                                node.common_aa->count(seq_at(child, pos));
                        }
                    }
                    else {
                        if (auto& child = tree_.inode(child_id); child.shown)
                            node.common_aa->update(*child.common_aa);
                    }
                }
                // max_count = std::max(max_count, node.common_aa->max().second);
            }
        }

        void set_transitions(sequences::pos0_t pos)
        {
            const auto non_common_tolerance = settings_.non_common_tolerance_for(pos);
            for (auto ref : tree_.visit(tree_visiting::inodes_post))
                set_transitions(*ref.inode(), pos, non_common_tolerance);
        }

        // char common_at(const Inode& inode, sequences::pos0_t pos, double non_common_tolerance)
        //     {
        //     }

        // The consensus aa at this position if the most frequent aa occupies more than
        // `tolerance` of the subtree (else 0 = no consensus). Gaps/unknowns never count
        // as a consensus, so transitions to/from "-"/"X" are not produced.
        static char common_at(const Inode& node, double tolerance)
        {
            if (!node.common_aa)
                return 0;
            const auto total = node.common_aa->total();
            if (total == 0)
                return 0;
            const auto [aa, count] = node.common_aa->max();
            if (aa == '-' || aa == 'X')
                return 0;
            return static_cast<double>(count) > tolerance * static_cast<double>(total) ? aa : char{0};
        }

        // A transition is placed on a child branch where the child subtree's consensus aa
        // differs from its (consensus) parent — i.e. the substitution happened on that edge.
        void set_transitions(Inode& node, sequences::pos0_t pos, double non_common_tolerance)
        {
            const char node_aa = common_at(node, non_common_tolerance);
            if (node_aa == 0)
                return; // parent has no consensus -> no defined transition here
            for (const auto child_id : node.children) {
                if (is_leaf(child_id))
                    continue;
                auto& child = tree_.inode(child_id);
                if (!child.shown)
                    continue;
                if (const char child_aa = common_at(child, non_common_tolerance); child_aa != 0 && child_aa != node_aa)
                    child.aa_transitions.add(node_aa, static_cast<sequences::pos1_t>(pos), child_aa);
            }
        }

        bool is_common_with_tolerance(const Inode& node, sequences::pos0_t pos, double tolerance)
        {
        //     const auto aa = node.common_aa->at(pos, tolerance);
        //     if (aa == NoCommon) {
        //         if constexpr (dbg)
        //             fmt::format_to_mb(msg, "common:no");
        //         return {false, fmt::to_string(msg)};
        //     }
        //     // tolerance problem: aa is common with tolerance but in
        //     // reality just 1 or 2 child nodes have this aa and other
        //     // children (with much fewer leaves) have different
        //     // aa's. In that case consider that aa to be not
        //     // common. See H3 and M346L labelling in the 3a clade.
        //     const auto [num_common_aa_children, common_children] = number_of_children_with_the_same_common_aa<dbg>(node, aa, pos, tolerance);
        //     const auto not_common = // num_common_aa_children > 0 && number_of_children_with_the_same_common_aa <= 1 &&
        //         node.subtree.size() > static_cast<size_t>(num_common_aa_children);
        //     if constexpr (dbg) {
        //         fmt::format_to_mb(msg, fmt::runtime("common:{} <-- {} {:5.3} aa:{} tolerance:{} number_of_children_with_the_same_common_aa:{} ({}) subtree-size:{}"), !not_common, pos, node.node_id,
        //                           aa, tolerance, num_common_aa_children, common_children, node.subtree.size());
        //     }
        //     return !not_common;
        }

        // bool is_common_with_tolerance_for_child(const Inode& node, sequences::pos0_t pos, double tolerance)
        // {
        //     fmt::memory_buffer msg;
        //     const auto aa = node.common_aa_->at(pos, tolerance);
        //     if (aa == NoCommon) {
        //         if constexpr (dbg)
        //             fmt::format_to_mb(msg, "common:no");
        //         return {false, fmt::to_string(msg)};
        //     }
        //     else {
        //         const auto [num_common_aa_children, common_children] = number_of_children_with_the_same_common_aa<dbg>(node, aa, pos, tolerance);
        //         const auto not_common = num_common_aa_children <= 1; // && node.subtree.size() > static_cast<size_t>(num_common_aa_children);
        //         if constexpr (dbg) {
        //             fmt::format_to_mb(msg, fmt::runtime("common:{} <-- {} {:5.3} aa:{} tolerance:{} number_of_children_with_the_same_common_aa:{} ({}) subtree-size:{}"), !not_common, pos,
        //                               node.node_id, aa, tolerance, num_common_aa_children, common_children, node.subtree.size());
        //         }
        //         return {!not_common, fmt::to_string(msg)};
        //     }
        // }

      private:
        Tree& tree_;
        sequences::pos0_t longest_seq_;
        const Leaf& root_leaf_;
        const AANucTransitionSettings& settings_;
    };
} // namespace ae::tree

// ----------------------------------------------------------------------

void ae::tree::set_aa_nuc_transition_labels_consensus(Tree& tree, const AANucTransitionSettings& settings)
{
    const auto& root_leaf = tree.leaf(tree.first_leaf(tree.root_index()));
    // const auto total_leaves = tree.number_leaves_in_subtree();
    const auto [max_aa, max_nuc] = tree.longest_sequence();
    set_aa_nuc_transition_labels_consensus_t<aa_nuc_e::aa> set_aa{tree, max_aa, root_leaf, settings};
    set_aa_nuc_transition_labels_consensus_t<aa_nuc_e::nuc> set_nuc{tree, max_nuc, root_leaf, settings};
    auto start = ae::clock_t::now(), chunk_start = start;
    for (sequences::pos0_t pos{0}; pos < max_aa; ++pos) {
        if (settings.set_aa_labels)
            set_aa.for_pos(pos);
        if (settings.set_nuc_labels)
            set_nuc.for_pos(pos);
        if ((*pos % 100) == 99) {
            AD_DEBUG("set_aa_nuc_transition_labels_consensus pos:{}  time: {:%H:%M:%S}", pos, ae::elapsed(chunk_start));
            chunk_start = ae::clock_t::now();
        }
    }
    AD_DEBUG("set_aa_nuc_transition_labels_consensus positions: {}  time: {:%H:%M:%S}", max_aa, ae::elapsed(start));

    // tree::iterate_pre(tree, [&parameters](Node& node) { node.aa_transitions_.remove_left_right_same(parameters, node); });

    // if (!tree.aa_transitions_.empty())
    //     AD_WARNING("Root AA transions: {} (hide some roots to show this transion(s) in the first branch)", tree.aa_transitions_);

} // ae::tree::set_aa_nuc_transition_labels_consensus

// ----------------------------------------------------------------------

// ======================================================================
// eu-20200915 — port of acmacs-tal cc/aa-transition-20200915.cc
// ======================================================================
//
// AD entry points ported here (`acmacs::tal::v3::detail::`):
//
//   update_aa_transitions_eu_20200915_per_pos()      the per-position driver (low-mem form;
//                                                    identical results to the all-positions
//                                                    form, since each position is independent)
//     update_common_aa_for_pos()                     -> update_common()
//     set_aa_transitions_eu_20210205_for_pos()       -> set_transitions()
//       set_aa_transitions_for_pos_eu_20210205()     -> set_transitions_for_node()
//         is_common_with_tolerance()                 -> is_common_with_tolerance()
//         is_common_with_tolerance_for_child()       -> is_common_with_tolerance_for_child()
//         Node::replace_aa_transition()              -> replace_transition()
//     update_aa_transitions_eu_20200915_stage_3()    -> stage_3()   <-- root-sequence anchoring
//   AA_Transitions::remove_left_right_same()         -> transitions_t::remove_left_right_same()
//
// Differences from ae's own `consensus` method, in order of impact on the output:
//
//  * ROOT ANCHORING (stage 3).  `consensus` writes `left` = the parent's consensus aa at
//    label time.  eu-20200915 sets it in a separate pre/post walk: `left` is the `right` of
//    the nearest ANCESTOR carrying a label at the same position, and — when there is no such
//    ancestor — the residue of the tree's FIRST LEAF (the root sequence).  That is what makes
//    an ancestral substitution appear at all, and what fixes its polarity.
//  * FLIP REMOVAL (stage 3).  When a descendant label reverts its ancestor's substitution
//    (`right == ancestor.left`) within fewer than 3 levels, and the reverting subtrees hold
//    more than 0.5 % of the ancestor's leaves, the ANCESTOR's label is dropped and the whole
//    walk repeats.  `consensus` has no such pass.
//  * "COMMON" IS STRICTER.  AD calls a node common only when the consensus holds AND every
//    one of its children shares it; a child is labelled only when >= 2 of the child's own
//    children share the child's consensus.  `consensus` just compares two consensus residues.
//  * LABEL LIFTING.  `Node::replace_aa_transition` removes the identical label from the
//    nearest descendants that carry one (pruning at the first labelled node on each path)
//    before adding it here, so a substitution is reported once, as high as it is common.
//  * 'X' IS NOT COUNTED into the consensus (AD `CommonAA::update`), while '-' IS — `consensus`
//    counts 'X' and then refuses '-' as a consensus residue.
//  * left == right labels are dropped at the very end (AD `remove_left_right_same`).

namespace ae::tree
{
    template <aa_nuc_e aa_nuc> class set_transitions_eu_20200915_t
    {
      public:
        set_transitions_eu_20200915_t(Tree& tree, const AANucTransitionSettings& settings) : tree_{tree}, settings_{settings} {}

        void run(sequences::pos0_t longest_seq)
        {
            const auto& root_leaf = tree_.leaf(tree_.first_leaf(tree_.root_index()));
            auto start = ae::clock_t::now(), chunk_start = start;
            for (sequences::pos0_t pos{0}; pos < longest_seq; ++pos) {
                update_common(pos);
                set_transitions(pos);
                stage_3(pos, seq_at(root_leaf, pos));
                if ((*pos % 100) == 99) {
                    AD_DEBUG("set_aa_nuc_transition_labels_eu_20200915 pos:{}  time: {:%H:%M:%S}", pos, ae::elapsed(chunk_start));
                    chunk_start = ae::clock_t::now();
                }
            }
            // AD: tree::iterate_pre(tree, [](Node& node) { node.aa_transitions_.remove_left_right_same(...); })
            for (auto ref : tree_.visit(tree_visiting::inodes))
                transitions(*ref.inode()).remove_left_right_same();
            if (!transitions(tree_.root()).empty())
                AD_WARNING("Root AA transitions: {} (hide some roots to show this transition(s) in the first branch)", transitions(tree_.root()));
            AD_DEBUG("set_aa_nuc_transition_labels_eu_20200915 positions: {}  time: {:%H:%M:%S}", longest_seq, ae::elapsed(start));
        }

      private:
        constexpr static char NoCommon{0}; // AD uses '.', which cannot occur in a sequence either

        Tree& tree_;
        const AANucTransitionSettings& settings_;

        static transitions_t& transitions(Inode& node)
        {
            if constexpr (aa_nuc == aa_nuc_e::aa)
                return node.aa_transitions;
            else
                return node.nuc_transitions;
        }

        static sequences::pos0_t seq_size(const Leaf& leaf)
        {
            if constexpr (aa_nuc == aa_nuc_e::aa)
                return leaf.aa.size();
            else
                return leaf.nuc.size();
        }

        static char seq_at(const Leaf& leaf, sequences::pos0_t pos) // ' ' if beyond the sequence, as AD's sequence_aligned_t::at()
        {
            if constexpr (aa_nuc == aa_nuc_e::aa)
                return leaf.aa[pos];
            else
                return leaf.nuc[pos];
        }

        // --- AD detail::update_common_aa_for_pos() -------------------------------------
        // Post-order: every inode's counter holds the residues of its shown leaves at `pos`.
        // 'X' is never counted (AD CommonAA::update skips `Any`); '-' is.
        void update_common(sequences::pos0_t pos) { update_common(Tree::root_index(), pos); }

        void update_common(node_index_t index, sequences::pos0_t pos)
        {
            Inode& node = tree_.inode(index);
            node.reset_common_aa();
            for (const auto child : node.children) {
                if (!is_leaf(child))
                    update_common(child, pos);
            }
            for (const auto child : node.children) {
                if (is_leaf(child)) {
                    if (const Leaf& leaf = tree_.leaf(child); leaf.shown && seq_size(leaf) > pos) {
                        if (const char aa = seq_at(leaf, pos); aa != 'X')
                            node.common_aa->count(aa);
                    }
                }
                else {
                    if (const Inode& child_inode = tree_.inode(child); child_inode.shown)
                        node.common_aa->update(*child_inode.common_aa);
                }
            }
        }

        // --- AD CommonAA::at(pos, tolerance) --------------------------------------------
        static char common_at(const Inode& node, double tolerance)
        {
            if (!node.common_aa)
                return NoCommon;
            const auto total = node.common_aa->total();
            if (total == 0)
                return NoCommon;
            const auto [aa, count] = node.common_aa->max();
            return (static_cast<double>(count) / static_cast<double>(total)) > tolerance ? aa : NoCommon;
        }

        // --- AD number_of_children_with_the_same_common_aa() -----------------------------
        // NB AD does not skip hidden children here (only update_common_aa does), so neither do we.
        std::size_t children_with_common_aa(const Inode& node, char aa, sequences::pos0_t pos, double tolerance) const
        {
            std::size_t num{0};
            for (const auto child : node.children) {
                if (is_leaf(child)) {
                    if (seq_at(tree_.leaf(child), pos) == aa)
                        ++num;
                }
                else {
                    if (common_at(tree_.inode(child), tolerance) == aa)
                        ++num;
                }
            }
            return num;
        }

        // --- AD is_common_with_tolerance() ----------------------------------------------
        // A consensus that only ONE child actually carries is not a consensus: the tolerance
        // lets one large child outvote several small ones (see AD's comment at the top of
        // aa-transition-20200915.cc for the case this guards against).
        bool is_common_with_tolerance(const Inode& node, sequences::pos0_t pos, double tolerance) const
        {
            const char aa = common_at(node, tolerance);
            if (aa == NoCommon)
                return false;
            return children_with_common_aa(node, aa, pos, tolerance) >= node.children.size();
        }

        // --- AD is_common_with_tolerance_for_child() -------------------------------------
        bool is_common_with_tolerance_for_child(const Inode& node, sequences::pos0_t pos, double tolerance) const
        {
            const char aa = common_at(node, tolerance);
            if (aa == NoCommon)
                return false;
            return children_with_common_aa(node, aa, pos, tolerance) > 1;
        }

        // --- AD Node::remove_aa_transition() ---------------------------------------------
        // Remove (pos, right) from this node and from the nearest descendants carrying a label
        // at `pos`, pruning each path at the first labelled node (AD iterate_leaf_pre_stop).
        void remove_transition(node_index_t index, sequences::pos1_t pos, char right)
        {
            if (is_leaf(index))
                return; // ae leaves carry no transitions
            Inode& node = tree_.inode(index);
            const bool present_any = transitions(node).find(pos) != nullptr;
            transitions(node).remove(pos, right);
            if (present_any)
                return;
            for (const auto child : node.children)
                remove_transition(child, pos, right);
        }

        // --- AD Node::replace_aa_transition() --------------------------------------------
        void replace_transition(node_index_t index, sequences::pos1_t pos, char right)
        {
            remove_transition(index, pos, right);
            transitions(tree_.inode(index)).add(pos, right);
        }

        // --- AD set_aa_transitions_eu_20210205_for_pos() ---------------------------------
        void set_transitions(sequences::pos0_t pos)
        {
            set_transitions(Tree::root_index(), pos, settings_.non_common_tolerance_for(pos));
        }

        void set_transitions(node_index_t index, sequences::pos0_t pos, double tolerance)
        {
            Inode& node = tree_.inode(index);
            for (const auto child : node.children) { // post-order, as AD tree::iterate_post
                if (!is_leaf(child))
                    set_transitions(child, pos, tolerance);
            }
            set_transitions_for_node(index, pos, tolerance);
        }

        // --- AD set_aa_transitions_for_pos_eu_20210205() ---------------------------------
        void set_transitions_for_node(node_index_t index, sequences::pos0_t pos, double tolerance)
        {
            const sequences::pos1_t pos1{pos};
            if (!is_common_with_tolerance(tree_.inode(index), pos, tolerance)) {
                // this node has no single residue: each child that does gets a (right-only) label
                for (const auto child : tree_.inode(index).children) {
                    if (is_leaf(child))
                        continue;
                    if (is_common_with_tolerance_for_child(tree_.inode(child), pos, tolerance)) {
                        const char aa = common_at(tree_.inode(child), tolerance);
                        transitions(tree_.inode(child)).add(pos1, aa);
                    }
                }
            }
            else {
                // this node has a single residue: a child whose own residue is established
                // takes the label over from its descendants (replace lifts it up the tree)
                for (const auto child : tree_.inode(index).children) {
                    if (is_leaf(child))
                        continue;
                    const Inode& child_inode = tree_.inode(child);
                    if (!child_inode.common_aa || child_inode.common_aa->total() == 0)
                        continue; // AD: child.common_aa_->empty(pos)
                    const char child_aa = common_at(child_inode, tolerance);
                    if (is_common_with_tolerance_for_child(child_inode, pos, tolerance))
                        replace_transition(child, pos1, child_aa);
                }
            }
        }

        // --- AD update_aa_transitions_eu_20200915_stage_3() ------------------------------
        // THE root-anchoring pass.  `left` of every label is the `right` of the nearest
        // ancestor label at the same position, else the root sequence's residue.  A label whose
        // descendants flip it back within < 3 levels, over > 0.5 % of its leaves, is removed and
        // the walk restarts.
        struct flips_leaves_t
        {
            transitions_t* transitions{nullptr};
            std::size_t flips{0};
            std::size_t leaves{0};
            std::ptrdiff_t min_flip_distance{0};

            void add(std::size_t number_of_leaves, std::ptrdiff_t distance)
            {
                if (flips == 0 || distance < min_flip_distance)
                    min_flip_distance = distance;
                ++flips;
                leaves += number_of_leaves;
            }
        };

        void stage_3(sequences::pos0_t pos, char root_aa)
        {
            const sequences::pos1_t pos1{pos};
            const double leaves_ratio_threshold{0.005};
            for (bool repeat{true}; repeat;) {
                repeat = false;
                std::vector<flips_leaves_t> stack;
                stage_3_walk(Tree::root_index(), pos1, root_aa, leaves_ratio_threshold, stack, repeat);
            }
        }

        void stage_3_walk(node_index_t index, sequences::pos1_t pos1, char root_aa, double leaves_ratio_threshold, std::vector<flips_leaves_t>& stack, bool& repeat)
        {
            if (is_leaf(index))
                return; // AD tree::iterate_pre_post visits inodes only
            Inode& node = tree_.inode(index);

            // --- pre ---
            if (transition_t* this_transition = transitions(node).find(pos1); this_transition != nullptr) {
                const transition_t* prev_trans{nullptr};
                flips_leaves_t* prev_frame{nullptr};
                std::ptrdiff_t distance{0};
                for (auto it = stack.rbegin(); it != stack.rend(); ++it, ++distance) {
                    if (const transition_t* found = it->transitions->find(pos1); found != nullptr) {
                        prev_trans = found;
                        prev_frame = &*it;
                        break;
                    }
                }
                if (prev_trans != nullptr) {
                    this_transition->left = prev_trans->right;
                    if (this_transition->left != this_transition->right && this_transition->right == prev_trans->left)
                        prev_frame->add(node.number_of_leaves(), distance);
                }
                else
                    this_transition->left = root_aa;
            }
            stack.push_back(flips_leaves_t{.transitions = &transitions(node)});

            for (const auto child : node.children)
                stage_3_walk(child, pos1, root_aa, leaves_ratio_threshold, stack, repeat);

            // --- post ---
            if (const auto& fl = stack.back(); fl.flips) {
                const auto node_leaves = node.number_of_leaves();
                const auto leaves_ratio = node_leaves ? static_cast<double>(fl.leaves) / static_cast<double>(node_leaves) : 0.0;
                if (fl.min_flip_distance < 3 && leaves_ratio > leaves_ratio_threshold) {
                    transitions(node).remove(pos1);
                    repeat = true;
                }
            }
            stack.pop_back();
        }
    };

} // namespace ae::tree

// ----------------------------------------------------------------------

void ae::tree::set_aa_nuc_transition_labels_eu_20200915(Tree& tree, const AANucTransitionSettings& settings)
{
    tree.update_number_of_leaves_in_subtree(); // stage 3's leaves_ratio needs these
    const auto [max_aa, max_nuc] = tree.longest_sequence();
    if (settings.set_aa_labels) {
        set_transitions_eu_20200915_t<aa_nuc_e::aa> set_aa{tree, settings};
        set_aa.run(max_aa);
    }
    if (settings.set_nuc_labels) {
        set_transitions_eu_20200915_t<aa_nuc_e::nuc> set_nuc{tree, settings};
        set_nuc.run(max_nuc);
    }

} // ae::tree::set_aa_nuc_transition_labels_eu_20200915

// ----------------------------------------------------------------------
