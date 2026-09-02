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
# Straight-through uses same yellow thickness as scripts/generate_ortho_tiles.py (2px);
# outer white is 1px so it matches corner/road weight after iso (2px yellow reads similar to road).
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


def _corner_bands(cells: int) -> tuple[int, list[tuple[tuple[int, int, int], int, int]]]:
    """Return (size, bands) with the same radii as make_corner."""
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
    return size, bands


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
    size, bands = _corner_bands(cells)
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


def _fillet_white_radii(cells: int) -> tuple[int, int, int, int]:
    """size, inner_r, inner-white r_in, inner-white r_out."""
    size, bands = _corner_bands(cells)
    inner_r = min(b[1] for b in bands)
    whites = [(c, ri, ro) for c, ri, ro in bands if c == WHITE]
    if whites:
        _wc, w_in, w_out = whites[-1]
    else:
        w_in, w_out = inner_r, inner_r + 2
    return size, inner_r, w_in, w_out


def _stroke_fillet_lip(img, cells: int, quadrant: int) -> None:
    """Inner curb white + grass-bite punch, drawn last so sibling greys cannot hide it."""
    if ImageDraw is None:
        return
    size, inner_r, w_in, w_out = _fillet_white_radii(cells)
    arc_cx, arc_cy, start_angle, end_angle = _arc_center(quadrant, size)
    draw = ImageDraw.Draw(img)
    bbox_w = (arc_cx - w_out, arc_cy - w_out, arc_cx + w_out, arc_cy + w_out)
    draw.pieslice(bbox_w, start_angle, end_angle, fill=(*WHITE, 255))
    if w_in > 0:
        bbox_g = (arc_cx - w_in, arc_cy - w_in, arc_cx + w_in, arc_cy + w_in)
        draw.pieslice(bbox_g, start_angle, end_angle, fill=(*ROAD_GREY, 255))
    bbox_inner = (arc_cx - inner_r, arc_cy - inner_r, arc_cx + inner_r, arc_cy + inner_r)
    draw.pieslice(bbox_inner, start_angle, end_angle, fill=(0, 0, 0, 0))


