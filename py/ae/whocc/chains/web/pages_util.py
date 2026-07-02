"""Small helpers shared by the page builders (ported from AD ``utils.py``)."""

# ======================================================================


def format_subtype(ctx, subtype_id: str, date_range: list[str]):
    """Split a ``subtype-assay[-rbc]-lab`` id into its parts and attach the coloring keys.

    Ported from AD ``utils.format_subtype`` — the ``request.app["clade_data"]`` lookup
    becomes ``ctx.clade_data``.
    """
    subtype, assay, *fields = subtype_id.split("-")
    if assay == "hi":
        rbc = "-".join(fields[:-1])
    else:
        rbc = None
    return {
        "subtype": subtype,
        "assay": assay,
        "rbc": rbc,
        "lab": fields[-1],
        "coloring": ctx.clade_data.entry_names_for_subtype(subtype, date_range),
    }


# ======================================================================
