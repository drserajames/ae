#!/usr/bin/env python3
"""Verify interactive/export_interactive.py fill_template(): each placeholder in the viewer
template is substituted exactly once, and never inside text that was substituted.

The regression: the exporter inlined the JS modules with one str.replace() and then the
data bundle with a second. main.js's header comment quotes the /*__DATA__*/ token, so
the second replace also pasted the whole bundle into that comment, doubling every page.

All strings here are invented placeholders — no WHO data.

Run::  PYTHONPATH=build:py python3 test/interactive_fill_template.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "interactive"))
from export_interactive import fill_template

DATA, MODULES = "/*__DATA__*/", "/*__MODULES__*/"


def expect_exit(fn, what):
    try:
        fn()
    except SystemExit:
        return
    raise AssertionError(f"expected SystemExit for {what}")


def main():
    tpl = f"<script>window.IV.__DATA__ = {DATA};</script>\n<script>\n{MODULES}\n</script>\n"
    payload = '{"meta":{"subtype":"TEST-SUBTYPE"}}'

    # 1. a module that quotes the data token in a comment keeps the token verbatim
    modules = f"// injected by the template as IV.__DATA__ (the {DATA} placeholder)\nconst x = 1;"
    html = fill_template(tpl, {DATA: payload, MODULES: modules})
    assert html.count(payload) == 1, f"bundle appears {html.count(payload)} times, expected 1"
    assert f"(the {DATA} placeholder)" in html, "module comment was rewritten"
    assert f"window.IV.__DATA__ = {payload};" in html

    # 2. a payload that happens to contain the modules token is not expanded either
    odd = '{"note":"/*__MODULES__*/"}'
    html = fill_template(tpl, {DATA: odd, MODULES: "const y = 2;"})
    assert html.count("const y = 2;") == 1 and odd in html

    # 3. the template itself must carry each token exactly once
    expect_exit(lambda: fill_template(MODULES, {DATA: payload, MODULES: ""}), "missing data token")
    expect_exit(lambda: fill_template(tpl + DATA, {DATA: payload, MODULES: ""}), "duplicated data token")

    # 4. the real template and modules: one bundle copy in the assembled page
    here = Path(__file__).resolve().parents[1] / "interactive"
    from export_interactive import build_modules
    real = fill_template((here / "viewer_template.html").read_text(),
                         {DATA: payload, MODULES: build_modules(here / "js")})
    assert real.count(payload) == 1, f"real template: bundle appears {real.count(payload)} times"

    print("all interactive fill_template checks passed")


if __name__ == "__main__":
    main()
