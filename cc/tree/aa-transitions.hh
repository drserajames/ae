#pragma once

#include "sequences/pos.hh"

// ======================================================================

namespace ae::tree
{
    class Tree;

    // `consensus`   — ae's own simple method: label a child branch whose subtree consensus
    //                 differs from its parent's consensus.
    // `eu_20200915` — port of acmacs-tal `cc/aa-transition-20200915.cc`
    //                 (`update_aa_transitions_eu_20200915[_per_pos]`), the method the WHO CC
    //                 report `.tal`s ask for by name.  Differs from `consensus` in three ways:
    //                 (1) a node counts as "common" only when EVERY child shares its consensus
    //                     aa, and a child is only labelled when at least TWO of its own children
    //                     share its consensus aa (the tolerance guard);
    //                 (2) a label is lifted to the highest node where the aa becomes common,
    //                     removing the same label from the nearest descendants that carry it;
    //                 (3) the left (ancestral) residue is anchored to the nearest ancestor
    //                     transition at that position, or, failing that, to the ROOT SEQUENCE —
    //                     and back-and-forth "flips" close to their ancestor are dropped.
    enum class aa_nuc_transition_method { consensus, eu_20200915 };

    struct AANucTransitionSettings
    {
        bool set_aa_labels{true};
        bool set_nuc_labels{false};
        aa_nuc_transition_method method{aa_nuc_transition_method::consensus};
        // Clear the labels the tree already carries (a `.asr` tjz's `A` fields) before computing.
        // acmacs-tal's `tal` does NOT: `Tal::reset()` runs only in its interactive loop, so a report
        // run imports the stored labels and the method ADDS to them — they take part in stage 3's
        // ancestor chain and so change the `left` residue of computed labels below them. Set this
        // false to reproduce an AD run over an `.asr` tree exactly.
        bool reset_labels{true};
        double non_common_tolerance{0.6};  // if in the intermediate node most freq aa occupies more that this value (relative to total), consider the most freq aa to be common in this node

        double non_common_tolerance_for(sequences::pos0_t /*pos*/) const
        {
            // if (non_common_tolerance_per_pos.size() <= *pos || non_common_tolerance_per_pos[*pos] < 0.0)
            return non_common_tolerance;
            // else
            //     return non_common_tolerance_per_pos[*pos];
        }
    };

    void set_aa_nuc_transition_labels(Tree& tree, const AANucTransitionSettings& settings);
}

// ======================================================================
