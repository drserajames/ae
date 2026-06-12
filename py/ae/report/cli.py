"""
Command-line entry point for assembling an SSM/seasonal report.

Mirrors AD ssm-report's ``bin/report-simple``: given a working directory that
contains a ``report.json`` settings file and the figure PDFs it references,
assemble the LaTeX source, compile it with ``pdflatex`` and (optionally) open the
result.

Usage (from a checkout, with the ae python package on PYTHONPATH):

    PYTHONPATH=build:py python3 -m ae.report.cli --working-dir <dir>

or via the wrapper:

    PYTHONPATH=build:py bin/ssm-report --working-dir <dir>
"""

import sys, argparse, logging, traceback
from pathlib import Path

from .report import make_report

module_logger = logging.getLogger(__name__)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--working-dir", dest="working_dir", default=".",
                        help="directory containing report.json and the figure PDFs (default: cwd)")
    parser.add_argument("--settings", dest="settings", default="report.json",
                        help="report settings file, relative to working-dir (default: report.json)")
    parser.add_argument("--output-dir", dest="output_dir", default="report",
                        help="output subdirectory for the .tex/.pdf (default: report)")
    parser.add_argument("--name", dest="report_name", default="report",
                        help="output base name (default: report)")
    parser.add_argument("--no-compile", dest="no_compile", action="store_true", default=False,
                        help="only write the .tex (skip pdflatex and the viewer)")
    parser.add_argument("--no-view", dest="no_view", action="store_true", default=False,
                        help="compile but do not open the PDF in a viewer")
    parser.add_argument("-d", "--debug", dest="loglevel", action="store_const",
                        const=logging.DEBUG, default=logging.INFO, help="enable debug logging")
    args = parser.parse_args(argv)

    logging.basicConfig(level=args.loglevel,
                        format="%(levelname)s %(asctime)s: %(message)s [%(name)s.%(funcName)s %(lineno)d]")

    working_dir = Path(args.working_dir).resolve()
    settings_path = working_dir / args.settings
    if not settings_path.exists():
        raise SystemExit(f"no settings file: {settings_path}")

    # make_report reads the settings file relative to cwd, so run from working_dir.
    import os
    os.chdir(working_dir)

    if args.no_compile or args.no_view:
        _make_report_staged(working_dir, Path(args.output_dir), args.report_name, args.settings,
                            compile_pdf=not args.no_compile, view=not (args.no_compile or args.no_view))
    else:
        make_report(source_dir=working_dir, source_dir_2=Path(""),
                    output_dir=Path(args.output_dir), report_name=args.report_name,
                    report_settings_file=args.settings)
    return 0


def _make_report_staged(working_dir, output_dir, report_name, settings_file, compile_pdf, view):
    """Like make_report() but lets the caller skip the compile and/or view steps.

    Useful for headless/CI use where pdflatex or a viewer may be unavailable, and
    for inspecting the generated .tex without producing a PDF.
    """
    from .jsonio import read_json
    from .report import LatexReport, LatexSignaturePageAddendum
    output_dir.mkdir(exist_ok=True)
    settings = read_json(settings_file)
    output_name = settings.get("output_name", report_name)
    report_type = settings.get("type", "report")
    if report_type == "report":
        report = LatexReport(source_dir=working_dir, source_dir_2=Path(""), output_dir=output_dir, output_name=output_name, settings=settings)
    elif report_type == "signature_pages":
        report = LatexSignaturePageAddendum(source_dir=working_dir, output_dir=output_dir, output_name=output_name, settings=settings)
    else:
        raise RuntimeError(f"Unrecognized report type: {report_type!r}")
    report.make()
    if compile_pdf:
        report.compile(update_toc=True)
        if view:
            report.view()


if __name__ == "__main__":
    try:
        exit_code = main()
    except Exception as err:
        logging.error("{}\n{}".format(err, traceback.format_exc()))
        exit_code = 1
    sys.exit(exit_code)
