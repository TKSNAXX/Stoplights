"""
Runtime corner sprite generation. Shared algo for scripts and render.
Corner size = cells * 32 ortho pixels. Band radii offset (not scaled):
+32px distance to inner corner per 2-cell step; bands remain 2px wide.
"""
from __future__ import annotations

import math

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None
    ImageDraw = None

from render.lane_paint import CURB_INSET, CURB_WIDTH, DRIVER_LEFT
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
# Clockwise from ortho bottom-left. After ortho→iso: BL=NW, BR=SW, TR=SE, TL=NE.
_CORNER_ARC_PRESETS: list[tuple[int, int, int, int]] = [
    (0, 1, 270, 360),  # q0 image BL → W+N
    (1, 1, 180, 270),  # q1 image BR → S+W
    (1, 0, 90, 180),   # q2 image TR → E+S
    (0, 0, 0, 90),     # q3 image TL → N+E
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


def make_corner(cells: int = 4, quadrant: int = 0, paint_thru_lines: bool = True):
    """
    Generate corner ortho image for given cell count. Size = cells * 32.
    quadrant 0..3 selects arc corner / sweep (W+N, S+W, E+S, N+E connectivity).
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
        if color == YELLOW:
            continue
        bbox = (arc_cx - r_outer, arc_cy - r_outer, arc_cx + r_outer, arc_cy + r_outer)
        draw.pieslice(bbox, start_angle, end_angle, fill=(*color, 255))
        if r_inner > 0:
            inner_bbox = (arc_cx - r_inner, arc_cy - r_inner, arc_cx + r_inner, arc_cy + r_inner)
            draw.pieslice(inner_bbox, start_angle, end_angle, fill=(*ROAD_GREY, 255))

    bbox_inner = (arc_cx - inner_r, arc_cy - inner_r, arc_cx + inner_r, arc_cy + inner_r)
    draw.pieslice(bbox_inner, start_angle, end_angle, fill=(0, 0, 0, 0))
    if paint_thru_lines:
        from render.thru_lines import stroke_thru_lines

        stroke_thru_lines(img, cells, "corner", quadrant=quadrant, paint=True)
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


def _fill_stem_shoulder(img, cells: int, axis: str, stem: str) -> None:
    """Opaque grey on the branch side of the through-band (not the open face)."""
    if ImageDraw is None:
        return
    size, c0, _c1, band_hi = _band_rect(cells)
    draw = ImageDraw.Draw(img)
    fill = (*ROAD_GREY, 255)
    if axis == "ns":
        if stem == "E":
            draw.rectangle((0, 0, size, c0), fill=fill)
        elif stem == "W":
            draw.rectangle((0, band_hi, size, size), fill=fill)
    else:
        if stem == "N":
            draw.rectangle((0, 0, c0, size), fill=fill)
        elif stem == "S":
            draw.rectangle((band_hi, 0, size, size), fill=fill)


def _stroke_fillet_lip(
    img,
    cells: int,
    quadrant: int,
    inner_r: int | None = None,
    origin: tuple[int, int] | None = None,
    color: tuple[int, int, int] = WHITE,
) -> None:
    """Inner curb white + optional grass-bite punch.

    inner_r 0 is a micro-fillet: curb-pack quarter-ring, no punch, so the white
    pops out to the lane curb instead of terminating as a square L.
    """
    if ImageDraw is None:
        return
    size = max(2, min(12, cells))
    if size % 2 != 0:
        size = (size // 2) * 2
    size_px = size * ORTHO_TILE_SIZE
    if inner_r is None:
        _sz, inner_r, w_in, w_out = _fillet_white_radii(cells)
    else:
        inner_r = max(0, int(inner_r))
        w_in = inner_r + CURB_INSET
        w_out = inner_r + CURB_INSET + CURB_WIDTH
    arc_cx, arc_cy, start_angle, end_angle = _arc_center(quadrant, size_px)
    if origin is not None:
        arc_cx, arc_cy = int(origin[0]), int(origin[1])
    draw = ImageDraw.Draw(img)
    bbox_w = (arc_cx - w_out, arc_cy - w_out, arc_cx + w_out, arc_cy + w_out)
    draw.pieslice(bbox_w, start_angle, end_angle, fill=(*color, 255))
    if w_in > 0:
        bbox_g = (arc_cx - w_in, arc_cy - w_in, arc_cx + w_in, arc_cy + w_in)
        draw.pieslice(bbox_g, start_angle, end_angle, fill=(*ROAD_GREY, 255))
    if inner_r > 0:
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


def make_straight_through(
    cells: int = 4,
    axis: str = "ns",
    omit_white: str | None = None,
    paint_thru_lines: bool = True,
):
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
    else:
        if omit_white not in ("lo", "both"):
            v_white_outer_1px(xa + 2)
        if omit_white not in ("hi", "both"):
            v_white_outer_1px(white_outer_right)

    if paint_thru_lines:
        from render.thru_lines import stroke_thru_lines

        stroke_thru_lines(img, cells, "straight", axis=axis, paint=True)

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
    """Four-way: grey plaza with filleted AABB corners. No through-band yellows."""
    if Image is None or ImageDraw is None:
        raise RuntimeError("Pillow required for cross generation: pip install Pillow")
    cells = max(2, min(12, cells))
    if cells % 2 != 0:
        cells = (cells // 2) * 2
    size = cells * ORTHO_TILE_SIZE
    img = Image.new("RGBA", (size, size), (*ROAD_GREY, 255))
    for q in range(4):
        _stroke_fillet_lip(img, cells, q)
    return img


def _even_aabb_cells(cells: int) -> int:
    n = max(2, min(12, int(cells)))
    if n % 2:
        n -= 1
    return max(2, n)


def _even_travel_cells(travel: int, cells: int) -> int:
    cells = _even_aabb_cells(cells)
    t = max(2, min(cells, int(travel)))
    if t % 2:
        t -= 1
    return max(2, t)


def _centered_lo_hi(cells: int, travel: int) -> tuple[int, int]:
    """Inclusive cell lo, exclusive hi for an AABB-centred even band."""
    cells = _even_aabb_cells(cells)
    travel = _even_travel_cells(travel, cells)
    lo = (cells - travel) // 2
    return lo, lo + travel


def double_fillet_inner_r(cells: int, travel_cells: int = 4) -> int:
    """Grass-bite radius for a centred even travel bundle; 0 when travel is flush."""
    cells = _even_aabb_cells(cells)
    travel = _even_travel_cells(travel_cells, cells)
    shoulder = max(0, (cells - travel) // 2)
    return shoulder * ORTHO_TILE_SIZE


def _span_width(span: tuple[int, int]) -> int:
    return span[1] - span[0] + 1


def _mouth_widths_equal(spans: dict[str, tuple[int, int]]) -> bool:
    widths = [_span_width(s) for s in spans.values()]
    return len(widths) >= 2 and len(set(widths)) == 1 and widths[0] > 0


def _centered_face_spans(
    cells: int,
    travel_x: int,
    travel_y: int,
    edges: tuple[str, ...] | frozenset[str],
) -> dict[str, tuple[int, int]]:
    xlo, xhi = _centered_lo_hi(cells, travel_x)
    ylo, yhi = _centered_lo_hi(cells, travel_y)
    spans: dict[str, tuple[int, int]] = {}
    for e in edges:
        if e in ("E", "W"):
            spans[e] = (ylo, yhi - 1)
        else:
            spans[e] = (xlo, xhi - 1)
    return spans


def _flip_span(span: tuple[int, int], n: int) -> tuple[int, int]:
    lo, hi = span
    return (n - 1 - hi, n - 1 - lo)


def _image_span_px(span: tuple[int, int], n: int) -> tuple[int, int]:
    """Mouth span in image pixels. N/S → Y and E/W → X, both flipped (iso BL = NW)."""
    return _span_px(_flip_span(span, n))


def make_double(
    cells: int = 8,
    travel_cells: int = 4,
    travel_x: int | None = None,
    travel_y: int | None = None,
):
    """Cross from centred mouth spans; cell fillets where leftover > 0, throat L at 0."""
    from render.intersection_topology import corner_leftovers_from_local

    cells = _even_aabb_cells(cells)
    tx = _even_travel_cells(travel_x if travel_x is not None else travel_cells, cells)
    ty = _even_travel_cells(travel_y if travel_y is not None else travel_cells, cells)
    spans = _centered_face_spans(cells, tx, ty, ("N", "S", "E", "W"))
    leftovers = corner_leftovers_from_local(cells, spans)
    return make_mixed(cells, leftovers, family="cross", spans=spans)


_DOUBLE_CORNER_EDGES: dict[int, tuple[str, str]] = {
    0: ("W", "N"),
    1: ("S", "W"),
    2: ("E", "S"),
    3: ("N", "E"),
}


def make_double_tee(
    cells: int = 8,
    axis: str = "ns",
    stem: str = "E",
    through_travel: int = 4,
    stem_travel: int = 4,
):
    """Tee from centred mouth spans on the three active faces."""
    from render.intersection_topology import corner_leftovers_from_local

    cells = _even_aabb_cells(cells)
    ax = axis if axis in ("ns", "ew") else "ns"
    sm = stem if stem in ("N", "S", "E", "W") else "E"
    th = _even_travel_cells(through_travel, cells)
    st = _even_travel_cells(stem_travel, cells)
    if ax == "ns":
        tx, ty = th, st
        edges: tuple[str, ...] = ("N", "S", sm if sm in ("E", "W") else "E")
    else:
        tx, ty = st, th
        edges = ("E", "W", sm if sm in ("N", "S") else "N")
    spans = _centered_face_spans(cells, tx, ty, edges)
    leftovers = corner_leftovers_from_local(cells, spans)
    return make_mixed(cells, leftovers, family="tee", spans=spans)


def make_double_corner(
    cells: int = 8,
    quadrant: int = 0,
    travel_x: int = 4,
    travel_y: int = 4,
):
    """Equal-width corner annulus from centred mouth spans."""
    from render.intersection_topology import corner_leftovers_from_local

    cells = _even_aabb_cells(cells)
    q = quadrant % 4
    tx = _even_travel_cells(travel_x, cells)
    ty = _even_travel_cells(travel_y, cells)
    spans = _centered_face_spans(cells, tx, ty, _DOUBLE_CORNER_EDGES[q])
    leftovers = corner_leftovers_from_local(cells, spans)
    return make_mixed(cells, leftovers, family="corner", spans=spans)


def make_big(cells: int = 4):
    """Deprecated alias of an unfilleted plaza; Double/Mixed replace this stamp."""
    if Image is None:
        raise RuntimeError("Pillow required for big generation: pip install Pillow")
    cells = max(2, min(12, cells))
    if cells % 2 != 0:
        cells = (cells // 2) * 2
    size = cells * ORTHO_TILE_SIZE
    return Image.new("RGBA", (size, size), (*ROAD_GREY, 255))


def _leftover_box(size: int, quadrant: int, dx: int, dy: int) -> tuple[int, int, int, int]:
    """PIL rectangle (x0, y0, x1, y1) for the AABB leftover of a corner."""
    if quadrant == 0:
        return (0, size - dy, dx, size)
    if quadrant == 1:
        return (size - dx, size - dy, size, size)
    if quadrant == 2:
        return (size - dx, 0, size, dy)
    return (0, 0, dx, dy)


def _leftover_fillet_origin(
    size: int, quadrant: int, dx: int, dy: int, r: int
) -> tuple[int, int]:
    """
    AABB-style arc origin of the mouth-adjacent r×r.

    Same sweep as the AABB fillet, translated so the square sits against both
    mouths. Opposite-quadrant sweep (q+2) mirrored the pie across the join.
    """
    q = quadrant % 4
    if q == 0:
        return (dx - r, min(size - 1, size - dy + r))
    if q == 1:
        return (min(size - 1, size - dx + r), min(size - 1, size - dy + r))
    if q == 2:
        return (min(size - 1, size - dx + r), max(0, dy - r))
    return (max(0, dx - r), max(0, dy - r))


def _fill_band(draw, x0: int, y0: int, x1: int, y1: int, fill) -> None:
    if x1 <= x0 or y1 <= y0:
        return
    draw.rectangle((x0, y0, x1 - 1, y1 - 1), fill=fill)


def _union_span(*spans: tuple[int, int] | None) -> tuple[int, int] | None:
    present = [s for s in spans if s]
    if not present:
        return None
    return (min(s[0] for s in present), max(s[1] for s in present))


def _span_px(span: tuple[int, int]) -> tuple[int, int]:
    lo, hi = span
    t = ORTHO_TILE_SIZE
    return lo * t, (hi + 1) * t


def _fill_through_band(draw, size: int, spans: dict[str, tuple[int, int]]) -> None:
    fill = (*ROAD_GREY, 255)
    n = size // ORTHO_TILE_SIZE
    edges = frozenset(spans)
    if edges <= frozenset({"E", "W"}):
        ew = _union_span(spans.get("E"), spans.get("W"))
        if ew is None:
            return
        x0, x1 = _image_span_px(ew, n)
        _fill_band(draw, x0, 0, x1, size, fill)
        return
    ns = _union_span(spans.get("N"), spans.get("S"))
    if ns is None:
        return
    y0, y1 = _image_span_px(ns, n)
    _fill_band(draw, 0, y0, size, y1, fill)


def _fill_corner_L(draw, size: int, spans: dict[str, tuple[int, int]]) -> None:
    """Pavement as two mouth-span bands meeting at the _PAIR_TO_QUADRANT image corner.

    N/S mouths are horizontal (image Y); E/W mouths are vertical (image X).
    """
    fill = (*ROAD_GREY, 255)
    n = size // ORTHO_TILE_SIZE
    edges = frozenset(spans)
    if edges == frozenset({"W", "N"}) and "W" in spans and "N" in spans:
        wx0, wx1 = _image_span_px(spans["W"], n)
        ny0, ny1 = _image_span_px(spans["N"], n)
        _fill_band(draw, wx0, ny0, wx1, size, fill)
        _fill_band(draw, 0, ny0, wx1, ny1, fill)
        return
    if edges == frozenset({"W", "S"}) and "W" in spans and "S" in spans:
        wx0, wx1 = _image_span_px(spans["W"], n)
        sy0, sy1 = _image_span_px(spans["S"], n)
        _fill_band(draw, wx0, sy0, wx1, size, fill)
        _fill_band(draw, wx0, sy0, size, sy1, fill)
        return
    if edges == frozenset({"E", "N"}) and "E" in spans and "N" in spans:
        ex0, ex1 = _image_span_px(spans["E"], n)
        ny0, ny1 = _image_span_px(spans["N"], n)
        _fill_band(draw, ex0, 0, ex1, ny1, fill)
        _fill_band(draw, 0, ny0, ex1, ny1, fill)
        return
    if edges == frozenset({"E", "S"}) and "E" in spans and "S" in spans:
        ex0, ex1 = _image_span_px(spans["E"], n)
        sy0, sy1 = _image_span_px(spans["S"], n)
        _fill_band(draw, ex0, 0, ex1, sy1, fill)
        _fill_band(draw, ex0, sy0, size, sy1, fill)
        return
    _fill_through_band(draw, size, spans)


def _fill_outer_pie(
    draw,
    cx: int,
    cy: int,
    r: int,
    start_a: int,
    end_a: int,
    color: tuple[int, int, int] = WHITE,
) -> None:
    """Pavement quarter-disk with a curb on the outer ring (no inner bite)."""
    if r <= 0:
        return
    bbox = (cx - r, cy - r, cx + r, cy + r)
    draw.pieslice(bbox, start_a, end_a, fill=(*ROAD_GREY, 255))
    white_outer = r - CURB_INSET
    grey_inner = r - CURB_INSET - CURB_WIDTH
    if white_outer > 0:
        bbox_w = (cx - white_outer, cy - white_outer, cx + white_outer, cy + white_outer)
        draw.pieslice(bbox_w, start_a, end_a, fill=(*color, 255))
    if grey_inner > 0:
        bbox_g = (cx - grey_inner, cy - grey_inner, cx + grey_inner, cy + grey_inner)
        draw.pieslice(bbox_g, start_a, end_a, fill=(*ROAD_GREY, 255))


def _stroke_v_curb(
    draw,
    x: int,
    y0: int,
    y1: int,
    toward_plus_x: bool,
    color: tuple[int, int, int] = WHITE,
) -> None:
    inset = CURB_INSET
    width = CURB_WIDTH
    grey = (*ROAD_GREY, 255)
    white = (*color, 255)
    if toward_plus_x:
        _fill_band(draw, x, y0, x + inset, y1, grey)
        _fill_band(draw, x + inset, y0, x + inset + width, y1, white)
    else:
        _fill_band(draw, x - inset, y0, x, y1, grey)
        _fill_band(draw, x - inset - width, y0, x - inset, y1, white)


def _stroke_h_curb(
    draw,
    y: int,
    x0: int,
    x1: int,
    toward_plus_y: bool,
    color: tuple[int, int, int] = WHITE,
) -> None:
    inset = CURB_INSET
    width = CURB_WIDTH
    grey = (*ROAD_GREY, 255)
    white = (*color, 255)
    if toward_plus_y:
        _fill_band(draw, x0, y, x1, y + inset, grey)
        _fill_band(draw, x0, y + inset, x1, y + inset + width, white)
    else:
        _fill_band(draw, x0, y - inset, x1, y, grey)
        _fill_band(draw, x0, y - inset - width, x1, y - inset, white)


def _exterior_L_fillet(img, size: int, spans: dict[str, tuple[int, int]], curb=None) -> None:
    """
    Convex outer of an L: straight from the narrower (or either, if equal)
    outer curb to a square of side min(widths), then a quarter-turn.
    """
    if ImageDraw is None:
        return
    n = size // ORTHO_TILE_SIZE
    edges = frozenset(spans)
    spec = None
    if edges == frozenset({"W", "N"}) and "W" in spans and "N" in spans:
        wx0, wx1 = _image_span_px(spans["W"], n)
        ny0, ny1 = _image_span_px(spans["N"], n)
        r = min(wx1 - wx0, ny1 - ny0)
        if r > 0:
            spec = {
                "q": 0,
                "cx": wx1 - r,
                "cy": ny0 + r,
                "r": r,
                "sq": (wx1 - r, ny0, wx1, ny0 + r),
                "v": (wx1, ny0 + r, size, False),
                "h": (ny0, 0, wx1 - r, True),
            }
    elif edges == frozenset({"W", "S"}) and "W" in spans and "S" in spans:
        wx0, wx1 = _image_span_px(spans["W"], n)
        sy0, sy1 = _image_span_px(spans["S"], n)
        r = min(wx1 - wx0, sy1 - sy0)
        if r > 0:
            spec = {
                "q": 1,
                "cx": wx0 + r,
                "cy": sy0 + r,
                "r": r,
                "sq": (wx0, sy0, wx0 + r, sy0 + r),
                "v": (wx0, sy0 + r, size, True),
                "h": (sy0, wx0 + r, size, True),
            }
    elif edges == frozenset({"E", "N"}) and "E" in spans and "N" in spans:
        ex0, ex1 = _image_span_px(spans["E"], n)
        ny0, ny1 = _image_span_px(spans["N"], n)
        r = min(ex1 - ex0, ny1 - ny0)
        if r > 0:
            spec = {
                "q": 3,
                "cx": ex1 - r,
                "cy": ny1 - r,
                "r": r,
                "sq": (ex1 - r, ny1 - r, ex1, ny1),
                "v": (ex1, 0, ny1 - r, False),
                "h": (ny1, 0, ex1 - r, False),
            }
    elif edges == frozenset({"E", "S"}) and "E" in spans and "S" in spans:
        ex0, ex1 = _image_span_px(spans["E"], n)
        sy0, sy1 = _image_span_px(spans["S"], n)
        r = min(ex1 - ex0, sy1 - sy0)
        if r > 0:
            spec = {
                "q": 2,
                "cx": ex0 + r,
                "cy": sy1 - r,
                "r": r,
                "sq": (ex0, sy1 - r, ex0 + r, sy1),
                "v": (ex0, 0, sy1 - r, True),
                "h": (sy1, ex0 + r, size, False),
            }
    if spec is None:
        return
    draw = ImageDraw.Draw(img)
    x0, y0, x1, y1 = spec["sq"]
    _fill_band(draw, x0, y0, x1, y1, (0, 0, 0, 0))
    _cx, _cy, start_a, end_a = _CORNER_ARC_PRESETS[spec["q"]]
    v_arm, h_arm = _Q_OUTER[spec["q"]]
    v_col = _curb_color(curb, v_arm)
    h_col = _curb_color(curb, h_arm)
    pie = YELLOW if curb is not None and v_arm in curb.halves and h_arm in curb.halves else WHITE
    _fill_outer_pie(draw, spec["cx"], spec["cy"], spec["r"], start_a, end_a, color=pie)
    vx, vy0, vy1, vplus = spec["v"]
    hy, hx0, hx1, hplus = spec["h"]
    _stroke_v_curb(draw, vx, vy0, vy1, vplus, color=v_col)
    _stroke_h_curb(draw, hy, hx0, hx1, hplus, color=h_col)


def _punch_open_edge(draw, size: int, edge: str, spans: dict[str, tuple[int, int]]) -> None:
    """
    Clear the open cardinal in image space matching make_tee:
    N left, E top, S right, W bottom.
    """
    clear = (0, 0, 0, 0)
    n = size // ORTHO_TILE_SIZE
    if edge in ("N", "S"):
        through = _union_span(spans.get("E"), spans.get("W"))
        if through is None:
            return
        x0, x1 = _image_span_px(through, n)
        if edge == "S":
            _fill_band(draw, x1, 0, size, size, clear)
        else:
            _fill_band(draw, 0, 0, x0, size, clear)
        return
    through = _union_span(spans.get("N"), spans.get("S"))
    if through is None:
        return
    y0, y1 = _image_span_px(through, n)
    if edge == "W":
        _fill_band(draw, 0, y1, size, size, clear)
    else:
        _fill_band(draw, 0, 0, size, y0, clear)


def _stroke_open_face_curb(
    img,
    size: int,
    edge: str,
    spans: dict[str, tuple[int, int]],
    color: tuple[int, int, int] = WHITE,
) -> None:
    """
    Through-road curb along the open cardinal, full length of that edge.

    Grey inset then the curb colour, matching lane tiles. Stem-side curbs stay the fillets.
    """
    if ImageDraw is None:
        return
    n = size // ORTHO_TILE_SIZE
    inset = CURB_INSET
    width = CURB_WIDTH
    grey = (*ROAD_GREY, 255)
    white = (*color, 255)
    draw = ImageDraw.Draw(img)
    if edge in ("N", "S"):
        through = _union_span(spans.get("E"), spans.get("W"))
        if through is None:
            return
        x0, x1 = _image_span_px(through, n)
        if edge == "S":
            _fill_band(draw, x1 - inset, 0, x1, size, grey)
            _fill_band(draw, x1 - inset - width, 0, x1 - inset, size, white)
        else:
            _fill_band(draw, x0, 0, x0 + inset, size, grey)
            _fill_band(draw, x0 + inset, 0, x0 + inset + width, size, white)
        return
    through = _union_span(spans.get("N"), spans.get("S"))
    if through is None:
        return
    y0, y1 = _image_span_px(through, n)
    if edge == "W":
        _fill_band(draw, 0, y1 - inset, size, y1, grey)
        _fill_band(draw, 0, y1 - inset - width, size, y1 - inset, white)
    else:
        _fill_band(draw, 0, y0, size, y0 + inset, grey)
        _fill_band(draw, 0, y0 + inset, size, y0 + inset + width, white)


def _stroke_virtual_curbs(
    img,
    size: int,
    quadrant: int,
    dx: int,
    dy: int,
    r: int,
    v_color: tuple[int, int, int] = WHITE,
    h_color: tuple[int, int, int] = WHITE,
) -> None:
    """Grey outline then curb colour along each virtual sharp, AABB to tangency."""
    if ImageDraw is None:
        return
    draw = ImageDraw.Draw(img)
    grey = (*ROAD_GREY, 255)
    v_rgba = (*v_color, 255)
    h_rgba = (*h_color, 255)
    inset = CURB_INSET
    width = CURB_WIDTH
    q = quadrant % 4
    if q == 0:
        y_s = size - dy
        x_end = max(0, dx - r)
        _fill_band(draw, 0, y_s - inset, x_end, y_s, grey)
        _fill_band(draw, 0, y_s - inset - width, x_end, y_s - inset, h_rgba)
        y_start = min(size, size - dy + r)
        _fill_band(draw, dx, y_start, dx + inset, size, grey)
        _fill_band(draw, dx + inset, y_start, dx + inset + width, size, v_rgba)
    elif q == 1:
        y_s = size - dy
        x_start = min(size, size - dx + r)
        _fill_band(draw, x_start, y_s - inset, size, y_s, grey)
        _fill_band(draw, x_start, y_s - inset - width, size, y_s - inset, h_rgba)
        y_start = min(size, size - dy + r)
        _fill_band(draw, size - dx - inset, y_start, size - dx, size, grey)
        _fill_band(draw, size - dx - inset - width, y_start, size - dx - inset, size, v_rgba)
    elif q == 2:
        y_s = dy
        x_start = min(size, size - dx + r)
        _fill_band(draw, x_start, y_s, size, y_s + inset, grey)
        _fill_band(draw, x_start, y_s + inset, size, y_s + inset + width, h_rgba)
        y_end = max(0, dy - r)
        _fill_band(draw, size - dx - inset, 0, size - dx, y_end, grey)
        _fill_band(draw, size - dx - inset - width, 0, size - dx - inset, y_end, v_rgba)
    else:
        y_s = dy
        x_end = max(0, dx - r)
        _fill_band(draw, 0, y_s, x_end, y_s + inset, grey)
        _fill_band(draw, 0, y_s + inset, x_end, y_s + inset + width, h_rgba)
        y_end = max(0, dy - r)
        _fill_band(draw, dx, 0, dx + inset, y_end, grey)
        _fill_band(draw, dx + inset, 0, dx + inset + width, y_end, v_rgba)


def _punch_leftover_extra(draw, size: int, quadrant: int, dx: int, dy: int, r: int) -> None:
    """
    Grass leftover beyond the mouth-adjacent r×r (toward the AABB).

    The fillet sits next to both mouths; extra unequal leftover is the AABB
    remainder. Punching from the AABB instead left the curve one cell inboard.
    """
    clear = (0, 0, 0, 0)
    q = quadrant % 4
    if q == 0:
        if dx > r:
            _fill_band(draw, 0, size - dy, dx - r, size, clear)
        if dy > r:
            _fill_band(draw, dx - r, size - dy + r, dx, size, clear)
    elif q == 1:
        if dx > r:
            _fill_band(draw, size - dx + r, size - dy, size, size, clear)
        if dy > r:
            _fill_band(draw, size - dx, size - dy + r, size - dx + r, size, clear)
    elif q == 2:
        if dx > r:
            _fill_band(draw, size - dx + r, 0, size, dy, clear)
        if dy > r:
            _fill_band(draw, size - dx, 0, size - dx + r, dy - r, clear)
    else:
        if dx > r:
            _fill_band(draw, 0, 0, dx - r, dy, clear)
        if dy > r:
            _fill_band(draw, dx - r, 0, dx, dy - r, clear)


def _apply_mixed_corner(
    img,
    cells: int,
    quadrant: int,
    leftover_x: int,
    leftover_y: int,
    family: str = "cross",
    curb=None,
) -> None:
    """Fill leftover plaza, extra-strip grass, inner fillet lip, virtual-sharp curbs.

    Leftover 0 on either axis: no grass bite; micro-fillet at the inner join
    (curb-pack quarter-ring) plus leftover-edge curb if one axis remains.
    Size-2 tee/cross leftover is a 1-cell bite on an asymmetric plaza — force
    the 0-throat L and punch the leftover cell (no rounded extra). Size-2
    corners keep the annulus / cell fillet.
    """
    if ImageDraw is None or leftover_x < 0 or leftover_y < 0:
        return
    t = ORTHO_TILE_SIZE
    size = cells * t
    # leftover_x is the E/W (world X) shoulder → image Y; leftover_y is N/S → image X.
    dx, dy = leftover_y * t, leftover_x * t
    size2_plaza = cells <= 2 and family in ("tee", "cross")
    if leftover_x > 0 and leftover_y > 0 and not size2_plaza:
        inner_r = min(dx, dy)
        draw = ImageDraw.Draw(img)
        x0, y0, x1, y1 = _leftover_box(size, quadrant, dx, dy)
        _fill_band(draw, x0, y0, x1, y1, (*ROAD_GREY, 255))
        _punch_leftover_extra(draw, size, quadrant, dx, dy, inner_r)
        origin = _leftover_fillet_origin(size, quadrant, dx, dy, inner_r)
        _stroke_fillet_lip(img, cells, quadrant, inner_r=inner_r, origin=origin, color=_fillet_color(curb, quadrant))
        _stroke_virtual_curbs(img, size, quadrant, dx, dy, inner_r, *_arm_colors(curb, quadrant))
        return
    # Leftover 0, or size-2 tee/cross: no cell fillet; micro-fillet at the join.
    if leftover_x > 0 and leftover_y > 0:
        _punch_leftover_extra(ImageDraw.Draw(img), size, quadrant, dx, dy, 0)
    _stroke_virtual_curbs(img, size, quadrant, dx, dy, CURB_INSET, *_arm_colors(curb, quadrant))
    origin = _leftover_fillet_origin(size, quadrant, dx, dy, 0)
    _stroke_fillet_lip(img, cells, quadrant, inner_r=0, origin=origin, color=_fillet_color(curb, quadrant))


def _draw_constant_width_annulus(
    img,
    cells: int,
    quadrant: int,
    inner_r: int,
    outer_r: int,
    outer_color: tuple[int, int, int] = WHITE,
    inner_color: tuple[int, int, int] = WHITE,
) -> None:
    """Quarter-annulus from an AABB corner: outer curb, optional inner bite."""
    if ImageDraw is None:
        return
    size_px = cells * ORTHO_TILE_SIZE
    outer_r = max(1, min(int(outer_r), size_px))
    inner_r = max(0, int(inner_r))
    arc_cx, arc_cy, start_angle, end_angle = _arc_center(quadrant, size_px)
    draw = ImageDraw.Draw(img)
    bbox = (arc_cx - outer_r, arc_cy - outer_r, arc_cx + outer_r, arc_cy + outer_r)
    draw.pieslice(bbox, start_angle, end_angle, fill=(*ROAD_GREY, 255))
    white_outer = outer_r - CURB_INSET
    grey_inner = outer_r - CURB_INSET - CURB_WIDTH
    if white_outer > 0:
        bbox_w = (arc_cx - white_outer, arc_cy - white_outer, arc_cx + white_outer, arc_cy + white_outer)
        draw.pieslice(bbox_w, start_angle, end_angle, fill=(*outer_color, 255))
    if grey_inner > 0:
        bbox_g = (arc_cx - grey_inner, arc_cy - grey_inner, arc_cx + grey_inner, arc_cy + grey_inner)
        draw.pieslice(bbox_g, start_angle, end_angle, fill=(*ROAD_GREY, 255))
    _stroke_fillet_lip(img, cells, quadrant, inner_r=inner_r, color=inner_color)


def _annulus_radii(
    cells: int,
    spans: dict[str, tuple[int, int]],
) -> tuple[int, int, int] | None:
    from render.intersection_topology import leftover_xy_for_pair

    if len(spans) != 2:
        return None
    a, b = tuple(spans)
    xy = leftover_xy_for_pair(cells, spans, a, b)
    if xy is None:
        return None
    from render.intersection_topology import corner_quadrant_for_sides

    q = corner_quadrant_for_sides(frozenset(spans))
    lx, ly = xy
    if lx != ly:
        return None
    inner_r = max(0, min(lx, ly)) * ORTHO_TILE_SIZE
    width = min(_span_width(s) for s in spans.values())
    outer_r = inner_r + width * ORTHO_TILE_SIZE
    return q, inner_r, outer_r


def _diag_offset(inward: tuple[int, int], dist: int) -> tuple[int, int]:
    ix, iy = inward
    s = dist / math.sqrt(2.0)
    ox, oy = round(ix * s), round(iy * s)
    if dist and ox == 0 and oy == 0:
        return ix, iy
    return ox, oy


def _stroke_diag_curb(
    draw,
    a: tuple[int, int],
    b: tuple[int, int],
    inward: tuple[int, int],
    color: tuple[int, int, int] = WHITE,
) -> None:
    """Curb along a 45° hypotenuse: grey inset on the grass side, then the curb colour."""
    og = _diag_offset(inward, CURB_INSET)
    ow = _diag_offset(inward, CURB_INSET + CURB_WIDTH)
    if ow == og:
        ow = (og[0] + inward[0], og[1] + inward[1])

    def add(p: tuple[int, int], o: tuple[int, int]) -> tuple[int, int]:
        return (p[0] + o[0], p[1] + o[1])

    draw.polygon([a, b, add(b, og), add(a, og)], fill=(*ROAD_GREY, 255))
    draw.polygon(
        [add(a, og), add(b, og), add(b, ow), add(a, ow)],
        fill=(*color, 255),
    )


def _chamfer_blocked_at_pair(
    n: int,
    spans: dict[str, tuple[int, int]],
    e1: str,
    e2: str,
) -> bool:
    """True when that AABB corner is leftover/mouth paint, not a chamfer site.

    Inner leftover (both axes > 0) already has a fillet. Leftover 0 on either
    axis means the other mouth occupies the corner — no non-mouth D×D room
    (typical size-4 flush twins). Chamfer only where leftover_xy is None
    (open face or straight).
    """
    from render.intersection_topology import leftover_xy_for_pair

    return leftover_xy_for_pair(n, spans, e1, e2) is not None


def _ns_through_chamfer(
    size: int,
    n: int,
    t: int,
    nspan: tuple[int, int],
    sspan: tuple[int, int],
    west: bool,
    spans: dict[str, tuple[int, int]],
) -> dict | None:
    if west:
        d = nspan[0] - sspan[0]
        lf, ls = min(nspan[0], sspan[0]), max(nspan[0], sspan[0])
        y_fat = size - lf * t
        y_skinny = size - ls * t
    else:
        d = sspan[1] - nspan[1]
        ln = (n - 1) - nspan[1]
        l_s = (n - 1) - sspan[1]
        lf, ls = min(ln, l_s), max(ln, l_s)
        y_fat = lf * t
        y_skinny = ls * t
    if d == 0:
        return None
    dpx = min(abs(d), n) * t
    if dpx <= 0:
        return None
    skinny_n = d > 0
    if west:
        pair = ("W", "N") if skinny_n else ("S", "W")
    else:
        pair = ("N", "E") if skinny_n else ("E", "S")
    if _chamfer_blocked_at_pair(n, spans, pair[0], pair[1]):
        return None
    if skinny_n:
        hyp0, hyp1 = (0, y_skinny), (dpx, y_fat)
        outer = [(0, y_skinny), (0, y_fat), (dpx, y_fat)]
        inner = [(0, y_skinny), (dpx, y_skinny), (dpx, y_fat)]
        inward = (1, -1) if west else (1, 1)
    else:
        hyp0, hyp1 = (size, y_skinny), (size - dpx, y_fat)
        outer = [(size, y_skinny), (size, y_fat), (size - dpx, y_fat)]
        inner = [(size, y_skinny), (size - dpx, y_skinny), (size - dpx, y_fat)]
        inward = (-1, -1) if west else (-1, 1)
    return {
        "inner": inner,
        "outer": outer,
        "hyp0": hyp0,
        "hyp1": hyp1,
        "inward": inward,
        "side": "W" if west else "E",
        "faces": ("N", "S"),
    }


def _ew_through_chamfer(
    size: int,
    n: int,
    t: int,
    espan: tuple[int, int],
    wspan: tuple[int, int],
    south: bool,
    spans: dict[str, tuple[int, int]],
) -> dict | None:
    if south:
        d = espan[0] - wspan[0]
        lf, ls = min(espan[0], wspan[0]), max(espan[0], wspan[0])
        x_fat = size - lf * t
        x_skinny = size - ls * t
    else:
        d = wspan[1] - espan[1]
        le = (n - 1) - espan[1]
        lw = (n - 1) - wspan[1]
        lf, ls = min(le, lw), max(le, lw)
        x_fat = lf * t
        x_skinny = ls * t
    if d == 0:
        return None
    dpx = min(abs(d), n) * t
    if dpx <= 0:
        return None
    skinny_e = d > 0
    if south:
        pair = ("E", "S") if skinny_e else ("S", "W")
    else:
        pair = ("N", "E") if skinny_e else ("W", "N")
    if _chamfer_blocked_at_pair(n, spans, pair[0], pair[1]):
        return None
    if skinny_e:
        hyp0, hyp1 = (x_skinny, 0), (x_fat, dpx)
        outer = [(x_skinny, 0), (x_fat, 0), (x_fat, dpx)]
        inner = [(x_skinny, 0), (x_skinny, dpx), (x_fat, dpx)]
        inward = (-1, 1) if south else (1, 1)
    else:
        hyp0, hyp1 = (x_skinny, size), (x_fat, size - dpx)
        outer = [(x_skinny, size), (x_fat, size), (x_fat, size - dpx)]
        inner = [(x_skinny, size), (x_skinny, size - dpx), (x_fat, size - dpx)]
        inward = (-1, -1) if south else (1, -1)
    return {
        "inner": inner,
        "outer": outer,
        "hyp0": hyp0,
        "hyp1": hyp1,
        "inward": inward,
        "side": "S" if south else "N",
        "faces": ("E", "W"),
    }


def _through_chamfer_specs(
    cells: int,
    spans: dict[str, tuple[int, int]],
) -> list[dict]:
    """D×D 45° tapers on the outside of an opposite-mouth width step.

    A two-axis leftover corner already has a concave inner fillet; skip those.
    """
    n = max(0, int(cells))
    t = ORTHO_TILE_SIZE
    size = n * t
    out: list[dict] = []
    if "N" in spans and "S" in spans:
        for west in (True, False):
            spec = _ns_through_chamfer(
                size, n, t, spans["N"], spans["S"], west, spans
            )
            if spec is not None:
                out.append(spec)
    if "E" in spans and "W" in spans:
        for south in (True, False):
            spec = _ew_through_chamfer(
                size, n, t, spans["E"], spans["W"], south, spans
            )
            if spec is not None:
                out.append(spec)
    return out


def _apply_through_chamfers(img, cells: int, spans: dict[str, tuple[int, int]], curb=None) -> None:
    """Replace opposite-mouth width jogs with a 45° curb chamfer."""
    if ImageDraw is None or not spans:
        return
    draw = ImageDraw.Draw(img)
    clear = (0, 0, 0, 0)
    grey = (*ROAD_GREY, 255)
    for spec in _through_chamfer_specs(cells, spans):
        draw.polygon(spec["inner"], fill=grey)
        draw.polygon(spec["outer"], fill=clear)
        color = WHITE
        if curb is not None and _road_side_yellow(spec["side"], spec["faces"], curb):
            color = YELLOW
        _stroke_diag_curb(draw, spec["hyp0"], spec["hyp1"], spec["inward"], color=color)


# Inner arms of each quadrant: (vertical curb side, approach face), (horizontal ...).
# Vertical arms are E/W-road curbs (constant world Y). Horizontal arms are N/S-road curbs.
_Q_ARMS: dict[int, tuple[tuple[str, str], tuple[str, str]]] = {
    0: (("N", "W"), ("W", "N")),
    1: (("S", "W"), ("W", "S")),
    2: (("S", "E"), ("E", "S")),
    3: (("N", "E"), ("E", "N")),
}
_Q_OUTER: dict[int, tuple[tuple[str, str], tuple[str, str]]] = {
    0: (("S", "W"), ("E", "N")),
    1: (("N", "W"), ("E", "S")),
    2: (("N", "E"), ("W", "S")),
    3: (("S", "E"), ("W", "N")),
}
_Q_PAIR = {
    frozenset({"W", "N"}): 0,
    frozenset({"S", "W"}): 1,
    frozenset({"E", "S"}): 2,
    frozenset({"N", "E"}): 3,
}
_STEM_QUADS = {
    "S": (1, 2),
    "N": (0, 3),
    "E": (3, 2),
    "W": (0, 1),
}
_STEM_SIDE_Q = {
    "S": {"W": 1, "E": 2},
    "N": {"W": 0, "E": 3},
    "E": {"N": 3, "S": 2},
    "W": {"N": 0, "S": 1},
}
_OPPOSITE_EDGE = {"N": "S", "S": "N", "E": "W", "W": "E"}


class _Curb:
    """Yellow curb halves (side, approach face) and fillet quadrants."""

    __slots__ = ("halves", "headings", "fillets")

    def __init__(self) -> None:
        self.halves: set[tuple[str, str]] = set()
        self.headings: dict[str, str | None] = {}
        self.fillets: set[int] = set()


def _curb_color(curb: _Curb | None, arm: tuple[str, str]) -> tuple[int, int, int]:
    if curb is not None and arm in curb.halves:
        return YELLOW
    return WHITE


def _fillet_color(curb: _Curb | None, quadrant: int) -> tuple[int, int, int]:
    if curb is not None and (quadrant % 4) in curb.fillets:
        return YELLOW
    return WHITE


def _arm_colors(
    curb: _Curb | None, quadrant: int
) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    v_arm, h_arm = _Q_ARMS[quadrant % 4]
    return _curb_color(curb, v_arm), _curb_color(curb, h_arm)


def _road_side_yellow(side: str, faces: tuple[str, ...], curb: _Curb) -> bool:
    """True when every present face of this road has a yellow curb on `side`."""
    present = [face for face in faces if face in curb.headings]
    if not present:
        return False
    return all(curb.headings[face] and (side, face) in curb.halves for face in present)


def _agreed_heading(faces: tuple[str, ...], headings: dict[str, str | None]) -> str | None:
    found: list[str] = []
    for face in faces:
        if face not in headings:
            continue
        heading = headings[face]
        if not heading:
            return None
        found.append(heading)
    if not found or any(heading != found[0] for heading in found):
        return None
    return found[0]


def _turn_inside(
    through_h: str, stem_h: str, stem: str
) -> tuple[bool, bool, int | None]:
    """Left/right and the inside quadrant of the through↔stem turn."""
    if stem_h == stem:
        h_from, h_to = through_h, stem_h
    elif stem_h == _OPPOSITE_EDGE[stem]:
        h_from, h_to = stem_h, through_h
    else:
        return False, False, None
    from sim.junction import LEFT_OF, RIGHT_OF

    left = h_to == LEFT_OF.get(h_from)
    right = h_to == RIGHT_OF.get(h_from)
    if not (left or right):
        return False, False, None
    inside = _Q_PAIR.get(frozenset({_OPPOSITE_EDGE[h_from], h_to}))
    return left, right, inside


def _paint_stem_fillets(curb: _Curb, through_h: str | None, stem_h: str | None, stem: str) -> None:
    """Tee stem fillets. A two-way face contributes none. Both one-way uses the turn."""
    quads = _STEM_QUADS.get(stem, ())
    if not quads:
        return
    for quad in quads:
        curb.fillets.discard(quad)
    side_q = _STEM_SIDE_Q.get(stem, {})

    def through_left() -> None:
        if not through_h:
            return
        left = DRIVER_LEFT.get(through_h)
        for quad, (v_arm, h_arm) in _Q_ARMS.items():
            if quad in quads and (v_arm[0] == left or h_arm[0] == left):
                curb.fillets.add(quad)

    def stem_left() -> None:
        if not stem_h:
            return
        quad = side_q.get(DRIVER_LEFT.get(stem_h, ""))
        if quad is not None:
            curb.fillets.add(quad)

    if through_h and stem_h:
        left_turn, right_turn, inside = _turn_inside(through_h, stem_h, stem)
        if inside is not None and (left_turn or right_turn):
            outside = next((quad for quad in quads if quad != inside), None)
            if left_turn:
                curb.fillets.add(inside)
            elif outside is not None:
                curb.fillets.add(outside)
            return
        through_left()
        stem_left()
        return
    if through_h:
        through_left()
        return
    stem_left()


def curb_scheme(
    intersection_key: str | None,
    family: str,
    axis: str = "ns",
    stem: str = "E",
) -> _Curb:
    """Yellow left curbs for single-direction mouths. No key, or a two-way face, stays white."""
    curb = _Curb()
    if not intersection_key:
        return curb
    from render.intersection_topology import (
        _face_ins_outs,
        _face_single_direction,
        _raw_mouth_crossings,
    )
    from sim import world

    cells = list(world.get_intersection_cells_by_key(intersection_key) or [])
    crossings = _raw_mouth_crossings(intersection_key, cells)
    edges = {edge for _i, edge, _kind, _x, _y in crossings}
    for edge in edges:
        if not _face_single_direction(edge, crossings):
            curb.headings[edge] = None
            continue
        ins, outs = _face_ins_outs(edge, crossings)
        headings = {world.lane_direction(lane) for lane in (ins or outs)}
        headings.discard("")
        if len(headings) != 1:
            curb.headings[edge] = None
            continue
        heading = next(iter(headings))
        curb.headings[edge] = heading
        left = DRIVER_LEFT.get(heading)
        if left:
            curb.halves.add((left, edge))
    for quad, (v_arm, h_arm) in _Q_ARMS.items():
        # A left curb that dies into the plaza still colours that fillet. A tee
        # then replaces its stem fillets with the turn rule.
        if v_arm in curb.halves or h_arm in curb.halves:
            curb.fillets.add(quad)
    if family == "tee":
        through = ("E", "W") if axis == "ew" else ("N", "S")
        _paint_stem_fillets(
            curb,
            _agreed_heading(through, curb.headings),
            curb.headings.get(stem) if stem in curb.headings else None,
            stem,
        )
    return curb


def _tee_paint_layout(
    spans: dict[str, tuple[int, int]],
    axis: str,
    stem: str,
) -> tuple[str, str]:
    """Through axis and stem from the mouths, so a default axis cannot colour the wrong edge."""
    edges = frozenset(spans)
    if frozenset({"E", "W"}) <= edges and ("N" in edges) != ("S" in edges):
        return "ew", ("N" if "N" in edges else "S")
    if frozenset({"N", "S"}) <= edges and ("E" in edges) != ("W" in edges):
        return "ns", ("E" if "E" in edges else "W")
    return axis, stem


def frozen_curb_key(
    intersection_key: str | None,
    family: str,
    axis: str = "ns",
    stem: str = "E",
    spans: dict[str, tuple[int, int]] | None = None,
) -> tuple:
    """Cache fragment: which curb halves and fillets are yellow."""
    paint_ax, paint_st = axis, stem
    if family == "tee":
        paint_ax, paint_st = _tee_paint_layout(spans or {}, axis, stem)
    curb = curb_scheme(intersection_key, family, paint_ax, paint_st)
    return (tuple(sorted(curb.halves)), tuple(sorted(curb.fillets)))


def _stroke_straight_edges(img, size: int, spans: dict[str, tuple[int, int]], curb: _Curb) -> None:
    """Left edge of a one-way through band is yellow; the right edge stays white.

    A width jog keeps the chamfer as its curb, so unequal mouths are not also stroked.
    """
    edges = frozenset(spans)
    if edges <= frozenset({"E", "W"}):
        if "E" in spans and "W" in spans and spans["E"] != spans["W"]:
            return
        faces = ("E", "W")
        sides = ("N", "S")
    elif edges <= frozenset({"N", "S"}):
        if "N" in spans and "S" in spans and spans["N"] != spans["S"]:
            return
        faces = ("N", "S")
        sides = ("E", "W")
    else:
        return
    for side in sides:
        color = YELLOW if _road_side_yellow(side, faces, curb) else WHITE
        _stroke_open_face_curb(img, size, side, spans, color=color)


def make_mixed(
    cells: int,
    leftovers: tuple[tuple[int, int, int], ...],
    family: str = "cross",
    axis: str = "ns",
    stem: str = "E",
    spans: dict[str, tuple[int, int]] | None = None,
    paint_thru_lines: bool = True,
    intersection_key: str | None = None,
):
    """
    Mouth-span overlay: leftover fillets + family clip + through-width chamfers.

    Corner with equal mouth widths is a constant-width annulus (inner leftover,
    outer leftover + width). Unequal mouths keep an L, an exterior outer fillet,
    and an inner leftover fillet. Cross/tee/straight taper the *outside* of
    opposite-mouth width steps with a 45° chamfer; inner leftover corners keep
    the fillet. Corners are not chamfered.
    leftovers are (quadrant, leftover_x_cells, leftover_y_cells).
    spans are local cell inclusive (min, max) per pierced edge.
    """
    if Image is None or ImageDraw is None:
        raise RuntimeError("Pillow required for mixed generation: pip install Pillow")

    cells = max(2, min(12, cells))
    if cells % 2 != 0:
        cells = (cells // 2) * 2
    size = cells * ORTHO_TILE_SIZE
    local = spans or {}
    fam = family if family in ("cross", "tee", "corner", "straight") else "cross"
    ax = axis if axis in ("ns", "ew") else "ns"
    st = stem if stem in ("N", "S", "E", "W") else "E"
    paint_ax, paint_st = _tee_paint_layout(local, ax, st) if fam == "tee" else (ax, st)
    curb = curb_scheme(intersection_key, fam, paint_ax, paint_st)

    if fam == "straight":
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        _fill_through_band(ImageDraw.Draw(img), size, local)
        _apply_through_chamfers(img, cells, local, curb)
        _stroke_straight_edges(img, size, local, curb)
        _stroke_mixed_thru(
            img, cells, fam, ax, st, local, paint_thru_lines, intersection_key
        )
        return img
    if fam == "corner":
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        radii = _annulus_radii(cells, local) if _mouth_widths_equal(local) else None
        if radii is not None:
            q, inner_r, outer_r = radii
            outer_arms = _Q_OUTER[q]
            outer_color = (
                YELLOW
                if all(arm in curb.halves for arm in outer_arms)
                else WHITE
            )
            _draw_constant_width_annulus(
                img,
                cells,
                q,
                inner_r,
                outer_r,
                outer_color=outer_color,
                inner_color=_fillet_color(curb, q),
            )
            _stroke_mixed_thru(
                img, cells, fam, ax, st, local, paint_thru_lines, intersection_key
            )
            return img
        _fill_corner_L(ImageDraw.Draw(img), size, local)
        _exterior_L_fillet(img, size, local, curb)
        for quad, lx, ly in leftovers:
            _apply_mixed_corner(img, cells, quad, lx, ly, family=fam, curb=curb)
        _stroke_mixed_thru(
            img, cells, fam, ax, st, local, paint_thru_lines, intersection_key
        )
        return img

    img = Image.new("RGBA", (size, size), (*ROAD_GREY, 255))
    for quad, lx, ly in leftovers:
        _apply_mixed_corner(img, cells, quad, lx, ly, family=fam, curb=curb)
    if fam == "tee":
        open_edges = frozenset({"N", "S", "E", "W"}) - frozenset(local)
        through = ("E", "W") if paint_ax == "ew" else ("N", "S")
        draw = ImageDraw.Draw(img)
        for edge in open_edges:
            _punch_open_edge(draw, size, edge, local)
            color = YELLOW if _road_side_yellow(edge, through, curb) else WHITE
            _stroke_open_face_curb(img, size, edge, local, color=color)
    _apply_through_chamfers(img, cells, local, curb)
    _stroke_mixed_thru(
        img, cells, fam, ax, st, local, paint_thru_lines, intersection_key
    )
    return img


def _stroke_mixed_thru(
    img,
    cells: int,
    family: str,
    axis: str,
    stem: str,
    spans: dict[str, tuple[int, int]],
    paint_thru_lines: bool,
    intersection_key: str | None,
) -> None:
    if not paint_thru_lines:
        return
    from render.thru_lines import stroke_thru_lines

    stroke_thru_lines(
        img,
        cells,
        family,
        axis=axis,
        stem=stem,
        spans=spans,
        intersection_key=intersection_key,
        paint=True,
    )


def make_tee(cells: int = 4, axis: str = "ns", stem: str = "E", paint_thru_lines: bool = True):
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

    img = make_straight_through(cells, axis=axis, omit_white=omit_white, paint_thru_lines=False)
    _fill_stem_shoulder(img, cells, axis, stem)
    quads = tee_corner_quadrants(stem)  # type: ignore[arg-type]
    _restroke_open_side_white(img, cells, axis, omit_white)
    for q in quads:
        _stroke_fillet_lip(img, cells, q)
    _clear_open_half(img, cells, axis, stem)
    if paint_thru_lines:
        from render.thru_lines import stroke_thru_lines

        stroke_thru_lines(img, cells, "tee", axis=axis, stem=stem, paint=True)
    return img
