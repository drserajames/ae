# ae (Acmacs-E) — Project Context for Claude Agents

## What this project is

`ae` is a C++ library and toolkit for **antigenic cartography** — constructing 2D/3D maps from immunological assay data (HI titers, FRA, PRNT, etc.) where map distances represent antigenic similarity between virus strains and sera. It is the successor to the older `acmacs-*` C++ family.

The project compiles to:
- A shared library (`libae.dylib`)
- A Python extension module (`ae_backend`) via pybind11
- A set of compiled binaries (`build/chart-relax`, `build/chart-v3-test`, etc.)
- Python CLI scripts in `bin/` that import `ae_backend`

---

## Architecture overview

```
ae/
├── cc/                  C++ source (organized by domain)
│   ├── chart/v3/        Core chart + optimization code
│   ├── ad/              Generic utilities (color, rjson, algorithms)
│   ├── sequences/       Sequence alignment, FASTA, seqdb
│   ├── tree/            Phylogenetic tree (Newick, export)
│   ├── virus/           Name/passage/reassortant parsing
│   ├── locdb/           Location database
│   ├── whocc/           WHO CC data ingestion (XLSX, TSV)
│   └── ext/             External wrappers (alglib, pybind11 bindings)
├── py/ae/               Python wrappers and helpers
│   ├── chart/           info.py, merge.py, text.py
│   ├── sequences/       Sequence utilities
│   └── virus/           Virus name utilities
├── bin/                 Python CLI scripts (need PYTHONPATH=build)
├── subprojects/         Vendored dependencies (alglib, fmt, lexy, pybind11, etc.)
├── build/               Symlink → build-arm64/ (native arm64, current default)
├── build-arm64/         Native arm64 build — Apple Clang 16, arm64 Homebrew deps
├── build-x86_64/        Original x86_64 pre-migration build (preserved as fallback)
├── doc/                 Format documentation (ace-format.js, merge-types.org, etc.)
├── test/                Test charts (chart1.ace)
└── meson.build          Build definition
```

---

## Porting from AD (Acmacs-D) — status & coordination

`ae` is the rewrite/successor of the older `AD` tree at `~/AC/eu/AD` (the `acmacs-*` C++
family). The core is ported, but several whole subsystems are **not yet implemented** and
exist only as empty stub directories. **Multiple agents may be porting different
subsystems in parallel** — the master plan, priority order, ownership table, and
coordination rules live in [`TODO.md`](TODO.md). **Read `TODO.md` and claim a subsystem
there before starting any porting work.**

**Already ported:** core chart engine (relax/optimize, merge, grid-test, procrustes,
serum circles, stress), sequences/seqdb, virus name/passage parsing, locationdb, tree
manipulation, WHO CC XLSX/TSV ingestion. Exposed via `ae_backend` submodules: `chart_v3`,
`chart_v2`, `seqdb`, `tree`, `virus`, `whocc`, `locdb_v3`, `utils`.

**Not yet ported (priority order — see `TODO.md` for detail):**

| # | Subsystem | AD source | ae stub | State |
|---|-----------|-----------|---------|-------|
| 1 | Map drawing (Cairo + map-draw) | `acmacs-draw`, `acmacs-map-draw` | `cc/draw/` (primitives only), `cc/map-draw/` (empty) | in progress |
| 2 | hidb (historical influenza DB) | `hidb-5` | `cc/hidb/` (empty) | not started |
| 3 | TAL (phylo tree drawing) | `acmacs-tal` | `cc/tal/` (empty) | not started |
| 4 | ssm-report (seasonal report) | `ssm-report` | — | not started |
| 5 | webserver | `acmacs-webserver` | — | not started |
| 6 | CLI wrappers over `chart_v3` | various `bin/chart-*` | — | not started |

**Coordination essentials (full rules in `TODO.md`):**
- `meson.build` is the main conflict risk — keep edits in a commented `# --- <subsystem> ---`
  block and append rather than reflow.
- Python bindings: add a `cc/py/<name>.cc` file and register it in
  [`cc/py/module.cc`](cc/py/module.cc) + [`cc/py/module.hh`](cc/py/module.hh) without
  reordering existing entries.
