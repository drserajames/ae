#!/usr/bin/env python3
"""
P2 fidelity harness — the renderer's pixel-diff scoreboard.

Given a manifest of (chart, style, [golden], [ad-ref]) entries, this:
  1. renders each map with the native C++ renderer
       (ae_backend.map_draw.export_styled_map -> PDF),
  2. rasterises the native PDF and each reference PDF to equal-size PNGs
       (pdftoppm -scale-to SIZE),
  3. pixel-compares native vs each reference with ImageMagick
       (magick compare -metric AE) at BOTH strict and -fuzz 30%,
  4. emits a per-map diff table (AE count + %) to stdout, plus scoreboard.csv
       and scoreboard.md in the output dir, and optional side-by-side montages.

This is how every current and future renderer milestone proves itself: point it
at the report charts + kateri goldens (and AD single-map references where they
are isolable) and read the scoreboard.

WHO-data note
-------------
The manifest references charts and reference PDFs by PATH — real report data that
lives OUTSIDE this repo and is NEVER committed. All rendered/rasterised output
(which would embed strain names + titer-derived coordinates) goes to an output
dir outside the repo (default: a scratch dir). Nothing real-data is written into
the repo. Ship + commit only the synthetic manifest.example.json.

Guardrails
----------
Every external command (render, pdftoppm, magick) is wrapped in `timeout` so a
hung tool can never stall the harness.

Usage
-----
    fidelity.py MANIFEST.json [--build-dir DIR] [--out-dir DIR] [--size 800]
                [--montage] [--only SUBSTR] [--timeout 120]

Manifest format: see manifest.example.json and README.md.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# external-command helpers (every one bounded by `timeout`)
# ---------------------------------------------------------------------------

def _timeout_cmd(seconds: int, cmd: list[str]) -> list[str]:
    return ["timeout", str(seconds), *cmd]


def run(cmd: list[str], seconds: int, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run cmd (prefixed with `timeout seconds`); return the CompletedProcess.

    Never raises on non-zero exit — callers inspect returncode/stderr. A timeout
    surfaces as returncode 124 (the `timeout` convention)."""
    full = _timeout_cmd(seconds, cmd)
    return subprocess.run(full, capture_output=True, text=True, env=env)


# ---------------------------------------------------------------------------
# render / rasterise / compare
# ---------------------------------------------------------------------------

def render_native(build_dir: Path, chart: str, style: str, width: float,
                  projection: int, out_pdf: Path, seconds: int) -> str | None:
    """Render one styled map via the native renderer, in a bounded subprocess.

    Returns None on success, else an error string."""
    code = (
        "import ae_backend;"
        f"ae_backend.map_draw.export_styled_map({chart!r}, {str(out_pdf)!r},"
        f" {style!r}, {float(width)!r}, {int(projection)!r})"
    )
    env = dict(os.environ)
    if build_dir:
        env["PYTHONPATH"] = str(build_dir) + os.pathsep + env.get("PYTHONPATH", "")
    env.setdefault("OMP_NUM_THREADS", "1")
    cp = run([sys.executable, "-c", code], seconds, env=env)
    if cp.returncode == 124:
        return "render TIMEOUT"
    if cp.returncode != 0 or not out_pdf.exists():
        tail = (cp.stderr or cp.stdout or "").strip().splitlines()
        return "render FAILED: " + (tail[-1] if tail else f"exit {cp.returncode}")
    return None


def rasterise(pdf: Path, out_prefix: Path, size: int, seconds: int,
              magick_tmp: Path) -> Path | None:
    """pdftoppm -scale-to SIZE -> first-page PNG. Returns the PNG path or None."""
    env = dict(os.environ)
    env["MAGICK_TMPDIR"] = str(magick_tmp)
    env.setdefault("OMP_NUM_THREADS", "1")
    cp = run(["pdftoppm", "-png", "-scale-to", str(size), "-singlefile",
              str(pdf), str(out_prefix)], seconds, env=env)
    png = out_prefix.with_suffix(".png")
    if cp.returncode == 0 and png.exists():
        return png
    # -singlefile is widely supported; fall back to the numbered form if not.
    cp = run(["pdftoppm", "-png", "-scale-to", str(size), str(pdf), str(out_prefix)],
             seconds, env=env)
    for cand in sorted(out_prefix.parent.glob(out_prefix.name + "*.png")):
        return cand
    return None


