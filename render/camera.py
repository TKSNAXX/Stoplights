"""Camera/projection helpers."""
from __future__ import annotations

from sim.constants import TILE_H, TILE_W


def grid_to_screen(
    gx: float,
    gy: float,
    center_x: float,
    center_y: float,
    grid_w: int,
    grid_h: int,
) -> tuple[float, float]:
    """Isometric projection: grid (gx, gy) -> screen (sx, sy)."""
    cx = (grid_w - 1) / 2
    cy = (grid_h - 1) / 2
    sx = center_x + (gx - gy) * TILE_W
    sy = center_y + (gx + gy - cx - cy) * TILE_H
    return (sx, sy)


def screen_to_grid(
    sx: float,
    sy: float,
    center_x: float,
    center_y: float,
    grid_w: int,
    grid_h: int,
) -> tuple[float, float]:
    """Inverse of grid_to_screen: screen (sx, sy) -> grid (gx, gy)."""
    cx = (grid_w - 1) / 2
    cy = (grid_h - 1) / 2
    u = (sx - center_x) / TILE_W
    v = (sy - center_y) / TILE_H + cx + cy
    gx = (u + v) / 2
    gy = (v - u) / 2
    return (gx, gy)
