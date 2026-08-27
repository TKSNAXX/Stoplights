"""
Infrastructure selection rims: iso AABB silhouette and edge-contrast bands.

Arcade-free. Occupancy is a grid AABB (places, intersections, cardinal lanes).
"""
from __future__ import annotations

from collections.abc import Callable, Sequence

from sim.constants import TILE_H, TILE_W

Point = tuple[float, float]
Quad = tuple[list[Point], tuple[int, int, int, int]]

RIM_DISTANCES = (1.5, 3.0, 4.5, 6.0, 8.0)
# Multiply factors (255 = unchanged). Edge is strongest darken.
_SHADOW_FACTORS = (196, 214, 228, 240, 249)
# Screen lift toward white (0 = unchanged). Edge is strongest lift.
_HIGHLIGHT_LIFTS = (42, 30, 20, 12, 6)
_EPS = 1e-6


def occupancy_aabb(cells: Sequence[tuple[int, int]]) -> tuple[int, int, int, int] | None:
    """Inclusive-origin AABB (x_lo, y_lo, w, h) covering cells, or None if empty."""
    if not cells:
        return None
    xs = [c[0] for c in cells]
    ys = [c[1] for c in cells]
    x_lo, y_lo = min(xs), min(ys)
    return (x_lo, y_lo, max(xs) - x_lo + 1, max(ys) - y_lo + 1)


def _diamond_vertices(sx: float, sy: float, half_w: float, half_h: float) -> dict[str, Point]:
    return {
        "W": (sx - half_w, sy),
        "E": (sx + half_w, sy),
        "N": (sx, sy + half_h),
        "S": (sx, sy - half_h),
    }


def _shoelace(poly: Sequence[Point]) -> float:
    total = 0.0
    n = len(poly)
    for i, (x0, y0) in enumerate(poly):
        x1, y1 = poly[(i + 1) % n]
        total += x0 * y1 - x1 * y0
    return total * 0.5


def ensure_ccw(poly: list[Point]) -> list[Point]:
    """Return a CCW copy (y-up). Needed so outward is rotate-edge-clockwise."""
    if len(poly) < 3:
        return list(poly)
    if _shoelace(poly) < 0:
        return list(reversed(poly))
    return list(poly)


def iso_aabb_silhouette(
    x_lo: int,
    y_lo: int,
    w: int,
    h: int,
    cell_center: Callable[[int, int], Point],
    half_w: float | None = None,
    half_h: float | None = None,
) -> list[Point]:
    """
    Screen-space convex silhouette of a grid AABB of iso diamonds.
    The union is always a parallelogram (a diamond when the block is square).
    """
    if w <= 0 or h <= 0:
        return []
    hw = TILE_W if half_w is None else half_w
    hh = TILE_H if half_h is None else half_h
    x_hi = x_lo + w
    y_hi = y_lo + h
    west = _diamond_vertices(*cell_center(x_lo, y_hi - 1), hw, hh)["W"]
    north = _diamond_vertices(*cell_center(x_hi - 1, y_hi - 1), hw, hh)["N"]
    east = _diamond_vertices(*cell_center(x_hi - 1, y_lo), hw, hh)["E"]
    south = _diamond_vertices(*cell_center(x_lo, y_lo), hw, hh)["S"]
    return ensure_ccw([west, north, east, south])


def _unit(dx: float, dy: float) -> Point | None:
    mag = (dx * dx + dy * dy) ** 0.5
    if mag < _EPS:
        return None
    return (dx / mag, dy / mag)


def _outward_unit(p0: Point, p1: Point) -> Point | None:
    """Outward normal for a CCW edge (y-up): rotate clockwise."""
    return _unit(p1[1] - p0[1], -(p1[0] - p0[0]))


def edge_faces_sw(p0: Point, p1: Point) -> bool:
    """True when the CCW edge's outward normal faces screen SW (not NE)."""
    n = _outward_unit(p0, p1)
    if n is None:
        return False
    return (n[0] + n[1]) < 0.0


def offset_polygon(poly: Sequence[Point], distance: float) -> list[Point]:
    """Shift a convex CCW polygon; positive distance is outward."""
    n = len(poly)
    if n < 3:
        return list(poly)
    out: list[Point] = []
    for i, p in enumerate(poly):
        prev = poly[(i - 1) % n]
        nxt = poly[(i + 1) % n]
        n1 = _outward_unit(prev, p)
        n2 = _outward_unit(p, nxt)
        if n1 is None and n2 is None:
            out.append(p)
            continue
        if n1 is None:
            n1 = n2
        if n2 is None:
            n2 = n1
        assert n1 is not None and n2 is not None
        denom = 1.0 + n1[0] * n2[0] + n1[1] * n2[1]
        if abs(denom) < _EPS:
            out.append((p[0] + distance * n1[0], p[1] + distance * n1[1]))
            continue
        scale = distance / denom
        out.append((p[0] + scale * (n1[0] + n2[0]), p[1] + scale * (n1[1] + n2[1])))
    return out


def _sw_mask(poly: Sequence[Point]) -> list[bool]:
    n = len(poly)
    return [edge_faces_sw(poly[i], poly[(i + 1) % n]) for i in range(n)]


def _quads_between(
    a: Sequence[Point],
    b: Sequence[Point],
    color: tuple[int, int, int, int],
    mask: Sequence[bool] | None,
) -> list[Quad]:
    n = min(len(a), len(b))
    quads: list[Quad] = []
    for i in range(n):
        if mask is not None and not mask[i]:
            continue
        j = (i + 1) % n
        quads.append(([a[i], a[j], b[j], b[i]], color))
    return quads


def rim_quads(poly: Sequence[Point]) -> tuple[list[Quad], list[Quad]]:
    """
    Iso bevel bands: (shadow_quads, highlight_quads).
    Shadow RGB is a multiply factor; highlight RGB is a screen lift. Alpha is 255.
    """
    if len(poly) < 3:
        return ([], [])
    sw = _sw_mask(poly)
    ne = [not f for f in sw]
    rings = [list(poly)]
    insets = [list(poly)]
    for d in RIM_DISTANCES:
        rings.append(offset_polygon(poly, d))
        insets.append(offset_polygon(poly, -d))
    shadows: list[Quad] = []
    highlights: list[Quad] = []
    for i, factor in enumerate(_SHADOW_FACTORS):
        shadows.extend(
            _quads_between(rings[i], rings[i + 1], (factor, factor, factor, 255), ne)
        )
    for i, lift in enumerate(_HIGHLIGHT_LIFTS):
        highlights.extend(
            _quads_between(insets[i + 1], insets[i], (lift, lift, lift, 255), sw)
        )
    return (shadows, highlights)
