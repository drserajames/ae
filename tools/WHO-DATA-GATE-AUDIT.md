# WHO-data gate — baseline audit

**Audited 13th September 2026.** Scope: every entry in `tools/who-data-gate-baseline.txt`
and the plaintext contents of `tools/who-data-gate-allowlist.txt`.

This file records **counts, paths and decisions only**. No strain name, serum id, AA
substitution, clade token or titer appears here, by design — this is a public repo.

## Why the audit happened

`TODO.md` open-defect row 1 flagged the baseline as "weaker than it looks". Two specific
worries, both borne out:

1. The baseline **grandfathers** matches past the scanner, and at the time of the audit all
   **34** entries carried the **same single boilerplate justification** — "Reference test
   data and strain/clade nomenclature already public in the tree since initial commit or
   prior to gate implementation". `--strict` was satisfied because the field was merely
   non-empty. Nothing had been reviewed file by file; one sentence covered everything.
2. `tools/who-data-gate-allowlist.txt` declared itself "WHO-data-clean by construction: no
   strain/AA/clade specifics" while containing a **real, long-published influenza vaccine
   strain name in plaintext**, plus three real clade designations mislabelled as
   "placeholder examples". The file broke its own stated rule.

## Result

| | before | after |
|---|---:|---:|
| baseline entries | 34 | **24** |
| suppressed tokens | 2362 | **2275** |
| distinct justifications | 1 | **23** |
| distinct expiry dates | 1 | **3** |
| unjustified entries | 0 | 0 |
| real strain names in the allowlist | 1 | **0** |

Whole-tree scan: `--all --strict` exit 0, ~1.4 s, private strain list loaded (54 names).

### What moved out of the baseline (10 entries, 87 tokens)

Nine files were grandfathered when they should have been allowlisted, and one was fixed
outright. The baseline is for **grandfathering**; the allowlist is for **false positives and
permanently-public nomenclature**. These were the latter filed as the former.

- **Eight files whose only matched tokens were published clade designations** —
  `TODO.md`, `cc/chart/v3/chart-import.cc`, `cc/geo/geo-draw-main.cc`,
  `cc/geo/test/pie-records.json`, `cc/geo/test/test-geo-pie.sh`, `cc/tal/draw-tree.cc`,
  `cc/tal/settings.hh`, `interactive/CONTRACT.md`.
  Clade designations are public nomenclature by definition (WHO, nextclade,
  `influenza-clade-nomenclature`) and can never become pre-publication. The **32** distinct
  clade tokens present anywhere in the tree are now `[allow-literal]` entries.
  **Listed individually on purpose**: a categorical clade regex in the allowlist would
  disable the clade rule outright, whereas an unlisted — i.e. newly designated — clade token
  still fails the gate.
- **`cc/tal/test/test-section-maps.py`** — its single token was an invented placeholder
  location in a fixture explicitly commented "no match". The reserved synthetic-location
  namespace in `[allow-regex]` was extended to cover it, alongside the existing one.
- **`py/ae/semantic/vaccine.py`** — its two tokens were real published vaccine strain names
  used as **docstring examples**. Replaced with reserved `EXAMPLE…` placeholders, per the
  repo's own convention and the precedent of `e176bfe`. The entry is gone, not suppressed.

### What stayed baselined (24 entries, 2275 tokens)

Each now carries a **specific** justification naming what the tokens are, and an expiry
chosen from the risk it actually carries:

| expiry | entries | class |
|---|---:|---|
| **2027-03-01** | 4 | `proj/weekly-tree/*.tal` — live pipeline config (see below) |
| **2028-09-01** | 18 | real published names in parser fixtures, comments and docstrings; illustrative AA substitutions |
| **2029-09-01** | 2 | static or wholly synthetic: alignment master sequences (1918–2009, GenBank); a format spec whose table is already `EXAMPLE…`/`LAB 0000-000` placeholders |

## The weekly-tree `.tal` files — the decision that was holding up 87.6% of the suppression

`archive/AE-PORT-PROGRESS.md:60` recorded that `proj/weekly-tree/*.tal` was looked at on
2026-07-03 and judged benign: "Eu's weekly-tree pipeline, in-repo since Jan 2022, tokens are
published clade/AA nomenclature". Four files carry **2008 of the 2275** remaining suppressed
tokens (88.3%; 2070 of 2362, or 87.6%, before the audit).

**Confirmed as acceptable — but the stated reason was wrong, and the correction matters.**

