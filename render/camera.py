"""Camera/projection helpers."""
from __future__ import annotations

from sim.constants import TILE_H, TILE_W


def _content_midpoint(x_lo: int, y_lo: int, x_hi: int, y_hi: int) -> tuple[float, float]:
    """Midpoint of inclusive cell range [lo, hi)."""
    return ((x_lo + x_hi - 1) / 2.0, (y_lo + y_hi - 1) / 2.0)


def grid_to_screen(
    gx: float,
    gy: float,
    center_x: float,
    center_y: float,
    x_lo: int,
    y_lo: int,
    x_hi: int,
    y_hi: int,
    zoom_scale: float = 1.0,
) -> tuple[float, float]:
    """Isometric projection: authored grid (gx, gy) -> screen (sx, sy)."""
    cx, cy = _content_midpoint(x_lo, y_lo, x_hi, y_hi)
    sx = center_x + (gx - gy) * TILE_W * zoom_scale
    sy = center_y + (gx + gy - cx - cy) * TILE_H * zoom_scale
    return (sx, sy)


def screen_to_grid(
    sx: float,
    sy: float,
    center_x: float,
    center_y: float,
    x_lo: int,
    y_lo: int,
    x_hi: int,
    y_hi: int,
    zoom_scale: float = 1.0,
) -> tuple[float, float]:
    """Inverse of grid_to_screen: screen (sx, sy) -> authored grid (gx, gy)."""
    cx, cy = _content_midpoint(x_lo, y_lo, x_hi, y_hi)
    u = (sx - center_x) / (TILE_W * zoom_scale)
    v = (sy - center_y) / (TILE_H * zoom_scale) + cx + cy
    gx = (u + v) / 2
    gy = (v - u) / 2
    return (gx, gy)