- AD source to reference for each subsystem is under `~/AC/eu/AD/sources/<package>`.
- Build with the native-arm64 Apple-Clang-16 procedure below (not `./mk`, not Homebrew
  LLVM). New drawing deps (Cairo, Pango) come from arm64 Homebrew at `/opt/homebrew`.

## Current build state (Apple Silicon)

**`build/` → `build-arm64/`** — The active build is **native arm64**, compiled with Apple Clang 16 and arm64 Homebrew dependencies at `/opt/homebrew`. No Rosetta 2 needed.

```bash
# Python usage — no arch flag needed
PYTHONPATH=/Users/sarahjames/AC/eu/ae/build python3 bin/chart-relax -n 100 input.ace output.ace

# Or in Python
import sys
sys.path.insert(0, '/Users/sarahjames/AC/eu/ae/build')
import ae_backend  # native arm64
```

**`build-x86_64/`** is the original pre-migration x86_64 build, preserved as a fallback. To use it under Rosetta 2:

```bash
PYTHONPATH=/Users/sarahjames/AC/eu/ae/build-x86_64 arch -x86_64 python3 bin/chart-relax -n 100 input.ace output.ace
```

---

## Building natively for arm64

### Prerequisites

arm64 Homebrew must be installed at `/opt/homebrew` with the following packages:

```bash
# Install arm64 Homebrew (requires admin — run in Terminal, not via Claude's Bash tool)
sudo mkdir -p /opt/homebrew && sudo chown -R $(whoami) /opt/homebrew
NONINTERACTIVE=1 arch -arm64 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install required arm64 packages
/opt/homebrew/bin/brew install brotli libomp catch2

# Install arm64-aware meson and ninja via pip for Python 3.10
arch -arm64 /Library/Frameworks/Python.framework/Versions/3.10/bin/python3 \
    -m pip install --user meson==1.1.0 ninja
```

**Do NOT use Homebrew LLVM** (currently version 22 in arm64 Homebrew). It is too new for the vendored `lexy` subproject and causes build failures with incomplete-type errors. Apple Clang 16 (`/usr/bin/clang++`) is the correct compiler for this project.

### Build procedure

```bash
cd /Users/sarahjames/AC/eu/ae

# PATH setup: Python 3.10 first (prevents Homebrew Python 3.14 being picked up
# by meson), then arm64 brew (so 'brew --prefix libomp' resolves correctly)
mkdir -p /tmp/arm64-bin
ln -sf /Library/Frameworks/Python.framework/Versions/3.10/bin/python3 /tmp/arm64-bin/python3
export PATH="/tmp/arm64-bin:/opt/homebrew/bin:$PATH"
export PKG_CONFIG_PATH="/opt/homebrew/opt/brotli/lib/pkgconfig"

# Create the meson native file specifying Apple Clang and Python 3.10
cat > /tmp/ae-arm64-native.ini << 'EOF'
[binaries]
c       = '/usr/bin/clang'
cpp     = '/usr/bin/clang++'
python3 = '/Library/Frameworks/Python.framework/Versions/3.10/bin/python3'

[properties]
pkg_config_libdir = '/opt/homebrew/opt/brotli/lib/pkgconfig'
EOF

# Configure (must run meson under arm64 Python so clang inherits arm64)
arch -arm64 /Library/Frameworks/Python.framework/Versions/3.10/bin/python3 \
    ~/Library/Python/3.10/bin/meson \
    setup build-arm64 \
    --native-file /tmp/ae-arm64-native.ini \
    -Doptimization=3 -Ddebug=true

# Compile (must use arm64 ninja — pip-installed universal binary)
arch -arm64 ~/Library/Python/3.10/bin/ninja -C build-arm64

# Make it the default (first time only)
mv build build-x86_64   # rename old build if present
ln -s build-arm64 build
```

### Why the arm64 meson and ninja matter

