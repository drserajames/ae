# Acmacs-E

## Dependencies (general description)

System packages (on macOS, `./build.sh check` verifies the formulae listed in `BREW_FORMULAE` in [`build.sh`](build.sh)):

- Apple Clang (macOS, currently clang 21) / clang-14+ / g++-11
- ninja
- meson 1.4+ (needed for the Python 3.14 build; 1.11.1 in use — meson 1.1.0 fails because Python 3.14 removed `distutils`)
- cmake 3.18+ (to build lexy)
- pkg-config (meson uses it to find the system libraries below)
- libomp (OpenMP)
- brotli
- zlib 1.2.8+ (macOS: the SDK copy is used)
- libbz2 (optional)
- liblzma (xz)
- catch2 v3 (if no system copy is found, meson falls back to the vendored `subprojects/catch2.wrap`)
- cairo (used by `tal-draw`)
- Python 3.14 with headers, for the `ae_backend` extension (the `.so` is ABI-locked to the minor version it was built for)
- gnu-time (optional — `build.sh` only uses it to time the build)

C++ libraries — fmt, simdjson, pybind11, range-v3, xlnt, xxHash, alglib, lexy — are
vendored as meson wraps in [`subprojects/`](subprojects/) and fetched during `meson setup`;
they need no separate install.

The Python package `py/ae` is pure-stdlib: there are no third-party Python dependencies.

## Installing dependencies on macOS

- install homebrew https://brew.sh
- brew install meson ninja libomp cmake brotli zlib xz catch2 cairo pkgconf python@3.14
- optional: brew install gnu-time

> **Apple Silicon:** use `./build.sh` (below); the full native-arm64 toolchain background (Python 3.14, Apple Clang) is in [`CLAUDE.md`](CLAUDE.md). Do **not** use `./mk`. Do **not** `brew install llvm`; Homebrew LLVM is incompatible with the vendored `lexy` subproject. Apple Clang (`/usr/bin/clang++`) is the correct compiler.

## Installing dependencies on Ubuntu

> **Untested** — nobody currently builds ae on Linux; this list is derived from
> `meson.build`, not from a verified build.

- sudo apt install g++-11 ninja-build cmake pkg-config python3-dev libbrotli-dev liblzma-dev zlib1g-dev libbz2-dev libcairo2-dev
  (with g++, OpenMP comes with the compiler; with clang also install `libomp-dev`)

- meson must be 1.4 or newer (check with `meson --version`); distribution packages are
  often older, in which case: `pip3 install --user 'meson>=1.4'`

- cmake must be 3.18 or newer (check with `cmake --version`); if the distribution's is
  older, install a current one with `pip3 install --user cmake`.

- catch2 is left to the vendored wrap; do not install a distribution catch2 v2 package, which
  meson would find and prefer.

## Build

On macOS/Apple Silicon, use the self-checking build script — it runs preflight
checks, generates the meson native file, configures, compiles, and verifies:

```sh
./build.sh          # configure (if needed) + compile; leaves build/ -> build-py314/
./build.sh check    # run preflight checks only (no build)
./build.sh -h       # all subcommands (clean, reconfigure, test)
```

`build.sh` uses **Apple Clang** (`/usr/bin/clang++`) and the Homebrew Python 3.14 —
do **not** `brew install llvm` (Homebrew LLVM is incompatible with the vendored `lexy`
subproject). It writes a `.build-native.ini` meson native file (gitignored). Override
the interpreter/compiler/build-dir with the `AE_PYTHON` / `AE_CXX` / `AE_BUILD_DIR`
environment variables. Full toolchain background is in [`CLAUDE.md`](CLAUDE.md).

> The legacy `./mk` script assumes Homebrew LLVM and does **not** work on the current
> Apple-Clang / Python-3.14 toolchain — prefer `./build.sh`.

## Use

After building, source the environment file to set `AE_ROOT`, `PYTHONPATH`
(so `import ae_backend` and the `bin/` tools work without per-command prefixes), and,
if the sibling `../acmacs-data` and `../whocc-tables` are present, the runtime data
variables (`LOCDB_V2`, `HIDB_V5`, `SEQDB_V4`, `AC_CLADES_JSON_V2`, `WHOCC_TABLES_DIR`):

```sh
source ae-env.sh
chart-relax -n 100 input.ace output.ace     # bin/ is now on PATH
```

Set `ACMACS_DATA=/path/to/acmacs-data` before sourcing if that repo lives elsewhere.
