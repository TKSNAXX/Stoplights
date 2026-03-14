"""
Runtime corner sprite generation. Shared algo for scripts and render.
Corner size scales with cell count (cells * 32 ortho pixels).
"""
from __future__ import annotations

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None
    ImageDraw = None

from sim.constants import ORTHO_TILE_SIZE

ROAD_GREY = (90, 90, 90)
YELLOW = (220, 220, 80)
WHITE = (220, 220, 220)

# Base band radii for 4-cell corner (128x128). Scale by cells/4 for other sizes.
# Arc center at NW corner (0, size-1). Arc 270->360°.
_CORNER_BANDS_BASE = [
    (ROAD_GREY, 95, 97),
    (WHITE, 93, 95),
    (YELLOW, 67, 69),
    (YELLOW, 61, 63),
    (WHITE, 35, 37),
    (ROAD_GREY, 33, 35),
]
_CORNER_ALIGN_OFFSET_BASE = -2


def make_corner(cells: int = 4):
    """
    Generate corner ortho image for given cell count. Size = cells * 32.
    Arc bands scale proportionally from 4-cell reference.
    """
    if Image is None or ImageDraw is None:
        raise RuntimeError("Pillow required for corner generation: pip install Pillow")

    cells = max(2, min(12, cells))
    if cells % 2 != 0:
        cells = (cells // 2) * 2

    size = cells * ORTHO_TILE_SIZE
    scale = cells / 4.0

    def scale_r(r: int) -> int:
        return max(0, int(round(r * scale)))

    offset = int(round(_CORNER_ALIGN_OFFSET_BASE * scale))
    bands = [(color, scale_r(r_in) + offset, scale_r(r_out) + offset) for color, r_in, r_out in _CORNER_BANDS_BASE]

    arc_cx = 0
    arc_cy = size - 1
    start_angle, end_angle = 270, 360

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    outer_r = max(r_out for _, _, r_out in bands)
    inner_r = min(r_in for _, r_in, _ in bands)

    bbox_base = (arc_cx - outer_r, arc_cy - outer_r, arc_cx + outer_r, arc_cy + outer_r)
    draw.pieslice(bbox_base, start_angle, end_angle, fill=(*ROAD_GREY, 255))

    for color, r_inner, r_outer in bands:
        bbox = (arc_cx - r_outer, arc_cy - r_outer, arc_cx + r_outer, arc_cy + r_outer)
        draw.pieslice(bbox, start_angle, end_angle, fill=(*color, 255))
        if r_inner > 0:
            inner_bbox = (arc_cx - r_inner, arc_cy - r_inner, arc_cx + r_inner, arc_cy + r_inner)
            draw.pieslice(inner_bbox, start_angle, end_angle, fill=(*ROAD_GREY, 255))

    bbox_inner = (arc_cx - inner_r, arc_cy - inner_r, arc_cx + inner_r, arc_cy + inner_r)
    draw.pieslice(bbox_inner, start_angle, end_angle, fill=(0, 0, 0, 0))

    return img