Apple Clang **inherits the architecture of its parent process**. Running clang from an x86_64 process (even on an arm64 Mac) produces x86_64 binaries silently — `file` on the output will confirm the architecture. The pip-installed `~/Library/Python/3.10/bin/ninja` is a universal binary that runs as arm64 natively, ensuring the entire toolchain spawns arm64 clang.

`/usr/local/bin/ninja` (from x86_64 Homebrew) must NOT be used — it spawns x86_64 clang.

### CMake 4.x / lexy reconfigure failure (after any `meson.build` edit)

Editing `meson.build` forces a full meson regenerate, which re-runs the vendored `lexy`
CMake subproject. arm64 Homebrew CMake is now **4.x**, which removed compatibility with the
`cmake_minimum_required(VERSION < 3.5)` that lexy's bundled doctest declares — the
regenerate fails with *"Compatibility with CMake < 3.5 has been removed."* Work around it by
exporting **`CMAKE_POLICY_VERSION_MINIMUM=3.5`** in the environment before running `ninja`
(or `meson setup`). This does not affect builds that don't reconfigure.

### Verifying the build architecture

```bash
file build/ae_backend.cpython-310-darwin.so
# → Mach-O 64-bit dynamically linked shared library arm64

python3 -c "import sys; sys.path.insert(0, 'build'); import ae_backend, platform; print(platform.machine())"
# → arm64
```

---

## Source code changes for Apple Clang 16 compatibility

Three categories of changes were applied to make the codebase compile with Apple Clang 16 on macOS 14+. These are committed in the source tree and should not need to be repeated unless the vendored subprojects are updated.

### 1. `cc/ext/compare.hh` — vector `operator<=>` ambiguity fix

Apple's macOS 13+ SDK ships `std::vector::operator<=>` in libc++ but does **not** define `__cpp_lib_three_way_comparison`. The project's fallback `#ifndef __cpp_lib_three_way_comparison` block also defines this operator, causing an "object of type X cannot be compared because its comparison function is implicitly deleted" error. Fixed by adding a macOS version guard:

```cpp
#if defined(__APPLE__) && defined(__ENVIRONMENT_MAC_OS_X_VERSION_MIN_REQUIRED__) && \
    __ENVIRONMENT_MAC_OS_X_VERSION_MIN_REQUIRED__ >= 130000
#  define AE_STDLIB_HAS_VECTOR_SPACESHIP 1
#else
#  define AE_STDLIB_HAS_VECTOR_SPACESHIP 0
#endif

#if !defined(__cpp_lib_three_way_comparison) && !AE_STDLIB_HAS_VECTOR_SPACESHIP
// ... fallback string/vector operator<=> implementations ...
#endif
```

### 2. 61 C++ files — `fmt::format_to` qualification

Apple Clang 16 with C++20 exposes both `std::format_to` (from `<format>`) and `fmt::format_to`. Unqualified `format_to(` calls are ambiguous and fail to compile. All 75 unqualified calls across 61 files in `cc/` were qualified as `fmt::format_to(`. If re-encountering this after adding new code, run:

```bash
find cc/ -name '*.hh' -o -name '*.cc' | xargs grep -l '[^:]format_to(' | \
    while IFS= read -r f; do
        perl -i.bak -pe 's/(?<![:\w])format_to\(/fmt::format_to(/g' "$f" && rm -f "${f}.bak"
    done
```

### 3. `meson.build` — OpenMP detection for Apple Clang

Apple Clang does not support `-fopenmp` (plain); it requires `-Xclang -fopenmp`. Also, `libomp` is keg-only in Homebrew (not symlinked into the main prefix), so its path must be found with `brew --prefix libomp`. The meson.build OpenMP section was updated:

```python
omp = dependency('openmp', required: false)
if host_machine.system() == 'darwin'
  libomp_prefix = run_command('brew', '--prefix', 'libomp', check: true).stdout().strip()
  libomp_dir = ['-L' + libomp_prefix + '/lib']
  if not omp.found()
    omp = declare_dependency(
      compile_args : ['-Xclang', '-fopenmp', '-I' + libomp_prefix + '/include'],
      link_args    : ['-L' + libomp_prefix + '/lib', '-lomp'],
    )
  endif
else
  libomp_dir = []
endif
```

