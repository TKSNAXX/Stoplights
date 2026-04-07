"""
Runtime corner sprite generation. Shared algo for scripts and render.
Corner size = cells * 32 ortho pixels. Band radii offset (not scaled):
+32px distance to inner corner per 2-cell step; bands remain 2px wide.
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

# Base band radii for 4-cell corner (128x128). Offset by (cells-4)*16 for others.
# Band width stays 2px; distance to inner corner +32px per 2-cell step.
_CORNER_BANDS_BASE = [
    (ROAD_GREY, 95, 97),
    (WHITE, 93, 95),
    (YELLOW, 67, 69),
    (YELLOW, 61, 63),
    (WHITE, 35, 37),
    (ROAD_GREY, 33, 35),
]
_CORNER_ALIGN_OFFSET_BASE = -2

# (arc_cx is 0 or size-1, arc_cy is 0 or size-1) via flags; then start/end angle (PIL degrees).
_CORNER_ARC_PRESETS: list[tuple[int, int, int, int]] = [
    (0, 1, 270, 360),  # cx=0, cy=size-1 — W+N arms (quadrant 0)
    (1, 1, 180, 270),  # SE corner of image
    (1, 0, 90, 180),
    (0, 0, 0, 90),
]


def _arc_center(quadrant: int, size: int) -> tuple[int, int, int, int]:
    q = quadrant % 4
    cx_flag, cy_flag, start_a, end_a = _CORNER_ARC_PRESETS[q]
    arc_cx = (size - 1) if cx_flag else 0
    arc_cy = (size - 1) if cy_flag else 0
    return arc_cx, arc_cy, start_a, end_a


def make_corner(cells: int = 4, quadrant: int = 0):
    """
    Generate corner ortho image for given cell count. Size = cells * 32.
    quadrant 0..3 selects arc corner / sweep (W+N, N+E, E+S, S+W connectivity).
    """
    if Image is None or ImageDraw is None:
        raise RuntimeError("Pillow required for corner generation: pip install Pillow")

    cells = max(2, min(12, cells))
    if cells % 2 != 0:
        cells = (cells // 2) * 2

    size = cells * ORTHO_TILE_SIZE
    radius_offset = (cells - 4) * 16
    align = _CORNER_ALIGN_OFFSET_BASE
    max_r = size - 1

    def clamp(r: int) -> int:
        return max(0, min(r, max_r))

    bands = []
    for color, r_in, r_out in _CORNER_BANDS_BASE:
        ri = clamp(r_in + radius_offset + align)
        ro = clamp(r_out + radius_offset + align)
        if ro <= ri:
            ro = ri + 2
        bands.append((color, ri, ro))

    arc_cx, arc_cy, start_angle, end_angle = _arc_center(quadrant, size)

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    outer_r = max(b[2] for b in bands)
    inner_r = min(b[1] for b in bands)

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


def make_straight_through(cells: int = 4, axis: str = "ns"):
    """
    Ortho patch: flat ROAD_GREY with a single dual carriageway through the centre two tiles.

    One double-yellow median between directions, yellow outer edges, white centreline in each lane
    (avoids four parallel yellows from drawing two independent lane strips).
    axis 'ns' = travel N–S (markings run vertically); 'ew' = travel E–W (markings horizontal).
    """
    if Image is None or ImageDraw is None:
        raise RuntimeError("Pillow required: pip install Pillow")

    cells = max(2, min(12, cells))
    if cells % 2 != 0:
        cells = (cells // 2) * 2

    size = cells * ORTHO_TILE_SIZE
    img = Image.new("RGBA", (size, size), (*ROAD_GREY, 255))
    draw = ImageDraw.Draw(img)

    t = ORTHO_TILE_SIZE
    c0 = (cells // 2 - 1) * t
    c1 = (cells // 2) * t
    xa, xb = c0, c1 + t

    def v_line(x0: int, x1: int) -> None:
        draw.rectangle((x0, 0, x1, size), fill=(*YELLOW, 255))

    def v_white(x0: int, x1: int) -> None:
        draw.rectangle((x0, 0, x1, size), fill=(*WHITE, 255))

    def h_line(y0: int, y1: int) -> None:
        draw.rectangle((0, y0, size, y1), fill=(*YELLOW, 255))

    def h_white(y0: int, y1: int) -> None:
        draw.rectangle((0, y0, size, y1), fill=(*WHITE, 255))

    if axis == "ew":
        ya, yb = c0, c1 + t
        split = c1
        h_line(ya + 2, ya + 4)
        h_line(yb - 4, yb - 2)
        h_line(split - 2, split)
        h_line(split + 1, split + 3)
        mid0 = ya + t // 2
        mid1 = c1 + t // 2
        h_white(mid0 - 1, mid0 + 1)
        h_white(mid1 - 1, mid1 + 1)
    else:
        v_line(xa + 2, xa + 4)
        v_line(xb - 4, xb - 2)
        split = c1
        v_line(split - 2, split)
        v_line(split + 1, split + 3)
        mid0 = xa + t // 2
        mid1 = c1 + t // 2
        v_white(mid0 - 1, mid0 + 1)
        v_white(mid1 - 1, mid1 + 1)

    return img
