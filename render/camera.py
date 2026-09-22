"""Camera/projection helpers."""
from __future__ import annotations

from sim.constants import TILE_H, TILE_W

CARDINALS_CW: tuple[str, str, str, str] = ("N", "E", "S", "W")
_ROAD_FOR_CARDINAL = {"N": "road_n", "E": "road_e", "S": "road_s", "W": "road_w"}
_LABEL_ANCHOR_YAW0 = {
    "N": ("center", "bottom"),
    "S": ("center", "top"),
    "E": ("right", "center"),
    "W": ("left", "center"),
}


def _content_midpoint(x_lo: int, y_lo: int, x_hi: int, y_hi: int) -> tuple[float, float]:
    """Midpoint of inclusive cell range [lo, hi)."""
    return ((x_lo + x_hi - 1) / 2.0, (y_lo + y_hi - 1) / 2.0)


def normalize_yaw(view_yaw_q: int) -> int:
    return int(view_yaw_q) % 4


def rotate_grid_point(
    gx: float,
    gy: float,
    x_lo: int,
    y_lo: int,
    x_hi: int,
    y_hi: int,
    view_yaw_q: int = 0,
) -> tuple[float, float]:
    """Rotate authored (gx, gy) 90° CW per yaw step around the content midpoint."""
    q = normalize_yaw(view_yaw_q)
    if q == 0:
        return (gx, gy)
    cx, cy = _content_midpoint(x_lo, y_lo, x_hi, y_hi)
    dx, dy = gx - cx, gy - cy
    for _ in range(q):
        dx, dy = dy, -dx
    return (cx + dx, cy + dy)


def unrotate_grid_point(
    gx: float,
    gy: float,
    x_lo: int,
    y_lo: int,
    x_hi: int,
    y_hi: int,
    view_yaw_q: int = 0,
) -> tuple[float, float]:
    """Inverse of rotate_grid_point."""
    return rotate_grid_point(gx, gy, x_lo, y_lo, x_hi, y_hi, -normalize_yaw(view_yaw_q))


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
    view_yaw_q: int = 0,
) -> tuple[float, float]:
    """Isometric projection: authored grid (gx, gy) -> screen (sx, sy)."""
    cx, cy = _content_midpoint(x_lo, y_lo, x_hi, y_hi)
    rx, ry = rotate_grid_point(gx, gy, x_lo, y_lo, x_hi, y_hi, view_yaw_q)
    sx = center_x + (rx - ry) * TILE_W * zoom_scale
    sy = center_y + (rx + ry - cx - cy) * TILE_H * zoom_scale
    return (sx, sy)


def grid_to_world_px(
    gx: float,
    gy: float,
    x_lo: int,
    y_lo: int,
    x_hi: int,
    y_hi: int,
    view_yaw_q: int = 0,
) -> tuple[float, float]:
    """Zoom-1 offset from the content center. The map camera applies pan and zoom."""
    return grid_to_screen(gx, gy, 0.0, 0.0, x_lo, y_lo, x_hi, y_hi, 1.0, view_yaw_q)


def map_camera_position(cam_x: float, cam_y: float, zoom_scale: float) -> tuple[float, float]:
    """Camera2D position that keeps the grid point under the cursor while panning."""
    z = zoom_scale if zoom_scale else 1.0
    return (cam_x / z, cam_y / z)


def map_camera_screen(
    world_x: float,
    world_y: float,
    cam_x: float,
    cam_y: float,
    zoom_scale: float,
    width: float,
    height: float,
) -> tuple[float, float]:
    """Screen point for a world pixel viewed through the map Camera2D.

    The camera uses ``zoom = zoom_scale`` and ``position = map_camera_position(...)``,
    with the projection centered on the window. That is
    ``screen = (world - position) * zoom + (width/2, height/2)``.
    """
    z = zoom_scale if zoom_scale else 1.0
    cam_px, cam_py = map_camera_position(cam_x, cam_y, z)
    return (
        (world_x - cam_px) * z + width / 2.0,
        (world_y - cam_py) * z + height / 2.0,
    )


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
    view_yaw_q: int = 0,
) -> tuple[float, float]:
    """Inverse of grid_to_screen: screen (sx, sy) -> authored grid (gx, gy)."""
    cx, cy = _content_midpoint(x_lo, y_lo, x_hi, y_hi)
    u = (sx - center_x) / (TILE_W * zoom_scale)
    v = (sy - center_y) / (TILE_H * zoom_scale) + cx + cy
    rx = (u + v) / 2
    ry = (v - u) / 2
    return unrotate_grid_point(rx, ry, x_lo, y_lo, x_hi, y_hi, view_yaw_q)


def iso_depth(
    gx: float,
    gy: float,
    x_lo: int,
    y_lo: int,
    x_hi: int,
    y_hi: int,
    view_yaw_q: int = 0,
) -> float:
    """Painter depth (rotated gx+gy). Larger is farther / drawn first."""
    rx, ry = rotate_grid_point(gx, gy, x_lo, y_lo, x_hi, y_hi, view_yaw_q)
    return rx + ry


def rotate_cardinal(cardinal: str, view_yaw_q: int = 0) -> str:
    """90° CW per yaw step: N→E→S→W→N."""
    key = cardinal if cardinal in CARDINALS_CW else "N"
    i = CARDINALS_CW.index(key)
    return CARDINALS_CW[(i + normalize_yaw(view_yaw_q)) % 4]


def rotate_sides(sides: frozenset[str], view_yaw_q: int = 0) -> frozenset[str]:
    return frozenset(rotate_cardinal(s, view_yaw_q) for s in sides)


def rotate_straight_axis(axis: str, view_yaw_q: int = 0) -> str:
    if normalize_yaw(view_yaw_q) % 2 == 0:
        return axis if axis in ("ns", "ew") else "ns"
    if axis == "ew":
        return "ns"
    return "ew"


def display_dir_index(world_dir_index: int, view_yaw_q: int = 0) -> int:
    """8-dir sprite index after yaw. 90° is two octants."""
    return (int(world_dir_index) + 2 * normalize_yaw(view_yaw_q)) % 8


def road_tile_key(world_dir: str, view_yaw_q: int = 0) -> str:
    disp = rotate_cardinal(world_dir, view_yaw_q)
    return _ROAD_FOR_CARDINAL[disp]


def cardinal_label_anchors(world_cardinal: str, view_yaw_q: int = 0) -> tuple[str, str]:
    """Arcade text anchors so the world cardinal sits outside its screen-edge cells."""
    disp = rotate_cardinal(world_cardinal, view_yaw_q)
    return _LABEL_ANCHOR_YAW0[disp]


def view_south_cell(
    origin_x: int,
    origin_y: int,
    cells_e: int,
    cells_n: int,
    x_lo: int,
    y_lo: int,
    x_hi: int,
    y_hi: int,
    view_yaw_q: int = 0,
) -> tuple[int, int]:
    """Footprint cell whose rotated gx+gy is minimum (iso screen-south / near)."""
    if cells_e <= 0 or cells_n <= 0:
        return (origin_x, origin_y)
    x1 = origin_x + cells_e - 1
    y1 = origin_y + cells_n - 1
    corners = (
        (origin_x, origin_y),
        (x1, origin_y),
        (origin_x, y1),
        (x1, y1),
    )
    best = corners[0]
    best_d = iso_depth(best[0], best[1], x_lo, y_lo, x_hi, y_hi, view_yaw_q)
    for cell in corners[1:]:
        d = iso_depth(cell[0], cell[1], x_lo, y_lo, x_hi, y_hi, view_yaw_q)
        if d < best_d:
            best = cell
            best_d = d
    return best