def make_corner_fillet(cells: int = 4, quadrant: int = 0):
    """
    AABB-corner grass bite plus grey pavement and the inner curb white.
    No turn yellows and no outer white — those collide when four corners meet.
    """
    if Image is None or ImageDraw is None:
        raise RuntimeError("Pillow required for corner generation: pip install Pillow")

    cells = max(2, min(12, cells))
    if cells % 2 != 0:
        cells = (cells // 2) * 2
    size, bands = _corner_bands(cells)
    arc_cx, arc_cy, start_angle, end_angle = _arc_center(quadrant, size)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    outer_r = max(b[2] for b in bands)
    inner_r = min(b[1] for b in bands)
    whites = [(c, ri, ro) for c, ri, ro in bands if c == WHITE]
    if whites:
        _wc, w_in, w_out = whites[-1]
    else:
        w_in, w_out = inner_r, inner_r + 2

    bbox_base = (arc_cx - outer_r, arc_cy - outer_r, arc_cx + outer_r, arc_cy + outer_r)
    draw.pieslice(bbox_base, start_angle, end_angle, fill=(*ROAD_GREY, 255))
    bbox_w = (arc_cx - w_out, arc_cy - w_out, arc_cx + w_out, arc_cy + w_out)
    draw.pieslice(bbox_w, start_angle, end_angle, fill=(*WHITE, 255))
    if w_in > 0:
        bbox_g = (arc_cx - w_in, arc_cy - w_in, arc_cx + w_in, arc_cy + w_in)
        draw.pieslice(bbox_g, start_angle, end_angle, fill=(*ROAD_GREY, 255))
    bbox_inner = (arc_cx - inner_r, arc_cy - inner_r, arc_cx + inner_r, arc_cy + inner_r)
    draw.pieslice(bbox_inner, start_angle, end_angle, fill=(0, 0, 0, 0))
    return img


def make_straight_through(cells: int = 4, axis: str = "ns", omit_white: str | None = None):
    """
    Ortho patch for straight-through intersections: grey only on the dual-carriageway band (two ortho
    cells); outside stays transparent so the iso sprite does not paint a full diamond over grass.

    Yellow median: two 1px lines (same stroke as outer white); exactly 6 grey px between them (split-4 and split+3).
    axis 'ns' = through traffic N–S → horizontal ortho stripes (like road_n/road_s); 'ew' = through E–W → vertical (like road_e/road_w).
    omit_white: 'lo' skips the low-ortho-edge white (top / left of the band); 'hi' skips the high-ortho-edge white;
    'both' skips both (through-lines only, for cross/tee composites).
    """
    if Image is None or ImageDraw is None:
        raise RuntimeError("Pillow required: pip install Pillow")

    cells = max(2, min(12, cells))
    if cells % 2 != 0:
        cells = (cells // 2) * 2

    size = cells * ORTHO_TILE_SIZE
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    t = ORTHO_TILE_SIZE
    c0 = (cells // 2 - 1) * t
    c1 = (cells // 2) * t
    xa, xb = c0, c1 + t

    # Road pavement: central two ortho cells only (not the full patch — avoids oversized grey diamond).
    if axis == "ns":
        draw.rectangle((0, c0, size, c1 + t), fill=(*ROAD_GREY, 255))
    else:
        draw.rectangle((c0, 0, c1 + t, size), fill=(*ROAD_GREY, 255))
    # Outer white column matches generate_ortho_tiles WHITE_LO (28) on the right-hand tile.
    white_outer_right = c1 + 28

    def v_white_outer_1px(x: int) -> None:
        draw.rectangle((x, 0, x + 1, size), fill=(*WHITE, 255))

    def h_white_outer_1px(y: int) -> None:
        draw.rectangle((0, y, size, y + 1), fill=(*WHITE, 255))

    split = c1
    if axis == "ns":
        ya, yb = c0, c1 + t
        white_outer_bottom = c1 + 28
        if omit_white not in ("lo", "both"):
            h_white_outer_1px(ya + 2)
        if omit_white not in ("hi", "both"):
            h_white_outer_1px(white_outer_bottom)
        _stroke_through_yellows(draw, size, split, "ns")
    else:
        if omit_white not in ("lo", "both"):
            v_white_outer_1px(xa + 2)
        if omit_white not in ("hi", "both"):
            v_white_outer_1px(white_outer_right)
        _stroke_through_yellows(draw, size, split, "ew")

    return img


def _stroke_through_yellows(draw, size: int, split: int, axis: str) -> None:
    """Dual 1px yellows at the dual-lane split (same coords as make_straight_through)."""
    if axis == "ns":
        draw.rectangle((0, split - 4, size, split - 3), fill=(*YELLOW, 255))
        draw.rectangle((0, split + 3, size, split + 4), fill=(*YELLOW, 255))
    else:
        draw.rectangle((split - 4, 0, split - 3, size), fill=(*YELLOW, 255))
        draw.rectangle((split + 3, 0, split + 4, size), fill=(*YELLOW, 255))


def _restroke_axis_yellows(img, cells: int, axis: str) -> None:
    if ImageDraw is None:
        return
    _size, _c0, c1, _band_hi = _band_rect(cells)
    draw = ImageDraw.Draw(img)
    _stroke_through_yellows(draw, img.size[0], c1, axis)


def _restroke_open_side_white(img, cells: int, axis: str, omit_white: str | None) -> None:
    """Redraw the through-band white that is not the stem join, after fillets."""
    if ImageDraw is None:
        return
    size, c0, c1, _band_hi = _band_rect(cells)
    draw = ImageDraw.Draw(img)
    if axis == "ns":
        ya = c0
        white_outer_bottom = c1 + 28
        if omit_white != "lo":
            draw.rectangle((0, ya + 2, size, ya + 3), fill=(*WHITE, 255))
        if omit_white != "hi":
            draw.rectangle((0, white_outer_bottom, size, white_outer_bottom + 1), fill=(*WHITE, 255))
    else:
        xa = c0
        white_outer_right = c1 + 28
        if omit_white != "lo":
            draw.rectangle((xa + 2, 0, xa + 3, size), fill=(*WHITE, 255))
        if omit_white != "hi":
            draw.rectangle((white_outer_right, 0, white_outer_right + 1, size), fill=(*WHITE, 255))


def _band_rect(cells: int) -> tuple[int, int, int, int]:
    """size, c0, band_hi (exclusive-ish bottom/right of the dual-cell band)."""
    cells = max(2, min(12, cells))
    if cells % 2 != 0:
        cells = (cells // 2) * 2
    t = ORTHO_TILE_SIZE
    c0 = (cells // 2 - 1) * t
    c1 = (cells // 2) * t
    return cells * t, c0, c1, c1 + t


def _clear_open_half(img, cells: int, axis: str, stem: str) -> None:
    """Punch the overlay half opposite the tee stem (the open face)."""
    if ImageDraw is None:
        return
    size, c0, _c1, band_hi = _band_rect(cells)
    draw = ImageDraw.Draw(img)
    clear = (0, 0, 0, 0)
    if axis == "ns":
        if stem == "E":
            draw.rectangle((0, band_hi, size, size), fill=clear)
        elif stem == "W":
            draw.rectangle((0, 0, size, c0), fill=clear)
    else:
        if stem == "N":
            draw.rectangle((band_hi, 0, size, size), fill=clear)
        elif stem == "S":
            draw.rectangle((0, 0, c0, size), fill=clear)


def make_cross(cells: int = 4):
    """Four-way: filleted AABB corners only. No through-band yellows or arm whites."""
    if Image is None:
        raise RuntimeError("Pillow required for cross generation: pip install Pillow")
    cells = max(2, min(12, cells))
    if cells % 2 != 0:
        cells = (cells // 2) * 2
    size = cells * ORTHO_TILE_SIZE
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    for q in range(4):
        img = Image.alpha_composite(img, make_corner_fillet(cells, quadrant=q))
    for q in range(4):
        _stroke_fillet_lip(img, cells, q)
    return img


def make_tee(cells: int = 4, axis: str = "ns", stem: str = "E"):
    """
    Through dual-lane lines plus two stem-side corner fillets.

    Stem-side white of the through-band is omitted so the fillet can bend it into
    the branch. The open face (opposite the stem) stays transparent — no stub.
    """
    if Image is None:
        raise RuntimeError("Pillow required for tee generation: pip install Pillow")
    from render.intersection_topology import tee_corner_quadrants

    omit_white: str | None = None
    if axis == "ns":
        if stem == "E":
            omit_white = "lo"
        elif stem == "W":
            omit_white = "hi"
    else:
        if stem == "N":
            omit_white = "lo"
        elif stem == "S":
            omit_white = "hi"

    img = make_straight_through(cells, axis=axis, omit_white=omit_white)
    quads = tee_corner_quadrants(stem)  # type: ignore[arg-type]
    for q in quads:
        img = Image.alpha_composite(img, make_corner_fillet(cells, quadrant=q))
    _restroke_axis_yellows(img, cells, axis)
    _restroke_open_side_white(img, cells, axis, omit_white)
    for q in quads:
        _stroke_fillet_lip(img, cells, q)
    _clear_open_half(img, cells, axis, stem)
    return img
