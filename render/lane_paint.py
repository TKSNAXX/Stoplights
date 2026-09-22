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

from render.camera import rotate_cardinal
from sim.constants import ORTHO_TILE_SIZE

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore

from sim import world

ROLE_SISTER = "sister"
ROLE_CURB = "curb"
ROLE_LEFT_CURB = "left_curb"
ROLE_ONCOMING = "oncoming"

PAVEMENT = (90, 90, 90)
YELLOW = (220, 220, 80)
WHITE = (220, 220, 220)

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


def paint_spec(
    heading: str,
    gx: int,
    gy: int,
    view_yaw_q: int = 0,
    occupancy: Mapping[tuple[int, int], int] | None = None,
    heading_for_lane: Callable[[int], str] | None = None,
) -> tuple[str, str, str, int]:
    """(display_dir, role_a, role_b, phase) for one cell."""
    h = heading if heading in _OPPOSITE_DIR else "N"
    roles = lateral_roles(h, gx, gy, occupancy, heading_for_lane)
    display_dir, role_a, role_b = display_edge_roles(h, roles, view_yaw_q)
    travel = gy if h in ("N", "S") else gx
    return display_dir, role_a, role_b, texture_phase(role_a, role_b, travel)


def raster_lane_ortho(display_dir: str, role_a: str, role_b: str, phase: int = 0):
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
