#! /usr/bin/env bash
#
# gen-stubs.sh — best-effort .pyi stub generation for the ae_backend extension.
#
# Invoked from meson.build as:
#   tools/gen-stubs.sh <python> <dir-containing-ae_backend.so> <output-dir>
#
# Stubs are a developer convenience (mypy / IDE completion); they are not part of
# the built library and nothing at runtime needs them. Generation must therefore
# never fail the build:
#
#   * mypy is optional and is frequently not installed at all;
#   * `stubgen` on PATH belongs to whichever interpreter happened to install mypy,
#     which is usually NOT the one this extension was built for. On this machine
#     it is the Python 3.10 one, and it cannot even start:
#         ImportError: dlopen(…/mypy/__init__.cpython-310-darwin.so): tried: …
#         (mach-o file, but is an incompatible architecture (have 'arm64',
#          need 'x86_64'))
#     Even if it did start it could not import a cpython-314 arm64 extension;
#   * a matching stubgen only works if it can import the freshly linked module,
#     hence the PYTHONPATH below.
#
# Anything that goes wrong is reported as a warning and the script still exits 0,
# so `ninja` (and ./build.sh, which runs under `set -e`) carries on to the arch
# and import verification. meson still gets the output directory it declared.
#
# Deliberately no `set -e`: a failure here is a warning, not an error.
set -uo pipefail

PY="${1:?usage: gen-stubs.sh <python> <module-dir> <output-dir>}"
MODULE_DIR="${2:?usage: gen-stubs.sh <python> <module-dir> <output-dir>}"
OUT="${3:?usage: gen-stubs.sh <python> <module-dir> <output-dir>}"

warn() { printf '\033[1;33m[warn]\033[0m gen-stubs: %s\n' "$*" >&2; }

# meson declared this directory as the target's output — it must exist even when
# no stubs get written.
mkdir -p "$OUT" || exit 0

run_stubgen() {
    PYTHONPATH="$MODULE_DIR${PYTHONPATH:+:$PYTHONPATH}" "$@" --package ae_backend --output "$OUT"
}

# Preferred: the mypy belonging to the interpreter the extension was built for —
# the only one that can import ae_backend (CPython extensions are ABI-locked per
# minor version, and this build is arm64-only).
if "$PY" -c 'import mypy.stubgen' >/dev/null 2>&1; then
    run_stubgen "$PY" -m mypy.stubgen && exit 0
    warn "'$PY -m mypy.stubgen' failed — skipping stub generation (build is unaffected)."
    exit 0
fi

# Fallback: stubgen on PATH. It may belong to a different interpreter or
# architecture, in which case it fails and we simply skip.
if command -v stubgen >/dev/null 2>&1; then
    run_stubgen stubgen && exit 0
    warn "'$(command -v stubgen)' could not generate stubs for this build — skipping."
    warn "It belongs to a different interpreter than $PY. To enable stubs:  $PY -m pip install mypy"
    exit 0
fi

warn "no mypy/stubgen found — skipping stub generation.  To enable:  $PY -m pip install mypy"
exit 0
