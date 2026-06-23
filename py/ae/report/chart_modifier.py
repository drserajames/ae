# Ported from vcm (ssm-report tooling) 2026-0119-tc2/py/vcm/v2/chart_modifier.py — Phase 1b engine tier.
# base ChartModifier(ConferenceData) — semantic styling. See py/ae/report/MIGRATION.md.
import sys, json, asyncio
from pathlib import Path
from typing import Any, Optional, Callable

import ae_backend.chart_v3
from ae import semantic
from ae.utils.org import dict_to_org_table
from ae.utils import kateri

try:
    import semantic_clades, semantic_vaccines  # acmacs-data (on path at report runtime)
except ImportError:  # absent when importing ae.report standalone
    semantic_clades = semantic_vaccines = None

from . import conference_data_base
try:
    import serology  # per-report module (present on a report working dir's path)
except ImportError:  # absent when importing ae.report standalone
    serology = None
from . import dirs

# ======================================================================

class ChartModifier (conference_data_base.ConferenceData):
    "Base class for adding semantic styles to the chart"

    def __init__(self, chart: ae_backend.chart_v3.Chart | Path | None = None):
        super().__init__()
        if isinstance(chart, ae_backend.chart_v3.Chart):
            self.chart = chart
        elif isinstance(chart, Path):
            if chart.exists():
                self.chart = ae_backend.chart_v3.Chart(chart)
            else:
                raise ValueError(f"{chart}: not found")
        elif chart is None:
            self.chart = ae_backend.chart_v3.Chart(dirs.VcmDirs.downloaded_filename())
        else:
            raise ValueError(f"unrecognized chart argument: {chart}")
        self.vaccine_data_for_sig_pages = []

    def populate_for_prestyle(self):
        self.populate_with_attributes_for_prestyle()
        self.populate_with_prestyles()

    def populate_for_style(self):
        self.populate_with_attributes_for_style()
        self.populate_with_styles()

    def populate_with_attributes_for_prestyle(self):
        semantic.clade.attributes(chart=self.chart, entries=self.semantic_attribute_clades())
        semantic.reference.attributes(chart=self.chart)  # Set reference ("R") semantic attribute for reference antigens
        semantic.passage.attributes(chart=self.chart)  # Set passage type ("p") semantic attributes for all antigens and sera

    def populate_with_attributes_for_style(self):
        self.populate_with_attributes_for_prestyle()
        semantic.older_than.attributes(chart=self.chart, conferencence_date=self.conferencence_date())
        semantic.continent.attributes(chart=self.chart)  # Set continent ("C9") and country ("c9") semantic attributes for all antigens and sera
        for previous_chart_no, previous_chart in reversed(list(enumerate(self.previous_charts(), start=1))):  # first mark previous-previous, then override with previous
            semantic.new_compared_to.attributes(chart=self.chart, previous_chart=ae_backend.chart_v3.Chart(previous_chart), new_attribute_value=previous_chart_no)
        # semantic.serum_circle.attributes(chart=self.chart)

    def populate_with_prestyles(self):
        self.chart.styles().remove()
        self.add_reset_style()
        self.add_vaccines_style()
        back_clades_priority = self.style_priority("-clades")
        for clade_style_name, clade_style_data in self.semantic_styles_clades().items():
            # print(f">>>> {clade_style_name} {clade_style_data}", file=sys.stderr)
            semantic.clade.style(chart=self.chart, style_name=clade_style_name, data=clade_style_data, legend_style=self.legend_style(), priority=back_clades_priority,
                                 antigen_fill_opacity=self.antigen_fill_opacity(),
                                 ) # mark_sequenced={"fill": "yellow", "outline": "red", "rais": True})
            back_clades_priority += 10
        clades_priority = self.style_priority("clades")
        for zoom_variant in self.zoom_variants():
            for clade_style_name in self.semantic_styles_clades():
                for info in ["", "info-"]:
                    def make_references(before_vaccines: str|None = None):
                        refs = [f"-reset{zoom_variant}", f"-{clade_style_name}", "-new-2", "-new-1", (vaccines_style_name + "-no-label") if info else vaccines_style_name]
                        if before_vaccines:
                            refs[-1:-1] = before_vaccines
                        return refs

                    def make_args(since: str|None = None):
                        if info:
                            return {"title": " ", "show_legend": False}
                        else:
                            if since:
                                title = f"{self.title_lab_subtype()} {self.title_by_clade()} (since {since})"
                            else:
                                title = f"{self.title_lab_subtype()} {self.title_by_clade()}"
                            return {"title": title, "title_style": self.title_style(), "show_legend": True, "legend_counter": True}

                    vaccines_style_name = "-vaccines" + self._clades_version_suffix(clade_style_name, infix="-")
                    semantic.front_style.add(chart=self.chart, style_name=f"{info}{clade_style_name}{zoom_variant}", references=make_references(), **make_args(), style_priority=clades_priority)
                    clades_priority += 1
                    semantic.front_style.add(chart=self.chart, style_name=f"{info}{clade_style_name}-6m{zoom_variant}", references=make_references(["-o6m-grey"]), **make_args(since=semantic.older_than.since_6m_label(self.conferencence_date())), style_priority=clades_priority)
                    clades_priority += 1
                    semantic.front_style.add(chart=self.chart, style_name=f"{info}{clade_style_name}-12m{zoom_variant}", references=make_references(["-o12m-grey"]), **make_args(since=semantic.older_than.since_12m_label(self.conferencence_date())), style_priority=clades_priority)
                    clades_priority += 1

    # def populate_with_styles(self):
    #     self.populate_with_prestyles()
    #     self.add_serology_style()
    #     semantic.older_than.style(chart=self.chart, priority=self.style_priority("-o6m-grey"))
    #     semantic.continent.style(chart=self.chart, priority=self.style_priority("-continent"))
    #     semantic.pale.style(chart=self.chart, priority=self.style_priority("-pale"))
    #     semantic.new_compared_to.style_new(chart=self.chart, number_of_previous_charts=len(self.previous_charts()), first_priority=self.style_priority("-new"))
    #     semantic.time_series.style(chart=self.chart, time_series=self.time_series(),
    #                                vaccine_style_name="-vaccines-ts" if self.vaccine_ts_data_key_mapping() else "-vaccines",
    #                                title_prefix=self.title_lab_subtype(), title_style=self.title_style(), priority=self.style_priority("-ts"), front_priority=self.style_priority("ts"))
    #     semantic.time_series.style_old_new(chart=self.chart, old_size=self.ts_old_size(), new_size=self.ts_new_size(), priority=self.style_priority("-ts-old-new"))

    def populate_with_styles(self):
        self.populate_with_prestyles()
        self.add_serology_style()
        semantic.older_than.style(chart=self.chart, priority=self.style_priority("-o6m-grey"))
        semantic.continent.style(chart=self.chart, priority=self.style_priority("-continent"), antigen_fill_opacity=self.antigen_fill_opacity())
        semantic.pale.style(chart=self.chart, priority=self.style_priority("-pale"))
        self.style_new_compared_to(chart=self.chart, number_of_previous_charts=len(self.previous_charts()), first_priority=self.style_priority("-new"))
        semantic.time_series.style(chart=self.chart, time_series=self.time_series(),
                                   vaccine_style_name="-vaccines-ts" if self.vaccine_ts_data_key_mapping() else "-vaccines",
                                   title_prefix=self.title_lab_subtype(), title_style=self.title_style(), priority=self.style_priority("-ts"), front_priority=self.style_priority("ts"))
        semantic.time_series.style_old_new(chart=self.chart, old_size=self.ts_old_size(), new_size=self.ts_new_size(), priority=self.style_priority("-ts-old-new"))

    def style_new_compared_to(self, chart: ae_backend.chart_v3.Chart, number_of_previous_charts: int, first_priority: int = 4500):
        """add "-new-1", "-new-2", "-new-1-big" styles marking antigens with the "new" semantic attribute"""
        if number_of_previous_charts > 0:
            priority = first_priority
            outline_widths = [1, 6, 3]
            for prev_no in range(number_of_previous_charts, 0, -1):
                semantic.style.style_with_one_modifier(chart=chart, style_name=f"-new-{prev_no}", selector={"new": prev_no}, modifier={"outline": "black", "outline_width": outline_widths[prev_no], "only": "antigens", "raise": True}, priority=priority)
                priority += 1

    def add_reset_style(self, style_name: str = "-reset"):
        for zoom_variant in self.zoom_variants():
            style = self.chart.styles()[style_name + zoom_variant]
            style.priority = self.style_priority(style_name)
            style.viewport(*self.viewport(zoom_variant=zoom_variant))
            style.add_modifier(only="antigens", size=self.reset_test_antigen_size())
            style.add_modifier(only="antigens", selector={"R": True}, size=self.reset_reference_antigen_size())
            style.add_modifier(only="sera", size=self.reset_serum_size())
            self.reset_style_additions(style=style, zoom_variant=zoom_variant)

    def reset_style_additions(self, style: ae_backend.chart_v3.SemanticStyle, zoom_variant: str):
        pass                    # override (chart specific, e.g. to hide antigens/sera)

    def add_vaccines_style(self):
        vaccs = semantic.vaccine.find(chart=self.chart, semantic_attribute_data=self.semantic_attribute_vaccines(), report=False)
        # set semantic attribute for the strains with the most layers (or choose another variant if necessary using self.vaccine_choose())
        semantic.vaccine.set_semantic(vaccs, current_vaccine_years=self.current_vaccine_years(), disable=self.vaccine_disable(), choose=self.vaccine_choose())
        vaccine_data = semantic.vaccine.update(semantic.vaccine.collect_data_for_styles(self.chart), self.vaccine_user_data())
        print(">>> Vaccines", dict_to_org_table(vaccine_data, field_order=semantic.vaccine.default_field_order()), sep="\n", file=sys.stderr)
        self.vaccine_data_for_sig_pages = [{"index": vdata["no"], "fill": vdata.get("fill", vdata.get("fill_v1")), "label_offset": [vdata["lox"], vdata["loy"]]} for vdata in vaccine_data]

        for clade_style_name in self.semantic_styles_clades():
            semantic.vaccine.style(chart=self.chart, style_name=f"-vaccines{self._clades_version_suffix(clade_style_name, infix='-')}",
                                   data=vaccine_data, data_key_mapping={"fill": f"fill{self._clades_version_suffix(clade_style_name, infix='_')}"},
                                   common_modifier={"outline": "black", "fill": ":bright", "size": self.vaccine_size(), "outline_width": self.vaccine_outline_width()},
                                   label_modifier={"size": self.vaccine_label_size(), "slant": "normal", "weight": "normal", "color": self.vaccine_label_color()}, priority=self.style_priority("-vaccines"))
            semantic.vaccine.style(chart=self.chart, style_name=f"-vaccines{self._clades_version_suffix(clade_style_name, infix='-')}-no-label",
                                   data=vaccine_data, data_key_mapping={"fill": f"fill{self._clades_version_suffix(clade_style_name, infix='_')}"},
                                   common_modifier={"outline": "black", "fill": ":bright", "size": self.vaccine_size(), "outline_width": self.vaccine_outline_width()},
                                   label_modifier={"size": 0}, priority=self.style_priority("-vaccines"))

        if data_key_mapping := self.vaccine_ts_data_key_mapping():
            semantic.vaccine.style(chart=self.chart, style_name="-vaccines-ts", data=vaccine_data, data_key_mapping=data_key_mapping,
                                   common_modifier={"outline": "black", "size": self.vaccine_size(), "outline_width": self.vaccine_outline_width()},
                                   label_modifier={"size": self.vaccine_label_size(), "slant": "normal", "weight": "normal", "color": self.vaccine_label_color()},
                                   priority=self.style_priority("-vaccines-ts"))

        # semantic.select_mark.style(chart=chart, style_name="-vic", antigen_selector=lambda ag: "VICTORIA/2570/2019" in ag.name)

    def add_serology_style(self):
        semantic.serology.remove_serology(self.chart)
        serology_antigens = semantic.serology.find(chart=self.chart, semantic_attribute_data=self.semantic_attribute_serology(), report=self.serology_report())
        for serology_antigen_en in serology_antigens:
            for psg, antigens in serology_antigen_en.items():
                if psg != "name":
                    antigens[0]["antigen"].semantic.set("serology", True)
        serology_data = semantic.serology.update(semantic.serology.collect_data_for_styles(self.chart), self.serology_user_data())
        print(">>> Serology", dict_to_org_table(serology_data, field_order=semantic.serology.default_field_order()), sep="\n", file=sys.stderr)

        semantic.serology.style(chart=self.chart, style_name="-serology", data=serology_data,
                                common_modifier={"outline": "black", "fill": ":bright", "size": self.serology_size(), "outline_width": self.serology_outline_width()},
                                label_modifier={"size": self.serology_label_size(), "slant": "normal", "weight": "normal", "color": "black"},
                                priority=self.style_priority("-serology"))
        if semantic_styles_clades := self.semantic_styles_clades():
            vaccines_style_name = "-vaccines" + self._clades_version_suffix(list(semantic_styles_clades)[0], infix="-")
        else:
            vaccines_style_name = "-vaccines"
        semantic.front_style.add(chart=self.chart, style_name="serology", references=["-reset", f"-{self.serology_clade_style()}", "-pale", "-serology", vaccines_style_name], title=f"{self.title_lab_subtype()} with serology antigens", title_style=self.title_style(), show_legend=True, legend_counter=True, style_priority=self.style_priority("serology"))

    def serology_report(self) -> bool:
        return False

    def serology_clade_style(self) -> str:
        return list(self.semantic_styles_clades())[0]

    def add_serum_coverage_styles(self, serum_selector: Callable | None = None, fold: float = 2.0, mark_serum: dict[str, str | float | bool] | None = {"size": 36.0, "fill": "black", "outline": "black", "raise_": True}):
        clade_style_name = self.style_for_serum_coverage_plot_spec()
        sc_back_style_priority = self.style_priority("-sci")
        sc_front_style_priority = self.style_priority("sc")
        if serum_selector:
            sera = self.chart.select_sera(serum_selector)
        else:
            sera = self.chart.select_all_sera()
        for serum_no, serum in sera:
            sco_style_name = f"-sco-{serum_no:03d}-f{fold}"
            title = self.title_for_serum_coverage(serum_no=serum_no, serum=serum)
            for et in ["e", "t"]:
                sci_style_name = f"-sci-{serum_no:03d}-f{fold}-{et}"
                semantic.serum_circle.style(chart=self.chart, style_name=sci_style_name, fold=fold, priority=sc_back_style_priority,
                                            sera=[serum_no], theoretical=(et == "t"), circle_style=self.serum_coverage_circle_style())
                # self.chart.styles()[sci_style_name].add_modifier(selector={"!i": serum_no}, only="sera", size=36, fill="black", outline="black", raise_=True)
                sc_back_style_priority += 1
                for zoom_variant in self.zoom_variants():
                    sc_style_name = f"sc-{serum_no:03d}-f{fold}-{et}{zoom_variant}"
                    fstyle = semantic.front_style.add(chart=self.chart, style_name=sc_style_name,
                                                      references=[f"-reset{zoom_variant}", f"-{clade_style_name}", "-pale", sci_style_name, sco_style_name, clade_style_name.replace("clades", "-vaccines")],
                                                      title=title, title_style=self.title_style(), show_legend=True, legend_counter=True, style_priority=sc_front_style_priority)
                    if mark_serum:
                        fstyle.add_modifier(selector={"!i": serum_no}, only="sera", **mark_serum)
                    sc_front_style_priority += 1
            semantic.serum_coverage.style(chart=self.chart, style_name=sco_style_name, fold=fold, serum_no=serum_no, priority=sc_back_style_priority)
            sc_back_style_priority += 1

    def title_for_serum_coverage(self, serum_no: int, serum: ae_backend.chart_v3.Serum) -> str:
        if clades := serum.semantic.clades():
            clade = clades[-1]
        else:
            clade = ""
        return f"{self.title_lab_subtype()} {self.title_by_clade()}\n{serum.designation()}\n{clade}"

    def style_for_legacy_plot_spec(self) -> str:
        raise NotImplementedError("override in derived (subtype specific)")

    def style_for_style_command(self) -> str:
        return self.style_for_legacy_plot_spec()

    def style_for_serum_coverage_plot_spec(self) -> str:
        return self.style_for_legacy_plot_spec()

    def zoom_variants(self) -> list[str]:
        "zoom variants support: list of style suffixes, default: \"\""
        return [""]

    def viewport(self, zoom_variant: str) -> list[float]:
        raise NotImplementedError("override in derived (chart specific)")

    def reset_test_antigen_size(self) -> float:
        return 20.0

    def reset_reference_antigen_size(self) -> float:
        return 20.0

    def reset_serum_size(self) -> float:
        return 20.0

    def ts_new_size(self) -> float:
        return 25.0

    def ts_old_size(self) -> float:
        return 15.0

    def vaccine_disable(self) -> dict[str, dict[str, list[str]]]:
        # subtype specific
        # {"any": {"name": ["CALIFORNIA/7/2009", "MICHIGAN/45/2015", "BRISBANE/2/2018"]}}
        return {}

    def vaccine_choose(self) -> dict[str, list[dict[str, str | int]]]:
        # chart specific
        # choose: {"egg": [{"name": "VICTORIA/2570/2019", "index": 1}]} use "name" or "year" as a selector to choose index (default is 0) to get from list for passage
        return {}

    def vaccine_ts_data_key_mapping(self) -> Optional[dict[str, str]]:
        "Different vaccine coloring in ts"
        return None

    def vaccine_user_data(self) -> list[dict[str, str | bool | int | float]]:
        raise NotImplementedError("override in derived (chart specific)")

    def vaccine_size(self) -> float:
        return 40.0

    def vaccine_label_size(self) -> float:
        return 30.0

    def vaccine_label_color(self) -> str:
        return "black"

    def vaccine_outline_width(self) -> float:
        return 1.0

    def serology_user_data(self) -> list[dict[str, str | bool | int | float]]:
        raise NotImplementedError("override in derived (chart specific)")

    def serology_size(self) -> float:
        return 50.0

    def serology_label_size(self) -> float:
        return 24.0

    def serology_outline_width(self) -> float:
        return 1.0

    sStylePriorities: dict[str, int] = {
        "clades": 100,
        "serology": 200,
        "sc": 200,
        "ts": 300,
        "-vaccines": 9000,
        "-vaccines-ts": 9010,
        "-continent": 10050,
        "-clades": 10100,
        "-serology": 10200,
        "-sci": 10200,
        "-ts": 10300,
        "-ts-old-new": 10350,
        "-o6m-grey": 10400,
        "-new": 10500,
        "-pale": 80000,
        "-reset": 90000,
    }

    def style_priority(self, style_name: str) -> int:
        return self.sStylePriorities.get(style_name, 0)

    def legend_style(self) -> dict[str, float]:
        return {"point_size": 15.0, "interline": 0.4, "text_size": 20.0}

    def title_style(self) -> dict[str, Any]:
        return {"offset": [19.0, 12.0], "origin": "tl", "size": 25, "weight": "bold", "slant": "normal", "face": "helvetica", "color": "black", "interline": 0.2}

    def subtype(self) -> str:
        raise NotImplementedError("override in derived: \"A(H1N1)\", \"A(H3N2)\"")

    def title_subtype(self) -> str:
        raise NotImplementedError("override in derived")

    def title_lab_subtype(self) -> str:
        return f"{self.title_lab()} {self.title_subtype()}"

    def title_by_clade(self) -> str:
        return "by clade"

    def chart_name_prefix(self) -> str:
        if nam := self.standard_vcm_chart_dir():
            return nam
        else:
            raise NotImplementedError("override in derived, should return e.g. \"h1-cdc\"")

    def semantic_attribute_clades(self) -> list[dict[str, str]]:
        return semantic_clades.semantic_attribute_data_for_subtype(self.subtype())["clades"]

    def semantic_styles_clades(self) -> dict[str, list[dict[str, str]]]:
        return semantic_clades.semantic_plot_spec_data_for_subtype(self.subtype())

    def semantic_styles_versions(self) -> set[str]:
        return set(self._clades_version_suffix(semantic_style_name, infix="") for semantic_style_name in self.semantic_styles_clades())

    def semantic_attribute_vaccines(self) -> list[dict[str, str]]:
        return semantic_vaccines.semantic_attribute_data_for_subtype(self.subtype())["vaccines"]

    def semantic_styles_vaccines(self) -> dict[str, list[dict[str, str]]]:
        return semantic_vaccines.semantic_plot_spec_data_for_subtype(self.subtype())

    def semantic_attribute_serology(self) -> list[dict[str, str]]:
        return serology.semantic_attribute_data_for_subtype(self.subtype())["serology"]

    def semantic_styles_serology(self) -> dict[str, list[dict[str, str]]]:
        return serology.semantic_plot_spec_data_for_subtype(self.subtype())

    def export_styles(self) -> list[str]:
        raise NotImplementedError("override in derived (subtype specific)")

    def export_info_styles(self) -> list[str]:
        raise NotImplementedError("override in derived (subtype specific)")

    # ----------------------------------------------------------------------

    def serum_coverage_circle_style(self) -> dict:
        return {
            "outline": {"egg": "red", "cell": "blue", "reassortant": "orange"},
            "fill": {"egg": "#18FF0000", "cell": "#180000FF", "reassortant": "#18FFA500"},
            "outline_width": 1.0,
            "dash": 0
        }

    # ----------------------------------------------------------------------

    def previous_charts(self) -> list[Path]:
        current_name = self.chart_name_prefix()
        if self.tc_ssm_dir_path().name.split("-")[-1] == "tc1":
            # just one previous
            pc = [self.find_previous_chart(current_name, number_of_previous=1)]
        else:
            # two previous
            pc = [self.find_previous_chart(current_name, number_of_previous=1), self.find_previous_chart(current_name, number_of_previous=2)]
        # eliminate not found
        return [pcc for pcc in pc if pcc is not None]

    def _clades_version_suffix(self, clade_style_name: str, infix: str):
        if (suffix := clade_style_name.replace("clades-", ""))[0] == "v" or suffix == "ts":
            return infix + suffix
        else:
            return ""

    async def export_mapi_for_signature_pages(self, filename: Path, style: str):
        kateri.communicator.set_style(style)
        viewport_data = await kateri.communicator.get_viewport()
        viewport = [
            - viewport_data["native"][2] / 2.0 + viewport_data["used"][0] + viewport_data["native_center"][0],
            - viewport_data["native"][3] / 2.0 + viewport_data["used"][1] + viewport_data["native_center"][1],
            viewport_data["used"][2]
        ]
        fill_key = "fill" + self._clades_version_suffix(style, infix="_")
        data = {
            "loc:viewport": [{"N": "viewport", "abs": viewport}],
            "loc:vaccines": [{"N": "antigens", "select": {"index": vdata["index"], "report": True}, "fill": vdata[fill_key], "outline": "black", "size": "$vaccine-size", "label": {"offset": vdata["label_offset"], "size": "$vaccine-label-size"}, "order": "raise"} for vdata in self.vaccine_data_for_sig_pages],
        }
        json.dump(data, filename.open("w"), indent=2)
        print(f">>>> export_mapi_for_signature_pages {viewport}", file=sys.stderr)

    def orient_to(self, master: ae_backend.chart_v3.Chart | Path):
        if isinstance(master, Path):
            if master.exists():
                master = ae_backend.chart_v3.Chart(master)
            else:
                raise ValueError(f"{master}: not found")
        self.chart.orient_to(master)

# ======================================================================
