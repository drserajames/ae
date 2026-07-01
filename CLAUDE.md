## Search scope

Keep broad filesystem searches (`find`, `grep -r`, `Glob`, `Grep`) within this project's directory by default. If you need to search outside it, ask first.

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
├── build/               Symlink → build-py314/ (native arm64, Python 3.14, current default)
├── build-py314/         Native arm64 build for Python 3.14 (cpython-314) — current default
├── build-arm64/         Native arm64 build for Python 3.10 (cpython-310) — fallback
├── build-x86_64/        Original x86_64 pre-migration build (preserved as fallback)
├── doc/                 Format documentation (ace-format.js, merge-types.org, etc.)
├── test/                Test charts (chart1.ace)
└── meson.build          Build definition
```

---

## Porting from AD (Acmacs-D) — status & coordination

`ae` is the rewrite/successor of the older `AD` tree at `~/AC/eu/AD` (the `acmacs-*` C++
family). The core was ported first; the remaining subsystems have since been ported (or
shelved by architecture decision) — **the bulk of the AD→ae port is now complete.**
**Multiple agents work different subsystems in parallel** — the master plan, ownership
table, per-subsystem milestones, and coordination rules live in [`TODO.md`](TODO.md).
**Read `TODO.md` and claim a subsystem there before starting any porting work.**

**Core, already ported:** chart engine (relax/optimize, merge, grid-test, procrustes,
serum circles, stress), sequences/seqdb, virus name/passage parsing, locationdb, tree
manipulation, WHO CC XLSX/TSV ingestion. Exposed via `ae_backend` submodules: `chart_v3`,
`chart_v2`, `seqdb`, `tree`, `virus`, `whocc`, `locdb_v3`, `hidb`, `utils`. The chart engine
also now writes layout coordinates (`Projection.set_coordinates` / `Layout.__setitem__` /
`set_unmovable`) for programmatic map adjustment.

**Subsystem status (priority order — see `TODO.md` for detail):**

| # | Subsystem | AD source | ae target | State |
|---|-----------|-----------|-----------|-------|
| 1 | Map drawing | `acmacs-draw`, `acmacs-map-draw` | — / `cc/geo/` | ⚪ **shelved** — antigenic maps are done in **kateri** (Dart app, separate repo, driven over a socket via `py/ae/utils/kateri.py`); `cc/map-draw/` removed (preserved on `map-draw-shelved`). `cc/draw/cairo-surface.*` kept (shared); **geographic** maps = `cc/geo/` + `geo-draw` (done) |
| 2 | hidb (historical influenza DB) | `hidb-5` | `cc/hidb/` | 🟢 done — reader + authoring (make/convert/stat), `ae_backend.hidb` |
| 3 | TAL (phylo tree drawing / sig pages) | `acmacs-tal` | `cc/tal/` + `tal-draw` + `py/ae/tal/` | 🟢 feature-complete (core) — tree render, clades/time-series, colouring, aa-transitions, settings-v3 `.tal` reader, signature pages |
| 4 | ssm-report (seasonal report) | `ssm-report` | `py/ae/report/` | 🟡 vcm engine consolidated; all figures generate on ae (kateri maps / `stat` / `geo-draw` / `tal-draw`); adjust ported (`ae.adjust` + kateri drag). Remaining: a full assembled-report run + geo clade colouring (#1). See [`py/ae/report/MIGRATION.md`](py/ae/report/MIGRATION.md) |
| 5 | webserver | `acmacs-webserver` | `py/ae/webserver/` | 🟢 done — Python rewrite; HTTP/HTTPS + chart-data verified |
| 6 | CLI wrappers over `chart_v3` | various `bin/chart-*` | `bin/` | 🟢 done |

> Note: **antigenic-map drawing lives in `kateri`** (a Dart/Flutter viewer + PDF generator,
> `github.com/drserajames/kateri`), not in `ae` C++ — ae drives it over a Unix socket
> (`ae.utils.kateri`: send `CHRT`, `set_style`, `pdf`/`get_chart`). Don't look for a C++ map
> renderer in `ae`; the only ae-side "map drawing" is the geographic world map (`cc/geo`).

**Coordination essentials (full rules in `TODO.md`):**
- `meson.build` is the main conflict risk — keep edits in a commented `# --- <subsystem> ---`
  block and append rather than reflow.