_AE_RE = re.compile(r"\(([0-9.eE+]+)\)\s*$")


def _parse_ae(stderr: str) -> int | None:
    """`magick compare -metric AE` prints `<scaled> (<AE-count>)` (e.g. `0 (0)` or
    `3.8e+09 (58400)`). The parenthesised integer is the differing-pixel count."""
    line = (stderr or "").strip().splitlines()
    if not line:
        return None
    last = line[-1].strip()
    m = _AE_RE.search(last)
    tok = m.group(1) if m else last.split()[0]
    try:
        return int(round(float(tok)))
    except (ValueError, IndexError):
        return None


def compare_ae(a: Path, b: Path, seconds: int, magick_tmp: Path,
               fuzz: str | None = None) -> int | None:
    """Return the absolute-error pixel count between two equal-size PNGs."""
    env = dict(os.environ)
    env["MAGICK_TMPDIR"] = str(magick_tmp)
    env.setdefault("OMP_NUM_THREADS", "1")
    cmd = ["magick", "compare", "-metric", "AE"]
    if fuzz:
        cmd += ["-fuzz", fuzz]
    cmd += [str(a), str(b), "null:"]
    cp = run(cmd, seconds, env=env)
    if cp.returncode == 124:
        return None
    # compare exits non-zero when images differ; the count is still on stderr.
    return _parse_ae(cp.stderr)


def dimensions(png: Path, seconds: int, magick_tmp: Path) -> str:
    env = dict(os.environ)
    env["MAGICK_TMPDIR"] = str(magick_tmp)
    cp = run(["magick", "identify", "-format", "%wx%h", str(png)], seconds, env=env)
    return (cp.stdout or "?").strip()


def montage(pngs: list[tuple[str, Path]], out: Path, seconds: int,
            magick_tmp: Path) -> None:
    env = dict(os.environ)
    env["MAGICK_TMPDIR"] = str(magick_tmp)
    cmd = ["magick", "montage"]
    for label, png in pngs:
        cmd += ["-label", label, str(png)]
    cmd += ["-tile", f"{len(pngs)}x1", "-geometry", "+4+4",
            "-background", "white", str(out)]
    run(cmd, seconds, env=env)


# ---------------------------------------------------------------------------
# manifest handling
# ---------------------------------------------------------------------------

def load_manifest(path: Path) -> tuple[dict, list[dict]]:
    doc = json.loads(path.read_text())
    if isinstance(doc, list):
        return {}, doc
    cfg = {k: v for k, v in doc.items() if k != "maps"}
    return cfg, doc.get("maps", [])


def resolve_golden(entry_val: str | None, chart: str, style: str) -> str | None:
    """Resolve a golden/ad path. Explicit path wins; 'auto' (or absent) derives the
    kateri golden name from the chart dir: out.1.<style>.pdf, <style>.pdf, <style>-info.pdf."""
    if entry_val and entry_val != "auto":
        return entry_val if Path(entry_val).exists() else None
    if entry_val is None:
        return None  # only auto-derive when explicitly requested
    d = Path(chart).parent
    for cand in (f"out.1.{style}.pdf", f"{style}.pdf", f"{style}-info.pdf"):
        p = d / cand
        if p.exists():
            return str(p)
    return None


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------

def find_build_dir(explicit: str | None) -> Path | None:
    if explicit:
        return Path(explicit)
    if os.environ.get("AE_BUILD"):
        return Path(os.environ["AE_BUILD"])
    # If PYTHONPATH already exposes ae_backend, defer to it (render subprocess inherits it).
    try:
        import ae_backend  # noqa: F401
        return None
    except Exception:
        pass
    repo_build = Path(__file__).resolve().parents[2] / "build-py314"
    return repo_build if repo_build.exists() else None


