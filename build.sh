#! /usr/bin/env bash
#
# build.sh — reproducible native build for ae (Acmacs-E)
#
# Replaces the stale `./mk` path (which assumes Homebrew LLVM and does not work on
# the current Apple-Clang / Python-3.14 toolchain). This script encodes the working
# recipe documented in CLAUDE.md, runs preflight checks that fail early with an
# actionable message, generates the meson native file, configures, compiles, and
# verifies the result.
#
# Usage:
#   ./build.sh              # configure (if needed) + compile the default build
#   ./build.sh check        # run preflight checks only (no build)
#   ./build.sh clean        # remove the build directory
#   ./build.sh reconfigure  # wipe and re-run meson setup from scratch
#   ./build.sh test         # run the meson test suite
#
# Override defaults via environment:
#   AE_BUILD_DIR   build directory name          (default: build-py314)
#   AE_PYTHON      python3 interpreter for the ext (default: /opt/homebrew/bin/python3.14)
#   AE_CXX/AE_CC   C++/C compiler                 (default: /usr/bin/clang++ , /usr/bin/clang)
#   AE_BREW        homebrew binary                (default: /opt/homebrew/bin/brew)
#
set -euo pipefail

AE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$AE_ROOT"

BUILD_DIR="${AE_BUILD_DIR:-build-py314}"
PY="${AE_PYTHON:-/opt/homebrew/bin/python3.14}"
CXX_BIN="${AE_CXX:-/usr/bin/clang++}"
CC_BIN="${AE_CC:-/usr/bin/clang}"
BREW="${AE_BREW:-/opt/homebrew/bin/brew}"
NATIVE_FILE="$AE_ROOT/.build-native.ini"   # generated; gitignored

# Homebrew formulae the build needs (system deps; C++ libs come via meson wraps).
BREW_FORMULAE=(meson ninja libomp cmake brotli zlib xz catch2 cairo)

# ----------------------------------------------------------------------
say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

# ----------------------------------------------------------------------
# Wrap a command in `arch -arm64` on Apple Silicon so the whole toolchain
# spawns arm64 clang. Apple Clang inherits its parent process architecture;
# an x86_64 meson/ninja silently produces x86_64 binaries even on an arm64 Mac.
run_native() {
    if [[ "$(uname -s)" == "Darwin" && "$(uname -m)" == "arm64" ]]; then
        arch -arm64 "$@"
    else
        "$@"
    fi
}

# ----------------------------------------------------------------------
# meson downloads the vendored subprojects (wraps) over HTTPS using the build
# Python's urllib. Homebrew's python@3.14 ships no CA bundle, so verification
# fails with CERTIFICATE_VERIFY_FAILED. Resolve a usable bundle to export as
# SSL_CERT_FILE. Prints the path, or nothing if none found.
ca_bundle() {
    if [[ -n "${SSL_CERT_FILE:-}" && -f "$SSL_CERT_FILE" ]]; then
        printf '%s\n' "$SSL_CERT_FILE"; return
    fi
    local certifi; certifi="$("$PY" -c 'import certifi;print(certifi.where())' 2>/dev/null || true)"
    if [[ -n "$certifi" && -f "$certifi" ]]; then printf '%s\n' "$certifi"; return; fi
    local brew_ca; brew_ca="$("$BREW" --prefix ca-certificates 2>/dev/null)/share/ca-certificates/cacert.pem"
    if [[ -f "$brew_ca" ]]; then printf '%s\n' "$brew_ca"; return; fi
    [[ -f /etc/ssl/cert.pem ]] && printf '%s\n' /etc/ssl/cert.pem
}

