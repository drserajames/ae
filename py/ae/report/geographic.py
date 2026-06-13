# Ported from vcm (ssm-report tooling) 2026-0119-tc2/py/vcm/v2/geographic.py — Phase 1b engine tier.
# geographic settings + maps; make_geo takes an injected ConferenceData. See py/ae/report/MIGRATION.md.
# import sys
# import os
# import pprint
# import copy
import subprocess
import json
from pathlib import Path

import ae.utils.datetime

from . import conference_data_base

# ----------------------------------------------------------------------

def make_geo(conference_data: "conference_data_base.ConferenceData", geo_dir: Path, subtypes: list[str] = ["h1", "h3", "b"], force: bool = False):
    geo_dir.mkdir(exist_ok=True)
    data = conference_data  # injected by the report (its concrete ConferenceData)
    time_series = data.time_series()
    if force or not geo_dir.joinpath("index.html").exists():
        prefixes = {}
        for subtype in subtypes:
            settings_filename = geo_dir.joinpath(f"{subtype}.json")
            if force or not settings_filename.exists():
                with settings_filename.open("w") as out:
                    json.dump({
                        **data.geographic_settings(),
                        "coloring": _preprocess_coloring(data.geographic_coloring(subtype=subtype)),
                        "start_date": time_series.front_YMD(),
                        "end_date": time_series.after_last_YMD(),
                    }, out, indent=4)

            output = geo_dir.joinpath(f"{subtype}-")
            script_filename = geo_dir.joinpath(f"{subtype}.sh")
            script_filename.open("w").write(f"#! /bin/bash\nexec geographic-draw -v -s '{geo_dir}/{subtype}.json' --time-series 'monthly' '{subtype}' '{output}'\n")
            script_filename.chmod(0o755)
            subprocess.check_call([str(script_filename)])
            prefixes[subtype] = output

        make_index_html(geo_dir.joinpath("index.html"), prefixes, safari=False)
        make_index_html(geo_dir.joinpath("index.safari.html"), prefixes, safari=True)
    # subprocess.check_call(f"echo pdf-combine {geo_dir}/h1-*.pdf {geo_dir}/h3-*.pdf {geo_dir}/b-*.pdf {geo_dir}/all.pdf && open {geo_dir}/all.pdf", shell=True)
    subprocess.check_call(f"qpdf --empty --pages {geo_dir}/h1-*.pdf {geo_dir}/h3-*.pdf {geo_dir}/b-*.pdf -- {geo_dir}/all.pdf && open {geo_dir}/all.pdf", shell=True)

# ----------------------------------------------------------------------

def _preprocess_coloring(coloring: dict) -> dict:
    for en in coloring["apply"]:
        if (aa := en.get("aa")) and isinstance(aa, str):
            en["aa"] = aa.split() # geographic-draw uses aa as list of str, e.g. ["156N", "155G"]
        if not en.get("color") and en.get("fill"):
            en["color"] = en["fill"]
            del en["fill"]
    return coloring

# ----------------------------------------------------------------------

def make_index_html(output_file, prefixes, safari):
    with output_file.open("w") as f:
        f.write("<html><head><style>\nimg {border: 1px solid black;}\nul {list-style-type: none;}\nli {margin: 0.5em 0; }\nobject {width: 800px; height: 415px; }\n</style><title>Geographic maps</title></head><body>\n")
        for vt in sorted(prefixes):
            f.write("<h1>{}</h1>\n<ul>".format(vt))
            for fn in sorted(prefixes[vt].parent.glob(prefixes[vt].name + "*.pdf")):
                if safari:
                    f.write('<li><img src="{}" /></li>\n'.format(Path(fn).name))
                else:
                    f.write('<li><object data="{}#toolbar=0"></object></li>\n'.format(Path(fn).name)) # toolbar=0 is for chrome
            f.write("</ul>\n")
        f.write("</body></html>\n")

# ======================================================================
# ======================================================================
# ======================================================================

