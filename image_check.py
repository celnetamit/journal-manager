"""Are the manuscript's images good enough to print?

This is the check an editorial team does by hand and the one a .docx can answer
exactly. Word stores two things about every inline picture: the file, which has a
pixel size, and the frame, which has a size on the page in inches. Divide them and
you have the effective resolution at the size it will actually be printed — which is
the only resolution that means anything.

Print wants 300 DPI. Both manuscripts checked when this was written had **every**
image below it: 198, 221, 152 and 193 DPI in one, 220 and 205 in the other. Nothing in
the tool had ever looked.

Reported, never changed. An image cannot be fixed by editing the document — the author
has to supply a larger original — so the only useful action is to say so early, while
they are still reachable.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import List, Optional

#: The print standard. Below this an image is soft on paper; below the second
#: threshold it is visibly blocky and no amount of care at layout will rescue it.
PRINT_DPI = 300
UNUSABLE_DPI = 150

#: An image so small on the page that its DPI is arbitrary — an icon, a logo, an
#: inline symbol. Checking those produces findings nobody can act on.
_MIN_INCHES = 0.6


@dataclass
class ImageFinding:
    rule: str
    severity: str
    paragraph: Optional[int]
    message: str
    detail: str = ""

    def __str__(self) -> str:
        return f"[{self.severity}] image {self.rule}: {self.message}"


@dataclass
class ImageFacts:
    index: int
    px_w: int
    px_h: int
    in_w: float
    in_h: float
    dpi: float
    mode: str
    fmt: str
    kb: int


def read_images(document) -> List[ImageFacts]:
    """Pixel size, printed size and effective DPI for every inline picture.

    Needs Pillow, and says so by returning nothing rather than raising: a missing
    optional dependency must not take down a manuscript's whole run.
    """
    try:
        from PIL import Image
    except ImportError:
        return []

    facts: List[ImageFacts] = []
    for i, shape in enumerate(document.inline_shapes):
        try:
            rid = shape._inline.graphic.graphicData.pic.blipFill.blip.embed
            blob = document.part.related_parts[rid].blob
            img = Image.open(io.BytesIO(blob))
            in_w = shape.width.inches
            in_h = shape.height.inches
        except Exception:                     # noqa: BLE001 — one odd picture only
            continue
        if in_w <= 0 or in_h <= 0:
            continue
        facts.append(ImageFacts(
            index=i, px_w=img.width, px_h=img.height,
            in_w=round(in_w, 2), in_h=round(in_h, 2),
            dpi=round(img.width / in_w, 0),
            mode=img.mode, fmt=img.format or "?", kb=len(blob) // 1024))
    return facts


def check_images(document) -> List[ImageFinding]:
    """Findings for the pictures that will not print well."""
    out: List[ImageFinding] = []
    for f in read_images(document):
        if f.in_w < _MIN_INCHES and f.in_h < _MIN_INCHES:
            continue                          # an icon, not a figure
        where = (f"{f.px_w}x{f.px_h} px shown at {f.in_w}x{f.in_h} in "
                 f"({f.fmt}, {f.kb} KB)")
        if f.dpi < UNUSABLE_DPI:
            out.append(ImageFinding(
                "image.resolution", "error", None,
                f"image {f.index + 1} is {f.dpi:.0f} DPI at the size it is placed; "
                f"below {UNUSABLE_DPI} it will look blocky in print. Ask the author "
                f"for the original file.", where))
        elif f.dpi < PRINT_DPI:
            out.append(ImageFinding(
                "image.resolution", "warning", None,
                f"image {f.index + 1} is {f.dpi:.0f} DPI at the size it is placed; "
                f"print needs {PRINT_DPI}. Either ask for a larger original or place "
                f"it smaller.", where))
    return out
