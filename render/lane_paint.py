"""
Default lane-edge paint from occupancy.

Roles (sister / curb / left curb / oncoming) are local: who sits in the perpendicular
neighbour cell. An empty driver's-left side is the yellow curb. Styles are a parameter table; a later paint tool can pass
a custom EdgeStyle or a new role without new tile art.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from render.camera import rotate_cardinal
from sim.constants import ORTHO_TILE_SIZE

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore

from sim import map_data, world

ROLE_SISTER = "sister"
ROLE_CURB = "curb"
ROLE_LEFT_CURB = "left_curb"
ROLE_ONCOMING = "oncoming"

PAVEMENT = (90, 90, 90)
YELLOW = (220, 220, 80)
WHITE = (220, 220, 220)
GRASS = (60, 120, 40)

_GRASS_PATH = Path(__file__).resolve().parents[1] / "assets" / "ortho" / "grass.png"
_grass_tile = None

_OPPOSITE_DIR = {"N": "S", "S": "N", "E": "W", "W": "E"}
# Driver's left under right-hand traffic.
DRIVER_LEFT = {"N": "W", "S": "E", "E": "N", "W": "S"}

# Bump when default styles change so iso caches cannot serve stale tiles.
STYLE_REV = 3


@dataclass(frozen=True)
class EdgeStyle:
    color: tuple[int, int, int]
    width: int
    inset: int
    dash_on: int
    dash_off: int
    dash_offset: int = 0


STYLES: dict[str, EdgeStyle] = {
    ROLE_SISTER: EdgeStyle(WHITE, width=1, inset=0, dash_on=16, dash_off=16),
    ROLE_CURB: EdgeStyle(WHITE, width=2, inset=2, dash_on=0, dash_off=0),
    ROLE_LEFT_CURB: EdgeStyle(YELLOW, width=2, inset=2, dash_on=0, dash_off=0),
    ROLE_ONCOMING: EdgeStyle(YELLOW, width=2, inset=2, dash_on=0, dash_off=0),
}

CURB_INSET = STYLES[ROLE_CURB].inset
CURB_WIDTH = STYLES[ROLE_CURB].width


def style_for_role(role: str) -> EdgeStyle:
    return STYLES.get(role, STYLES[ROLE_CURB])


def dash_period(style: EdgeStyle) -> int:
    if style.dash_on <= 0 and style.dash_off <= 0:
        return 0
    return max(1, int(style.dash_on) + int(style.dash_off))


def dash_on_at(style: EdgeStyle, along: int) -> bool:
    period = dash_period(style)
    if period == 0:
        return True
    return (int(along) + int(style.dash_offset)) % period < int(style.dash_on)


def texture_phase(role_a: str, role_b: str, travel: int) -> int:
    """Start offset along the stripe so consecutive travel cells continue the dash."""
    periods = [dash_period(style_for_role(r)) for r in (role_a, role_b)]
    periods = [p for p in periods if p > 0]
    if not periods:
        return 0
    period = periods[0]
    for p in periods[1:]:
        period = math.lcm(period, p)
    return (int(travel) * ORTHO_TILE_SIZE) % period


def role_for_neighbor(
    heading: str,
    neighbor_heading: str | None,
    *,
    side: str | None = None,
) -> str:
    """Role of the lateral toward `side`. An empty driver's-left side is a yellow curb."""
    if not neighbor_heading:
        if side is not None and side == DRIVER_LEFT.get(heading):
            return ROLE_LEFT_CURB
        return ROLE_CURB
    if neighbor_heading == heading:
        return ROLE_SISTER
    if _OPPOSITE_DIR.get(heading) == neighbor_heading:
        return ROLE_ONCOMING
    return ROLE_CURB


def lateral_neighbor_cells(heading: str, gx: int, gy: int) -> dict[str, tuple[int, int]]:
    """World cardinal → neighbour cell on the two laterals."""
    if heading in ("N", "S"):
        return {"W": (gx - 1, gy), "E": (gx + 1, gy)}
    return {"N": (gx, gy + 1), "S": (gx, gy - 1)}


