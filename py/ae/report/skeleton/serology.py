"""
Per-season serology antigens — COPY + edit. Same interface as acmacs-data's
`semantic_clades` (keyed by subtype). Use synthetic placeholders here; the real
table lives in the report dir, never committed to ae.
"""

from ae.utils.org import org_table_to_dict

sData = {
    "A(H1N1)": org_table_to_dict("""
| name                       | passage | comment |
|----------------------------+---------+---------|
| A(H1N1)/<CITY>/<N>/<YYYY>  | cell    |         |
"""),
}

def semantic_attribute_data_for_subtype(subtype: str) -> dict:
    return {"serology": sData.get(subtype, [])}

def semantic_plot_spec_data_for_subtype(subtype: str) -> dict:
    return {}
