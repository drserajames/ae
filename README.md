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

./mk
meson compile -C build
