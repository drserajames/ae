# Per-report skeleton — bootstrap a report against `ae.report`

Copy these files into a report working dir and edit the placeholders. They encode the
per-report adaptation that was **validated end-to-end** (a real chart → `chart_modifier`
styling → kateri → a map PDF matching the known-good reference). See
[`../MIGRATION.md`](../MIGRATION.md).

## Files

| file | goes where | edit each |
|------|-----------|-----------|
| `conference_data.py` | report dir | season — subclasses `ae.report.conference_data_base.ConferenceData` |
| `h1_chart_modifier.py` | report dir | season — subtype modifier; **mixes in the concrete `ConferenceData`** |
| `serology.py` | report dir | season — serology antigen table |
| `0do` | each map dir (`h1-cdc/`, …) | per map — the `Downloaded_ChartModifier` overrides |

## The one non-obvious wiring

The engine's `ChartModifier` inherits the **base** `ConferenceData` (interface stubs).
So a report's subtype modifier must inherit **both** the engine class and the report's
**concrete** `ConferenceData`:

```python
class H1_ChartModifier(ae.report.chart_modifier.ChartModifier, conference_data.ConferenceData):
    ...
```

(MRO: `… → ChartModifier → ConferenceData(concrete) → ConferenceData(base) → VcmDirs`, so
`self.conferencence_date()`/`time_series()` resolve to the concrete report values.)

## Runtime needs

- `PYTHONPATH` = ae `py/` (for `ae.report`) + the report dir + **acmacs-data**
  (`semantic_clades` / `semantic_vaccines`).
- env: `$HIDB_V5`, `$LOCDB_V2`, `$WHOCC_TABLES_DIR`; the `kateri` executable on PATH (export).
- Python 3.10 (for `ae_backend`).

## Commands (`./0do <cmd>`)

`download` → `populate` → `prestyle` → (`adjust`, still AD) → `style` → `export`.
Figures: antigenic maps via kateri (`export`), stat via `ae.report.stat`/`stat_tables`,
geographic via `ae.report.geographic.make_geo`, trees via `ae.report.trees.make_trees`.

> Use **synthetic** placeholders (`A(H1N1)/<CITY>/<N>/<YYYY>`) in anything committed to
> `ae`; real strain names / data stay in the report dir only.