This works for both x86_64 Homebrew (`/usr/local`) and arm64 Homebrew (`/opt/homebrew`) because `brew --prefix libomp` returns the formula-specific prefix regardless of which Homebrew is in PATH.

---

## Build system (standard path)

```bash
./mk                        # configure with meson (creates build/)
meson compile -C build      # compile everything
```

**Note**: The `mk` script assumes Homebrew LLVM (`/opt/homebrew/opt/llvm/bin/clang++` or `/usr/local/opt/llvm/bin/clang++`). On this machine, arm64 Homebrew LLVM (version 22) is installed but **incompatible** with the vendored `lexy` subproject. Use the manual arm64 build procedure above (Apple Clang 16) instead of `./mk`.

Dependencies: clang-14+ / g++-11+, ninja, meson ≥0.60, cmake ≥3.18, libomp, brotli, zlib, libbz2, liblzma, catch2.

---

## File format: `.ace`

Charts are stored in `.ace` files. The format is JSON, optionally compressed:
- **XZ** (`.ace` with XZ magic bytes) — decompress with `xz -d -c file.ace | python3 -m json.tool`
- **Brotli** — use brotli CLI or `ae_backend`
- **Plain JSON** — rare, only for very small files

The JSON schema is documented in [`doc/ace-format.js`](doc/ace-format.js). Top-level key is `"c"` (chart). Key subkeys:
- `"i"` — metadata (lab, assay, virus type, date, RBC species)
- `"a"` — antigen list (`"N"` = name, `"P"` = passage, `"R"` = reassortant, `"T"` = semantic attributes)
- `"s"` — serum list (same structure as antigens, plus `"I"` = serum ID)
- `"t"` — titer table (`"l"` = rows list; `"L"` = layers for merged charts)
- `"P"` — projections list (coordinates, minimum column basis, transformation matrix)

Titer encoding: numeric strings (`"160"`), `"<40"` (below threshold), `">2560"` (above threshold), `"*"` (missing).

---

## Python API (`ae_backend.chart_v3`)

```python
import sys
sys.path.insert(0, '/Users/sarahjames/AC/eu/ae/build')
import ae_backend

# Load a chart
chart = ae_backend.chart_v3.Chart('path/to/chart.ace')

# Inspect
chart.number_of_antigens()      # int
chart.number_of_sera()          # int
chart.number_of_projections()   # int
chart.name(0)                   # str — descriptive name for projection 0

# Antigens and sera
for no, ag in chart.select_all_antigens():
    ag.name()          # full name
    ag.passage()
    ag.reassortant()

for no, sr in chart.select_all_sera():
    sr.name()
    sr.serum_id()

# Projections
proj = chart.projection(0)          # best projection
proj.stress()                       # float
proj.minimum_column_basis()         # str, e.g. "none" or "1280"
proj.comment()                      # str

# Layout (coordinates)
layout = proj.layout()
layout.number_of_dimensions()       # int (2 or 3)
len(layout)                         # n_antigens + n_sera
for coords in layout:               # iterate — each coords is list[float]
    x, y = coords
# NOTE: do NOT use layout[i] — raises TypeError: Unregistered type

# Column bases
chart.column_bases(proj.minimum_column_basis())   # list[float], one per serum

# Titers
titers = chart.titers()
titers.number_of_layers()       # >1 means this is a merge

# Optimization
chart.relax(
    number_of_dimensions=2,
    number_of_optimizations=100,
    minimum_column_basis="none",   # or e.g. "1280"
    dimension_annealing=False,
    rough=False,
)

# Relax an existing projection further
proj.relax(rough=False)

# Incremental relaxation (for incremental merges)
chart.relax_incremental(
    number_of_optimizations=100,
    remove_source_projection=True,
    unmovable_non_nan_points=False,
    rough=False,
)

# Grid test (find and fix trapped/hemisphering points)
result = chart.grid_test()
result.count_trapped()          # int
result.trapped_hemisphering()   # iterable of results
result.apply(proj)              # move trapped points
proj.relax()

# Keep only the N best projections
chart.keep_projections(10)

# Save
chart.write('output.ace')
```

