#!/usr/bin/env zsh
# Wire up the ae arm64 / Python 3.10 environment and run export_interactive.py.
# All args are forwarded to the exporter.  Example:
#   ./run.sh --tree <h3.asr.tjz> --chart vidrl=<styled.ace> --subtype "A(H3N2)" --assay HI --out data/h3-hi.html
set -e
AE=/Users/sarahjames/AC/eu/ae
# acmacs-data carries semantic_clades.py (canonical clade palette, used by E1)
export PYTHONPATH="${AE}/build-arm64:${AE}/py:/Users/sarahjames/AC/eu/acmacs-data${PYTHONPATH:+:${PYTHONPATH}}"
PY="/Library/Frameworks/Python.framework/Versions/3.10/bin/python3"
HERE="${0:A:h}"
exec arch -arm64 "$PY" "${HERE}/export_interactive.py" "$@"
