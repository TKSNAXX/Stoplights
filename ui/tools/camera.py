"""Exclusive camera tool: pan, zoom, and orbit modes."""
from __future__ import annotations

from ui.theme import (
    CAMERA_MODE_ORBIT,
    CAMERA_MODE_PAN,
    CAMERA_MODE_ZOOM,
    CAMERA_MODES,
)
from ui.tools.base import Tool
from ui.tools.host import ToolHost


class CameraTool(Tool):
    id = "camera"

    def __init__(self, host: ToolHost) -> None:
        super().__init__(host)
        self.mode = CAMERA_MODE_PAN
        self.orbit_ccw = False
        self._grabbing = False
        self._zooming = False
        self._orbit_press: tuple[float, float] | None = None

    @property
    def active_action(self) -> str | None:
        return "camera"

    @property
    def fly(self) -> bool:
        return bool(getattr(self.host, "pan_fly", False))

    def enter(self) -> None:
        self._sync_toolbar()

    def exit(self) -> None:
        self._clear_gesture()

    def _sync_toolbar(self) -> None:
        self.host.toolbar.camera_mode = self.mode
        self.host.toolbar.orbit_ccw = self.orbit_ccw

    def _clear_gesture(self) -> None:
        self._grabbing = False
        self._zooming = False
        self._orbit_press = None
        self.host.end_zoom_drag()
        if not getattr(self.host, "space_panning", False):
            self.host.end_camera_fly()
            self.host.end_camera_grab()

    def toggle_mode(self) -> str:
        i = CAMERA_MODES.index(self.mode) if self.mode in CAMERA_MODES else 0
        self.mode = CAMERA_MODES[(i + 1) % len(CAMERA_MODES)]
        self._clear_gesture()
        self._sync_toolbar()
        if self.mode == CAMERA_MODE_ZOOM:
            return "Zoom"
        if self.mode == CAMERA_MODE_ORBIT:
            return "Orbit"
        return "Pan"

    def toggle_overlay(self) -> str | None:
        if self.mode == CAMERA_MODE_PAN:
            toggle = getattr(self.host, "toggle_pan_fly", None)
            if callable(toggle):
                return toggle()
            return "Grab"
        if self.mode == CAMERA_MODE_ORBIT:
            self.orbit_ccw = not self.orbit_ccw
            self._sync_toolbar()
            return "CCW" if self.orbit_ccw else "CW"
        return None

    def on_press(self, x: float, y: float) -> bool:
        self._clear_gesture()
        if self.mode == CAMERA_MODE_PAN:
            if self.fly:
                self.host.begin_camera_fly(x, y)
            else:
                self._grabbing = True
                self.host.begin_camera_grab(x, y)
            return True
        if self.mode == CAMERA_MODE_ZOOM:
            self._zooming = True
            self.host.begin_zoom_drag(x, y)
            return True
        self._orbit_press = (x, y)
        return True

    def on_drag(self, x: float, y: float, dx: float, dy: float) -> None:
        if self.mode == CAMERA_MODE_PAN:
            if self._grabbing:
                self.host.update_camera_grab(x, y)
            return
        if self.mode == CAMERA_MODE_ZOOM and self._zooming:
            self.host.update_zoom_drag(x, y)

    def on_release(self, x: float, y: float) -> None:
        if self.mode == CAMERA_MODE_ORBIT and self._orbit_press is not None:
            ox, oy = self._orbit_press
            self.host.orbit_camera_at(ox, oy, clockwise=not self.orbit_ccw)
        self._clear_gesture()
