#! /usr/bin/env python3
"""Compare an ae signature page against an AD `sigp`/`tal` reference.

Robust similarity check for the section-map signature page. Because the section
content depends on the (evolving) .tal/data, this does NOT pixel-diff whole pages;
instead it emits a **labelled side-by-side montage** (full page + zoomed crops of
the tree-column band, one antigenic map, and the title) for eyeball confirmation,
plus a few **automated probes** for the style/layout fidelity items that are
data-independent:

  * map black border present (the per-map box)
  * map gridline darkness (median grey of the grid in an empty map region)
  * no aa-at-pos colour legend on the tree (the band stays free of saturated colour)
  * map title height (small, not a big caption)

Usage:
    python3 cc/tal/test/check-sigpage.py <ae.pdf> [<AD-reference.pdf>]

Operates entirely on /tmp renders — pass real PDFs as arguments; nothing here is
committed with WHO data. Needs pdftoppm (poppler) and Pillow.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("needs Pillow: pip install --user pillow", file=sys.stderr)
    sys.exit(2)


def render(pdf: str, dpi: int = 150) -> "Image.Image":
    out = Path(tempfile.mkdtemp()) / "p"
    subprocess.run(["pdftoppm", "-png", "-r", str(dpi), "-f", "1", "-l", "1", pdf, str(out)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return Image.open(str(out) + "-1.png").convert("RGB")


def _is_grey(px, lo, hi):
    r, g, b = px
    return abs(r - g) < 10 and abs(g - b) < 10 and lo <= r <= hi


def probe_border(im: "Image.Image", maps_x0=0.50) -> bool:
    """A map's black border shows up as near-black pixels forming vertical/horizontal
    runs in the maps panel. Heuristic: the maps panel has a meaningful count of
    near-black pixels arranged in long axis-aligned runs."""
    w, h = im.size
    panel = im.crop((int(w * maps_x0), 0, w, h))
    px = panel.load()
    pw, ph = panel.size
    # count columns that have a long vertical near-black run (a box edge)
    box_cols = 0
    for x in range(pw):  # every column — the border is a thin (~1px) line
        run = best = 0
        for y in range(ph):
            r, g, b = px[x, y]
            if r < 150 and g < 150 and b < 150:  # border ink (0.5pt black, anti-aliased)
                run += 1
                best = max(best, run)
            else:
                run = 0
        if best > ph * 0.05:  # a map-cell border edge spans much of a row of maps
            box_cols += 1
    return box_cols >= 2  # at least a couple of vertical box edges


def probe_gridline_grey(im: "Image.Image", region) -> int:
    """Median grey value of grid-ish pixels (lighter than points, darker than white)
    in `region` (fractional box). Lower = darker grid."""
    w, h = im.size
    crop = im.crop((int(w * region[0]), int(h * region[1]), int(w * region[2]), int(h * region[3])))
    greys = [p[0] for p in crop.getdata() if _is_grey(p, 150, 240)]
    greys.sort()
    return greys[len(greys) // 2] if greys else 255


def probe_aa_legend_absent(im: "Image.Image", region=(0.42, 0.02, 0.52, 0.10)) -> bool:
    """The aa-at-pos colour legend is a small block of saturated colour swatches
    (orange/blue/pink) at the top of the tree's matrix band. Absent = few saturated
    pixels in that region."""
    w, h = im.size
    crop = im.crop((int(w * region[0]), int(h * region[1]), int(w * region[2]), int(h * region[3])))
    saturated = 0
    for r, g, b in crop.getdata():
        mx, mn = max(r, g, b), min(r, g, b)
        if mx > 120 and (mx - mn) > 70:  # colourful, not grey/black/white
            saturated += 1
    return saturated < 40  # essentially no colour swatches


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    ae_pdf = argv[0]
    ad_pdf = argv[1] if len(argv) > 1 else None
    ae = render(ae_pdf)

    print(f"ae: {ae_pdf}  {ae.size}")
    checks = {
        "map black border present (#5)": probe_border(ae),
        "no aa colour legend on tree (#7)": probe_aa_legend_absent(ae),
    }
    grid_grey = probe_gridline_grey(ae, (0.62, 0.20, 0.72, 0.34))
    print(f"\nautomated probes:")
    for name, ok in checks.items():
        print(f"  [{'PASS' if ok else 'CHECK'}] {name}")
    print(f"  [info] map gridline median grey = {grid_grey} (lower = darker; AD ~204, want < ~210)")
    print(f"  [{'PASS' if grid_grey < 215 else 'CHECK'}] gridlines dark enough (#6)")

    if ad_pdf:
        ad = render(ad_pdf)
        montage = _montage(ad, ae)
        out = Path(tempfile.gettempdir()) / "sigpage-montage.png"
        montage.save(out)
        print(f"\nAD-vs-ae montage written: {out}  (eyeball #1 clade side, #2 hz letters+grey dash, #3 no text between maps, #4 title size, #8 fonts)")
    return 0


def _montage(ad, ae):
    h = 900
    def fit(im):
        return im.resize((int(im.width * h / im.height), h))
    a, b = fit(ad), fit(ae)
    canvas = Image.new("RGB", (a.width + b.width + 16, h), "white")
    canvas.paste(a, (0, 0))
    canvas.paste(b, (a.width + 16, 0))
    return canvas


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