- Python bindings: add a `cc/py/<name>.cc` file and register it in
  [`cc/py/module.cc`](cc/py/module.cc) + [`cc/py/module.hh`](cc/py/module.hh) without
  reordering existing entries.
- AD source to reference for each subsystem is under `~/AC/eu/AD/sources/<package>`.
- Build with the native-arm64 Apple-Clang procedure below (not `./mk`, not Homebrew
  LLVM). New drawing deps (Cairo, Pango) come from arm64 Homebrew at `/opt/homebrew`.

## Current build state (Apple Silicon)

**`build/` → `build-py314/`** — The active build is **native arm64 for Python 3.14**
(`ae_backend.cpython-314-darwin.so`), compiled with **Apple Clang** and arm64 Homebrew
dependencies at `/opt/homebrew`. No Rosetta 2 needed. Import it with the default
`/opt/homebrew/bin/python3` (3.14.x).

> **Toolchain note (Jul 2026).** The active compiler is now **Apple clang 21** (macOS 26.5
> SDK), after a 27 Jun 2026 Xcode update. Its stricter libc++ requires complete element types
> in `std::vector`/`std::pair`, which needed behaviour-preserving source fixes — see
> *clang 21 / macOS 26.5 SDK* under "Source code changes" below. The build tooling also moved
> off the (evaporated) `/tmp` venv onto **persistent Homebrew meson/ninja** — see the Python
> 3.14 procedure below. Earlier "Apple Clang 16" references predate this; the tree now builds
> under clang 21.

> **Python version history.** Homebrew bumped its default `python3` to **3.14** (Jun 2026).
> CPython extensions are ABI-locked per minor version, so the older 3.10 `.so` would not
> import under 3.14. The build was retargeted to 3.14 on **18 Jun 2026**. The previous
> **`build-arm64/`** (`cpython-310`, native arm64) is preserved as a **Python 3.10 fallback**
> — use `PYTHONPATH=…/ae/build-arm64` with a 3.10 interpreter if ever needed. The only change
> required to retarget was a newer **meson (≥ ~1.4; built with 1.11.1)** — meson 1.1.0 relies
> on the `distutils` that Python 3.14 removed. pybind11 2.10.0 and all other vendored deps
> compiled against 3.14 unchanged.

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

**Do NOT use Homebrew LLVM** (currently version 22 in arm64 Homebrew). It is too new for the vendored `lexy` subproject and causes build failures with incomplete-type errors. Apple Clang (`/usr/bin/clang++`, currently clang 21) is the correct compiler for this project.

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

### Building for Python 3.14 (current default — this is what `build/` points at)

The procedure above documents the original Python 3.10 build (`build-arm64/`). The active
build now targets **Python 3.14** in `build-py314/`. Two deltas from the 3.10 procedure:

1. **meson must be newer than 1.1.0** — meson 1.1.0 fails with *"is not a valid python or it
   is missing distutils"* because Python 3.14 removed `distutils`. Use meson ≥ ~1.4 (this
   build used **1.11.1**). ninja is unchanged (universal2; runs arm64).
2. **`python3` in the native file points at 3.14**, and meson must run under an arm64 3.14
   interpreter so clang inherits arm64.

Install meson/ninja from **arm64 Homebrew** — persistent and reboot-safe. (Historically these
lived in a `/tmp/ae-py314-venv` venv because Homebrew's `python@3.14` is PEP-668
externally-managed; that venv + its `/tmp` native file evaporated, leaving the build
un-rebuildable, so we moved to brew-managed tools. Homebrew's meson runs on its own
`python@3.14`, sidestepping PEP 668 without `--break-system-packages`.)

```bash
cd /Users/sarahjames/AC/eu/ae
export PATH="/opt/homebrew/bin:$PATH"
export PKG_CONFIG_PATH="/opt/homebrew/opt/brotli/lib/pkgconfig"
export CMAKE_POLICY_VERSION_MINIMUM=3.5     # lexy/CMake-4.x workaround (see below)

# Persistent arm64 meson + ninja (meson 1.11.1 on python@3.14, ninja 1.13.2)
brew install meson ninja

# Native file: Apple Clang + Python 3.14 — kept OUTSIDE /tmp so it survives reboots.
# `ninja` is pinned to the arm64 brew binary so meson never picks /usr/local/bin/ninja
# (the x86_64 Homebrew one that would silently spawn x86_64 clang).
cat > ~/AC/eu/ae-py314-native.ini << 'EOF'
[binaries]
c       = '/usr/bin/clang'
cpp     = '/usr/bin/clang++'
python3 = '/opt/homebrew/bin/python3.14'
ninja   = '/opt/homebrew/bin/ninja'

[properties]
pkg_config_libdir = '/opt/homebrew/opt/brotli/lib/pkgconfig'
EOF

# Configure + compile
arch -arm64 /opt/homebrew/bin/meson setup build-py314 \
    --native-file ~/AC/eu/ae-py314-native.ini -Doptimization=3 -Ddebug=true
arch -arm64 /opt/homebrew/bin/ninja -C build-py314

# Make it the default once verified (keeps build-arm64 as the 3.10 fallback)
ln -sfn build-py314 build
```