# ----------------------------------------------------------------------
preflight() {
    say "Preflight checks"

    local os arch_
    os="$(uname -s)"; arch_="$(uname -m)"
    if [[ "$os" != "Darwin" || "$arch_" != "arm64" ]]; then
        warn "This script targets macOS/arm64 (Apple Silicon). Detected: $os/$arch_."
        warn "Linux builds are only nominally supported (g++-11); expect to adapt this script."
    fi

    # Compiler: must be Apple Clang, NOT Homebrew LLVM (too new for vendored lexy).
    [[ -x "$CXX_BIN" ]] || die "C++ compiler not found: $CXX_BIN  (set AE_CXX=…)"
    if ! "$CXX_BIN" --version 2>/dev/null | grep -qi "Apple clang"; then
        warn "$CXX_BIN is not Apple Clang. Homebrew LLVM is known to break the vendored 'lexy' subproject."
        warn "Use /usr/bin/clang++ (Apple Clang). Continuing, but the build may fail."
    fi

    # Python interpreter (CPython extension is ABI-locked to this minor version).
    [[ -x "$PY" ]] || die "Python not found: $PY  (set AE_PYTHON=…, e.g. brew install python@3.14)"
    local pyver; pyver="$("$PY" -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
    say "Python for ae_backend: $PY (CPython $pyver) — the .so is ABI-locked to this minor version"

    # Homebrew + formulae.
    [[ -x "$BREW" ]] || die "Homebrew not found: $BREW. Install from https://brew.sh (set AE_BREW=…)"
    local missing=()
    for f in "${BREW_FORMULAE[@]}"; do
        "$BREW" --prefix "$f" >/dev/null 2>&1 || missing+=("$f")
    done
    if (( ${#missing[@]} )); then
        die "Missing Homebrew formulae: ${missing[*]}
     Install with:  $BREW install ${missing[*]}"
    fi

    # meson >= 1.4 (Python 3.14 removed distutils; meson 1.1.0 fails).
    local meson_bin; meson_bin="$("$BREW" --prefix meson)/bin/meson"
    [[ -x "$meson_bin" ]] || meson_bin="meson"
    local mv; mv="$("$meson_bin" --version 2>/dev/null || echo 0)"
    # ok when 1.4 sorts before (or equals) $mv, i.e. $mv >= 1.4
    if ! printf '1.4\n%s\n' "$mv" | sort -V -C; then
        die "meson $mv is too old (need >= 1.4 for Python 3.14; distutils was removed). Try: $BREW upgrade meson"
    fi
    say "meson $mv, ninja $("$("$BREW" --prefix ninja)/bin/ninja" --version 2>/dev/null || echo '?')"

    command -v gtime >/dev/null 2>&1 || warn "gtime (brew install gnu-time) not found — build timing will be skipped."
}

# ----------------------------------------------------------------------
write_native_file() {
    local brotli_prefix; brotli_prefix="$("$BREW" --prefix brotli)"
    local ninja_bin; ninja_bin="$("$BREW" --prefix ninja)/bin/ninja"
    say "Writing meson native file: $NATIVE_FILE"
    cat > "$NATIVE_FILE" <<EOF
# Auto-generated by build.sh — do not edit by hand, do not commit.
[binaries]
c       = '$CC_BIN'
cpp     = '$CXX_BIN'
python3 = '$PY'
ninja   = '$ninja_bin'

[properties]
pkg_config_libdir = '$brotli_prefix/lib/pkgconfig'
EOF
}

# ----------------------------------------------------------------------
configure() {
    write_native_file
    local ssl; ssl="$(ca_bundle)"
    if [[ -n "$ssl" ]]; then
        say "Using CA bundle for wrap downloads: $ssl"
    else
        warn "No CA bundle found — meson wrap downloads may fail with CERTIFICATE_VERIFY_FAILED."
        warn "Install certs (brew install ca-certificates) or export SSL_CERT_FILE=/path/to/cacert.pem."
    fi
    say "meson setup $BUILD_DIR"
    # CMAKE_POLICY_VERSION_MINIMUM: arm64 Homebrew CMake is 4.x, which rejects the
    # cmake_minimum_required(<3.5) declared by vendored lexy's doctest.
    # PKG_CONFIG_PATH: brotli is keg-only-ish; make its .pc visible to pkg-config.
    # SSL_CERT_FILE: Homebrew python@3.14 has no CA bundle; meson downloads wraps over HTTPS.
    CMAKE_POLICY_VERSION_MINIMUM=3.5 \
    PKG_CONFIG_PATH="$("$BREW" --prefix brotli)/lib/pkgconfig" \
    SSL_CERT_FILE="$ssl" \
        run_native "$("$BREW" --prefix meson)/bin/meson" setup "$BUILD_DIR" \
            --native-file "$NATIVE_FILE" \
            -Doptimization=3 -Ddebug=true
}

compile() {
    local ninja_bin; ninja_bin="$("$BREW" --prefix ninja)/bin/ninja"
    say "Compiling ($BUILD_DIR)"
    # Build an explicit argv: [gtime] [arch -arm64] ninja -C build.  gtime must
    # exec a real binary, so 'arch' (not the run_native shell function) goes here.
    local -a cmd=()
    command -v gtime >/dev/null 2>&1 && cmd+=(gtime)
    if [[ "$(uname -s)" == "Darwin" && "$(uname -m)" == "arm64" ]]; then
        cmd+=(arch -arm64)
    fi
    cmd+=("$ninja_bin" -C "$BUILD_DIR")
    CMAKE_POLICY_VERSION_MINIMUM=3.5 "${cmd[@]}"
}

verify() {
    say "Verifying build"
    local so; so="$(ls "$BUILD_DIR"/ae_backend.*.so 2>/dev/null | head -1 || true)"
    [[ -n "$so" ]] || die "ae_backend .so not found in $BUILD_DIR — build did not complete."
    file "$so" | grep -q arm64 || warn "$so is not arm64 — check that meson/ninja ran under arch -arm64."
    if PYTHONPATH="$BUILD_DIR" "$PY" -c 'import ae_backend' 2>/dev/null; then
        say "OK: '$so' imports cleanly under $PY"
    else
        warn "ae_backend built but failed to import under $PY. Run: PYTHONPATH=$BUILD_DIR $PY -c 'import ae_backend'"
    fi
}

link_default() {
    # Point build/ at the just-built dir (idempotent). Never rm -rf an existing dir.
    if [[ -L build || ! -e build ]]; then
        ln -sfn "$BUILD_DIR" build
        say "build -> $BUILD_DIR"
    else
        warn "'build' exists and is not a symlink; leaving it untouched."
    fi
}

# ----------------------------------------------------------------------
do_build() {
    preflight
    if [[ -f "$BUILD_DIR/meson-private/coredata.dat" ]]; then
        say "$BUILD_DIR already configured — recompiling only (use './build.sh reconfigure' to wipe)."
    else
        configure
    fi
    compile
    verify
    link_default
    say "Done. Next:  source ae-env.sh   then e.g.   chart-relax -n 100 in.ace out.ace"
}

case "${1:-build}" in
    build)        do_build ;;
    check)        preflight; say "Preflight OK — toolchain and dependencies satisfied." ;;
    reconfigure)  rm -rf "$BUILD_DIR"; do_build ;;
    clean)        say "Removing $BUILD_DIR"; rm -rf "$BUILD_DIR" ;;
    test)         run_native "$("$BREW" --prefix meson)/bin/meson" test -C "$BUILD_DIR" --print-errorlogs ;;
    -h|--help)    sed -n '2,30p' "$0" ;;
    *)            die "Unknown argument: $1  (try -h)" ;;
esac
