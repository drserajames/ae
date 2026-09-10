#!/usr/bin/env python3
"""WHO-data gate — mechanical scanner blocking pre-publication WHO CC influenza
data from entering the public `ae` repository (files, staged blobs, commit messages).

Stdlib-only. See tools/WHO-DATA-GATE.md for the full policy and rationale.

WHAT IT CATCHES (conservative — false positives acceptable, false negatives are not):
  * Virus strain names           A/Somewhere/123/2021, B/Place Name/7/17
  * Bare strain names (no A/B)    SOMEWHERE/123/2021 (Capitalised location/number/year)
  * seq_id forms                 SOMEWHERE/123/2021_MDCK1_A1B2C3D4
  * Serum ids                    lab-prefixed ids, and a strain name followed by one
  * Titer table rows             an org/markdown row of >=4 titer-shaped cells
  * Long AA / nucleotide runs    pasted sequence data
  * Amino-acid substitutions     K160T, N145S
  * Clade tokens                 3C.2a1b.2a.2, 5a.1
  * Any entry of an external, PRIVATE current-season strain list (never stored
    in this repo; sourced at runtime from $WHO_STRAIN_LIST or a gitignored file).

HOW MATCHES ARE SUPPRESSED (so the existing, already-public tree passes):
  * subprojects/** (vendored third-party) and binary/data files are not scanned.
  * Hex colour codes (#rrggbb) and 0x.. literals are masked before matching.
  * An allowlist file (plaintext) lists genuine, non-WHO false-positive tokens,
    ignore regexes, and extra skip-path globs.
  * A baseline file grandfathers REVIEWED FILES. One line per file, recording a
    hash of that file's whole matched-token set (no plaintext), a written
    justification and an expiry date. Suppression is scoped to that one path, so
    a token grandfathered in file A still fails in file B; and adding *or*
    removing a token changes the set hash, which re-surfaces the whole file for
    review. Expired or unjustified entries fail under --strict.

The private strain list ALWAYS fails, unconditionally — it is never grandfathered.

Every run prints how much the baseline suppressed. Use --redact when the output
goes somewhere public (CI logs): findings are then reported by location and rule
only, never by value.

Exit codes: 0 = clean, 1 = potential WHO data found, 2 = usage/environment error.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import os
import re
import subprocess
import sys
from fnmatch import fnmatch

# --------------------------------------------------------------------------- #
# Detection rules
# --------------------------------------------------------------------------- #
# An isolate id is usually numeric but labs also use alphanumerics (R10785, 16V-9267,
# NIC-NIH-1721). The trailing (?![0-9_A-Za-z-]) — rather than \b — is what lets the year
# be followed by a seq_id passage/hash suffix (…/2021_MDCK1_A1B2C3D4) and still match:
# \b failed there because "_" is a word character, which hid every seq_id from the gate.
_ISOLATE = r"[0-9][0-9A-Za-z_-]{0,19}"
_YEAR = r"(?:19|20)?[0-9]{2}"
_END = r"(?![0-9])"
# Strain names: A/Location/123/2021, B/Some Place/7/17  (2- or 4-digit year)
RE_STRAIN = re.compile(rf"\b[AB]/[A-Za-z][A-Za-z .'_-]*/{_ISOLATE}/{_YEAR}{_END}")
# Bare strain names WITHOUT an A/B prefix: Location/number/year, e.g. VICTORIA/2570/2019.
# Requires a Capitalised location word (>=3 alpha) so lowercase paths ("results/2/2024")
# don't match; "_" and "-" are allowed because seq_ids write spaces as underscores
# (SOUTH_AFRICA/…, NIIGATA-C/…).
RE_STRAIN_BARE = re.compile(rf"\b[A-Z][A-Za-z][A-Za-z_-]+/{_ISOLATE}/{_YEAR}{_END}")
# Serum ids: WHO CC lab-prefixed forms, e.g. "CDC 2016-045", "CRICK 2019-021".
RE_SERUM_ID = re.compile(
    r"\b(?:CDC|CRICK|NIID|VIDRL|NIMR|MELB|CNIC|NIB)[ _-]?[0-9]{4}-[0-9]{2,3}\b")
# A strain name immediately followed by a short alphanumeric id — the "strain + serum id"
# shape that leaked into TODO.md. Very low false-positive rate, so worth its own rule.
RE_STRAIN_SERUM = re.compile(
    rf"\b[A-Z][A-Za-z][A-Za-z_-]+/{_ISOLATE}/{_YEAR}\s+[A-Z]{{1,3}}[0-9]{{3,6}}[A-Z]?\b")
# Long amino-acid / nucleotide runs — pasted sequence data.
RE_SEQUENCE = re.compile(r"\b(?:[ACDEFGHIKLMNPQRSTVWXY]{60,}|[ACGTNU]{60,})\b")
# Amino-acid substitutions: <AA><pos 2-3 digits><AA>, e.g. K160T
RE_AASUB = re.compile(r"\b[A-Z][0-9]{2,3}[A-Z]\b")
# Clade tokens
RE_CLADE_3C = re.compile(r"\b3C\.[0-9A-Za-z.]+\b")
RE_CLADE_GEN = re.compile(r"\b[0-9][a-z]\.[0-9][0-9A-Za-z.]*\b")

RULES = [
    ("strain", RE_STRAIN),
    ("strain", RE_STRAIN_BARE),
    ("serum-id", RE_SERUM_ID),
    ("serum-id", RE_STRAIN_SERUM),
    ("sequence", RE_SEQUENCE),
    ("aa-sub", RE_AASUB),
    ("clade", RE_CLADE_3C),
    ("clade", RE_CLADE_GEN),
]

# Titer tables are matched per line, not per token: an org/markdown row whose cells are
# mostly titer-shaped ("160", "<20", ">2560", "*"). The matched value is never reported.
RE_TITER_CELL = re.compile(r"^\s*(?:[<>]?[0-9]{1,5}|\*)\s*$")


def titer_row(line: str) -> bool:
    cells = [c for c in line.split("|")[1:-1]] if line.lstrip().startswith("|") else []
    titers = [c for c in cells if RE_TITER_CELL.match(c)]
    return len(titers) >= 4

# Masked (turned to spaces) before rules run — removes the commonest false positives.
RE_HEX_COLOUR = re.compile(r"#[0-9A-Fa-f]{3,8}\b")
RE_HEX_LITERAL = re.compile(r"0[xX][0-9A-Fa-f]+")

# Never scanned (binary / compressed / image / built artefacts) — content is opaque.
SKIP_EXT = {
    ".xz", ".gz", ".bz2", ".br", ".zip", ".ace", ".png", ".jpg", ".jpeg",
    ".gif", ".ico", ".pdf", ".so", ".o", ".a", ".dylib", ".bin", ".woff",
    ".woff2", ".ttf", ".otf", ".wraplock", ".DS_Store",
}
# Built-in path skips (vendored third-party). Extendable via the allowlist file.
DEFAULT_SKIP_PATHS = ["subprojects/**"]

HASH_LEN = 16  # truncated sha256 hex chars stored in the baseline
BASELINE_MONTHS = 12  # how long a --update-baseline entry stays valid
UNJUSTIFIED = "UNJUSTIFIED — review required"


def token_hash(tok: str) -> str:
    norm = tok.strip().upper()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:HASH_LEN]


def token_set_hash(tokens) -> str:
    """Hash of a file's WHOLE matched-token set. Adding or removing any token changes
    it, which re-surfaces the file for review. Stores no plaintext."""
    joined = "\n".join(sorted({t.strip().upper() for t in tokens}))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:HASH_LEN]


def today() -> datetime.date:
    return datetime.date.today()


def default_expiry() -> str:
    d = today()
    year, month = divmod(d.month - 1 + BASELINE_MONTHS, 12)
    return d.replace(year=d.year + year, month=month + 1, day=1).isoformat()


class BaselineEntry:
    def __init__(self, path, set_hash, count, expires, justification):
        self.path = path
        self.set_hash = set_hash
        self.count = count
        self.expires = expires
        self.justification = justification

    @property
    def expired(self) -> bool:
        try:
            return datetime.date.fromisoformat(self.expires) < today()
        except ValueError:
            return True

    @property
    def unjustified(self) -> bool:
        return not self.justification or self.justification.startswith("UNJUSTIFIED")

    def line(self) -> str:
        return (f"{self.path}\t{self.set_hash}\t{self.count}\t{self.expires}"
                f"\t# {self.justification}\n")


# --------------------------------------------------------------------------- #
# Allowlist + baseline loading
# --------------------------------------------------------------------------- #
class Config:
    def __init__(self):
        self.allow_literal: set[str] = set()   # uppercased exact tokens
        self.allow_regex: list[re.Pattern] = []
        self.skip_paths: list[str] = list(DEFAULT_SKIP_PATHS)
        self.baseline: dict[str, BaselineEntry] = {}   # relpath -> entry
        self.private_list: list[str] = []      # lowercased private strain names
        self.suppressed: dict[str, int] = {}   # relpath -> matches suppressed this run

    def allowed(self, tok: str) -> bool:
        """Allowlist only. Baseline suppression is per-file and handled in scan_text."""
        up = tok.strip().upper()
        if up in self.allow_literal:
            return True
        for rx in self.allow_regex:
            if rx.fullmatch(tok):
                return True
        return False

    def baselined(self, source: str, tokens) -> bool:
        """True if `source` is a reviewed, unexpired baseline entry whose recorded
        token set still matches exactly what was found."""
        entry = self.baseline.get(source)
        return entry is not None and entry.set_hash == token_set_hash(tokens)

    def path_skipped(self, relpath: str) -> bool:
        for pat in self.skip_paths:
            if fnmatch(relpath, pat) or fnmatch(relpath, pat.rstrip("*/") + "/*"):
                return True
        return False


def load_allowlist(path: str, cfg: Config) -> None:
    if not path or not os.path.exists(path):
        return
    section = "allow-literal"
    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip().lower()
                continue
            if section == "allow-literal":
                cfg.allow_literal.add(line.upper())
            elif section == "allow-regex":
                try:
                    cfg.allow_regex.append(re.compile(line))
                except re.error as exc:
                    print(f"who-data-gate: bad allow-regex {line!r}: {exc}", file=sys.stderr)
            elif section == "skip-path":
                cfg.skip_paths.append(line)


def load_baseline(path: str, cfg: Config) -> None:
    if not path or not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            fields, _, justification = raw.rstrip("\n").partition("#")
            parts = fields.split("\t")
            if len(parts) < 4:
                print(f"who-data-gate: {path}:{lineno}: malformed baseline entry "
                      "(expected path\\thash\\tcount\\texpiry\\t# justification)",
                      file=sys.stderr)
                continue
            rel, set_hash, count, expires = (p.strip() for p in parts[:4])
            cfg.baseline[rel] = BaselineEntry(
                rel, set_hash.lower(), count, expires, justification.strip())


def load_private_list(cfg: Config, root: str) -> str | None:
    """Return the source path used, or None if no private list was found."""
    candidates = []
    env = os.environ.get("WHO_STRAIN_LIST")
    if env:
        candidates.append(env)
    # gitignored local fallbacks (never committed)
    candidates.append(os.path.join(root, ".who-strain-list"))
    candidates.append(os.path.join(root, ".who-strain-list.txt"))
    for cand in candidates:
        if cand and os.path.exists(cand):
            with open(cand, "r", encoding="utf-8") as fh:
                for raw in fh:
                    name = raw.strip()
                    if name and not name.startswith("#"):
                        cfg.private_list.append(name.lower())
            return cand
    return None


# --------------------------------------------------------------------------- #
# Scanning
# --------------------------------------------------------------------------- #
REDACT = False  # set from --redact; when on, no matched value is ever printed


class Finding:
    def __init__(self, source, lineno, rule, token, snippet):
        self.source = source
        self.lineno = lineno
        self.rule = rule
        self.token = token
        self.snippet = snippet

    def __str__(self):
        loc = f"{self.source}:{self.lineno}" if self.lineno else self.source
        if REDACT:
            return f"  {loc}: [{self.rule}] <redacted sha:{token_hash(self.token)}>"
        return f"  {loc}: [{self.rule}] {self.token!r}  in: {self.snippet.strip()[:120]}"


def matched_tokens(text: str):
    """Yield (lineno, rule, token, line) for every rule match, before suppression."""
    for i, line in enumerate(text.splitlines(), 1):
        masked = RE_HEX_LITERAL.sub(" ", RE_HEX_COLOUR.sub(" ", line))
        for rule, rx in RULES:
            for m in rx.finditer(masked):
                yield i, rule, m.group(0), line
        if titer_row(line):
            # never surface the row itself — the location is enough to act on
            yield i, "titer-row", f"<titer-row:{token_hash(line)}>", "<redacted>"


def scan_text(text: str, source: str, cfg: Config, collect_tokens=None) -> list[Finding]:
    """Scan text. If collect_tokens is a set, add every matched token to it
    (baseline-generation mode) and do NOT apply allowlist/baseline suppression."""
    findings: list[Finding] = []
    candidates = []   # (lineno, rule, token, line) surviving the allowlist
    for i, rule, tok, line in matched_tokens(text):
        if collect_tokens is not None:
            collect_tokens.add(tok)
            continue
        if cfg.allowed(tok):
            continue
        candidates.append((i, rule, tok, line))

    if collect_tokens is None:
        if cfg.baselined(source, (t for _, _, t, _ in candidates)):
            cfg.suppressed[source] = len(candidates)
        else:
            findings += [Finding(source, i, r, t, l) for i, r, t, l in candidates]

    # Private strain list — unconditional, case-insensitive substring, not maskable,
    # and NEVER suppressed by the allowlist or the baseline.
    if collect_tokens is None and cfg.private_list:
        lines = text.splitlines()
        low = text.lower()
        for i, line in enumerate(lines, 1):
            ll = line.lower()
            for name in cfg.private_list:
                if name in ll:
                    findings.append(Finding(source, i, "private-list", name, line))
        # also catch names split across the whole blob but not a single line (rare)
        for name in cfg.private_list:
            if name in low and not any(name in l.lower() for l in lines):
                findings.append(Finding(source, 0, "private-list", name, "(multi-line)"))
    return findings


def is_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def read_text(path: str) -> str | None:
    try:
        data = open(path, "rb").read()
    except OSError:
        return None
    if is_binary(data):
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return data.decode("latin-1")
        except UnicodeDecodeError:
            return None


def scan_file(path: str, relpath: str, cfg: Config, collect_tokens=None) -> list[Finding]:
    if os.path.splitext(relpath)[1] in SKIP_EXT:
        return []
    if cfg.path_skipped(relpath):
        return []
    text = read_text(path)
    if text is None:
        return []
    return scan_text(text, relpath, cfg, collect_tokens)


# --------------------------------------------------------------------------- #
# Git helpers
# --------------------------------------------------------------------------- #
def git(root, *args) -> str:
    return subprocess.check_output(["git", "-C", root, *args], text=True)


def git_root(start: str) -> str:
    try:
        return git(start, "rev-parse", "--show-toplevel").strip()
    except subprocess.CalledProcessError:
        return os.path.abspath(start)


def tracked_files(root: str) -> list[str]:
    return [f for f in git(root, "ls-files").splitlines() if f]


def staged_files(root: str) -> list[str]:
    out = git(root, "diff", "--cached", "--name-only", "--diff-filter=ACM")
    return [f for f in out.splitlines() if f]


def staged_blob(root: str, relpath: str) -> str | None:
    try:
        data = subprocess.check_output(["git", "-C", root, "show", f":{relpath}"])
    except subprocess.CalledProcessError:
        return None
    if is_binary(data):
        return None
    for enc in ("utf-8", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return None


# --------------------------------------------------------------------------- #
# Baseline generation
# --------------------------------------------------------------------------- #
BASELINE_HEADER = """\
# who-data-gate baseline — REVIEWED grandfathered files.
#
# One line per file:   <path>\\t<token-set-hash>\\t<n>\\t<expires>\\t# <justification>
#
# The hash covers that file's WHOLE set of matched tokens (sha256 of the sorted,
# uppercased set, truncated) — no strain/serum/clade plaintext is ever stored here.
# Suppression is scoped to the one path, so a token grandfathered here still fails
# anywhere else; and adding OR removing a token changes the hash, which re-surfaces
# the whole file for review. Entries expire, and --strict fails on expired or
# unjustified ones, so nothing stays grandfathered by inertia.
#
# THE BASELINE IS THE DANGEROUS PART OF THIS TOOL. Every line is a standing decision
# that some real-looking data may live in the repo. Justify each one in words, and
# prefer fixing the data or using [allow-literal]/[allow-regex] for true false
# positives. Never add an entry to silence a hit you have not read.
#
# Regenerate: tools/who-data-gate.py --update-baseline --justification "..."
#   (existing justifications and expiry dates are carried over per path)
"""


def update_baseline(root: str, baseline_path: str, cfg: Config, justification: str) -> None:
    previous = dict(cfg.baseline)
    entries: list[BaselineEntry] = []
    for rel in tracked_files(root):
        if os.path.splitext(rel)[1] in SKIP_EXT or cfg.path_skipped(rel):
            continue
        text = read_text(os.path.join(root, rel))
        if text is None:
            continue
        tokens = [t for _, _, t, _ in matched_tokens(text) if not cfg.allowed(t)]
        if not tokens:
            continue
        old = previous.get(rel)
        entries.append(BaselineEntry(
            path=rel,
            set_hash=token_set_hash(tokens),
            count=str(len(tokens)),
            expires=(old.expires if old and not old.expired else default_expiry()),
            justification=(justification or (old.justification if old else "") or UNJUSTIFIED),
        ))
    entries.sort(key=lambda e: e.path)
    with open(baseline_path, "w", encoding="utf-8") as fh:
        fh.write(BASELINE_HEADER)
        fh.write(f"# {len(entries)} grandfathered file(s), "
                 f"{sum(int(e.count) for e in entries)} suppressed match(es).\n")
        for e in entries:
            fh.write(e.line())
    unjustified = sum(1 for e in entries if e.unjustified)
    print(f"who-data-gate: wrote {len(entries)} baseline entries to {baseline_path}"
          + (f" — {unjustified} still UNJUSTIFIED" if unjustified else ""))


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="WHO-data gate scanner")
    ap.add_argument("paths", nargs="*", help="explicit files/dirs to scan")
    ap.add_argument("--all", action="store_true", help="scan all git-tracked files (CI)")
    ap.add_argument("--staged", action="store_true", help="scan git staged blobs (pre-commit)")
    ap.add_argument("--message-file", help="also scan the commit message in this file")
    ap.add_argument("--message", help="also scan this literal message text")
    ap.add_argument("--root", help="repo root (default: git toplevel of cwd)")
    ap.add_argument("--allowlist", help="allowlist file")
    ap.add_argument("--baseline", help="baseline file")
    ap.add_argument("--update-baseline", action="store_true",
                    help="regenerate the baseline from the current tree and exit")
    ap.add_argument("--justification",
                    help="with --update-baseline: written reason for grandfathering")
    ap.add_argument("--strict", action="store_true",
                    help="fail if no private strain list is configured, or if any "
                         "baseline entry is expired or unjustified (use in CI/hooks)")
    ap.add_argument("--redact", action="store_true",
                    help="report findings by location only — never print a matched "
                         "value (use whenever output goes somewhere public, e.g. CI logs)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    global REDACT
    REDACT = args.redact

    root = git_root(args.root or ".")
    tools_dir = os.path.join(root, "tools")
    allowlist_path = args.allowlist or os.path.join(tools_dir, "who-data-gate-allowlist.txt")
    baseline_path = args.baseline or os.path.join(tools_dir, "who-data-gate-baseline.txt")

    cfg = Config()
    load_allowlist(allowlist_path, cfg)
    load_baseline(baseline_path, cfg)

    if args.update_baseline:
        update_baseline(root, baseline_path, cfg, args.justification)
        return 0

    hard_errors: list[str] = []

    priv_src = load_private_list(cfg, root)
    if priv_src:
        if not args.quiet:
            print(f"who-data-gate: private strain list loaded ({len(cfg.private_list)} names) "
                  f"from {priv_src}", file=sys.stderr)
    else:
        msg = ("no private strain list found ($WHO_STRAIN_LIST or .who-strain-list) — "
               "the high-signal check is OFF and only the regex rules are running")
        if args.strict:
            hard_errors.append(msg)
        else:
            print(f"who-data-gate: WARNING — {msg}.\n"
                  "  Point $WHO_STRAIN_LIST at the current-season name list "
                  "(see tools/WHO-DATA-GATE.md).", file=sys.stderr)

    expired = sorted(e.path for e in cfg.baseline.values() if e.expired)
    unjustified = sorted(e.path for e in cfg.baseline.values() if e.unjustified)
    for label, paths in (("expired", expired), ("unjustified", unjustified)):
        if not paths:
            continue
        msg = (f"{len(paths)} baseline entr{'y' if len(paths) == 1 else 'ies'} "
               f"{label}: {', '.join(paths[:5])}"
               + (" …" if len(paths) > 5 else ""))
        if args.strict:
            hard_errors.append(msg)
        elif not args.quiet:
            print(f"who-data-gate: WARNING — {msg}", file=sys.stderr)

    findings: list[Finding] = []

    if args.all:
        for rel in tracked_files(root):
            findings += scan_file(os.path.join(root, rel), rel, cfg)
    if args.staged:
        for rel in staged_files(root):
            if os.path.splitext(rel)[1] in SKIP_EXT or cfg.path_skipped(rel):
                continue
            text = staged_blob(root, rel)
            if text is not None:
                findings += scan_text(text, rel, cfg)
    for p in args.paths:
        if os.path.isdir(p):
            for dirpath, _dirs, names in os.walk(p):
                for n in names:
                    fp = os.path.join(dirpath, n)
                    rel = os.path.relpath(fp, root)
                    findings += scan_file(fp, rel, cfg)
        elif os.path.isfile(p):
            rel = os.path.relpath(p, root)
            findings += scan_file(p, rel, cfg)
        else:
            print(f"who-data-gate: no such path: {p}", file=sys.stderr)

    if args.message_file:
        try:
            msg = open(args.message_file, "r", encoding="utf-8", errors="replace").read()
            # git commit-msg passes the whole file incl. comment lines starting with '#';
            # strip them so scissored/commented text isn't scanned.
            msg = "\n".join(l for l in msg.splitlines() if not l.lstrip().startswith("#"))
            findings += scan_text(msg, "<commit-message>", cfg)
        except OSError as exc:
            print(f"who-data-gate: cannot read message file: {exc}", file=sys.stderr)
            return 2
    if args.message:
        findings += scan_text(args.message, "<commit-message>", cfg)

    # Always report what the baseline hid — a silent suppression is how real data
    # sat in TODO.md unnoticed. Counts only; never the values.
    if cfg.suppressed and not args.quiet:
        total = sum(cfg.suppressed.values())
        print(f"who-data-gate: baseline SUPPRESSED {total} match(es) in "
              f"{len(cfg.suppressed)} reviewed file(s):", file=sys.stderr)
        for rel in sorted(cfg.suppressed, key=lambda r: -cfg.suppressed[r]):
            entry = cfg.baseline[rel]
            print(f"    {cfg.suppressed[rel]:5d}  {rel}  (expires {entry.expires}) "
                  f"— {entry.justification}", file=sys.stderr)

    if findings:
        print("\nWHO-DATA GATE: potential WHO influenza data detected "
              f"({len(findings)} hit(s)) — commit/push BLOCKED:\n", file=sys.stderr)
        for f in findings:
            print(str(f), file=sys.stderr)
        print("\nIf this is a genuine false positive, extend the allowlist "
              "(tools/who-data-gate-allowlist.txt) — see tools/WHO-DATA-GATE.md.\n"
              "Do NOT bypass the gate to commit real WHO data.", file=sys.stderr)
        return 1

    if hard_errors:
        print("\nWHO-DATA GATE: --strict preconditions not met — BLOCKED:\n",
              file=sys.stderr)
        for msg in hard_errors:
            print(f"  {msg}", file=sys.stderr)
        print("\nSee tools/WHO-DATA-GATE.md.", file=sys.stderr)
        return 1

    if not args.quiet:
        print("who-data-gate: clean.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
