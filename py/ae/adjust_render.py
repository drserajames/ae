"""
ae.adjust_render — draw the adjust stage's review snapshots.

This is the rendering half of `ae.adjust`'s `Slot` (see `py/ae/report/MIGRATION.md`
Stage B, step 4). An `adjust/0do` script's loop is *select -> look -> re-cut the
polygon*: `slot.select_antigens(..., modify={"outline": "magenta", ...})` marks what a
polygon caught, and the snapshot that follows is how the analyst (or an agent) checks it
caught the right points.

AD did this through `acmacs.ChartDraw`, which edits the **legacy** per-point plot spec and
draws it. ae's styling is the **semantic style system** (`c["R"]` named styles), so the
port is a translation, not a rename:

  * an AD `modify(...)` becomes one semantic style modifier per selected point,
    `selector={"!i": <per-side index>}` + `only="antigens"`/`"sera"` — the same idiom
    `ae.semantic.select_mark` uses;
  * they are collected into one throw-away named style (`"-adjust"` by default) whose
    first modifier is `parent=<base style>`, so the snapshot starts from the chart's own
    clade colouring (the ae-native successor of AD's `color_by_clade` mapi marking);
  * the style is rendered headlessly by `ae_backend.map_draw.export_styled_map`, the same
    native renderer the report uses (`ae.report.map_renderer.NativeRenderer`).

**The working chart is never modified.** The style is built on a throw-away copy made by
round-tripping the chart's JSON through a temp file, so nothing a snapshot does can leak
into the slot's `99.ace`. The round trip goes through *uncompressed* JSON on purpose:
`Chart.write()` always xz-compresses, which costs ~14 s on the largest report chart, while
`Chart.export()` + a plain write is ~0.1 s, and `Chart(...)` sniffs the compression on the
way back in. A whole snapshot of the largest chart in the current report cycle
(12,737 antigens) takes well under a second.

**Not ported: drawing the polygon itself.** `slot.path(outline=...)` outlines the selection
polygon on AD's snapshot. ae has no polygon primitive above the Cairo surface — the
semantic style model (`cc/chart/v3/styles.hh`) has no path/figure/arrow element and
`cc/map-draw/styled-draw.cc` draws only points, serum circles, the grid, labels, the legend
and the title — so this needs new C++, not new Python. See `polygon_support_note()`.
"""
import os
import sys
import subprocess
import tempfile
from pathlib import Path

# ======================================================================
# AD `modify` kwargs -> ae semantic-style modifier kwargs
# ----------------------------------------------------------------------

#: AD's `slot.modify` signature (`acmacs_py/zero_do_5.py`), which is also the key set
#: allowed in a `select_antigens(modify={...})` dict.
AD_MODIFY_KEYS = ("fill", "outline", "outline_width", "show", "shape", "size", "aspect",
                  "rotation", "order", "label", "legend")

#: AD `PointLabel` key -> ae semantic label key. AD's `font` has no ae equivalent.
_LABEL_KEYS = {"show": "shown", "shown": "shown", "format": "text", "text": "text",
               "offset": "offset", "color": "color", "size": "size",
               "weight": "weight", "slant": "slant", "rotation": "rotation"}


def normalize_modify(kwargs: dict) -> dict:
    """Translate one AD `modify(...)` kwargs dict into `Style.add_modifier` kwargs.

    Most keys pass straight through — `fill`, `outline`, `outline_width`, `size`,
    `shape`, `aspect`, `rotation`, `show` are spelled the same on both sides, and ae's
    `point_shape` parses AD's shape names (`"circle"`, `"box"`, `"egg"`, `"uglyegg"`,
    `"triangle"`) because it switches on the first letter. Three need work:

    * `order` — AD takes `"raise"` / `"lower"`; ae takes `raise_=True` / `lower=True`.
    * `label` — AD's `PointLabel` dict (`show`, `format`, `offset`, `color`, `size`,
      `weight`, `slant`, `font`); ae's is `shown`, `text`, `offset`, `color`, `size`,
      `weight`, `slant`, `rotation`. `font` is dropped (no ae equivalent).
    * `legend` — AD's `PointLegend` dict (`format`, `show_if_none_selected`, `replace`,
      `show`); ae takes a legend row's text as a plain string. `format` becomes the text;
      the other three have no ae equivalent and are dropped.

    Unknown keys and dropped sub-keys are reported on stderr rather than raising, so a
    ported script runs and says what it lost.
    """
    out: dict = {}
    for key, value in kwargs.items():
        if value is None:
            continue
        if key in ("fill", "outline", "outline_width", "size", "shape", "aspect", "rotation", "show"):
            out[key] = value
        elif key == "order":
            order = str(value).lower()
            if order.startswith("r"):            # "raise"
                out["raise_"] = True
            elif order.startswith("l"):          # "lower"
                out["lower"] = True
            else:
                _warn(f"modify: unrecognized order {value!r} (expected 'raise' or 'lower')")
        elif key == "label":
            label = {}
            for lkey, lvalue in dict(value).items():
                if (mapped := _LABEL_KEYS.get(lkey)) is not None:
                    label[mapped] = lvalue
                else:
                    _warn(f"modify: label key {lkey!r} has no ae equivalent — dropped")
            if label:
                out["label"] = label
        elif key == "legend":
            legend = dict(value) if not isinstance(value, str) else {"format": value}
            if (text := legend.pop("format", None) or legend.pop("text", None)):
                out["legend"] = text
            if (priority := legend.pop("priority", None)) is not None:
                out["legend_priority"] = priority
            for leftover in legend:
                _warn(f"modify: legend key {leftover!r} has no ae equivalent — dropped")
        else:
            _warn(f"modify: unrecognized key {key!r} — dropped")
    return out


