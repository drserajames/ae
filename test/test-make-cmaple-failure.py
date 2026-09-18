#!/usr/bin/env python3
# Tests the failure path of `proj/weekly-tree/make-cmaple` -- TODO.md open-defect #17.
#
# Why this exists: `submit()` counted failed cmaple runs, logged them and carried on. `cmaple()`
# then wrote `cmaple_tree.txt` naming an `000.treefile` that was never produced, `main()` sent the
# "completed" mail and the process exited 0 -- so `submit`'s `&&` chain ran on into rotate.R, and
# the next week's `init` linked its `previous.newick` to the missing tree.
#
# No cluster is needed: a stub `srun` on PATH stands in for slurm and exits non-zero, which is what
# a dead cmaple job looks like to `run_cmaple`'s `subprocess.check_call`. A stub `mail` stands in
# for `/usr/bin/mail` (via AE_WEEKLY_TREE_MAIL_CMD) so the test records the subject line instead of
# sending anything.
#
# Everything here is invented -- the working directory is a fresh temp dir and the one sequence in
# source.fas is named "OUTGROUP" with a made-up 8-base sequence. NO WHO data.
#
# Run (from the ae worktree root):
#   PYTHONPATH="$PWD/build:$PWD/py" python3 test/test-make-cmaple-failure.py

import os
import subprocess
import sys
import tempfile
from pathlib import Path

AE_ROOT = Path(__file__).resolve().parents[1]
MAKE_CMAPLE = AE_ROOT / "proj" / "weekly-tree" / "make-cmaple"

FAILURES = []


def check(condition, message):
    if condition:
        print(f"  ok   {message}")
    else:
        print(f"  FAIL {message}")
        FAILURES.append(message)


# ======================================================================

tmpdir = Path(tempfile.mkdtemp(prefix="ae-make-cmaple-"))
working_dir = tmpdir / "h3"
working_dir.mkdir()
(working_dir / "source.fas").write_text(">OUTGROUP\nACGTACGT\n")

bindir = tmpdir / "bin"
bindir.mkdir()

# a stub srun that fails the way a dead cmaple job does
srun = bindir / "srun"
srun.write_text("#!/bin/sh\necho 'stub srun: simulated job failure' >&2\nexit 1\n")
srun.chmod(0o755)

# a stub mail that records what it was asked to send instead of sending it
mail_log = tmpdir / "mail.log"
mail = bindir / "mail"
mail.write_text(f"#!/bin/sh\necho \"$2 $3\" >> {mail_log}\ncat > /dev/null\nexit 0\n")
mail.chmod(0o755)

env = dict(os.environ)
env["PATH"] = f"{bindir}:{env['PATH']}"
env["AE_ROOT"] = str(AE_ROOT)
env["AE_WEEKLY_TREE_MAIL_CMD"] = str(mail)
env["AE_WEEKLY_TREE_MAIL_TO"] = "nobody@example.invalid"
env.pop("DYLD_INSERT_LIBRARIES", None)

print(f"running make-cmaple with a stub srun that exits 1 ({working_dir})")
completed = subprocess.run(
    [sys.executable, str(MAKE_CMAPLE), str(working_dir), "--method", "scratch", "-n", "2"],
    env=env, capture_output=True, text=True,
)

stderr = completed.stderr
mail_subjects = mail_log.read_text() if mail_log.exists() else ""

print()
check(completed.returncode != 0,
      f"make-cmaple exits non-zero when every cmaple run fails  (got {completed.returncode})")
check("2 of 2 runs failed" in stderr,
      "the failure names how many runs died")
check("FAILED" in mail_subjects,
      f"the FAILED mail is sent  (mail subjects: {mail_subjects.strip()!r})")
check("completed" not in mail_subjects,
      "the \"completed\" mail is NOT sent")

cmaple_tree_txt = list(working_dir.glob("cmaple_tree.txt"))
check(not cmaple_tree_txt,
      f"cmaple_tree.txt is not written  (found {[str(p) for p in cmaple_tree_txt]})")

# and the tree it would have named really is absent -- that is what made the file poisonous
treefiles = list(working_dir.glob("cmaple.*/000.treefile"))
check(not treefiles,
      f"no 000.treefile was produced  (found {[str(p) for p in treefiles]})")

# ======================================================================

print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for failure in FAILURES:
        print(f"  - {failure}")
    print()
    print("--- make-cmaple stderr ---")
    print(stderr[-3000:])
    sys.exit(1)
print("all checks passed")
