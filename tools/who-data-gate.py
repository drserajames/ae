#!/usr/bin/env python3
"""WHO-data gate — mechanical scanner blocking pre-publication WHO CC influenza
data from entering the public `ae` repository (files, staged blobs, commit messages).

Stdlib-only. See tools/WHO-DATA-GATE.md for the full policy and rationale.

WHAT IT CATCHES (conservative — false positives acceptable, false negatives are not):
  * Virus strain names           A/Somewhere/123/2021, B/Place Name/7/17
  * Bare strain names (no A/B)    SOMEWHERE/123/2021 (Capitalised location/number/year)
  * Amino-acid substitutions     K160T, N145S
  * Clade tokens                 3C.2a1b.2a.2, 5a.1
  * Any entry of an external, PRIVATE current-season strain list (never stored
    in this repo; sourced at runtime from $WHO_STRAIN_LIST or a gitignored file).

HOW MATCHES ARE SUPPRESSED (so the existing, already-public tree passes):
  * subprojects/** (vendored third-party) and binary/data files are not scanned.
  * Hex colour codes (#rrggbb) and 0x.. literals are masked before matching.
  * An allowlist file (plaintext) lists genuine, non-WHO false-positive tokens,
    ignore regexes, and extra skip-path globs.
  * A baseline file grandfathers tokens ALREADY public in the tree, stored as
    sha256 hashes (so no strain/AA/clade plaintext is ever committed here).
    Any NEW token, absent from the baseline, fails the gate.

The private strain list ALWAYS fails, unconditionally — it is never grandfathered.

Exit codes: 0 = clean, 1 = potential WHO data found, 2 = usage/environment error.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from fnmatch import fnmatch

# --------------------------------------------------------------------------- #
# Detection rules
# --------------------------------------------------------------------------- #
# Strain names: A/Location/123/2021, B/Some Place/7/17  (2- or 4-digit year)
RE_STRAIN = re.compile(r"\b[AB]/[A-Za-z][A-Za-z .'_-]*/[0-9]+/(?:19|20)?[0-9]{2}\b")
# Bare strain names WITHOUT an A/B prefix: Location/number/year, e.g. VICTORIA/2570/2019.
# Requires a Capitalised location word (>=3 alpha) so lowercase paths ("results/2/2024") don't match.
RE_STRAIN_BARE = re.compile(r"\b[A-Z][A-Za-z]{2,}/[0-9]+/(?:19|20)?[0-9]{2}\b")
# Amino-acid substitutions: <AA><pos 2-3 digits><AA>, e.g. K160T
RE_AASUB = re.compile(r"\b[A-Z][0-9]{2,3}[A-Z]\b")
# Clade tokens
RE_CLADE_3C = re.compile(r"\b3C\.[0-9A-Za-z.]+\b")
RE_CLADE_GEN = re.compile(r"\b[0-9][a-z]\.[0-9][0-9A-Za-z.]*\b")

RULES = [
    ("strain", RE_STRAIN),
    ("strain", RE_STRAIN_BARE),
    ("aa-sub", RE_AASUB),
    ("clade", RE_CLADE_3C),
    ("clade", RE_CLADE_GEN),
]

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


def token_hash(tok: str) -> str:
    norm = tok.strip().upper()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:HASH_LEN]


# --------------------------------------------------------------------------- #
# Allowlist + baseline loading
# --------------------------------------------------------------------------- #
class Config:
    def __init__(self):
        self.allow_literal: set[str] = set()   # uppercased exact tokens
        self.allow_regex: list[re.Pattern] = []
        self.skip_paths: list[str] = list(DEFAULT_SKIP_PATHS)
        self.baseline: set[str] = set()        # token hashes
        self.private_list: list[str] = []      # lowercased private strain names

    def allowed(self, tok: str) -> bool:
        up = tok.strip().upper()
        if up in self.allow_literal:
            return True
        if token_hash(tok) in self.baseline:
            return True
        for rx in self.allow_regex:
            if rx.fullmatch(tok):
                return True
        return False

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
        for raw in fh:
            line = raw.split("#", 1)[0].strip()
            if line:
                cfg.baseline.add(line.lower())


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
class Finding:
    def __init__(self, source, lineno, rule, token, snippet):
        self.source = source
        self.lineno = lineno
        self.rule = rule
        self.token = token
        self.snippet = snippet

    def __str__(self):
        loc = f"{self.source}:{self.lineno}" if self.lineno else self.source
        return f"  {loc}: [{self.rule}] {self.token!r}  in: {self.snippet.strip()[:120]}"


def scan_text(text: str, source: str, cfg: Config, collect_tokens=None) -> list[Finding]:
    """Scan text. If collect_tokens is a set, add every matched token to it
    (baseline-generation mode) and do NOT apply allowlist/baseline suppression."""
    findings: list[Finding] = []
    lines = text.splitlines()
    for i, line in enumerate(lines, 1):
        masked = RE_HEX_LITERAL.sub(" ", RE_HEX_COLOUR.sub(" ", line))
        for rule, rx in RULES:
            for m in rx.finditer(masked):
                tok = m.group(0)
                if collect_tokens is not None:
                    collect_tokens.add(tok)
                    continue
                if cfg.allowed(tok):
                    continue
                findings.append(Finding(source, i, rule, tok, line))
    # Private strain list — unconditional, case-insensitive substring, not maskable.
    if collect_tokens is None and cfg.private_list:
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
def update_baseline(root: str, baseline_path: str, cfg: Config) -> None:
    tokens: set[str] = set()
    for rel in tracked_files(root):
        if os.path.splitext(rel)[1] in SKIP_EXT or cfg.path_skipped(rel):
            continue
        text = read_text(os.path.join(root, rel))
        if text is None:
            continue
        scan_text(text, rel, cfg, collect_tokens=tokens)
    hashes = sorted(token_hash(t) for t in tokens)
    with open(baseline_path, "w", encoding="utf-8") as fh:
        fh.write("# who-data-gate baseline — AUTO-GENERATED, do not hand-edit.\n")
        fh.write("# sha256(uppercased-token)[:16] of tokens ALREADY public in the\n")
        fh.write("# tree at generation time. No strain/AA/clade plaintext is stored.\n")
        fh.write("# Regenerate: tools/who-data-gate.py --update-baseline\n")
        fh.write(f"# {len(hashes)} grandfathered token(s).\n")
        for h in hashes:
            fh.write(h + "\n")
    print(f"who-data-gate: wrote {len(hashes)} baseline hashes to {baseline_path}")


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
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    root = git_root(args.root or ".")
    tools_dir = os.path.join(root, "tools")
    allowlist_path = args.allowlist or os.path.join(tools_dir, "who-data-gate-allowlist.txt")
    baseline_path = args.baseline or os.path.join(tools_dir, "who-data-gate-baseline.txt")

    cfg = Config()
    load_allowlist(allowlist_path, cfg)
    load_baseline(baseline_path, cfg)

    if args.update_baseline:
        update_baseline(root, baseline_path, cfg)
        return 0

    priv_src = load_private_list(cfg, root)
    if not args.quiet:
        if priv_src:
            print(f"who-data-gate: private strain list loaded ({len(cfg.private_list)} names) "
                  f"from {priv_src}", file=sys.stderr)
        else:
            print("who-data-gate: WARNING — no private strain list found "
                  "($WHO_STRAIN_LIST or .who-strain-list); relying on regex rules only.",
                  file=sys.stderr)

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

    if findings:
        print("\nWHO-DATA GATE: potential WHO influenza data detected "
              f"({len(findings)} hit(s)) — commit/push BLOCKED:\n", file=sys.stderr)
        for f in findings:
            print(str(f), file=sys.stderr)
        print("\nIf this is a genuine false positive, extend the allowlist "
              "(tools/who-data-gate-allowlist.txt) — see tools/WHO-DATA-GATE.md.\n"
              "Do NOT bypass the gate to commit real WHO data.", file=sys.stderr)
        return 1

    if not args.quiet:
        print("who-data-gate: clean.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
