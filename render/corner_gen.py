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

from render.lane_paint import CURB_INSET, CURB_WIDTH
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


def make_corner(cells: int = 4, quadrant: int = 0):
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
) -> None:
    """Inner curb white + grass-bite punch, drawn last so sibling greys cannot hide it."""
    if ImageDraw is None:
        return
    size = max(2, min(12, cells))
    if size % 2 != 0:
        size = (size // 2) * 2
    size_px = size * ORTHO_TILE_SIZE
    if inner_r is None:
        _sz, inner_r, w_in, w_out = _fillet_white_radii(cells)
    else:
        inner_r = max(2, int(inner_r))
        w_in = inner_r + CURB_INSET
        w_out = inner_r + CURB_INSET + CURB_WIDTH
    arc_cx, arc_cy, start_angle, end_angle = _arc_center(quadrant, size_px)
    if origin is not None:
        arc_cx, arc_cy = int(origin[0]), int(origin[1])
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


def _double_shoulder_cells(cells: int, travel: int) -> int:
    cells = _even_aabb_cells(cells)
    travel = _even_travel_cells(travel, cells)
    return max(1, (cells - travel) // 2)


def double_fillet_inner_r(cells: int, travel_cells: int = 4) -> int:
    """Grass-bite radius for a centred even travel bundle on a larger AABB."""
    cells = _even_aabb_cells(cells)
    travel = _even_travel_cells(travel_cells, cells)
    shoulder = max(1, (cells - travel) // 2)
    return max(2, shoulder * ORTHO_TILE_SIZE)


def make_double(
    cells: int = 8,
    travel_cells: int = 4,
    travel_x: int | None = None,
    travel_y: int | None = None,
):
    """
    Larger Cross: grey plaza, four AABB fillets sized to the twin shoulder.

    Does not use AABB-scaled 4-cell bands, which would bite into the travel bundle.
    travel_x is the N/S mouth width; travel_y is the E/W mouth width.
    """
    if Image is None or ImageDraw is None:
        raise RuntimeError("Pillow required for double generation: pip install Pillow")
    cells = _even_aabb_cells(cells)
    tx = _even_travel_cells(travel_x if travel_x is not None else travel_cells, cells)
    ty = _even_travel_cells(travel_y if travel_y is not None else travel_cells, cells)
    size = cells * ORTHO_TILE_SIZE
    img = Image.new("RGBA", (size, size), (*ROAD_GREY, 255))
    sx = _double_shoulder_cells(cells, tx)
    sy = _double_shoulder_cells(cells, ty)
    inner_r = max(2, min(sx, sy) * ORTHO_TILE_SIZE)
    if sx != sy:
        draw = ImageDraw.Draw(img)
        dx, dy = sx * ORTHO_TILE_SIZE, sy * ORTHO_TILE_SIZE
        for q in range(4):
            _punch_leftover_extra(draw, size, q, dx, dy, inner_r)
    for q in range(4):
        _stroke_fillet_lip(img, cells, q, inner_r=inner_r)
    return img


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
    """
    Centred even through + stem bands, two stem-side AABB fillets, open face punched.

    No through-yellows and no Mixed leftover extra-strips from offset mouths.
    axis/stem follow make_tee (display space).
    """
    if Image is None or ImageDraw is None:
        raise RuntimeError("Pillow required for double tee generation: pip install Pillow")
    from render.intersection_topology import tee_corner_quadrants

    cells = _even_aabb_cells(cells)
    size = cells * ORTHO_TILE_SIZE
    img = Image.new("RGBA", (size, size), (*ROAD_GREY, 255))
    draw = ImageDraw.Draw(img)
    clear = (0, 0, 0, 0)
    th = _even_travel_cells(through_travel, cells)
    st = _even_travel_cells(stem_travel, cells)
    tlo, thi = _centered_lo_hi(cells, th)
    slo, shi = _centered_lo_hi(cells, st)
    tile = ORTHO_TILE_SIZE
    t0, t1 = tlo * tile, thi * tile
    s0, s1 = slo * tile, shi * tile
    ax = axis if axis in ("ns", "ew") else "ns"
    sm = stem if stem in ("N", "S", "E", "W") else "E"

    if ax == "ns":
        if sm == "E":
            _fill_band(draw, 0, t1, size, size, clear)
            _fill_band(draw, 0, 0, s0, t0, clear)
            _fill_band(draw, s1, 0, size, t0, clear)
        else:
            _fill_band(draw, 0, 0, size, t0, clear)
            _fill_band(draw, 0, t1, s0, size, clear)
            _fill_band(draw, s1, t1, size, size, clear)
    else:
        if sm == "N":
            _fill_band(draw, t1, 0, size, size, clear)
            _fill_band(draw, 0, 0, t0, s0, clear)
            _fill_band(draw, 0, s1, t0, size, clear)
        else:
            _fill_band(draw, 0, 0, t0, size, clear)
            _fill_band(draw, t1, 0, size, s0, clear)
            _fill_band(draw, t1, s1, size, size, clear)

    inner_r = max(
        2,
        min(_double_shoulder_cells(cells, th), _double_shoulder_cells(cells, st)) * tile,
    )
    for q in tee_corner_quadrants(sm):  # type: ignore[arg-type]
        _stroke_fillet_lip(img, cells, q, inner_r=inner_r)
    return img


def make_double_corner(
    cells: int = 8,
    quadrant: int = 0,
    travel_x: int = 4,
    travel_y: int = 4,
):
    """L of two centred even bands plus one inner AABB fillet. No scaled pie."""
    if Image is None or ImageDraw is None:
        raise RuntimeError("Pillow required for double corner generation: pip install Pillow")
    cells = _even_aabb_cells(cells)
    size = cells * ORTHO_TILE_SIZE
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    q = quadrant % 4
    tx = _even_travel_cells(travel_x, cells)
    ty = _even_travel_cells(travel_y, cells)
    xlo, xhi = _centered_lo_hi(cells, tx)
    ylo, yhi = _centered_lo_hi(cells, ty)
    spans: dict[str, tuple[int, int]] = {}
    for edge in _DOUBLE_CORNER_EDGES[q]:
        if edge in ("E", "W"):
            spans[edge] = (ylo, yhi - 1)
        else:
            spans[edge] = (xlo, xhi - 1)
    _fill_corner_L(ImageDraw.Draw(img), size, spans)
    inner_r = max(
        2,
        min(_double_shoulder_cells(cells, tx), _double_shoulder_cells(cells, ty))
        * ORTHO_TILE_SIZE,
    )
    _stroke_fillet_lip(img, cells, q, inner_r=inner_r)
    return img


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
    edges = frozenset(spans)
    if edges <= frozenset({"E", "W"}):
        ew = _union_span(spans.get("E"), spans.get("W"))
        if ew is None:
            return
        y0, y1 = _span_px(ew)
        _fill_band(draw, 0, y0, size, y1, fill)
        return
    ns = _union_span(spans.get("N"), spans.get("S"))
    if ns is None:
        return
    x0, x1 = _span_px(ns)
    _fill_band(draw, x0, 0, x1, size, fill)


def _fill_corner_L(draw, size: int, spans: dict[str, tuple[int, int]]) -> None:
    """Pavement as two mouth-span bands that meet (an L), not a scaled pie."""
    fill = (*ROAD_GREY, 255)
    edges = frozenset(spans)
    if edges == frozenset({"W", "N"}) and "W" in spans and "N" in spans:
        w0, w1 = _span_px(spans["W"])
        n0, n1 = _span_px(spans["N"])
        _fill_band(draw, 0, w0, n1, w1, fill)
        _fill_band(draw, n0, w0, n1, size, fill)
        return
    if edges == frozenset({"W", "S"}) and "W" in spans and "S" in spans:
        w0, w1 = _span_px(spans["W"])
        s0, s1 = _span_px(spans["S"])
        _fill_band(draw, 0, w0, s1, w1, fill)
        _fill_band(draw, s0, 0, s1, w1, fill)
        return
    if edges == frozenset({"E", "N"}) and "E" in spans and "N" in spans:
        e0, e1 = _span_px(spans["E"])
        n0, n1 = _span_px(spans["N"])
        _fill_band(draw, n0, e0, size, e1, fill)
        _fill_band(draw, n0, e0, n1, size, fill)
        return
    if edges == frozenset({"E", "S"}) and "E" in spans and "S" in spans:
        e0, e1 = _span_px(spans["E"])
        s0, s1 = _span_px(spans["S"])
        _fill_band(draw, s0, e0, size, e1, fill)
        _fill_band(draw, s0, 0, s1, e1, fill)
        return
    _fill_through_band(draw, size, spans)


def _punch_open_edge(draw, size: int, edge: str, spans: dict[str, tuple[int, int]]) -> None:
    """Clear the open cardinal outside the through-mouth span (not a centre-two half)."""
    clear = (0, 0, 0, 0)
    if edge in ("E", "W"):
        through = _union_span(spans.get("N"), spans.get("S"))
        if through is None:
            return
        x0, x1 = _span_px(through)
        if edge == "E":
            _fill_band(draw, x1, 0, size, size, clear)
        else:
            _fill_band(draw, 0, 0, x0, size, clear)
        return
    through = _union_span(spans.get("E"), spans.get("W"))
    if through is None:
        return
    y0, y1 = _span_px(through)
    if edge == "N":
        _fill_band(draw, 0, y1, size, size, clear)
    else:
        _fill_band(draw, 0, 0, size, y0, clear)


def _stroke_virtual_curbs(img, size: int, quadrant: int, dx: int, dy: int, r: int) -> None:
    """Grey outline then white inset along each virtual sharp, AABB to tangency."""
    if ImageDraw is None:
        return
    draw = ImageDraw.Draw(img)
    grey = (*ROAD_GREY, 255)
    white = (*WHITE, 255)
    inset = CURB_INSET
    width = CURB_WIDTH
    q = quadrant % 4
    if q == 0:
        y_s = size - dy
        x_end = max(0, dx - r)
        _fill_band(draw, 0, y_s - inset, x_end, y_s, grey)
        _fill_band(draw, 0, y_s - inset - width, x_end, y_s - inset, white)
        y_start = min(size, size - dy + r)
        _fill_band(draw, dx, y_start, dx + inset, size, grey)
        _fill_band(draw, dx + inset, y_start, dx + inset + width, size, white)
    elif q == 1:
        y_s = size - dy
        x_start = min(size, size - dx + r)
        _fill_band(draw, x_start, y_s - inset, size, y_s, grey)
        _fill_band(draw, x_start, y_s - inset - width, size, y_s - inset, white)
        y_start = min(size, size - dy + r)
        _fill_band(draw, size - dx - inset, y_start, size - dx, size, grey)
        _fill_band(draw, size - dx - inset - width, y_start, size - dx - inset, size, white)
    elif q == 2:
        y_s = dy
        x_start = min(size, size - dx + r)
        _fill_band(draw, x_start, y_s, size, y_s + inset, grey)
        _fill_band(draw, x_start, y_s + inset, size, y_s + inset + width, white)
        y_end = max(0, dy - r)
        _fill_band(draw, size - dx - inset, 0, size - dx, y_end, grey)
        _fill_band(draw, size - dx - inset - width, 0, size - dx - inset, y_end, white)
    else:
        y_s = dy
        x_end = max(0, dx - r)
        _fill_band(draw, 0, y_s, x_end, y_s + inset, grey)
        _fill_band(draw, 0, y_s + inset, x_end, y_s + inset + width, white)
        y_end = max(0, dy - r)
        _fill_band(draw, dx, 0, dx + inset, y_end, grey)
        _fill_band(draw, dx + inset, 0, dx + inset + width, y_end, white)


def _punch_leftover_extra(draw, size: int, quadrant: int, dx: int, dy: int, r: int) -> None:
    """
    Grass only the leftover beyond the r×r AABB square.

    The square itself is the Double-style quarter-circle bite, not a rectangle —
    punching the full leftover pinched the mouth corridors into an X.
    """
    clear = (0, 0, 0, 0)
    q = quadrant % 4
    if q == 0:
        if dx > r:
            _fill_band(draw, r, size - dy, dx, size, clear)
        if dy > r:
            _fill_band(draw, 0, size - dy, min(dx, r), size - r, clear)
    elif q == 1:
        if dx > r:
            _fill_band(draw, size - dx, size - dy, size - r, size, clear)
        if dy > r:
            _fill_band(draw, max(size - dx, size - r), size - dy, size, size - r, clear)
    elif q == 2:
        if dx > r:
            _fill_band(draw, size - dx, 0, size - r, dy, clear)
        if dy > r:
            _fill_band(draw, max(size - dx, size - r), r, size, dy, clear)
    else:
        if dx > r:
            _fill_band(draw, r, 0, dx, dy, clear)
        if dy > r:
            _fill_band(draw, 0, r, min(dx, r), dy, clear)


def _apply_mixed_corner(img, cells: int, quadrant: int, leftover_x: int, leftover_y: int) -> None:
    """AABB-corner fillet of min leftover, plus extra-strip grass; curbs on virtual sharps."""
    if ImageDraw is None or leftover_x <= 0 or leftover_y <= 0:
        return
    t = ORTHO_TILE_SIZE
    size = cells * t
    dx, dy = leftover_x * t, leftover_y * t
    inner_r = max(2, min(dx, dy))
    draw = ImageDraw.Draw(img)
    _punch_leftover_extra(draw, size, quadrant, dx, dy, inner_r)
    _stroke_fillet_lip(img, cells, quadrant, inner_r=inner_r)
    _stroke_virtual_curbs(img, size, quadrant, dx, dy, inner_r)


def make_mixed(
    cells: int,
    leftovers: tuple[tuple[int, int, int], ...],
    family: str = "cross",
    axis: str = "ns",
    stem: str = "E",
    spans: dict[str, tuple[int, int]] | None = None,
):
    """
    Mouth-span plaza: leftover fillets + family mask. No centre-two tee/corner recipes.
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

    if fam == "straight":
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        _fill_through_band(ImageDraw.Draw(img), size, local)
        return img
    if fam == "corner":
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        _fill_corner_L(ImageDraw.Draw(img), size, local)
        for quad, lx, ly in leftovers:
            _apply_mixed_corner(img, cells, quad, lx, ly)
        return img

    img = Image.new("RGBA", (size, size), (*ROAD_GREY, 255))
    for quad, lx, ly in leftovers:
        _apply_mixed_corner(img, cells, quad, lx, ly)
    if fam == "tee":
        open_edges = frozenset({"N", "S", "E", "W"}) - frozenset(local)
        draw = ImageDraw.Draw(img)
        for edge in open_edges:
            _punch_open_edge(draw, size, edge, local)
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
    _fill_stem_shoulder(img, cells, axis, stem)
    quads = tee_corner_quadrants(stem)  # type: ignore[arg-type]
    _restroke_axis_yellows(img, cells, axis)
    _restroke_open_side_white(img, cells, axis, omit_white)
    for q in quads:
        _stroke_fillet_lip(img, cells, q)
    _clear_open_half(img, cells, axis, stem)
    return img