def fmt_pct(count: int | None, total: int) -> str:
    if count is None:
        return "  n/a"
    return f"{100.0 * count / total:5.2f}%"


def main() -> int:
    ap = argparse.ArgumentParser(description="P2 native-renderer fidelity harness")
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--build-dir", default=None,
                    help="dir containing ae_backend.*.so (default: $AE_BUILD, else "
                         "already-importable, else <repo>/build-py314)")
    ap.add_argument("--out-dir", default=None,
                    help="output dir for renders/rasters/scoreboard (default: scratch)")
    ap.add_argument("--size", type=int, default=800, help="raster px (scale-to)")
    ap.add_argument("--width", type=float, default=None,
                    help="native render width override (default: manifest or size)")
    ap.add_argument("--projection", type=int, default=None)
    ap.add_argument("--montage", action="store_true",
                    help="also write native|kateri[|AD] montages")
    ap.add_argument("--only", default=None, help="run only entries whose label contains SUBSTR")
    ap.add_argument("--timeout", type=int, default=120, help="per-command timeout (s)")
    args = ap.parse_args()

    cfg, maps = load_manifest(args.manifest)
    size = args.size or cfg.get("raster_size", 800)
    width = args.width if args.width is not None else cfg.get("width", size)
    projection = args.projection if args.projection is not None else cfg.get("projection", 0)
    build_dir = find_build_dir(args.build_dir or cfg.get("build_dir"))

    out_dir = Path(args.out_dir or cfg.get("out_dir")
                   or (os.environ.get("TMPDIR", "/tmp") + "/p2-fidelity"))
    out_dir.mkdir(parents=True, exist_ok=True)
    magick_tmp = out_dir  # keep magick scratch out of /tmp (sandbox-friendly)

    print(f"# P2 fidelity harness")
    print(f"# build-dir : {build_dir or '(inherited PYTHONPATH)'}")
    print(f"# out-dir   : {out_dir}")
    print(f"# raster    : {size}px   render-width {width}   projection {projection}")
    print()

    total_px = size * size
    rows = []
    for i, entry in enumerate(maps):
        label = entry.get("label") or f"{Path(entry['chart']).parent.name}/{entry['style']}"
        if args.only and args.only not in label:
            continue
        chart = entry["chart"]
        style = entry["style"]
        golden = resolve_golden(entry.get("golden", "auto"), chart, style)
        ad_ref = resolve_golden(entry.get("ad_ref"), chart, style)

        row = {"label": label, "style": style, "dims": "-",
               "kat_strict": None, "kat_fuzz": None,
               "ad_strict": None, "ad_fuzz": None, "note": ""}

        if not Path(chart).exists():
            row["note"] = "chart missing"
            rows.append(row)
            print(f"[{i}] {label}: chart missing ({chart})")
            continue

        stem = re.sub(r"[^A-Za-z0-9._-]", "_", label)
        native_pdf = out_dir / f"{stem}.native.pdf"
        err = render_native(build_dir, chart, style, width, projection, native_pdf, args.timeout)
        if err:
            row["note"] = err
            rows.append(row)
            print(f"[{i}] {label}: {err}")
            continue

        native_png = rasterise(native_pdf, out_dir / f"{stem}.native", size, args.timeout, magick_tmp)
        if native_png is None:
            row["note"] = "native rasterise failed"
            rows.append(row)
            print(f"[{i}] {label}: native rasterise failed")
            continue
        row["dims"] = dimensions(native_png, args.timeout, magick_tmp)

        montage_imgs = [("native", native_png)]

        if golden:
            gpng = rasterise(Path(golden), out_dir / f"{stem}.kateri", size, args.timeout, magick_tmp)
            if gpng:
                row["kat_strict"] = compare_ae(native_png, gpng, args.timeout, magick_tmp)
                row["kat_fuzz"] = compare_ae(native_png, gpng, args.timeout, magick_tmp, fuzz="30%")
                montage_imgs.append(("kateri", gpng))
            else:
                row["note"] = "kateri golden rasterise failed"
        else:
            row["note"] = "no kateri golden"

        if ad_ref:
            apng = rasterise(Path(ad_ref), out_dir / f"{stem}.ad", size, args.timeout, magick_tmp)
            if apng:
                row["ad_strict"] = compare_ae(native_png, apng, args.timeout, magick_tmp)
                row["ad_fuzz"] = compare_ae(native_png, apng, args.timeout, magick_tmp, fuzz="30%")
                montage_imgs.append(("AD", apng))

        if args.montage and len(montage_imgs) > 1:
            montage(montage_imgs, out_dir / f"{stem}.montage.png", args.timeout, magick_tmp)

        rows.append(row)
        print(f"[{i}] {label}: kateri strict {fmt_pct(row['kat_strict'], total_px)}"
              f"  fuzz30 {fmt_pct(row['kat_fuzz'], total_px)}"
              + (f"  | AD strict {fmt_pct(row['ad_strict'], total_px)}"
                 f" fuzz30 {fmt_pct(row['ad_fuzz'], total_px)}" if ad_ref else "")
              + (f"   ({row['note']})" if row['note'] else ""))

    write_scoreboard(rows, out_dir, total_px)
    print()
    print_table(rows, total_px)
    print(f"\nscoreboard: {out_dir}/scoreboard.md , {out_dir}/scoreboard.csv")
    return 0