# sSettings = {
#     "coloring?": [
#         {"N": "continent", "?continent_color": {"EUROPE": {"fill": "green", "outline": "black", "outline_width": 0}}},
#         {"N": "clade", "?clade_color": {"SEQUENCED": {"fill": "yellow", "outline": "black", "outline_width": 0}}},
#         {"N": "lineage", "?lineage_color": {"VICTORIA_2DEL": {"fill": "#23a8d1", "outline": "black", "outline_width": 0}, "VICTORIA_3DEL": {"fill": "#80FF00", "outline": "black", "outline_width": 0}}},
#         {"N": "lineage-deletion-mutants", "?lineage_color": {"VICTORIA_2DEL": {"fill": "#23a8d1", "outline": "black", "outline_width": 0}, "VICTORIA_3DEL": {"fill": "#80FF00", "outline": "black", "outline_width": 0}}},
#         {"N": "amino-acid", "apply": [{"sequenced": True, "color": "red"}, {"aa": ["156N" ,"155G"], "color": "blue"}], "report": False},
#         # {
#         #     "ana1":  "#03569b",
#         #     "ana2":  "#e72f27",
#         #     "ana3":  "#ffc808",
#         #     "ana4":  "#a2b324",
#         #     "ana5":  "#a5b8c7",
#         #     "ana6":  "#049457",
#         #     "ana7":  "#f1b066",
#         #     "ana8":  "#742f32",
#         #     "ana9":  "#9e806e",
#         #     "ana10": "#75ada9",
#         #     "ana11": "#675b2c",
#         #     "ana12": "#a020f0",
#         #     "ana13": "#8b8989",
#         #     "ana14": "#e9a390",
#         #     "ana15": "#dde8cf",
#         #     "ana16": "#00939f"
#         # }
#     ],
#     "point_size_in_pixels": 8.0,
#     "point_density": 0.8,
#     "continent_outline_color": "grey63",
#     "continent_outline_width": 0.5,
#     "output_image_width": 800,

#     "title": {"offset": [0, 0], "text_size": 20, "background": "transparent", "border_color": "black", "border_width": 0, "text_color": "black", "padding": 10.0},

#     "priority?": "draw VICTORIA_DEL on top of VICTORIA",
#     "priority": [
#         "YAMAGATA",
#         "VICTORIA",
#         "VICTORIA_DEL",
#         "3C.2A1B",
#         "3C.2A1B1A",
#         "3C.2A1B2A"
#     ]
# }

# sColoringByVirusType = {
#     "b": {                     # 2021-1216-tc1, Sarah 2021-12-11 14:27: colour the points as per clade in the second set of maps
#         "N": "amino-acid",
#         "report": True,
#         "default": {"color": "transparent", "outline": "#A0A0A0", "outline_width": 0.3},
#         "apply": [
#             {"sequenced": True,                                                  "color": "#ffff80", "outline": "#808080", "outline_width": 1},
#             {"aa": ["162-", "163-",  "164-", "!165-"],                           "color": "#C0C0C0", "outline": "#808080", "outline_width": 1},
#             {"aa": ["162-", "163-",  "164-", "!165-",   "126K"],                 "color": "#8DA0CB", "outline": "#808080", "outline_width": 1},
#             {"aa": ["162-", "163-",  "164-", "!165-",   "133G", "129N"],         "color": "#8C6BB1", "outline": "#808080", "outline_width": 1},
#             {"aa": ["162-", "163-",  "164-", "!165-",   "150K"],                 "color": "#66C2A5", "outline": "#808080", "outline_width": 1},
#             {"aa": ["162-", "163-",  "164-", "!165-",   "150K", "241Q", "220M"], "color": "#33A02C", "outline": "#808080", "outline_width": 1},
#             {"aa": ["162-", "163-",  "164-", "!165-",   "150K", "144L"],         "color": "#CCFF9E", "outline": "#808080", "outline_width": 1},
#             {"aa": ["162-", "163-",  "164-", "!165-",   "150K", "144L", "122Q"], "color": "#A6D854", "outline": "#808080", "outline_width": 1},
#             {"aa": ["162-", "163-",  "164-", "!165-",   "133R"],                 "color": "#FFD92F", "outline": "#808080", "outline_width": 1},
#             {"aa": ["162-", "163-",  "164-", "!165-",   "133R", "128K"],         "color": "#FC8D62", "outline": "#808080", "outline_width": 1},
#             {"aa": ["162-", "163-",  "164-", "!165-",   "133R", "129N"],         "color": "#E78AC3", "outline": "#808080", "outline_width": 1},
#             {"aa": ["162-", "163-",  "164-", "!165-",   "133R", "136K"],         "color": "#E5C494", "outline": "#808080", "outline_width": 1}
#         ],
#         "report": False
#     },
#     "b-before-2021-1216-tc1": {
#         "N": "lineage-deletion-mutants",
#         "debug": False,
#     },