What is right: the AA substitutions (1272 of h3.tal's 1352 tokens alone) are clade-defining
transitions, and the clade tokens are published designations. Those *are* nomenclature.

What is wrong: a large share of the tokens are **not nomenclature at all**. They are
per-node **seq_ids** — strain name plus passage history plus sequence hash — used to anchor
tree sections, together with bare strain names. Unique strain-shaped tokens per file: 159,
131, 48 and 26. One block is an explicit exclusion list of 70 isolates from a single
submitting institution. These are individual surveillance identifiers, which is precisely
the shape the gate exists to catch.

The defensible basis for keeping them is therefore **not** "it's nomenclature" but:

- **Latest collection year is 2021** (measured per file: h3 2021, h1 2021, bvic 2021, byam
  2020; earliest 2013). That is four seasons before the current round's cutoff.
- **Public on GitHub since 2022-01-08**, unchanged in substance since 2026-05-13. Removing
  them now would not unpublish them — they are in the history.
- **B/Yamagata has not circulated since 2020**, so `byam.tal` is wholly historical.

**Forward-looking risk, and what was done about it.** These files are live pipeline config,
not frozen fixtures. If one is regenerated against a current tree it will acquire
current-season seq_ids. The token-set hash re-surfaces the whole file for review when that
happens — but a blind `--update-baseline` would silently re-grandfather the new tokens under
the existing justification, which is exactly how the single-boilerplate state arose in the
first place. Mitigations: a **short expiry (2027-03-01)** forcing a re-look before the next
round's tree work, and a justification that says so in words.

## Allowlist contradiction — resolved

The allowlist held one real, long-published influenza vaccine strain name in plaintext. It
is published nomenclature, so it was never a leak — but it broke the file's own stated rule,
and an allowlist entry is **unscoped and permanent**: one line passes that name in every
file, forever. That is the same class of problem row 1 was written about.

Resolved by **removing it** rather than by weakening the rule. It was load-bearing in two
places, both **documentation text**, and both were sanitised to reserved `EXAMPLE…`
placeholders instead:

- `tools/who-data-gate.py` — a comment illustrating one of the gate's own rules. The gate
  must obey its own placeholder convention.
- `py/ae/semantic/vaccine.py` — a docstring showing the settings format.

Its third occurrence, in `proj/weekly-tree/h1.tal`, is now covered by that file's baseline
entry: stored as a hash, scoped to the one file, instead of as plaintext passing everywhere.

Two further fixes in the same file:

- Three **real clade designations** were listed under a comment calling them "placeholder
  examples". They are not placeholders. They are folded into the new, honestly-labelled
  published-clade block.
- The header's claim ("WHO-data-clean by construction: no strain/AA/clade specifics") was
  **false as written** and is replaced by the rule the file actually follows: invented
  placeholders and published clade designations belong here; **a real strain name never
  does, however long it has been published**, because entries here are unscoped and
  permanent. Real names that are genuinely already public go in the baseline, where they are
  hashed and scoped to one path.

## Findings left open

1. **Doc-comment examples use real published strain names.** Seven baselined files
   (`bin/chart-semantic-populate`, `doc/ace-format.js`, `py/ae/semantic/name_passage.py`,
   `py/ae/semantic/serology.py`, `py/ae/virus/name_format.py`,
   `cc/whocc/xlsx/sheet-extractor.cc`, `py/ae/tal/signature_page.py`) use a real name where
   an `EXAMPLE…` placeholder would do. None is a leak — all are long-published reference or
   vaccine strains — and each is individually justified. Four are marked in their
   justification as "sanitise next time this file is touched"; the other three would lose
   the point of the example (a real abbreviation mapping, a two-word location, a documented
   deletion position) and are deliberately kept. Not swept now: each is a judgement about
   whether the comment still says anything once the name is gone.
2. **Executable fixtures are not sanitisable for free.** `cc/chart/v2/name-format.cc` passes
   real names into `antigen.name()` / `serum.name()` in a unit test; changing the input would
   mean changing the expected output. Left baselined.
3. **Lab codenames and serum ids — asked, and closed.** The private list covers strain names
   only, and the long-standing open action (`archive/AE-PORT-PROGRESS.md:60`) was to extend it
   to lab-internal identifiers that the regex rules structurally cannot match. Such identifiers
   are not derivable from `hidb5` or `seqdb`, so the user was asked directly on 13th September
   2026 and **knows of none** in this workflow. The item is closed, not deferred.

   Reopen it only if one actually turns up. If it does: entries go in
   `acmacs-data/.who-strain-list` under the same normalisation, and note the `PRIVATE_MIN_LEN`
   constraint — an entry shorter than the minimum (8 characters) is **rejected with a warning,
   not matched**, so check the warning count after regenerating. A shorter identifier needs a
   rule change, which is the user's decision, not a quiet edit to the constant.

## How to re-verify this audit

```sh
cd ~/AC/eu/ae
tools/who-data-gate.py --all --strict        # exit 0, no expired or unjustified entries
awk -F'\t' '!/^#/ && NF>=4 {n+=$3; c++} END {print c" entries, "n" suppressed tokens"}' \
    tools/who-data-gate-baseline.txt          # 24 entries, 2275 suppressed tokens
awk -F'#' '!/^#/ {print $2}' tools/who-data-gate-baseline.txt | sort -u | wc -l   # 23
```

To re-derive what a given entry actually suppresses **without putting tokens anywhere**, scan
the one file with `--redact`: findings are reported by location and rule only.

**Do not run `--update-baseline` to make a hit go away.** It carries existing justifications
over **per path**, so a blind regenerate re-grandfathers new tokens under words written about
different ones. Read the file first, every time.