def lateral_roles(
    heading: str,
    gx: int,
    gy: int,
    occupancy: Mapping[tuple[int, int], int] | None = None,
    heading_for_lane: Callable[[int], str] | None = None,
) -> dict[str, str]:
    """World cardinal → role for this cell's two lateral edges."""
    occ = occupancy if occupancy is not None else world.cell_occupancy()
    laterals = lateral_neighbor_cells(heading, gx, gy)
    roles: dict[str, str] = {}
    for card, cell in laterals.items():
        other_id = occ.get(cell)
        other_dir: str | None = None
        if other_id is not None:
            if heading_for_lane is not None:
                other_dir = heading_for_lane(other_id) or None
            else:
                other_dir = world.lane_direction(other_id) or None
        roles[card] = role_for_neighbor(heading, other_dir, side=card)
    return roles


def display_edge_roles(
    heading: str,
    world_roles: Mapping[str, str],
    view_yaw_q: int = 0,
) -> tuple[str, str, str]:
    """
    Map world laterals onto the display tile's two stripe slots.

    NS display: role_a = ortho bottom, role_b = ortho top (world W / E at yaw 0).
    EW display: role_a = ortho left, role_b = ortho right (world N / S at yaw 0).
    """
    display_dir = rotate_cardinal(heading, view_yaw_q)
    by_display: dict[str, str] = {}
    for world_card, role in world_roles.items():
        by_display[rotate_cardinal(world_card, view_yaw_q)] = role
    if display_dir in ("N", "S"):
        return display_dir, by_display.get("W", ROLE_CURB), by_display.get("E", ROLE_CURB)
    return display_dir, by_display.get("N", ROLE_CURB), by_display.get("S", ROLE_CURB)


def _cell_hosted(gx: int, gy: int) -> bool:
    """True when this cell belongs to a place or an intersection."""
    if world.get_intersection_at_cell((gx, gy)):
        return True
    for rect in world.get_place_rects().values():
        x = int(rect.get("x", 0))
        y = int(rect.get("y", 0))
        w = int(rect.get("w", 0))
        h = int(rect.get("h", 0))
        if w > 0 and h > 0 and x <= gx < x + w and y <= gy < y + h:
            return True
    return False


def _heading_of(
    lane_id: int,
    heading_for_lane: Callable[[int], str] | None,
) -> str | None:
    if heading_for_lane is not None:
        return heading_for_lane(lane_id) or None
    return world.lane_direction(lane_id) or None


def mouth_chamfer(
    heading: str,
    gx: int,
    gy: int,
    occupancy: Mapping[tuple[int, int], int] | None = None,
    heading_for_lane: Callable[[int], str] | None = None,
) -> tuple[str, str] | None:
    """
    ('start'|'end', world cardinal of the outer curb) when this cell tapers.

    A start or end on open road, beside one same-heading sister who continues
    past the mouth, with an empty outer side. Shared mouths, middle lanes,
    oncoming neighbours, a mother/daughter join, and ends aimed at a place
    or intersection stay square.
    """
    h = heading if heading in _OPPOSITE_DIR else "N"
    occ = occupancy if occupancy is not None else world.cell_occupancy()
    lane_id = occ.get((gx, gy))
    if lane_id is None:
        return None
    fx, fy = map_data.offset_for_direction(h)
    if fx == 0 and fy == 0:
        return None
    ahead = (gx + fx, gy + fy)
    behind = (gx - fx, gy - fy)

    def same_lane(cell: tuple[int, int]) -> bool:
        return occ.get(cell) == lane_id

    is_end = not same_lane(ahead)
    is_start = not same_lane(behind)
    if not is_end and not is_start:
        return None

    laterals = lateral_neighbor_cells(h, gx, gy)
    sisters: list[tuple[str, int]] = []
    empties: list[str] = []
    for card, cell in laterals.items():
        other_id = occ.get(cell)
        if other_id is None:
            empties.append(card)
            continue
        if _heading_of(other_id, heading_for_lane) == h:
            sisters.append((card, other_id))
    if len(sisters) != 1 or len(empties) != 1:
        return None
    sister_side, sister_id = sisters[0]
    outer = empties[0]
    sx, sy = laterals[sister_side]
    found: list[tuple[str, str]] = []
    for mouth, active, lane_beyond, step in (
        ("end", is_end, ahead, (fx, fy)),
        ("start", is_start, behind, (-fx, -fy)),
    ):
        if not active:
            continue
        # The next cell of the same road is a daughter (or this cell's mother).
        other_id = occ.get(lane_beyond)
        if (
            other_id is not None
            and other_id != lane_id
            and _heading_of(other_id, heading_for_lane) == h
        ):
            continue
        beyond_sister = (sx + step[0], sy + step[1])
        if occ.get(beyond_sister) != sister_id:
            continue
        if _cell_hosted(gx, gy) or _cell_hosted(*lane_beyond):
            continue
        found.append((mouth, outer))
    if len(found) != 1:
        return None
    return found[0]