#     "h1": {
#         "N": "amino-acid",
#         "debug": False,
#         "report": True,
#         "default": {"color": "transparent", "outline": "#A0A0A0", "outline_width": 0.5},
#         "apply": [
#             {"sequenced": True,      "color": "#a2b324", "outline": "black", "outline_width": 3},
#             {"aa": ["155E"],         "color": "#ffc808"},
#             {"aa": ["155X"],         "color": "#742f32"},
#             {"aa": ["156D"],         "color": "#a2b324"},
#             {"aa": ["156S"],         "color": "#049457"},
#             {"aa": ["156K"],         "color": "#e72f27"},
#             {"aa": ["156X"],         "color": "#f1b066"},
#             {"aa": ["156N" ,"155G"], "color": "#03569b"}
#         ],
#         "report": False
#     },

#     "h3": {                     # 2021-1216-tc1, Sarah 2021-12-11 14:27: colour the points as per clade in the second set of maps
#         "N": "amino-acid",
#         "report": True,
#         "default": {"color": "transparent", "outline": "#A0A0A0", "outline_width": 0.5},
#         "apply": [
#             {"sequenced": True, "color": "transparent"},
#             {"color": "#1B9E77", "aa": ["92R", "121K", "158N", "159Y", "171K", "311Q", "406V",  "131K"]},
#             {"color": "#66A61E", "aa": ["92R", "121K", "158N", "159Y", "171K", "311Q", "406V",  "135K"]},
#             {"color": "#D95F02", "aa": ["92R", "121K", "131K", "158N",         "311Q", "406V",   "83E", "!94Y",  "186S"]},
#             {"color": "#E6AB02", "aa": ["92R", "121K", "131K", "158N",         "311Q", "406V",   "83E", "!94Y",  "159N"]},
#             {"color": "#674d01", "aa": ["92R", "121K", "131K", "158N",         "311Q", "406V",   "83E", "!94Y",  "159N", "156S"]},
#             {"color": "#fede83", "aa": ["92R", "121K", "131K", "158N",         "311Q", "406V",   "83E", "!94Y",  "159N", "156Q"]},
#             {"color": "#4037B3", "aa": ["92R", "121K", "158N", "159Y", "171K", "311Q", "406V",  "135K", "138S", "186D", "190N", "193S", "198P"]},
#             {"color": "#9a4ef2", "aa": ["92R", "121K", "158N", "159Y", "171K", "311Q", "406V",  "135K", "138S", "186D", "190N", "193S", "198P",  "192F"]},
#             {"color": "#E7298A", "aa": ["92R", "121K", "158N", "159Y", "171K", "311Q", "406V",  "135K", "137F", "138S", "193S"]}
#         ],
#         "report": False
#     },
#     "h3-before-2021-1216-tc1": {
#         "N": "clade",
#         "debug": False,
#         "clade_color": {
#             "SEQUENCED": {
#                 "fill": "#FFFF00",
#                 "outline": "#A0A000",
#                 "outline_width": 0.05
#             },
#             "3C.2A1B1A": {
#                 "fill": "#7570B3",
#                 "outline": "black",
#                 "outline_width": 0
#             },
#             "3C.2A1B2A": {
#                 "fill": "#1B9E77",
#                 "outline": "black",
#                 "outline_width": 0
#             }
#         }
#     }
# }

# ======================================================================
