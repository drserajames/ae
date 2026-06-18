"""
Phylogenetic-tree PDFs for the report's `phylogenetic_tree` pages.

The report-side glue (mirrors `geographic.make_geo` / `stat.make_stat_json`): for
each subtype, translate the report's acmacs-tal settings-v3 `.tal` config into
tal-draw's JSON schema (via `ae.tal.settings_v3`) and run **`tal-draw`** on the
tree file (`.tjz` / `tree.json[.xz]`) to produce the `<…>.pdf` the report embeds.

This replaces the AD `tal -s <settings.tal> <tree.tjz> <out.pdf>` invocation that
the report's `tree/0do` used. tal-draw + the `.tal`→schema translation are the
TAL subsystem's (`cc/tal`, `py/ae/tal`); a `.tal` that uses features the
translator doesn't cover yet emits warnings and those bits are skipped.
"""

import json
import lzma
import shutil
import subprocess
import tempfile
from pathlib import Path

# ----------------------------------------------------------------------


def _tree_title(tree_file: Path) -> str | None:
    """Subtype/lineage title string for the tree, matching AD's
    ``{virus-type/lineage}`` substitution (acmacs-tal settings.cc): the virus
    type alone (e.g. ``A(H3N2)``, ``A(H1N1)``) unless it is B with a lineage, in
    which case ``B/`` + the lineage's first three letters capitalised (``B/Vic``).
    Reads only the small JSON header of the phylogenetic-tree-v3 file."""
    try:
        with open(tree_file, "rb") as fh:
            magic = fh.read(6)
            fh.seek(0)
            raw = lzma.open(fh).read(4096) if magic[:1] == b"\xfd" else fh.read(4096)
    except (OSError, lzma.LZMAError):
        return None
    text = raw.decode("utf-8", "replace")
    import re
    v = re.search(r'"v"\s*:\s*"([^"]*)"', text)
    if not v:
        return None
    virus_type = v.group(1)
    l = re.search(r'"l"\s*:\s*"([^"]*)"', text)
    lineage = l.group(1) if l else ""
    if virus_type != "B" or not lineage:
        return virus_type
    return f"{virus_type}/{lineage[:3].capitalize()}"

# ----------------------------------------------------------------------

def make_tree(tree_file, settings, output_pdf, defines: dict | None = None,
              size: int | None = None, tal_draw: str | None = None) -> Path:
    """Render one tree PDF. *settings* is an acmacs-tal `.tal` config (translated
    to the tal-draw schema) or a tal-draw JSON file. *defines* are `-D name=value`
    overrides for `.tal` `$variables`."""
    tree_file, output_pdf = Path(tree_file), Path(output_pdf)
    tal_draw = tal_draw or _resolve_tal_draw()
    settings = Path(settings)

    if settings.suffix == ".tal":
        from ae.tal import settings_v3
        schema, warnings = settings_v3.load_tal(settings, defines=defines)
        for w in warnings:
            print(f">>> tree {output_pdf.name}: .tal warning: {w}", file=__import__("sys").stderr)
        # AD prints the subtype/lineage as a top-left title (conf/tal.json
        # `{"N":"title","text":"{virus-type/lineage}"}`); the report `.tal`s
        # don't carry a title module, so derive it from the tree header.
        if not schema.get("title"):
            title = _tree_title(tree_file)
            if title:
                schema["title"] = title
        schema_file = output_pdf.with_suffix(".tal-schema.json")
        schema_file.write_text(json.dumps(schema))
        settings_arg = schema_file
    else:
        settings_arg = settings

    cmd = [tal_draw, f"--settings={settings_arg}", str(tree_file), str(output_pdf)]
    if size:
        cmd.append(str(size))
    subprocess.check_call(cmd)
    return output_pdf


def make_trees(specs: list[tuple], force: bool = False, tal_draw: str | None = None) -> list[Path]:
    """Render several tree PDFs. *specs* is a list of
    ``(tree_file, settings, output_pdf[, defines])`` tuples."""
    tal_draw = tal_draw or _resolve_tal_draw()
    outputs = []
    for spec in specs:
        tree_file, settings, output_pdf = spec[0], spec[1], spec[2]
        defines = spec[3] if len(spec) > 3 else None
        if not force and Path(output_pdf).exists():
            outputs.append(Path(output_pdf))
            continue
        outputs.append(make_tree(tree_file, settings, output_pdf, defines=defines, tal_draw=tal_draw))
    return outputs


def _resolve_tal_draw() -> str:
    found = shutil.which("tal-draw")
    if found:
        return found
    build = Path(__file__).resolve().parents[3] / "build" / "tal-draw"
    return str(build) if build.exists() else "tal-draw"