# ======================================================================
# the base style the snapshot starts from
# ----------------------------------------------------------------------

def default_base_style(chart=None, exported: bytes = None) -> str:
    """Pick the chart's own full clade-colouring style to draw the snapshot on top of.

    A report `prestyled.ace` carries a `c["R"]` block of named styles. The one that colours
    every antigen by clade with no date restriction is named `clades` (H1 charts) or
    `clades-v<N>` (charts with several clade-definition versions, where the highest N is
    the current one). Building blocks are prefixed `-`, and the `info-`/`-6m`/`-12m`
    variants are the report's other cuts, so none of those are candidates.

    Pass *exported* (the chart's JSON, as `Chart.export()` returns it) when you have it
    already — the style names are only readable through the JSON, because the pybind
    `SemanticStyles` iterator yields styles without their names.

    Returns `""` when the chart carries no such style — the renderer then falls back to its
    own default (kateri's: grey test antigens, transparent reference antigens and sera),
    which is what AD's `reset_plot_spec` produces anyway.
    """
    try:
        names = style_names(chart=chart, exported=exported)
    except Exception:                                        # pragma: no cover - defensive
        return ""
    if "clades" in names:
        return "clades"
    versioned = []
    for name in names:
        if name.startswith("clades-v") and name.count("-") == 1:
            try:
                versioned.append((int(name[len("clades-v"):]), name))
            except ValueError:
                pass
    if versioned:
        return max(versioned)[1]
    return ""


def style_names(chart=None, exported: bytes = None) -> list:
    "Names of the chart's `c[\"R\"]` named styles, in file order."
    import json
    if exported is None:
        exported = chart.export()
    return list(json.loads(exported)["c"].get("R", {}))


# ======================================================================
# building the throw-away snapshot style
# ----------------------------------------------------------------------

#: Name of the style the snapshot is rendered from. Leading `-` follows the report's
#: convention for a style that is a building block rather than a figure in its own right.
SNAPSHOT_STYLE = "-adjust"


def build_style(chart, entries, base_style: str = None, style_name: str = SNAPSHOT_STYLE,
                priority: int = 1000) -> str:
    """Put the accumulated *entries* onto *chart* as one named style and return its name.

    *entries* are what `ae.adjust.Slot` records — see `Slot.modify` / `Slot.path`:

        {"kind": "modify", "selected": [point_no, ...], "modifier": {ae kwargs}}
        {"kind": "path", ...}          # recorded, not drawn (see polygon_support_note)

    A `"modify"` entry becomes one modifier per selected point. `selected` holds **point**
    numbers in `ae.adjust`'s convention (a serum is `number_of_antigens + serum_no`), which
    is split back into a per-side index plus `only="antigens"`/`"sera"` because that is what
    the `"!i"` selector means. A selection covering *every* antigen (or every serum) — the
    `slot.modify(selected=slot.select_antigens(lambda ag: True), size=10)` idiom that opens
    most real adjust scripts — collapses to a single modifier with an empty selector, which
    is both faster and what a human would have written.

    Modifiers apply in order, so a later `modify` wins over an earlier one on the same
    point, exactly as successive `ChartDraw.modify` calls do in AD.
    """
    if base_style is None:
        base_style = default_base_style(chart)
    n_antigens = chart.number_of_antigens()
    n_sera = chart.number_of_sera()
    style = chart.styles()[style_name]
    style.remove_modifiers()
    style.priority = priority
    if base_style:
        style.add_modifier(parent=base_style)
    for entry in entries:
        if entry.get("kind") != "modify":
            continue
        modifier = entry.get("modifier") or {}
        if not modifier:
            continue
        antigens = sorted(no for no in entry.get("selected") or () if no < n_antigens)
        sera = sorted(no - n_antigens for no in entry.get("selected") or () if no >= n_antigens)
        for indexes, only, total in ((antigens, "antigens", n_antigens), (sera, "sera", n_sera)):
            if not indexes:
                continue
            if len(indexes) == total:
                style.add_modifier(selector={}, only=only, **modifier)
            else:
                for index in indexes:
                    style.add_modifier(selector={"!i": index}, only=only, **modifier)
    return style_name


