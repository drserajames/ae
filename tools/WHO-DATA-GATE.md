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
| **Private strain list** | exact names from an **external** file | (see below) |

Hex colour codes (`#rrggbb`) and `0x..` literals are masked before the rules run, so they
never trip the gate.

## The private strain list (the high-signal check)

The authoritative, current-season sensitive strain names are **never stored in this repo**
(that would itself be the leak). They are sourced at runtime from, in order:

1. `$WHO_STRAIN_LIST` — path to a newline-delimited file of strain names, or
2. a gitignored local file at repo root: `.who-strain-list` (or `.who-strain-list.txt`).

Matches against this list are **case-insensitive substring** and **unconditional** — they
fail the gate even if they would otherwise be allowlisted or baselined. If no list is found
the scanner prints a warning and falls back to the regex rules only.

## Allowlist mechanism

Two files, both **WHO-data-clean** (no strain/AA/clade plaintext):

- **`tools/who-data-gate-allowlist.txt`** — hand-edited. Sections:
  - `[allow-literal]` — exact non-WHO false-positive tokens (e.g. a code identifier that
    trips the AA rule), passed now and in future, anywhere.
  - `[allow-regex]` — categorical false-positive patterns (`fullmatch`).
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