def _cell(count: int | None, total: int) -> str:
    if count is None:
        return "n/a"
    return f"{count} ({100.0*count/total:.2f}%)"


def print_table(rows: list[dict], total: int) -> None:
    hdr = f"{'label':<34} {'dims':>9} {'kateri strict':>16} {'kateri fuzz30':>16} {'AD strict':>16} {'AD fuzz30':>16}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(f"{r['label'][:34]:<34} {r['dims']:>9} "
              f"{_cell(r['kat_strict'], total):>16} {_cell(r['kat_fuzz'], total):>16} "
              f"{_cell(r['ad_strict'], total):>16} {_cell(r['ad_fuzz'], total):>16}"
              + (f"  [{r['note']}]" if r['note'] else ""))


def write_scoreboard(rows: list[dict], out_dir: Path, total: int) -> None:
    with (out_dir / "scoreboard.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["label", "style", "dims", "total_px",
                    "kateri_strict_ae", "kateri_strict_pct",
                    "kateri_fuzz30_ae", "kateri_fuzz30_pct",
                    "ad_strict_ae", "ad_strict_pct",
                    "ad_fuzz30_ae", "ad_fuzz30_pct", "note"])
        for r in rows:
            def pc(x):
                return "" if x is None else f"{100.0*x/total:.3f}"
            w.writerow([r["label"], r["style"], r["dims"], total,
                        r["kat_strict"] if r["kat_strict"] is not None else "", pc(r["kat_strict"]),
                        r["kat_fuzz"] if r["kat_fuzz"] is not None else "", pc(r["kat_fuzz"]),
                        r["ad_strict"] if r["ad_strict"] is not None else "", pc(r["ad_strict"]),
                        r["ad_fuzz"] if r["ad_fuzz"] is not None else "", pc(r["ad_fuzz"]),
                        r["note"]])
    md = ["# P2 renderer fidelity scoreboard", "",
          "native-vs-kateri (and native-vs-AD where isolable) differing-pixel counts,",
          "at strict and `-fuzz 30%`. Lower is better; % is of total raster pixels.", "",
          "| map | dims | kateri strict | kateri fuzz30 | AD strict | AD fuzz30 | note |",
          "|-----|------|---------------|---------------|-----------|-----------|------|"]
    for r in rows:
        md.append(f"| {r['label']} | {r['dims']} | {_cell(r['kat_strict'], total)} | "
                  f"{_cell(r['kat_fuzz'], total)} | {_cell(r['ad_strict'], total)} | "
                  f"{_cell(r['ad_fuzz'], total)} | {r['note']} |")
    (out_dir / "scoreboard.md").write_text("\n".join(md) + "\n")


if __name__ == "__main__":
    sys.exit(main())
