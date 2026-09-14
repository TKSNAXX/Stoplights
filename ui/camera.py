"""Always-on pan, discrete zoom, and session view yaw. Not an exclusive tool."""
from __future__ import annotations

import math

import arcade

from render.camera import grid_to_screen, screen_to_grid
from sim import world
from sim.constants import TILE_H, TILE_W
from ui.theme import FLY_DEADZONE, FLY_REF_DIST, ZOOM_DRAG_PX

ZOOM_STEPS = 20
ZOOM_LEVEL_FIT = 0
ZOOM_LEVEL_MAX = 19
EDGE_PAN_MARGIN = 48
CAM_PAN_SPEED = 300.0


class CameraController:
    """Zoom steps, arrow pan, edge pan, grab/fly, orbit yaw. Window owns edge-pan flag."""

    def __init__(self) -> None:
        self.cam_x = 0.0
        self.cam_y = 0.0
        self.zoom_level = ZOOM_LEVEL_FIT
        self.zoom_scale = 1.0
        self.view_yaw_q = 0
        self.pan_speed = CAM_PAN_SPEED
        self._key_left = False
        self._key_right = False
        self._key_up = False
        self._key_down = False
        self._fly_origin: tuple[float, float] | None = None
        self._grab_anchor: tuple[float, float] | None = None
        self._zoom_press_y = 0.0
        self._zoom_press_level = 0
        self._zoom_anchor: tuple[float, float] | None = None

    @property
    def fly_origin(self) -> tuple[float, float] | None:
        return self._fly_origin

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

    def begin_grab(self, x: float, y: float, width: float, height: float) -> None:
        """Lock the grid point under (x, y) for the rest of the drag."""
        cx, cy = self.effective_center(width, height)
        bounds = world.get_bounds()
        self._grab_anchor = screen_to_grid(
            x, y, cx, cy, *bounds, self.zoom_scale, self.view_yaw_q
        )

    def update_grab(self, x: float, y: float, width: float, height: float) -> None:
        if self._grab_anchor is None:
            return
        gx, gy = self._grab_anchor
        self.keep_grid_at_screen(gx, gy, x, y, width, height)

    def end_grab(self) -> None:
        self._grab_anchor = None

    def begin_fly(self, x: float, y: float) -> None:
        self._fly_origin = (x, y)

    def end_fly(self) -> None:
        self._fly_origin = None

    def begin_zoom_drag(self, press_y: float, gx: float, gy: float) -> None:
        self._zoom_press_y = press_y
        self._zoom_press_level = self.zoom_level
        self._zoom_anchor = (gx, gy)

    def update_zoom_drag(self, y: float, mx: float, my: float, width: float, height: float) -> bool:
        if self._zoom_anchor is None:
            return False
        steps = int((y - self._zoom_press_y) / ZOOM_DRAG_PX)
        new_level = max(ZOOM_LEVEL_FIT, min(ZOOM_LEVEL_MAX, self._zoom_press_level + steps))
        if new_level == self.zoom_level:
            return False
        self.zoom_level = new_level
        self.update_zoom_scale(width, height)
        gx, gy = self._zoom_anchor
        self.keep_grid_at_screen(gx, gy, mx, my, width, height)
        return True

    def end_zoom_drag(self) -> None:
        self._zoom_anchor = None

    def keep_grid_at_screen(
        self, gx: float, gy: float, mx: float, my: float, width: float, height: float
    ) -> None:
        bounds = world.get_bounds()
        sx0, sy0 = grid_to_screen(
            gx, gy, width / 2, height / 2, *bounds, self.zoom_scale, self.view_yaw_q
        )
        self.cam_x = sx0 - mx
        self.cam_y = sy0 - my
        self.clamp(width, height)

    def orbit_at(self, sx: float, sy: float, clockwise: bool, width: float, height: float) -> None:
        bounds = world.get_bounds()
        cx, cy = self.effective_center(width, height)
        gx, gy = screen_to_grid(
            sx, sy, cx, cy, *bounds, self.zoom_scale, self.view_yaw_q
        )
        self.view_yaw_q = (self.view_yaw_q + (1 if clockwise else -1)) % 4
        sx0, sy0 = grid_to_screen(
            gx, gy, width / 2, height / 2, *bounds, self.zoom_scale, self.view_yaw_q
        )
        self.cam_x = sx0 - width / 2
        self.cam_y = sy0 - height / 2
        self.clamp(width, height)

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
        flying = self._fly_origin is not None
        if flying:
            ox, oy = self._fly_origin
            dx, dy = mouse_x - ox, mouse_y - oy
            dist = math.hypot(dx, dy)
            if dist > FLY_DEADZONE:
                speed = self.pan_speed * ((dist - FLY_DEADZONE) / FLY_REF_DIST)
                ux, uy = dx / dist, dy / dist
                # Autoscroll: view travels toward the mouse offset (content goes the other way).
                vx += ux * speed
                vy += uy * speed
        grabbing = self._grab_anchor is not None
        if grabbing:
            vx = 0.0
            vy = 0.0
        elif (
            not flying
            and edge_pan_enabled
            and mouse_in_window
            and not over_dialog
        ):
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
