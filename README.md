# Acmacs-E

## Dependencies (general description)

- Apple Clang (macOS, currently clang 21) / clang-14+ / g++-11
- ninja
- meson 1.4+ (needed for the Python 3.14 build; 1.11.1 in use — meson 1.1.0 fails because Python 3.14 removed `distutils`)
- cmake 3.18+ (to build lexy)
- libomp
- brotli
- zlib
- libbz2
- liblzma
- catch2

## Installing dependencies on macOS

- install homebrew https://brew.sh
- brew install meson ninja libomp cmake brotli zlib xz gnu-time catch2

> **Apple Silicon:** the authoritative native-arm64 build (Python 3.14, Apple Clang) is documented in [`CLAUDE.md`](CLAUDE.md) — use it rather than `./mk`. Do **not** `brew install llvm`; Homebrew LLVM is incompatible with the vendored `lexy` subproject. Apple Clang (`/usr/bin/clang++`) is the correct compiler.

## Installing dependencies on Ubuntu

- sudo apt install g++-11 ninja-build meson cmake libbrotli-dev liblzma-dev

- Check version of meson: meson --version
  If version older than 0.60: pip3 install --user meson

- Check version of cmake: cmake --version
  If version is older than 3.18: ?

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
`numpy` is an additional runtime dependency of the kateri move→relax flow —
`/opt/homebrew/bin/python3 -m pip install --user --break-system-packages numpy`.
