#!/usr/bin/env python3
# Tests for tools/who-data-gate.py — the `--range` mode and the "examined nothing" guard.
#
# Why this exists: the gate reported "clean" twice in one week while examining something
# other than what was shipping.
#   1. `--staged` reads the INDEX. On a tree with nothing staged it printed "clean" and exited
#      0 having examined zero files.
#   2. A tip-only scan (`--all`, `--staged`, paths) cannot see history: a name added in one
#      commit and removed in a later one still ships in the pushed history. `--range` scans
#      every commit's touched blobs and message, never the range's net diff, which would
#      net such a name out to nothing.
#
# Everything runs in throwaway git repos under a temp dir, with the gate pointed at an empty
# allowlist and baseline and at an invented private list. The strain-shaped name is invented
# and assembled at run time, so this file itself carries nothing the gate matches.
#
# Run (from the ae worktree root; stdlib only, no build needed):
#   python3 test/test-who-data-gate.py

import os
import subprocess
import sys
import tempfile
from pathlib import Path

GATE = Path(__file__).resolve().parent.parent / "tools" / "who-data-gate.py"

# Invented: matches RE_STRAIN, is not a real place, and a 2099 isolate cannot exist.
FAKE_STRAIN = "/".join(["A", "Nowhere", "999", "2099"])
# Invented private-list entry, deliberately NOT regex-shaped, so only the list catches it.
FAKE_PRIVATE = "zzqx " + "imaginary isolate"

failures = 0


def check(name, cond, detail=""):
    global failures
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}")
    if not cond:
        failures += 1
        if detail:
            print("        " + detail.replace("\n", "\n        "))