# ======================================================================
# rendering
# ----------------------------------------------------------------------

def render(adjust, output, entries, base_style: str = None, width: float = 800.0,
           style_name: str = SNAPSHOT_STYLE, open_after: bool = False) -> Path:
    """Render *adjust*'s chart, styled by *entries*, to *output* (`.png` raster, else PDF).

    The chart is copied first (JSON round trip through a temp file), so the style exists
    only for the duration of this call and `slot.final_ace()` stays exactly what the
    adjust operations produced.
    """
    import ae_backend.chart_v3
    import ae_backend.map_draw

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ae-adjust-snapshot-") as tmpdir:
        exported = adjust.chart.export()
        if base_style is None:
            base_style = default_base_style(exported=exported)
        source = Path(tmpdir, "chart.json")
        source.write_bytes(exported)
        chart = ae_backend.chart_v3.Chart(source)
        name = build_style(chart, entries, base_style=base_style, style_name=style_name)
        styled = Path(tmpdir, "styled.json")
        styled.write_bytes(chart.export())
        ae_backend.map_draw.export_styled_map(styled, output, name, width, 0, "")
    if open_after:
        _open(output)
    return output


class SnapshotRenderer:
    """The default `ae.adjust.Slot.renderer`: draw the slot's snapshot with the native
    renderer.

    Called as `renderer(slot, path, png=bool, open=bool)` — the hook `Slot.plot` already
    defined. *width* is the page width in points, matching `ae.report.map_renderer`.
    Pass *base_style* to override the auto-detected clade style the snapshot is drawn on
    (`""` for the renderer's plain grey default).

    A failure to draw is reported and swallowed: a snapshot is a review artefact, and a
    chart with no projection (or a style that will not resolve) must not take down a script
    whose real product is `99.ace`.
    """

    def __init__(self, width: float = 800.0, base_style: str = None,
                 style_name: str = SNAPSHOT_STYLE):
        self.width = width
        self.base_style = base_style
        self.style_name = style_name

    def __call__(self, slot, path, png: bool = False, open: bool = False):
        "Draw `path`, plus a sibling `.png` when *png* (AD's `make_final_png` behaviour)."
        base_style = self.base_style if self.base_style is not None else getattr(slot, "base_style", None)
        outputs = [Path(path)]
        if png and Path(path).suffix.lower() != ".png":
            outputs.append(Path(path).with_suffix(".png"))
        for n, output in enumerate(outputs):
            try:
                render(slot.adjust, output, slot.styling, base_style=base_style,
                       width=self.width, style_name=self.style_name,
                       open_after=(open and n == 0))
            except Exception as err:
                _warn(f"{slot.slot_name}: snapshot {output.name} not drawn "
                      f"({type(err).__name__}: {err})")
                return None
            print(f">>> {output}", file=sys.stderr)
        return outputs[0]


# ======================================================================

def polygon_support_note() -> str:
    """Why `slot.path(outline=...)` draws nothing, in one paragraph — printed once per
    slot that asks for it, and quoted in the migration notes."""
    return ("slot.path(outline=…) cannot draw the polygon: ae has no polygon primitive "
            "above the Cairo surface. The semantic style model (cc/chart/v3/styles.hh) "
            "carries no path/figure element and cc/map-draw/styled-draw.cc draws only "
            "points, serum circles, grid, labels, legend and title, so this needs new C++ "
            "(a Style path element + export/import + a pybind kwarg + a draw call on the "
            "existing CairoPdf::path_negative_move), not new Python. The points the "
            "polygon caught ARE marked, by the modify= that normally accompanies it, so "
            "the select→look→re-cut loop works; only the outline is missing.")


def _warn(message: str):
    print(f">> {message}", file=sys.stderr)


def _open(path: Path):
    "Open a drawn snapshot in the desktop viewer, as AD's `open=True` does."
    try:
        if sys.platform == "darwin":
            subprocess.call(["open", str(path)])
        elif os.name == "posix":
            subprocess.call(["xdg-open", str(path)])
    except Exception as err:                                 # pragma: no cover - desktop only
        _warn(f"cannot open {path}: {err}")

# ======================================================================
