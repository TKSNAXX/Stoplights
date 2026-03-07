"""Debug rendering helpers."""
from __future__ import annotations

from sim.visibility import forward_right_vectors


def visibility_fan_vertices(
    gx: float, gy: float, dir_index_8: int, length: float, half_width: float
) -> list[tuple[float, float]]:
    """Return 4 grid-space corners of the visibility fan."""
    (fx, fy), (rx, ry) = forward_right_vectors(dir_index_8)
    back_center = (gx, gy)
    front_center = (gx + fx * length, gy + fy * length)
    back_left = (back_center[0] - rx * half_width, back_center[1] - ry * half_width)
    back_right = (back_center[0] + rx * half_width, back_center[1] + ry * half_width)
    front_left = (front_center[0] - rx * half_width, front_center[1] - ry * half_width)
    front_right = (front_center[0] + rx * half_width, front_center[1] + ry * half_width)
    return [back_left, front_left, front_right, back_right]