def paint_spec(
    heading: str,
    gx: int,
    gy: int,
    view_yaw_q: int = 0,
    occupancy: Mapping[tuple[int, int], int] | None = None,
    heading_for_lane: Callable[[int], str] | None = None,
) -> tuple[str, str, str, int, tuple[str, str] | None]:
    """(display_dir, role_a, role_b, phase, chamfer) for one cell.

    chamfer is ('start'|'end', display cardinal of the outer curb), or None.
    """
    h = heading if heading in _OPPOSITE_DIR else "N"
    roles = lateral_roles(h, gx, gy, occupancy, heading_for_lane)
    display_dir, role_a, role_b = display_edge_roles(h, roles, view_yaw_q)
    travel = gy if h in ("N", "S") else gx
    raw = mouth_chamfer(h, gx, gy, occupancy, heading_for_lane)
    chamfer = None
    if raw is not None:
        mouth, outer = raw
        chamfer = (mouth, rotate_cardinal(outer, view_yaw_q))
    return display_dir, role_a, role_b, texture_phase(role_a, role_b, travel), chamfer


def raster_lane_ortho(
    display_dir: str,
    role_a: str,
    role_b: str,
    phase: int = 0,
    chamfer: tuple[str, str] | None = None,
):
    """32×32 pavement with two lateral stripes. role_a/b as in display_edge_roles."""
    if Image is None:
        return None
    size = ORTHO_TILE_SIZE
    img = Image.new("RGBA", (size, size), (*PAVEMENT, 255))
    px = img.load()
    style_a = style_for_role(role_a)
    style_b = style_for_role(role_b)
    if display_dir in ("N", "S"):
        _paint_h(px, size, _bottom_span(size, style_a), style_a, phase)
        _paint_h(px, size, _top_span(size, style_b), style_b, phase)
    else:
        _paint_v(px, size, _left_span(size, style_a), style_a, phase)
        _paint_v(px, size, _right_span(size, style_b), style_b, phase)
    if chamfer is not None:
        _apply_chamfer(img, display_dir, role_a, role_b, chamfer)
    return img


def _top_span(size: int, style: EdgeStyle) -> tuple[int, int]:
    y0 = max(0, int(style.inset))
    return y0, min(size, y0 + max(0, int(style.width)))


def _bottom_span(size: int, style: EdgeStyle) -> tuple[int, int]:
    y1 = size - max(0, int(style.inset))
    y0 = y1 - max(0, int(style.width))
    return max(0, y0), min(size, y1)


def _left_span(size: int, style: EdgeStyle) -> tuple[int, int]:
    x0 = max(0, int(style.inset))
    return x0, min(size, x0 + max(0, int(style.width)))


def _right_span(size: int, style: EdgeStyle) -> tuple[int, int]:
    x1 = size - max(0, int(style.inset))
    x0 = x1 - max(0, int(style.width))
    return max(0, x0), min(size, x1)


def _paint_h(px, size: int, span: tuple[int, int], style: EdgeStyle, phase: int) -> None:
    y0, y1 = span
    for y in range(y0, y1):
        for x in range(size):
            if dash_on_at(style, int(phase) + x):
                px[x, y] = (*style.color, 255)


