#!/usr/bin/env python3
# Tests for nucleotide rules in the geographic-map colouring
# (py/ae/report/geographic.py `_norm_coloring` + `_Coloring`).
#
# Why this exists: `Clades::clades` (cc/sequences/clades.cc) assigns a clade only when both its
# `aa` and its `nuc` tokens match, so a clade defined partly at nucleotide positions could not be
# reproduced by an aa-only `geographic_coloring` rule. Rules now take an optional `nuc` field.
#
# The seqdb is a stub: the bindings expose no constructor for SequenceAA/SequenceNuc, so the
# sequences here are small Python objects implementing the same `matches_all` token semantics
# (1-based "POS<char>", "!" negation). Everything is invented — strain names "V<n>", sequences of
# a few letters — NO WHO data.
#
# Checked:
#   1. `nuc` is normalised like `aa` (string -> tokens, absent -> []);
#   2. aa-only, nuc-only and aa+nuc rules match only when every non-empty list matches;
#   3. a negated nuc token;
#   4. a rule with nuc tokens does NOT match an antigen with no nucleotide sequence;
#   5. later matches win, `sequenced` still sets only the fill, and a rule with neither aa nor
#      nuc is ignored;
#   6. the memoised result reflects the nuc test.
#
# Run (from the ae worktree root; needs no build):
#   PYTHONPATH="$PWD/py" python3 test/test-geographic-nuc-rules.py

import sys

from ae.report.geographic import _Coloring, _norm_coloring

FAILURES: list[str] = []


def check_eq(got, expected, message):
    if got == expected:
        print(f"  ok   {message}")
    else:
        print(f"  FAIL {message}: got {got!r}, expected {expected!r}")
        FAILURES.append(message)


class FakeSeq:
    def __init__(self, text):
        self.text = text

    def __bool__(self):
        return bool(self.text)

    def matches_all(self, tokens):
        for token in tokens:
            negate = token.startswith("!")
            body = token[1:] if negate else token
            pos, char = int(body[:-1]), body[-1]
            at = self.text[pos - 1] if pos <= len(self.text) else " "
            if (at == char) == negate:
                return False
        return True


class FakeRef:
    def __init__(self, aa, nuc):
        self.aa, self.nuc = FakeSeq(aa), FakeSeq(nuc)


class FakeSelected(list):
    def filter_name(self, name, reassortant, passage):
        return FakeSelected(ref for ref_name, ref in self if ref_name == name)

    def find_masters(self):
        pass


class FakeSeqdb:
    def __init__(self, entries):
        self.entries = entries
        self.lookups = 0

    def select_all(self):
        self.lookups += 1
        return FakeSelected(self.entries.items())


class FakeBackend:
    def __init__(self, seqdb):
        self.seqdb = type("seqdb", (), {"for_subtype": staticmethod(lambda subtype: seqdb)})


class FakeAntigen:
    def __init__(self, name):
        self._name = name
        self.passage = self.reassortant = ""

    def name(self):
        return self._name


def fill(colorer, name):
    return colorer.color(FakeAntigen(name))["color"]


# ======================================================================

print("1. normalisation")
default, rules = _norm_coloring({"default": {"fill": "white"}, "apply": [
    {"aa": "1K 2L", "fill": "red"}, {"nuc": "3G !4T", "fill": "blue"}, {"aa": ["1K"], "fill": "green"}]})
check_eq([r["aa"] for r in rules], [["1K", "2L"], [], ["1K"]], "aa tokens")
check_eq([r["nuc"] for r in rules], [[], ["3G", "!4T"], []], "nuc tokens, absent -> []")

# ======================================================================

seqdb = FakeSeqdb({
    "V1": FakeRef("KL", "ACGA"),     # aa 1K, nuc 3G 4A
    "V2": FakeRef("KL", "ACTA"),     # aa 1K, nuc 3T
    "V3": FakeRef("ML", "ACGA"),     # aa 1M, nuc 3G
    "V4": FakeRef("KL", ""),         # aa 1K, no nuc
    "V5": FakeRef("KL", "ACGT"),     # aa 1K, nuc 3G 4T
    "V6": FakeRef("", "ACGA"),       # no aa: unsequenced
})


def colorer(apply):
    return _Coloring(FakeBackend(seqdb), "X", {"default": {"color": "white"}, "apply": apply})


print("2. aa-only / nuc-only / aa+nuc")
aa_only = colorer([{"aa": "1K", "fill": "red"}])
check_eq([fill(aa_only, n) for n in ("V1", "V2", "V3", "V4")], ["red", "red", "white", "red"], "aa-only ignores nuc")
nuc_only = colorer([{"nuc": "3G", "fill": "blue"}])
check_eq([fill(nuc_only, n) for n in ("V1", "V2", "V3", "V4")], ["blue", "white", "blue", "white"], "nuc-only")
both = colorer([{"aa": "1K", "nuc": "3G", "fill": "purple"}])
check_eq([fill(both, n) for n in ("V1", "V2", "V3", "V4")], ["purple", "white", "white", "white"], "aa+nuc needs both")

print("3. negated nuc")
negated = colorer([{"nuc": "3G !4T", "fill": "blue"}])
check_eq([fill(negated, n) for n in ("V1", "V5", "V2")], ["blue", "white", "white"], "3G !4T")

print("4. nuc rule, no nuc sequence")
check_eq(fill(colorer([{"aa": "1K", "nuc": "!3T", "fill": "blue"}]), "V4"), "white",
         "a negated-only nuc rule still needs a nuc sequence")

print("5. ordering, sequenced, empty rules")
ordered = colorer([{"sequenced": True, "fill": "grey"}, {"aa": "1K", "fill": "red"}, {"nuc": "3G", "fill": "blue"},
                   {"fill": "orange"}])
check_eq([fill(ordered, n) for n in ("V1", "V2", "V3", "V6")], ["blue", "red", "blue", "white"],
         "later match wins; rule with neither aa nor nuc ignored; no aa -> default")
outline = colorer([{"nuc": "3G", "fill": "blue", "outline": "black", "outline_width": 2}]).color(FakeAntigen("V1"))
check_eq((outline["outline"], outline["outline_width"]), ("black", 2.0), "nuc match sets outline")

print("6. memoisation")
memo = colorer([{"nuc": "3G", "fill": "blue"}])
before = seqdb.lookups
check_eq([fill(memo, "V2"), fill(memo, "V2"), fill(memo, "V1")], ["white", "white", "blue"], "cached result per antigen")
check_eq(seqdb.lookups - before, 2, "one seqdb lookup per antigen")

# ======================================================================

if FAILURES:
    print(f"\n{len(FAILURES)} FAILED")
    sys.exit(1)
print("\nall ok")
