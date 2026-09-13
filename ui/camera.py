"""Always-on pan and discrete zoom. Not an exclusive tool."""
from __future__ import annotations

import arcade

from sim import world
from sim.constants import TILE_H, TILE_W

ZOOM_STEPS = 5
ZOOM_LEVEL_FIT = 0
ZOOM_LEVEL_MAX = 4
EDGE_PAN_MARGIN = 48
CAM_PAN_SPEED = 300.0


class CameraController:
    """Zoom steps, arrow pan, edge pan. Window owns edge-pan enabled flag."""

    def __init__(self) -> None:
        self.cam_x = 0.0
        self.cam_y = 0.0
        self.zoom_level = ZOOM_LEVEL_FIT
        self.zoom_scale = 1.0
        self.pan_speed = CAM_PAN_SPEED
        self._key_left = False
        self._key_right = False
        self._key_up = False
        self._key_down = False

    def handle_key_press(self, key: int) -> bool:
        if key == arcade.key.LEFT:
            self._key_left = True
            return True
        if key == arcade.key.RIGHT:
            self._key_right = True
            return True
        if key == arcade.key.UP:
            self._key_up = True
            return True
        if key == arcade.key.DOWN:
            self._key_down = True
            return True
        return False

    def handle_key_release(self, key: int) -> bool:
        if key == arcade.key.LEFT:
            self._key_left = False
            return True
        if key == arcade.key.RIGHT:
            self._key_right = False
            return True
        if key == arcade.key.UP:
            self._key_up = False
            return True
        if key == arcade.key.DOWN:
            self._key_down = False
            return True
        return False

    def handle_scroll(self, scroll_y: int) -> None:
        if scroll_y > 0:
            self.zoom_level = min(ZOOM_LEVEL_MAX, self.zoom_level + 1)
        elif scroll_y < 0:
            self.zoom_level = max(ZOOM_LEVEL_FIT, self.zoom_level - 1)

    def update_zoom_scale(self, width: float, height: float) -> None:
        map_w = (world.get_grid_w() + world.get_grid_h()) * TILE_W
        map_h = (world.get_grid_w() + world.get_grid_h()) * TILE_H
        scale_min = min(width / map_w, height / map_h)
        scale_max = height / (4 * 2 * TILE_H)
        level = max(0, min(ZOOM_LEVEL_MAX, self.zoom_level))
        if scale_max <= scale_min or level == 0:
            self.zoom_scale = scale_min
        else:
            self.zoom_scale = scale_min * (scale_max / scale_min) ** (level / ZOOM_LEVEL_MAX)

    def effective_center(self, width: float, height: float) -> tuple[float, float]:
        return (width / 2 - self.cam_x, height / 2 - self.cam_y)

    def clamp(self, width: float, height: float) -> None:
        z = self.zoom_scale
        map_w = (world.get_grid_w() + world.get_grid_h() - 2) * TILE_W * z * 1.5
        map_h = (world.get_grid_w() + world.get_grid_h() - 2) * TILE_H * z * 1.5
        max_cam_x = max(0, map_w / 2 - width / 2)
        max_cam_y = max(0, map_h / 2 - height / 2)
        self.cam_x = max(-max_cam_x, min(max_cam_x, self.cam_x))
        self.cam_y = max(-max_cam_y, min(max_cam_y, self.cam_y))

    def update(
        self,
        dt: float,
        width: float,
        height: float,
        mouse_x: float,
        mouse_y: float,
        mouse_in_window: bool,
        over_dialog: bool,
        edge_pan_enabled: bool,
    ) -> None:
        vx = self.pan_speed if self._key_right else (-self.pan_speed if self._key_left else 0.0)
        vy = self.pan_speed if self._key_up else (-self.pan_speed if self._key_down else 0.0)
        if edge_pan_enabled and mouse_in_window and not over_dialog:
            if mouse_x < EDGE_PAN_MARGIN:
                vx -= self.pan_speed
            elif mouse_x > width - EDGE_PAN_MARGIN:
                vx += self.pan_speed
            if mouse_y < EDGE_PAN_MARGIN:
                vy -= self.pan_speed
            elif mouse_y > height - EDGE_PAN_MARGIN:
                vy += self.pan_speed
        self.cam_x += vx * dt
        self.cam_y += vy * dt
        self.clamp(width, height)