---

## Command-line tools (in `bin/`)

All scripts require `PYTHONPATH=build`. No `arch -x86_64` needed — `build/` is now native arm64:

```bash
export PYTHONPATH=/Users/sarahjames/AC/eu/ae/build

# Optimize from scratch (100 runs, 2D, keep 10 best)
bin/chart-relax -n 100 input.ace output.ace

# Options:
#   -n N       number of optimizations (default 100)
#   -d N       dimensions (default 2)
#   -m N       minimum column basis (default "none")
#   -k N       projections to keep (0=all, default 10)
#   --rough    faster but less precise
#   --dimension-annealing
#   --no-grid  skip grid test after optimization
#   --incremental  relax incremental merge

# Relax an existing projection
bin/chart-relax --existing 0 input.ace output.ace

# Merge charts
bin/chart-merge ...

# Chart information
bin/chart-info input.ace
bin/chart-info-and-table input.ace

# Procrustes comparison
bin/chart-procrustes chart1.ace chart2.ace

# Serum circles
bin/chart-serum-circles input.ace output.ace

# Grid test
bin/chart-grid-test input.ace
```

---

## Merge types (summary — see `doc/merge-types.org` for full detail)

| Type | Behaviour |
|------|-----------|
| 1 | Tables merged, no projections |
| 2 | Tables merged, best projection from chart 1 copied, NaN for new points — use `relax_incremental()` to relax |
| 3 | Overlay via procrustes, common point coords averaged — not relaxed |
| 4 | Type 3 then relax with chart-1 points frozen |
| 5 | Full reoptimization from merged table |
| 6 | Incremental merge |

---

## Test data

- `test/chart1.ace` — A(H3N2) HI guinea-pig assay, AC lab, 2018-11-11  
  22 antigens × 10 sera, no projections (needs optimization).  
  After 10 optimizations → stress ≈ **66.12** (all runs converge, stable solution). Verified on both x86_64 (Rosetta) and native arm64 (stress = 66.1247).

---

## Common gotchas

- `ae_backend` must be on `PYTHONPATH` (from `build/`) — it is **not** installed system-wide.
- `build/` is a **symlink** to `build-arm64/`. To remove it: `rm build` (not `rm -rf build`, which would delete the build directory contents).
- `.ace` files are usually XZ-compressed; opening with a text editor or `cat` will show binary garbage. Use `xz -d -c file.ace` to inspect raw JSON.
- Titer `"*"` = missing; `"<N"` = below detection; `">N"` = above threshold. Do not treat these as numbers.
- Column bases (`colbases`) are `log2(max_titer_per_serum)` and are fundamental to stress calculations — they are not stored in projections by default, only in forced-column-bases overrides.
- The `Layout` object supports iteration (`for coords in layout`) but **not** direct indexing via `layout[i]` — raises `TypeError: Unregistered type`.
- **New C++ code**: Always use `fmt::format_to(` (not bare `format_to(`). Both `std::format_to` and `fmt::format_to` are visible in C++20 mode under Apple Clang 16 and the unqualified form is ambiguous.
- **Homebrew LLVM 22** (at `/opt/homebrew/opt/llvm/`) is installed but **not used** — incompatible with the vendored `lexy` subproject. Apple Clang 16 (`/usr/bin/clang++`) is the correct compiler.
- **Rebuilding**: Run meson via `arch -arm64 python3.10` and ninja via `arch -arm64 ~/Library/Python/3.10/bin/ninja`. The x86_64 `/usr/local/bin/ninja` will silently produce x86_64 binaries even on an arm64 Mac.
- **Python 3.14** (from arm64 Homebrew) lacks `distutils` and causes meson to fail. Always put `/Library/Frameworks/Python.framework/Versions/3.10/bin/python3` first in PATH when configuring the build.
- **`brew --prefix libomp`**: libomp is keg-only — always use the formula-specific form `brew --prefix libomp` rather than bare `brew --prefix` when constructing library/include paths.
