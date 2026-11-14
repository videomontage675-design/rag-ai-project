"""Generate the Dafira braid mark (ضفيرة = braid) as SVG files.

Three strands follow sine waves shifted by a third of a period. Each strand is split into
runs at its crossings; runs that pass under another strand are drawn first, so the strands
alternate over and under like a real three-strand plait (in a twisted rope, by contrast, one
strand stays in front). A paper-coloured halo under each run separates strands at crossings.

Usage: python tools/brand/make_braid.py   (writes into src/rag_app/web/static/brand/)
"""

from __future__ import annotations

import math
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "src" / "rag_app" / "web" / "static" / "brand"
STRANDS = ("#3346A0", "#17766A", "#D99A1E")  # indigo, teal, saffron (docs/07_UI_AND_IDENTITY.md)
PAPER = "#F6F7FB"


def braid(length: float, width: float, period: float, *, vertical: bool, steps: int) -> str:
    """Return SVG <path> elements for a braid running along the main axis."""
    amp = width / 2 - 3
    back: list[str] = []
    front: list[str] = []
    for i, colour in enumerate(STRANDS):
        phase = i * 2 * math.pi / 3
        run: list[tuple[float, float]] = []
        run_front = None
        for s in range(steps + 1):
            t = 2 + (length - 4) * s / steps
            angle = 2 * math.pi * t / period + phase
            offset = width / 2 + amp * math.sin(angle)
            point = (offset, t) if vertical else (t, offset)
            # Plait rule: over, under, over, under at successive crossings (crossings at
            # angle = 30°, 150°, 210°, 330°), unlike a rope where depth follows cos(angle).
            is_front = math.cos(2 * angle - math.pi / 3) >= 0
            if run_front is not None and is_front != run_front:
                run.append(point)  # close the run exactly where the next one starts
                (front if run_front else back).append(_path(run, colour))
                run = []
            run.append(point)
            run_front = is_front
        (front if run_front else back).append(_path(run, colour))
    return "".join(back + front)


def _path(points: list[tuple[float, float]], colour: str) -> str:
    """One strand run: a paper-coloured halo under a coloured stroke."""
    d = "M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in points)
    return (
        f'<path d="{d}" stroke="{PAPER}" stroke-width="5.6"/>'
        f'<path d="{d}" stroke="{colour}" stroke-width="3.2"/>'
    )


def svg(w: float, h: float, body: str, title: str) -> str:
    """Wrap paths in an accessible SVG document."""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" role="img" '
        f'fill="none" stroke-linecap="round"><title>{title}</title>{body}</svg>\n'
    )


def main() -> None:
    """Write the mark (square, for the header and favicon) and the progress strip."""
    OUT.mkdir(parents=True, exist_ok=True)
    mark = braid(40, 28, 38, vertical=True, steps=64)
    (OUT / "braid-mark.svg").write_text(
        svg(28, 40, mark, "ضفيرة"), encoding="utf-8"
    )
    favicon = f'<rect width="40" height="40" rx="9" fill="{PAPER}"/><g transform="translate(6 0)">{mark}</g>'
    (OUT / "favicon.svg").write_text(svg(40, 40, favicon, "ضفيرة"), encoding="utf-8")
    # Two periods long, so sliding it by one period loops seamlessly (processing indicator).
    strip = braid(2 * 30 + 4, 20, 30, vertical=False, steps=96)
    (OUT / "braid-strip.svg").write_text(svg(64, 20, strip, ""), encoding="utf-8")


if __name__ == "__main__":
    main()
