#!/usr/bin/env zsh
# Wire up the ae arm64 environment (current build/, Homebrew python3) and run export_interactive.py.
# All args are forwarded to the exporter.  Example:
#   ./run.sh --tree <h3.asr.tjz> --chart vidrl=<styled.ace> --subtype "A(H3N2)" --assay HI --out data/h3-hi.html
set -e
HERE="${0:A:h}"          # …/ae/interactive  (this script's dir — no absolute path baked in)
AE="${HERE:h}"           # …/ae              (the ae checkout this run.sh lives in)
# acmacs-data carries semantic_clades.py (canonical clade palette, used by E1); it sits
# beside the ae checkout, so derive it relative to AE rather than hard-coding a home path.
export PYTHONPATH="${AE}/build:${AE}/py:${AE:h}/acmacs-data${PYTHONPATH:+:${PYTHONPATH}}"
# Use whatever build/ points at (build-py314 today) rather than naming a Python version.
# The interpreter must match that extension; override it with AE_PYTHON. Never fall back to a
# bare python3 from PATH: /usr/local/bin/python3 is x86_64 and cannot import ae_backend.
PY="${AE_PYTHON:-/opt/homebrew/bin/python3}"

# Fail clearly on an interpreter/extension mismatch, which otherwise surfaces as a bare
# ModuleNotFoundError: No module named 'ae_backend'.
sos=( "${AE}"/build/ae_backend.cpython-*-darwin.so(N) )
if (( ${#sos} != 1 )); then
    print -u2 "run.sh: expected one ae_backend.cpython-*-darwin.so in ${AE}/build, found ${#sos}"
    exit 1
fi
so_ver="${${sos[1]:t}#ae_backend.cpython-}"; so_ver="${so_ver%%-*}"
py_ver="$(arch -arm64 "$PY" -c 'import sys; print(f"{sys.version_info[0]}{sys.version_info[1]}")')" || {
    print -u2 "run.sh: cannot run interpreter ${PY} (set AE_PYTHON)"
    exit 1
}
if [[ "$py_ver" != "$so_ver" ]]; then
    print -u2 "run.sh: ${PY} is cpython-${py_ver}, but ${sos[1]:A} is built for cpython-${so_ver}; set AE_PYTHON to a matching arm64 interpreter"
    exit 1
fi

exec arch -arm64 "$PY" "${HERE}/export_interactive.py" "$@"
