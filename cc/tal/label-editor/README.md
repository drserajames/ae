# tal MRCA aa-transition label editor

A small **WYSIWYG drag editor** for the curated **MRCA aa-transition labels** on a `tal-draw`
phylogenetic tree (the `draw-aa-transitions` `per-node` set — clade-defining substitution names
placed at MRCA nodes). An auto-placement algorithm already positions these labels into
whitespace; this tool is for **manual touch-up** of the cases the algorithm gets ugly: drag a
label to a prettier spot, Save, and the final `tal-draw` PDF reproduces it exactly.

**Scope:** only the curated `MrcaLabel` set. It does **not** touch the dense per-branch inode
transition labels, nor leaf `NodeText` labels.

---

## How it works

```
.tal ──load_tal()──▶ tal-draw schema (+ mrca_label_sidecar, image_size)
     ──tal-draw──────▶ tree.pdf + labels.json (geometry sidecar)  +  pdftoppm ─▶ backdrop.png
browser (editor.html): backdrop.png + draggable label overlay (from labels.json, device units)
     ──drag + Save──▶ POST /save ─▶ patch the source .tal per-node entry ─▶ re-render
```

A label is identified **not by node id** but as `MRCA(first, last)` of two leaf `seq_id`s the
entry records — so a manual nudge survives weekly tree rebuilds where node numbering changes.

### Offset semantics (exact, fs-independent)

The renderer places a **pinned** label so its text-box top-left sits at

```
box.x0 = anchor.x + offset.x * page.width
box.y0 = anchor.y + offset.y * page.height      (+y is DOWN, PDF device units)
```

where `anchor` is the MRCA branch node point. The editor inverts this exactly:

```
offset.x = (box.x0 - anchor.x) / page.width
offset.y = (box.y0 - anchor.y) / page.height
```

so a label dragged by Δ device units moves by exactly Δ in the regenerated PDF.

### Pinned vs auto

- An **un-pinned** label is auto-placed into whitespace (collision-avoiding, with a tether) —
  unchanged behaviour.
- A **pinned** label (one you dragged) is placed at its offset **and reserved as a fixed
  obstacle**; the remaining un-pinned labels still auto-place *around* it. Pinning some labels
  therefore reshuffles the auto labels (they re-optimise around the new obstacles) — by design.
  The auto solver is deterministic, so the only thing that moves auto labels is the set of pins.

---

## C++ / Python side (what this depends on)

Implemented in the `ae-tree` worktree:

| File | Change |
|------|--------|
| `cc/tal/draw-tree.hh` | `MrcaLabel.pinned`; `TreeDrawParameters.mrca_label_sidecar` |
| `cc/tal/draw-tree.cc` | pinned labels get a single offset-derived candidate + reserved box; auto search routes around them. Emits the `tal-mrca-labels/1` geometry sidecar |
| `cc/tal/settings.cc` | parse `pinned` + `mrca_label_sidecar` |
| `cc/tal/tal-draw-main.cc` | `--mrca-sidecar=PATH` flag (applied after `--settings`) |
| `py/ae/tal/settings_v3.py` | threads `pinned` from the per-node entry into the emitted `mrca_label` |

Rebuild `tal-draw` after a C++ change (no `meson.build` edit ⇒ no reconfigure):

```bash
cd ae-tree && export PATH="/opt/homebrew/bin:$PATH" PKG_CONFIG_PATH="/opt/homebrew/opt/brotli/lib/pkgconfig" CMAKE_POLICY_VERSION_MINIMUM=3.5
arch -arm64 /tmp/ae-py314-venv/bin/ninja -C build-py314 tal-draw
```

### Sidecar schema (`tal-mrca-labels/1`)

```json
{
  "schema": "tal-mrca-labels/1",
  "pdf": "tree.pdf", "image_size": 1000,
  "page": { "width": 648.6, "height": 1000.0 },   // PDF device units, origin top-left, +y DOWN
  "auto_place": true,
  "labels": [
    { "id": 0, "first": "<seq_id>", "last": "<seq_id>", "text": "I140K", "nlines": 1,
      "pinned": false,
      "anchor": { "x": 87.0, "y": 88.4 },          // branch node point (offset origin)
      "tether": { "x": 70.2, "y": 88.4 },          // leader target = mid of the node's horizontal edge
      "box": { "x0": 51.3, "y0": 88.2, "x1": 73.9, "y1": 92.7 },   // current placed box
      "offset": { "x": -0.055, "y": -0.0002 },     // reproduces box if pinned
      "color": "#4d4d4d", "fs": 9.5 }
  ]
}
```

### `.tal` write-back format

The matching active `draw-aa-transitions` `per-node` entry (keyed by `{first,last}`, matching
either `first`/`?first`) is patched **surgically** (text edit, relaxed-JSON formatting/comments
preserved; the disabled `?per-node` block is never touched):

```json
{ "pinned": true, "name": "I140K", "label": {"offset": [-0.12, 0.02], ...}, ... }
```

"Reset to auto" sets `"pinned": false` (the offset is then ignored and the label re-flows).

---

## Run

```bash
cd ae-tree/cc/tal/label-editor
python3 server.py --tal <path/to/x.tal> --tree <path/to/x.tjz> [--out DIR] \
                  [--image-size N] [-D name[=value] ...] [--dpi 150] [--port 8753]
```

- `--tal` is the file rendered **and patched on Save** — point it at the real run config you
  want to edit, e.g. `ac/results/ssm/<run>/tree/h3.after-2021.tal`.
- `--tree` is the matching tree (e.g. `…/tree/h3.asr.after-2021.tjz`).
- Outputs (pdf / png / sidecar / schema) go to `--out` (a temp dir by default) — **never** into
  the repo. Server binds `127.0.0.1` only.

A browser opens on the printed URL. Drag labels, hit **Save & re-render**, repeat.

### Editor controls

| Action | Effect |
|--------|--------|
| drag a label | reposition it → **pins** it |
| double-click a label / "auto" in the list | reset that label to auto-placement |
| scroll | zoom to cursor |
| Space-drag / right-drag / shift-scroll | pan |
| Fit | reset the view |
| Save & re-render | patch the `.tal`, re-run `tal-draw`, reload |

---

## Verification (h3, 2026-0223-ssm)

Round-trip on `h3.after-2021.tal` (44 curated labels) + `h3.asr.after-2021.tjz`:

- C++/Python suites green: `cc/tal/test/test-draw-tree.sh`, `test-aa-transitions.py`,
  `test-settings-v3.py`.
- Drag 3 labels → Save → re-render: each lands at its dragged position to **< 0.01 device units**
  (exact inverse), `pinned:true`; the untouched labels remain auto-placed (re-optimised around the
  pins). Two no-edit re-renders differ by **0.0** (auto-place is deterministic).
- HTTP round-trip verified (`GET /`, `/labels.json`, `/backdrop.png`; `POST /save`).

## Known limitations / deferred

- Pinning labels reshuffles the remaining auto labels (global re-optimisation around the new
  obstacles). Faithful to the design; a warm-started/incremental auto-place that minimises churn
  is a possible future refinement.
- Bracket-depth scanning of the `per-node` array assumes `seq_id`s / label names carry no `[`/`]`
  (true for influenza names).
- Requires `pdftoppm` (poppler) for the backdrop and a local Python 3 (stdlib only;
  `ae.tal.settings_v3` is pure-Python — no `ae_backend` needed).
```
