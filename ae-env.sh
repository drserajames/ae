# ae-env.sh — set up the environment to USE ae after building.
#
#   source ae-env.sh
#
# Sets AE_ROOT and PYTHONPATH so the bin/ tools and `import ae_backend` work
# without per-command PYTHONPATH= prefixes. If the sibling reference-data repo
# (../acmacs-data) and WHO CC tables (../whocc-tables) are present, wires the
# runtime data env vars too; otherwise prints a hint and leaves them unset.
#
# Safe to source from bash or zsh. Does not `exit` (it is meant to be sourced).

# --- locate this script's directory (works sourced from bash or zsh) ---
if [ -n "${BASH_SOURCE:-}" ]; then
    _ae_src="${BASH_SOURCE[0]}"
elif [ -n "${ZSH_VERSION:-}" ]; then
    _ae_src="${(%):-%x}"
else
    _ae_src="$0"
fi
AE_ROOT="$(cd "$(dirname "$_ae_src")" && pwd)"
export AE_ROOT
unset _ae_src

# --- PYTHONPATH: build/ (native ae_backend .so) + py/ (the `ae` package) ---
# bin/chart-* do a bare `import ae_backend` and `from ae... import ...`, so both
# dirs must be on PYTHONPATH. AE_ROOT-based tools also read $AE_ROOT directly.
if ! ls "$AE_ROOT"/build/ae_backend.*.so >/dev/null 2>&1; then
    printf '[ae-env] note: no built ae_backend under %s/build — run ./build.sh first.\n' "$AE_ROOT" >&2
fi
case ":${PYTHONPATH:-}:" in
    *":$AE_ROOT/build:"*) ;;   # already present
    *) export PYTHONPATH="$AE_ROOT/build:$AE_ROOT/py${PYTHONPATH:+:$PYTHONPATH}" ;;
esac

# --- put bin/ on PATH for convenience ---
case ":${PATH:-}:" in
    *":$AE_ROOT/bin:"*) ;;
    *) export PATH="$AE_ROOT/bin:$PATH" ;;
esac

# --- reference data (optional) --------------------------------------------
# LOCDB_V2 / AC_CLADES_JSON_V2 point at FILES; HIDB_V5 / SEQDB_V4 at DIRECTORIES.
_ae_data="${ACMACS_DATA:-$AE_ROOT/../acmacs-data}"
if [ -d "$_ae_data" ]; then
    _ae_data="$(cd "$_ae_data" && pwd)"
    [ -f "$_ae_data/locationdb.json.xz" ] && export LOCDB_V2="$_ae_data/locationdb.json.xz"
    [ -f "$_ae_data/clades.json" ]        && export AC_CLADES_JSON_V2="$_ae_data/clades.json"
    # HIDB_V5 is the directory holding hidb5.{h1,h3,b}.json.xz
    [ -f "$_ae_data/hidb5.h3.json.xz" ]   && export HIDB_V5="$_ae_data"
    # SEQDB_V4 is the directory holding the seqdb*.v4.json.xz files
    [ -f "$_ae_data/seqdb-h3.v4.json.xz" ] && export SEQDB_V4="$_ae_data"
else
    printf '[ae-env] note: reference data (%s) not found — LOCDB_V2/HIDB_V5/SEQDB_V4/AC_CLADES_JSON_V2 left unset.\n' "$_ae_data" >&2
    printf '[ae-env]       clone acmacs-data beside this checkout, or set ACMACS_DATA=/path/to/acmacs-data before sourcing.\n' >&2
fi
unset _ae_data

# --- WHO CC assay tables (optional; needed only by whocc-* ingestion tools) ---
_ae_whocc="${WHOCC_TABLES_DIR:-$AE_ROOT/../whocc-tables}"
if [ -d "$_ae_whocc" ]; then
    export WHOCC_TABLES_DIR="$(cd "$_ae_whocc" && pwd)"
fi
unset _ae_whocc

printf '[ae-env] AE_ROOT=%s\n' "$AE_ROOT" >&2
