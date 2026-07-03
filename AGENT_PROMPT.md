Add comprehensive docstrings to the Python package at py/ae (the pybind11 wrapper +
report/analysis code for the "ae" antigenic cartography toolkit), working in this
directory: ~/AC/eu/ae-docs — a dedicated git worktree already checked out on branch
docs/py-ae-docstrings (created off main). This is scoped to Python only — do not touch
the C++ sources (cc/), the legacy AD/ tree, or anything outside py/ae. Do not create
another branch or worktree — you're already on the right one.

CONTEXT
A docstring-coverage survey found: 137/545 (25%) of public functions/classes have
docstrings, and 60/75 files lack even a module-level docstring. Coverage is uneven —
some recently-worked modules are well documented and should be used as the style
template; large swaths of data-ingestion and report-plumbing code have zero docstrings
despite real complexity.

READ FIRST
- CLAUDE.md (in this worktree root) — architecture, build, and conventions for this
  project.
- ~/AC/eu/CLAUDE.md — workspace-level context (ae is the active toolkit, AD is
  predecessor/legacy, do not touch AD; this worktree is one of several sharing ae's
  git history — uncommitted changes in other worktrees don't affect you and vice versa).
- Pick 2-3 files from the "well-documented" list below and read their existing
  docstrings to match the house style (format, level of detail, whether they use
  Args/Returns sections or prose) before writing new ones.

STYLE MODELS (already well documented — copy their conventions, don't rewrite them)
- py/ae/adjust.py (18/30 documented)
- py/ae/tal/section_maps.py (18/26)
- py/ae/tal/signature_page.py (10/12)
- py/ae/report/multiple_circles.py (8/9)
- py/ae/utils/kateri.py (6/29)
- py/ae/webserver/server.py (6/12)

PRIORITY ORDER (highest value first — do these even if you don't reach the tail)
1. Zero-coverage files with real complexity (structural/entry-point code — read
   callers elsewhere in py/ae to understand intent before documenting, don't guess
   from the function body alone):
   - py/ae/report/dirs.py (19 undocumented items)
   - py/ae/report/modules.py (9)
   - py/ae/sequences/source/parse.py (17)
   - py/ae/sequences/source/ncbi.py (10)
   - py/ae/utils/time_series.py (14)
   - py/ae/whocc/torg.py (12)
   - py/ae/whocc/table_dir.py (7)
2. Large files with low coverage ratio (size makes the gap costlier):
   - py/ae/report/latex.py (505 lines, 1/20 documented)
   - py/ae/report/chart_modifier.py (435 lines, 4/62)
3. Remaining zero-coverage files (smaller, but still worth closing):
   py/ae/utils/json.py, py/ae/semantic/name_generator.py,
   py/ae/report/stat_tables.py, py/ae/report/skeleton/conference_data.py,
   py/ae/report/skeleton/h1_chart_modifier.py, py/ae/utils/open_file.py,
   py/ae/utils/traceback.py, py/ae/semantic/front_style.py,
   py/ae/report/skeleton/serology.py, py/ae/virus/subtype_prefix.py,
   py/ae/chart/info.py, py/ae/chart/text.py, py/ae/utils/load_module.py,
   py/ae/utils/num_digits.py, py/ae/utils/timeit.py, py/ae/sequences/utils.py,
   py/ae/semantic/select_mark.py, py/ae/semantic/style.py
4. Add a module-level docstring to any remaining file still missing one (60/75
   currently lack this) — one or two sentences on what the module is for.

RULES
- Docstrings must describe actual behavior read from the code (and its call sites
  where the function's purpose isn't obvious in isolation) — never invent or guess
  at what a function does. If a function's purpose is genuinely unclear from reading
  it and its callers, flag it in your final report rather than fabricating a docstring.
- Do not add inline implementation comments, type annotations, or refactor code —
  docstrings only. Do not change logic, formatting, or imports.
- Do not touch __init__.py files that are empty/trivial (0 lines or just re-exports)
  beyond an optional one-line module docstring if genuinely useful — don't pad them.
- Keep docstrings concise: what it does, params/returns/raises only where non-obvious
  from names and types. Match the style-model files' verbosity, don't over-write.
- After editing, run a syntax check (python3 -m py_compile on each touched file, or
  python3 -c "import ae.<module>" where the package is importable) to confirm nothing
  broke — do not run the wider test/build suite unless one exists and is documented
  in CLAUDE.md.
- Commit your work in this worktree on the existing branch docs/py-ae-docstrings —
  do not commit to main, do not create a new branch. Before any commit, check for
  WHO CC surveillance data leakage per this workspace's policy (no titer/strain data
  belongs in commit messages or diffs — this task shouldn't touch data files at all,
  but verify).
- Do not push. Stop after committing locally and report which files were changed,
  which were skipped and why, and final docstring-coverage numbers (before/after).

DELIVERABLE
A local commit (or set of commits) on branch docs/py-ae-docstrings in this worktree,
plus a summary report: files documented, files skipped (with reason), and updated
docstring-coverage stats.