class Repo:
    def __init__(self, base: Path, name: str):
        self.dir = base / name
        self.dir.mkdir()
        self.aux = base / (name + "-aux")
        self.aux.mkdir()
        (self.aux / "allowlist.txt").write_text("")
        (self.aux / "baseline.txt").write_text("")
        (self.aux / "private.txt").write_text(FAKE_PRIVATE + "\n")
        self.git("init", "-q")
        self.git("symbolic-ref", "HEAD", "refs/heads/main")   # `init -b` needs git >= 2.28

    def git(self, *args) -> str:
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid",
                   GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")
        return subprocess.run(["git", "-C", str(self.dir), "-c", "core.hooksPath=/dev/null", *args],
                              check=True, capture_output=True, text=True, env=env).stdout.strip()

    def write(self, rel, text):
        p = self.dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def commit(self, message, *paths) -> str:
        self.git("add", "-A", *paths)
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")

    def gate(self, *args):
        env = dict(os.environ, WHO_STRAIN_LIST=str(self.aux / "private.txt"))
        env.pop("ACMACS_DATA", None)
        r = subprocess.run(
            [sys.executable, str(GATE), "--root", str(self.dir),
             "--allowlist", str(self.aux / "allowlist.txt"),
             "--baseline", str(self.aux / "baseline.txt"), *args],
            cwd=self.dir, capture_output=True, text=True, env=env)
        return r.returncode, r.stdout + r.stderr


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="who-gate-test-") as tmp:
        base = Path(tmp)

        print("added-then-removed name: --range fails, a tip-only scan passes")
        r = Repo(base, "added-removed")
        r.write("README", "nothing here\n")
        root = r.commit("initial")
        r.write("notes.txt", f"see {FAKE_STRAIN} for details\n")
        leak = r.commit("add notes")
        r.write("notes.txt", "see the reference virus for details\n")
        r.commit("reword notes")
        code, out = r.gate("--all")
        check("--all at tip exits 0", code == 0, out)
        code, out = r.gate("--range", f"{root}..HEAD")
        check("--range exits 1", code == 1, out)
        check("--range names the leaking commit and file", f"{leak[:12]}:notes.txt" in out, out)
        check("--range labels that commit as history, not tip",
              f"{leak[:12]} [history]" in out and "[tip]" not in out, out)
        check("--range reports how much it examined",
              "2 file(s)" in out and "2 commit message(s)" in out and "2 commit(s)" in out, out)
        code, out = r.gate("--range", f"{root}..HEAD", "--redact")
        check("--redact never echoes the name", code == 1 and FAKE_STRAIN not in out, out)

        print("private-list name in history")
        r.write("notes.txt", f"from the {FAKE_PRIVATE.upper()} collection\n")
        priv = r.commit("private name")
        r.write("notes.txt", "from a collection\n")
        r.commit("remove it")
        code, out = r.gate("--range", f"{priv}~1..HEAD")
        check("--range catches it (exit 1)", code == 1 and "private-list" in out, out)
        code, out = r.gate("--all", "--strict")
        check("--all --strict at tip exits 0", code == 0, out)

        print("name only in a commit message")
        r.write("README", "still nothing\n")
        msg = r.commit(f"compare with {FAKE_STRAIN}")
        r.write("README", "still nothing at all\n")
        r.commit("clean message")
        code, out = r.gate("--range", f"{msg}~1..HEAD")
        check("--range exits 1", code == 1, out)
        check("--range names the commit's message", f"{msg[:12]}:<commit-message>" in out, out)

        print("finding at the tip is labelled tip")
        r.write("tip.txt", f"{FAKE_STRAIN}\n")
        tip = r.commit("tip leak")
        code, out = r.gate("--range", "HEAD~1..HEAD")
        check("exit 1, labelled [tip]", code == 1 and f"{tip[:12]} [tip]" in out, out)
        r.write("tip.txt", "gone\n")
        r.commit("fix tip")

        print("merge commits")
        m = Repo(base, "merge")
        m.write("a.txt", "one\n")
        mbase = m.commit("base")
        m.git("checkout", "-q", "-b", "side")
        m.write("b.txt", f"{FAKE_STRAIN}\n")
        side_leak = m.commit("side leak")
        m.write("b.txt", "clean\n")
        m.commit("side fix")
        m.git("checkout", "-q", "main")
        m.write("a.txt", "two\n")
        m.commit("main change")
        m.git("merge", "-q", "--no-ff", "--no-commit", "side")
        m.write("a.txt", f"two {FAKE_STRAIN}\n")   # introduced by the merge resolution itself
        m.git("add", "a.txt")
        m.git("commit", "-q", "-m", "merge side")
        merge = m.git("rev-parse", "HEAD")
        code, out = m.gate("--range", f"{mbase}..HEAD")
        check("side-branch history is scanned", f"{side_leak[:12]}:b.txt" in out, out)
        check("content introduced by the merge itself is scanned",
              f"{merge[:12]}:a.txt" in out, out)
        check("a clean file brought in by the merge is not re-reported against the merge",
              f"{merge[:12]}:b.txt" not in out, out)
        code, out = m.gate("--range", f"main...{mbase}")
        check("A...B spelling accepted", code == 1 and f"{merge[:12]}:a.txt" in out, out)

        print("clean range")
        c = Repo(base, "quiet-range")   # not "clean": the name appears in paths the gate prints
        c.write("x.txt", "hello\n")
        cbase = c.commit("base")
        c.write("x.txt", "hello world\n")
        c.write("y.bin", "\x00\x01")
        c.commit("more")
        code, out = c.gate("--range", f"{cbase}..HEAD", "--strict")
        check("exits 0", code == 0, out)
        check("says clean AND what it examined",
              "clean" in out and "1 file(s)" in out and "1 commit message(s)" in out
              and "1 commit(s)" in out, out)

        print("empty range and empty index never print 'clean'")
        code, out = c.gate("--range", "HEAD..HEAD")
        check("empty range: exit 0, no 'clean', says 0 commits",
              code == 0 and "clean" not in out and "0 commits" in out, out)
        code, out = c.gate("--range", "HEAD..HEAD", "--strict")
        check("empty range --strict: exit 1", code == 1, out)
        code, out = c.gate("--staged")
        check("empty index: exit 0, no 'clean', says 0 files",
              code == 0 and "clean" not in out and "examined 0 files" in out, out)
        code, out = c.gate("--staged", "--message", "an ordinary message")
        check("empty index + a message still warns about the index",
              "examined 0 files" in out and "clean" not in out, out)
        code, out = c.gate("--staged", "--strict")
        check("empty index --strict: exit 1", code == 1, out)
        code, out = c.gate("--strict")
        check("no mode at all --strict: exit 1, no 'clean'", code == 1 and "clean" not in out, out)
        c.write("x.txt", "hello again\n")
        c.git("add", "x.txt")
        code, out = c.gate("--staged", "--strict")
        check("staged file: exit 0, clean, examined 1 file",
              code == 0 and "clean" in out and "1 file(s)" in out, out)

        print("bad input")
        code, out = c.gate("--range", "no-such-rev..HEAD")
        check("unknown revision: exit 2", code == 2, out)
        code, out = c.gate("--range", "--all")
        check("option-looking range: exit 2", code == 2, out)

    print(f"\n{'FAILED: ' + str(failures) + ' check(s)' if failures else 'all checks passed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