def _paint_v(px, size: int, span: tuple[int, int], style: EdgeStyle, phase: int) -> None:
    x0, x1 = span
    for x in range(x0, x1):
        for y in range(size):
            if dash_on_at(style, int(phase) + y):
                px[x, y] = (*style.color, 255)


def _image_corner(along: str, across: str, size: int) -> tuple[int, int]:
    """Ortho corner. Small x is north, small y is east."""
    x = y = 0
    for card in (along, across):
        if card == "N":
            x = 0
        elif card == "S":
            x = size
        elif card == "E":
            y = 0
        elif card == "W":
            y = size
    return (x, y)


def _grass_side(x: int, y: int, a: tuple[int, int], b: tuple[int, int], grass: tuple[int, int]) -> bool:
    ax, ay = a
    bx, by = b
    cross = (bx - ax) * (y - ay) - (by - ay) * (x - ax)
    gcross = (bx - ax) * (grass[1] - ay) - (by - ay) * (grass[0] - ax)
    return cross * gcross >= 0


def _diag_offset(inward: tuple[int, int], dist: int) -> tuple[int, int]:
    ix, iy = inward
    step = dist / math.sqrt(2.0)
    ox, oy = round(ix * step), round(iy * step)
    if dist and ox == 0 and oy == 0:
        return (ix, iy)
    return (ox, oy)


def grass_at(x: int, y: int) -> tuple[int, int, int, int]:
    """Opaque grass for this ortho pixel. The lane tile is the cell, so the cut must carry grass."""
    global _grass_tile
    if _grass_tile is None and Image is not None:
        try:
            img = Image.open(_GRASS_PATH).convert("RGBA")
            if img.size != (ORTHO_TILE_SIZE, ORTHO_TILE_SIZE):
                img = img.resize((ORTHO_TILE_SIZE, ORTHO_TILE_SIZE), Image.NEAREST)
            _grass_tile = img
        except OSError:
            _grass_tile = False
    if not _grass_tile:
        return (*GRASS, 255)
    return _grass_tile.getpixel((x, y))


def _role_on_side(display_dir: str, side: str, role_a: str, role_b: str) -> str:
    if display_dir in ("N", "S"):
        return role_a if side == "W" else role_b
    return role_a if side == "N" else role_b


def _apply_chamfer(
    img,
    display_dir: str,
    role_a: str,
    role_b: str,
    chamfer: tuple[str, str],
) -> None:
    """Cut the forward-outer (end) or back-outer (start) triangle and stroke it."""
    if ImageDraw is None or display_dir not in _OPPOSITE_DIR:
        return
    mouth, outer = chamfer
    if mouth not in ("start", "end") or outer not in _OPPOSITE_DIR:
        return
    size = img.size[0]
    forward = display_dir
    back = _OPPOSITE_DIR[forward]
    inner = _OPPOSITE_DIR[outer]
    if mouth == "end":
        grass = _image_corner(forward, outer, size)
        a = _image_corner(forward, inner, size)
        b = _image_corner(back, outer, size)
    else:
        grass = _image_corner(back, outer, size)
        a = _image_corner(back, inner, size)
        b = _image_corner(forward, outer, size)
    px = img.load()
    for y in range(size):
        for x in range(size):
            if _grass_side(x, y, a, b, grass):
                px[x, y] = grass_at(x, y)
    mid_x = (a[0] + b[0]) / 2.0
    mid_y = (a[1] + b[1]) / 2.0
    inward = (1 if mid_x > grass[0] else -1, 1 if mid_y > grass[1] else -1)
    color = style_for_role(_role_on_side(display_dir, outer, role_a, role_b)).color
    og = _diag_offset(inward, CURB_INSET)
    ow = _diag_offset(inward, CURB_INSET + CURB_WIDTH)
    if ow == og:
        ow = (og[0] + inward[0], og[1] + inward[1])

    def add(p: tuple[int, int], o: tuple[int, int]) -> tuple[int, int]:
        return (p[0] + o[0], p[1] + o[1])

    draw = ImageDraw.Draw(img)
    draw.polygon([a, b, add(b, og), add(a, og)], fill=(*PAVEMENT, 255))
    draw.polygon([add(a, og), add(b, og), add(b, ow), add(a, ow)], fill=(*color, 255))
