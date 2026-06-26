#!/usr/bin/env zsh
# Wire up the ae arm64 / Python 3.10 environment and run export_interactive.py.
# All args are forwarded to the exporter.  Example:
#   ./run.sh --tree <h3.asr.tjz> --chart vidrl=<styled.ace> --subtype "A(H3N2)" --assay HI --out data/h3-hi.html
set -e
HERE="${0:A:h}"          # …/ae/interactive  (this script's dir — no absolute path baked in)
AE="${HERE:h}"           # …/ae              (the ae checkout this run.sh lives in)
# acmacs-data carries semantic_clades.py (canonical clade palette, used by E1); it sits
# beside the ae checkout, so derive it relative to AE rather than hard-coding a home path.
export PYTHONPATH="${AE}/build-arm64:${AE}/py:${AE:h}/acmacs-data${PYTHONPATH:+:${PYTHONPATH}}"
PY="/Library/Frameworks/Python.framework/Versions/3.10/bin/python3"
exec arch -arm64 "$PY" "${HERE}/export_interactive.py" "$@"
