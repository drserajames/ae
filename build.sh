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
# Subproject bootstrap (fresh checkout / fresh worktree).
#
# meson populates subprojects/ from the .wrap files during `meson setup`. That
# needs two kinds of write that sandboxes protecting VCS metadata (agent
# sandboxes do) refuse *anywhere inside the project*:
#
#   * a git repository — lexy and range-v3 are [wrap-git], so meson runs
#     `git clone` directly into subprojects/, and git writes .git/config and
#     copies the template hooks into .git/hooks/ as it goes:
#         fatal: cannot copy '…/git-core/templates/hooks/commit-msg.sample' to
#                '…/subprojects/lexy/.git/hooks/commit-msg.sample': Operation not permitted
#     -> meson setup aborts with "Git command failed";
#   * a .gitmodules file — several [wrap-file] release tarballs contain one, and
#     meson's archive extraction dies on it:
#         ERROR: failed to unpack archive with error: [Errno 1] Operation not
#         permitted: '…/subprojects/xlnt-1.5.0/.gitmodules'
#
# Either way a fresh worktree cannot be configured at all; the manual workaround
# has been `rsync -a --exclude='.*'` from an already-populated checkout.
#
# Handle it here instead of asking for the sandbox to be widened: probe whether
# subprojects/ can take those writes and, if it cannot, let meson resolve every
# wrap into a throwaway project *outside* the tree (where the writes are allowed)
# and copy the resulting directories in, minus their dot-entries. All the wrap
# semantics — hashes, patch_directory overlays, patch_url, git revisions — stay
# with meson; we only relocate where the work happens.
#
# When the probe succeeds (normal, unsandboxed use) this is a no-op and meson's
# own wrap machinery does the work during `meson setup`, exactly as before.

# First uncommented "key = value" from a .wrap file.
wrap_value() {
    sed -n "s/^[[:space:]]*$2[[:space:]]*=[[:space:]]*//p" "$1" | head -1
}

# Copy the contents of one directory over another (tar, not rsync: tar is always
# present, rsync is not guaranteed on a stock macOS).
copy_tree() {
    ( cd "$1" && tar cf - . ) | ( cd "$2" && tar xf - )
}

meson_bin() {
    local m; m="$("$BREW" --prefix meson 2>/dev/null)/bin/meson"
    [[ -x "$m" ]] && printf '%s\n' "$m" || printf 'meson\n'
}

in_tree_subprojects_writable() {
    local probe="subprojects/.ae-write-probe.$$" ok=0
    rm -rf "$probe"
    mkdir -p "$probe"
    git init -q "$probe" >/dev/null 2>&1 || ok=1
    # 2>/dev/null first: a failing redirection is reported before later
    # redirections are applied, so the usual trailing form would still leak.
    ( : 2>/dev/null > "$probe/.gitmodules" ) || ok=1
    rm -rf "$probe"
    return $ok
}

subprojects_help() {
    printf '%s\n' \
        "     Populate subprojects/ by hand from an already-built checkout, e.g." \
        "       rsync -a --exclude='.*' /path/to/other/ae/subprojects/ $AE_ROOT/subprojects/" \
        "     then re-run ./build.sh."
}

# Names of the wrap directories that are not yet present, one per line.
missing_subprojects() {
    local wrap dir
    for wrap in subprojects/*.wrap; do
        [[ -f "$wrap" ]] || continue
        dir="$(wrap_value "$wrap" directory)"
        [[ -n "$dir" && ! -d "subprojects/$dir" ]] && printf '%s\n' "$dir"
    done
    return 0
}

bootstrap_subprojects() {
    local -a missing=()
    while IFS= read -r dir; do missing+=("$dir"); done < <(missing_subprojects)
    (( ${#missing[@]} )) || return 0
    in_tree_subprojects_writable && return 0   # normal case — meson setup handles it

    warn "This environment denies git-metadata writes (.git/config, .git/hooks, .gitmodules)"
    warn "under the project, so meson could not populate subprojects/ in place."
    say "Resolving wraps out-of-tree instead: ${missing[*]}"

    local scratch; scratch="$(mktemp -d "${TMPDIR:-/tmp}/ae-wrap-XXXXXX")"
    mkdir -p "$scratch/subprojects"
    printf "project('ae-wrap-bootstrap', 'cpp')\n" > "$scratch/meson.build"
    cp subprojects/*.wrap "$scratch/subprojects/"
    local d
    for d in packagefiles packagecache; do
        [[ -d "subprojects/$d" ]] && cp -R "subprojects/$d" "$scratch/subprojects/"
    done

    # Downloads here are occasionally truncated (a short read yields a hash
    # mismatch); meson only re-fetches what is still missing, so just retry.
    local attempt still
    for attempt in 1 2 3; do
        SSL_CERT_FILE="$(ca_bundle)" run_native "$(meson_bin)" subprojects download \
            --sourcedir "$scratch" --num-processes 1 || true
        still=0
        for dir in "${missing[@]}"; do [[ -d "$scratch/subprojects/$dir" ]] || still=1; done
        (( still )) || break
        warn "wrap download incomplete (attempt $attempt/3) — retrying"
    done

    for dir in "${missing[@]}"; do
        if [[ ! -d "$scratch/subprojects/$dir" ]]; then
            rm -rf "$scratch"
            die "could not download subproject '$dir' (no network, or a persistently bad download).
$(subprojects_help)"
        fi
        # Drop every dot-entry before copying in: the sandboxes that make this
        # bootstrap necessary are precisely the ones refusing .gitmodules /
        # .vscode / … writes, and no vendored subproject needs its dotfiles to
        # build. (The manual `rsync -a --exclude='.*'` workaround did the same.)
        find "$scratch/subprojects/$dir" -depth -name '.*' -exec rm -rf {} +
        rm -rf "subprojects/$dir"; mkdir -p "subprojects/$dir"
        if ! copy_tree "$scratch/subprojects/$dir" "subprojects/$dir"; then
            rm -rf "$scratch" "subprojects/$dir"
            die "could not populate subprojects/$dir.
$(subprojects_help)"
        fi
        say "  subprojects/$dir"
    done
    # Keep the downloaded tarballs so a later reconfigure needs no network.
    [[ -d "$scratch/subprojects/packagecache" ]] && {
        mkdir -p subprojects/packagecache
        copy_tree "$scratch/subprojects/packagecache" subprojects/packagecache || true
    }
    rm -rf "$scratch"
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
    bootstrap_subprojects
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
    if ! CMAKE_POLICY_VERSION_MINIMUM=3.5 \
         PKG_CONFIG_PATH="$("$BREW" --prefix brotli)/lib/pkgconfig" \
         SSL_CERT_FILE="$ssl" \
             run_native "$("$BREW" --prefix meson)/bin/meson" setup "$BUILD_DIR" \
                 --native-file "$NATIVE_FILE" \
                 -Doptimization=3 -Ddebug=true
    then
        die "meson setup failed — see $BUILD_DIR/meson-logs/meson-log.txt
     If it failed fetching a subproject (a 'Git command failed' or a download error):
$(subprojects_help)"
    fi
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
    if [[ -f "$BUILD_DIR/meson-private/coredata.dat" && -f "$BUILD_DIR/build.ninja" ]]; then
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
