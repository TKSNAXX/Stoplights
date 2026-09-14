"""Procedural pan / zoom / orbit glyphs for the camera tool."""
from __future__ import annotations

import math

import arcade

from ui.theme import CAMERA_ICON_FILL, CAMERA_ICON_STROKE


def _poly_fill_stroke(pts: list[tuple[float, float]], fill, stroke, width: float = 1.5) -> None:
    arcade.draw_polygon_filled(pts, fill)
    arcade.draw_polygon_outline(pts, stroke, width)


def _segment_quad(
    x0: float, y0: float, x1: float, y1: float, thickness: float
) -> list[tuple[float, float]]:
    dx, dy = x1 - x0, y1 - y0
    mag = math.hypot(dx, dy) or 1.0
    px, py = (-dy / mag) * thickness * 0.5, (dx / mag) * thickness * 0.5
    return [(x0 + px, y0 + py), (x1 + px, y1 + py), (x1 - px, y1 - py), (x0 - px, y0 - py)]


def _ellipse_pts(cx: float, cy: float, rx: float, ry: float, n: int = 24) -> list[tuple[float, float]]:
    return [
        (cx + rx * math.cos(2.0 * math.pi * i / n), cy + ry * math.sin(2.0 * math.pi * i / n))
        for i in range(n)
    ]


def draw_pan_arrows(
    cx: float,
    cy: float,
    size: float = 11.0,
    fill=CAMERA_ICON_FILL,
    stroke=CAMERA_ICON_STROKE,
) -> None:
    """Four-way cross arrows, centred on (cx, cy)."""
    s = size
    head = s * 0.42
    half = s * 0.16
    shaft = s * 0.22
    polys = (
        ((cx, cy + s), (cx - head * 0.55, cy + s - head), (cx + head * 0.55, cy + s - head)),
        ((cx, cy - s), (cx - head * 0.55, cy - s + head), (cx + head * 0.55, cy - s + head)),
        ((cx + s, cy), (cx + s - head, cy - head * 0.55), (cx + s - head, cy + head * 0.55)),
        ((cx - s, cy), (cx - s + head, cy - head * 0.55), (cx - s + head, cy + head * 0.55)),
        (
            (cx - half, cy + shaft),
            (cx + half, cy + shaft),
            (cx + half, cy - shaft),
            (cx - half, cy - shaft),
        ),
        (
            (cx - shaft, cy + half),
            (cx + shaft, cy + half),
            (cx + shaft, cy - half),
            (cx - shaft, cy - half),
        ),
    )
    for pts in polys:
        _poly_fill_stroke(list(pts), fill, stroke)


def draw_zoom_icon(
    cx: float,
    cy: float,
    size: float = 11.0,
    fill=CAMERA_ICON_FILL,
    stroke=CAMERA_ICON_STROKE,
) -> None:
    """Magnifying glass with a vertical double arrow."""
    r = size * 0.42
    gx = cx - size * 0.18
    gy = cy + size * 0.12
    arcade.draw_ellipse_filled(gx, gy, r * 2.0, r * 2.0, fill)
    arcade.draw_polygon_outline(_ellipse_pts(gx, gy, r, r), stroke, 2)
    hx0 = gx + r * 0.62
    hy0 = gy - r * 0.62
    hx1 = gx + r * 1.35
    hy1 = gy - r * 1.35
    _poly_fill_stroke(_segment_quad(hx0, hy0, hx1, hy1, 2.4), fill, stroke, 1.0)
    ax = cx + size * 0.55
    top = cy + size * 0.85
    bot = cy - size * 0.85
    wing = size * 0.28
    _poly_fill_stroke(_segment_quad(ax, bot + wing, ax, top - wing, 2.0), fill, stroke, 1.0)
    _poly_fill_stroke(
        [(ax, top), (ax - wing, top - wing), (ax + wing, top - wing)], fill, stroke
    )
    _poly_fill_stroke(
        [(ax, bot), (ax - wing, bot + wing), (ax + wing, bot + wing)], fill, stroke
    )


def draw_orbit_icon(
    cx: float,
    cy: float,
    size: float = 11.0,
    ccw: bool = False,
    fill=CAMERA_ICON_FILL,
    stroke=CAMERA_ICON_STROKE,
) -> None:
    """Elliptical loop with an arrowhead; ccw mirrors horizontally."""
    rx = size * 0.95
    ry = size * 0.55
    n = 28
    start = 0.35
    end = 2.0 * math.pi - 0.45
    pts: list[tuple[float, float]] = []
    for i in range(n):
        t = start + (end - start) * i / (n - 1)
        x = cx + rx * math.cos(t)
        y = cy + ry * math.sin(t)
        if ccw:
            x = 2.0 * cx - x
        pts.append((x, y))
    for i in range(len(pts) - 1):
        _poly_fill_stroke(_segment_quad(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], 2.2), fill, stroke, 1.0)
    tip = pts[-1]
    prev = pts[max(0, len(pts) - 4)]
    dx = tip[0] - prev[0]
    dy = tip[1] - prev[1]
    mag = math.hypot(dx, dy) or 1.0
    ux, uy = dx / mag, dy / mag
    px, py = -uy, ux
    head = size * 0.38
    wing = size * 0.22
    base = (tip[0] - ux * head, tip[1] - uy * head)
    _poly_fill_stroke(
        [
            tip,
            (base[0] + px * wing, base[1] + py * wing),
            (base[0] - px * wing, base[1] - py * wing),
        ],
        fill,
        stroke,
    )