> The final `Generating ae_backend_stubs` step may print `ae_backend: Failed to import,
> skipping` — the build-time stub generator can't import the freshly-linked module. It is
> non-fatal (ninja exits 0) and does not affect the module; `PYTHONPATH=build-py314` import
> works.

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
file build/ae_backend.cpython-314-darwin.so
# → Mach-O 64-bit bundle arm64   (build-arm64/ still has the cpython-310 fallback)

python3 -c "import sys; sys.path.insert(0, 'build'); import ae_backend, platform; print(platform.machine())"
# → arm64
```

---

## Source code changes for Apple Clang compatibility

These changes were applied to make the codebase compile with Apple Clang on macOS 14+ (originally clang 16; §4 covers the clang 21 / macOS 26.5 SDK update). They are committed in the source tree and should not need to be repeated unless the vendored subprojects or the toolchain are updated.

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

### 4. clang 21 / macOS 26.5 SDK — libc++ requires complete element types in containers

A 27 Jun 2026 Xcode update bumped the toolchain to **Apple clang 21 + macOS 26.5 SDK**. Its libc++ is stricter: `std::vector<T>` / `std::pair<…, T>` now evaluate `is_trivially_relocatable` / `alignof` on the element, which **requires `T` complete** — where the code previously relied on `std::vector<incomplete>` (the old libc++ tolerated it). A from-scratch build of the whole tree broke with *"field has incomplete type"* / *"invalid application of 'alignof' to an incomplete type"* / *"no matching function for call to `__add_alignment_assumption`"*.

The fix (behaviour-preserving) is to **out-of-line the recursive-variant container members so they instantiate only after the `value` type is complete**. For a JSON-like `value` that is a variant over `object`/`array` (which themselves hold `std::vector<value>`), any member touching the vector (`begin`/`end`/`data`/`erase`/…) must be defined below the full `value` definition, not inline in the class body. Applied in:

- `cc/utils/collection.hh` — `dynamic::{object,array}` `begin`/`end`/`data`
- `cc/ad/rjson-v2.hh` — `rjson::{object,array}::all_of`
- `cc/ad/rjson-v3.hh` — `rjson::v3::detail::{object,array}` `begin`/`end`

Also a genuine upstream **lexy** typo (`_colum_nr` in `input_location.hpp`) that clang 21 now instantiates in an `operator<` template body — carried as a tracked `subprojects/packagefiles/lexy/` overlay wired via `patch_directory = lexy` in `lexy.wrap`. Note `subprojects/.gitignore` must anchor its `lexy` rule to `/lexy` (not bare `lexy`), or the `packagefiles/lexy` overlay is ignored too.

> **If you hit a new "incomplete type" error after adding code**: it is almost always a
> `std::vector<X>`/`std::pair<…,X>` instantiated (via an inline member) while `X` is only
> forward-declared. Move that member's definition below `X`'s full definition.

### libc++ hardening differs between builds — `build-py314` traps on UB that `build-arm64` ignores

`build-py314/` (3.14) is configured with **`-D_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_FAST`**;
`build-arm64/` (3.10) is **not**. FAST hardening adds bounds/iterator checks that, on failure, call
`__builtin_trap()` → **SIGTRAP (exit 133)**, with no Python traceback (faulthandler does not catch
SIGTRAP — register it explicitly: `faulthandler.register(signal.SIGTRAP)`). This means a *latent*
out-of-bounds/UB bug can run cleanly under the 3.10 build but hard-crash under the 3.14 build, and
look like a "Python 3.14 incompatibility" when it is really a pre-existing C++ bug the 3.14 build's
hardening simply exposes. One such bug (a cross-buffer iterator subtraction in
`cc/chart/v3/selected-antigens-sera.hh` `SelectedIterator`, surfaced as a fake "kateri handshake
failure" in the ssm-report `style` step) was found and fixed this way on 2026-06-18. When triaging a
3.14-only SIGTRAP, suspect libc++ hardening catching real UB — get the native frame with a
`backtrace()` SIGTRAP handler (lldb attach / core dumps are blocked by hardened-runtime Python).

---

## Build system (standard path)

```bash
./mk                        # configure with meson (creates build/)
meson compile -C build      # compile everything
```

**Note**: The `mk` script assumes Homebrew LLVM (`/opt/homebrew/opt/llvm/bin/clang++` or `/usr/local/opt/llvm/bin/clang++`). On this machine, arm64 Homebrew LLVM (version 22) is installed but **incompatible** with the vendored `lexy` subproject. Use the manual arm64 build procedure above (Apple Clang) instead of `./mk`.

Dependencies: Apple Clang (currently clang 21) / g++-11+, ninja, meson ≥1.4 (for Python 3.14; 1.11.1 in use), cmake ≥3.18, libomp, brotli, zlib, libbz2, liblzma, catch2.

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
x, y = layout[i]                    # read one point's coords by index (negative index counts from end)
layout[i] = [x, y]                  # move a point (also proj.set_coordinates(point_no, [x, y]))
proj.set_unmovable([i, j])          # pin points so a subsequent relax() keeps them fixed

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
- **`numpy` is a runtime dependency** of `py/ae/adjust.py` (`_kabsch_align`, used by the kateri move→relax flow in `adjust_from_kateri`). It is **not** part of the build; install it for the Homebrew Python 3.14 interpreter that runs the report `0do` scripts: `/opt/homebrew/bin/python3 -m pip install --user --break-system-packages numpy` (PEP-668 externally-managed; `--user` keeps it out of Homebrew's tree). Without it, dragging a point and hitting relax in kateri fails with `ModuleNotFoundError: No module named 'numpy'`.
- `build/` is a **symlink** to `build-py314/` (the Python 3.14 build; `build-arm64/` is the 3.10 fallback). Repoint with `ln -sfn build-py314 build`. To remove it: `rm build` (not `rm -rf build`, which would delete the build directory contents).
- `.ace` files are usually XZ-compressed; opening with a text editor or `cat` will show binary garbage. Use `xz -d -c file.ace` to inspect raw JSON.
- Titer `"*"` = missing; `"<N"` = below detection; `">N"` = above threshold. Do not treat these as numbers.
- Column bases (`colbases`) are `log2(max_titer_per_serum)` and are fundamental to stress calculations — they are not stored in projections by default, only in forced-column-bases overrides.
- The `Layout` object supports iteration (`for coords in layout`) and indexed read/write: `layout[i]` reads a point's coords, `layout[i] = [x, y]` sets them (negative index counts from the end). Coordinates can also be set via `proj.set_coordinates(point_no, [x, y])`, and `proj.set_unmovable([i, j])` pins points so a subsequent `relax()` keeps them fixed.
- **New C++ code**: Always use `fmt::format_to(` (not bare `format_to(`). Both `std::format_to` and `fmt::format_to` are visible in C++20 mode under Apple Clang 16 and the unqualified form is ambiguous.
- **Homebrew LLVM 22** (at `/opt/homebrew/opt/llvm/`) is installed but **not used** — incompatible with the vendored `lexy` subproject. Apple Clang (`/usr/bin/clang++`, currently clang 21) is the correct compiler.
- **Rebuilding**: Run meson via `arch -arm64 python3.10` and ninja via `arch -arm64 ~/Library/Python/3.10/bin/ninja`. The x86_64 `/usr/local/bin/ninja` will silently produce x86_64 binaries even on an arm64 Mac.
- **Python 3.14** (the current Homebrew default, which `build/`→`build-py314/` targets) lacks `distutils`, so **meson 1.1.0 fails** with *"is not a valid python or it is missing distutils"*. Fix by using a newer meson (≥ ~1.4; the active build used 1.11.1), not by downgrading Python. The old 3.10 instructions that put `/Library/Frameworks/Python.framework/Versions/3.10/bin/python3` first in PATH apply only to the legacy `build-arm64/` (3.10) fallback.
- **`brew --prefix libomp`**: libomp is keg-only — always use the formula-specific form `brew --prefix libomp` rather than bare `brew --prefix` when constructing library/include paths.
