import sys
import re
import ae_backend

# AD's egg-passage detection (acmacs-virus passage.cc re_egg + Passage::is_egg, which does a
# regex_search over the WHOLE passage string — "contains an egg element", not "last element is
# egg"). ae's own Passage.passage_type() only inspects the LAST deconstructed element and only
# recognises "E"/"SPFCE", so it misclassifies SPF/SPE/D egg passages (e.g. SPF2, E4SPF9, E2SIAT1)
# as cell. Replicate AD's regex here so serum-circle egg/cell colouring matches AD exactly.
# (suffix groups in AD's regex are all optional, so they reduce to this core egg token search.)
_AD_EGG_RE = re.compile(r"(?:(?:E|D|SPF(?:CE)?|SPE)(?:\?|[0-9][0-9]?)|EGG)")

def _passage_is_egg(passage) -> bool:
    return bool(_AD_EGG_RE.search(str(passage)))

# ======================================================================

def attributes(chart: ae_backend.chart_v3.Chart):
    """Set serum circle semantic attribute for all sera"""
    for fold in [2.0, 3.0]:
        for circle_data in chart.projection().serum_circles(fold=fold):
            attr = {"cb": circle_data.column_basis}
            if empirical := circle_data.empirical():
                attr["e"] = empirical
            if theoretical := circle_data.theoretical():
                attr["t"] = theoretical
            chart.serum(circle_data.serum_no).semantic.set(f"CI{int(fold)}", attr)
            # print(f">>>> SR {circle_data.serum_no:3d} {chart.serum(circle_data.serum_no).designation():40s} {chart.serum(circle_data.serum_no).semantic}", file=sys.stderr)
            # for en in circle_data:
            #     print(f">>>>    {en.status()}", file=sys.stderr)

# ======================================================================

def style(chart: ae_backend.chart_v3.Chart, style_name: str, priority: int = 100, sera: list[int] | None = None, fold: float = 2.0, theoretical: bool = False, fallback: bool = True, circle_style: dict = {"outline": {"egg": "red", "cell": "blue", "reassortant": "orange"}, "fill": {"egg": "transparent", "cell": "transparent", "reassortant": "transparent"}, "outline_width": 1.0, "dash": 0}) -> set[str]:
    """If sera is None show circles for all sera (if semantic attribute data is available), otherwise it's a list of serum indexes.
    empirical: True - show empirical, False - show theoretical.
    fallback: True - show fallback circle if empirical/theoretical is not available.
    circle_style: {
      "outline": {"egg": "red", "cell": "blue", "reassortant": "orange"},
      "fill": {"egg": "transparent", "cell": "transparent", "reassortant": "transparent"},
      "outline_width": 1.0,
      "dash": 0,
      "angles": None, # two angles to show radius lines and fill between lines only
      "radius_lines": {"outline": {}, "outline_width": 1.0, "dash": 0}
    }
    """
    style = chart.styles()[style_name]
    style.priority = priority
    num_sera = chart.number_of_sera()
    sera = sera if sera is not None else list(range(num_sera))
    for serum_no in sera:
        if serum_no >= 0 and serum_no < num_sera:
            serum = chart.serum(serum_no)
            # Classify the serum's passage type exactly as AD's serum-circle drawing does:
            # passage_type(reassortant_as_egg::no) (acmacs-map-draw mapi-settings-serum-circles.cc:29).
            # A reassortant serum is its OWN class ("reassortant" -> orange), NOT egg, even when its
            # passage string is egg (e.g. NYMC-333 E1/E9). Only NON-reassortant egg-passaged sera are
            # "egg" (red); everything else is "cell" (blue). ae's Passage.passage_type() is
            # reassortant-unaware (egg/cell only), so it must be checked here — otherwise reassortant
            # sera get painted red instead of orange, the red/blue split that diverged from AD.
            reassortant = serum.reassortant()
            reassortant_empty = reassortant.empty() if hasattr(reassortant, "empty") else not str(reassortant)
            if not reassortant_empty:
                serum_passage_type = "reassortant"
            elif not (passage := serum.passage()).empty():
                # AD's passage_type(reassortant_as_egg::no): "contains egg element" -> egg, else cell.
                # NOT ae's Passage.passage_type(), which only checks the last element and misses SPF/SPE/D.
                serum_passage_type = "egg" if _passage_is_egg(passage) else "cell"
            elif "EGG" in serum.serum_id():
                serum_passage_type = "egg"
            else:
                serum_passage_type = "cell"
            # print(f">>>> SR {serum_no} {serum.designation()} I:{serum.serum_id()} EI:{'EGG' in serum.serum_id()} P:[{serum.passage()}] PT:{serum_passage_type}", file=sys.stderr)
            this_circle_style = {**circle_style}
            # index per-passage-type colour maps; fall back to "egg" if a style omits the
            # "reassortant" key (older callers) so a reassortant serum can't KeyError.
            if isinstance(this_circle_style.get("outline"), dict):
                _o = this_circle_style["outline"]
                this_circle_style["outline"] = _o.get(serum_passage_type, _o.get("egg"))
            if isinstance(this_circle_style.get("fill"), dict):
                _f = this_circle_style["fill"]
                this_circle_style["fill"] = _f.get(serum_passage_type, _f.get("egg"))
            if isinstance(this_circle_style.get("radius_lines", {}).get("outline"), dict):
                this_circle_style["radius_lines"]["outline"] = this_circle_style["radius_lines"]["outline"][serum_passage_type]
            style.add_modifier(selector={"!i": serum_no}, only="sera", serum_circle={"fold": fold, "theoretical": theoretical, "fallback": fallback, "style": this_circle_style})
        else:
            print(f">> serum_circle.style: invalid serum no {serum_no}, number of sera in the chart: {num_sera}", file=sys.stderr)
    return set([style_name])

# ======================================================================
