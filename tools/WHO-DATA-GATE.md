# WHO-data gate

A mechanical safeguard that blocks **pre-publication WHO Collaborating Centre (WHO CC)
influenza data** from ever being committed or pushed to the **public** `ae` repository.
A leak to a public repo is permanent, so the gate is deliberately conservative:
**false positives are acceptable; false negatives are not.**

It is the safety precondition for migrating report-engine code into public `ae`.

## What it catches

Scanning file contents **and** commit messages, it flags:

| Rule | Pattern | Example (invented) |
|------|---------|--------------------|
| Strain name | `[AB]/Location/number/year` | `A/Somewhere/123/2021` |
| AA substitution | `<AA><2–3 digits><AA>` | `K160T` |
| Clade (3C) | `3C.<...>` | `3C.2a1b.2a.2` |
| Clade (generic) | `<digit><letter>.<digit>...` | `5a.1` |
| **Private strain list** | normalised substring match against an **external** file | (see below) |

Hex colour codes (`#rrggbb`) and `0x..` literals are masked before the rules run, so they
never trip the gate.

## The private strain list (the high-signal check)

The regex rules above match anything *shaped* like `LOCATION/isolate/year`. The private
list exists for the names they **structurally cannot** match — and for nothing else.

**It is the complement of the rules, not a name dump.** A name already caught by a regex
rule must **not** be added: it buys no coverage, and every entry costs time on every
commit. Enforced by construction — the generator drops any candidate the rules already
match. (Measured 2026-09-13: a 6,486-name dump was 89.8% redundant and reduced to 54
genuine residuals, cutting a full-tree scan from ~37 s to ~1.5 s.)

### Where it lives

The names themselves are **never stored in this repo** — that would itself be the leak.
They live in the **private** `acmacs-data` repo, gitignored even there, and are found at
runtime via:

1. **`$WHO_STRAIN_LIST`** — an explicit override. `ae-env.sh` exports it as
   `$ACMACS_DATA/.who-strain-list` when that file exists.
2. **`$ACMACS_DATA/.who-strain-list`, else `../acmacs-data/.who-strain-list`** beside this
   checkout — found automatically, with no environment set up at all. This matters: **git
   hooks do not inherit a shell that sourced `ae-env.sh`**, so without this the pre-commit
   hook would quietly fall back to regex-only at the exact moment the check matters most.
   A silently degraded gate is the failure mode this tool exists to prevent.
3. A gitignored `.who-strain-list` / `.who-strain-list.txt` at **this repo's root** — a
   legacy fallback that still works but **must not be used**. A file of pre-publication
   names sitting in a public checkout is one `git add -f` away from a permanent leak.
   Keep the list in `acmacs-data`.

Note that `--all` scans **git-tracked** files, so a gitignored list sitting in this repo's
root is not scanned even though it is there. A clean `--all` is **not** evidence that no
strain data is present in the checkout — check that with `ls`, not with the gate.

If no list is found the scanner warns and falls back to the regex rules only; `--strict`
turns that warning into a failure (use it in CI and hooks).

### How matching works

- **Case-insensitive substring**, and **unconditional** — a private-list hit fails the gate
  even if the token would otherwise be allowlisted or baselined. It is never grandfathered.
- **Whitespace and underscores are normalised** to single spaces on both sides (list entry
  and scanned text) before comparing. This is not cosmetic: seq_ids write spaces as
  underscores, so a multi-word location stored as `EXAMPLE TOWN/…` would otherwise
  **silently miss** the `EXAMPLE_TOWN/…` form that actually appears in the data — a false
  negative, the one failure class this gate exists to prevent.
- Entries shorter than `PRIVATE_MIN_LEN` (8 characters) are **rejected with a warning**, not
  matched. A short entry substring-matches ordinary English words and would fail the gate
  everywhere.

### Regenerating it

In `acmacs-data`, from a per-round candidate dump:

```sh
# 1. dump every candidate name from the round's charts (+ current vaccine strains)
./who-strain-candidates-make.py <path-to-round> -o .who-strain-candidates
# 2. keep only the names the gate's regex rules do NOT already match
./who-strain-list-make.py .who-strain-candidates -o .who-strain-list
```

Step 1 derives its season cutoff from the round label (`2026-0921-ssm` → strains collected
on/after 2025-09-01, vaccines recommended on/after 202509); `--since` / `--vaccines-since`
override it, and `--all-dates` takes every name in the round's charts as a superset.
`ae/ae-env.sh` must be sourced first, for `ae_backend`.

Both files are gitignored in `acmacs-data`; the two generator scripts are clean and are
tracked. Re-run after each round, and whenever the regex rules change — the list shrinks on
its own as the rules improve.

## Allowlist mechanism

Two files, both **WHO-data-clean** (no strain/AA/clade plaintext):

- **`tools/who-data-gate-allowlist.txt`** — hand-edited. Sections:
  - `[allow-literal]` — exact non-WHO false-positive tokens (e.g. a code identifier that
    trips the AA rule), passed now and in future, anywhere.
  - `[allow-regex]` — categorical false-positive patterns (`fullmatch`). Also the home of
    path- and URL-shaped false positives, which look like `LOCATION/isolate/year` to the
    strain rules — build paths (`Cellar/<pkg>/<version>`) and FTP URL segments are
    allowlisted here rather than baselined, because they are categorical, not grandfathered.
  - `[skip-path]` — extra `fnmatch` globs not to scan (`subprojects/**` is skipped by default).
- **`tools/who-data-gate-baseline.txt`** — **auto-generated**. Holds `sha256(uppercased
  token)[:16]` hashes of tokens that were **already public** in the tree when the gate was
  created (published reference strains in test fixtures, clade tokens in tree-config `.tal`
  files, etc.). This lets the existing tree pass while any **new** token — absent from the
  baseline — fails. Because only hashes are stored, no strain/AA/clade plaintext is ever
  committed. Regenerate after an intentional, reviewed addition of already-public reference
  data with:

  ```sh
  tools/who-data-gate.py --update-baseline
  ```

  Prefer `[allow-literal]`/`[skip-path]` for genuine false positives; use the baseline only
  for grandfathering already-public content.

## How to run

```sh
# Whole tree (what CI runs)
tools/who-data-gate.py --all

# Staged blobs only (what the pre-commit hook runs)
tools/who-data-gate.py --staged

# A commit message
tools/who-data-gate.py --message-file .git/COMMIT_EDITMSG
tools/who-data-gate.py --message "some text"

# Explicit files/dirs
tools/who-data-gate.py path/to/file.py some/dir
```

Exit codes: `0` clean · `1` potential WHO data found (blocked) · `2` usage/environment error.

## Git hook wiring (local enforcement)

Two hooks in `.githooks/` cover both surfaces (a `pre-commit` hook cannot see the final
message, so message enforcement lives in `commit-msg`):

- `.githooks/pre-commit` → scans **staged file contents**.
- `.githooks/commit-msg` → scans the **commit message**.

Enable them once per clone (hooks are not auto-installed by git):

```sh
git config core.hooksPath .githooks
```

CI (`.github/workflows/who-data-gate.yml`) enforces the same scan on every push and PR —
file contents **and** the pushed/PR commit messages — so the gate holds even if a
contributor has not set `core.hooksPath`.

## Bypassing is forbidden

Do **not** use `git commit --no-verify`, delete baseline entries to silence a real hit, or
weaken the rules to sneak WHO data past the gate. If the gate blocks a **genuine** false
positive, extend the allowlist (and say so in review). If it blocks **real** WHO data, that
is the gate working — remove the data.
