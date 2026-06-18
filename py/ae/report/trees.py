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
import shutil
import subprocess
import tempfile
from pathlib import Path

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
