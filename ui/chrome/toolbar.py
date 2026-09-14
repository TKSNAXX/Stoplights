"""Data-driven left toolbar."""
from __future__ import annotations

from dataclasses import dataclass

import arcade

from draw_compat import rect_filled, rect_outline
from ui.chrome.camera_icons import draw_orbit_icon, draw_pan_arrows, draw_zoom_icon
from ui.theme import (
    CAMERA_MODE_ORBIT,
    CAMERA_MODE_PAN,
    CAMERA_MODE_ZOOM,
    LABEL_COLOR,
    SELECT_MODE_CARS,
    SELECT_MODE_MAP,
    SELECT_POINTER_CARS_FILL,
    SELECT_POINTER_CARS_STROKE,
    SELECT_POINTER_MAP_FILL,
    SELECT_POINTER_MAP_STROKE,
    TOOLBAR_BG,
    TOOLBAR_BORDER,
    TOOLBAR_BUTTON_SIZE,
    TOOLBAR_GAP,
    TOOLBAR_GROUP_ORDER,
    TOOLBAR_WIDTH,
)


@dataclass(frozen=True)
class ToolbarItem:
    action: str
    group: str
    fallback: str = ""


DEFAULT_TOOLBAR_ITEMS: tuple[ToolbarItem, ...] = (
    ToolbarItem("select", "select"),
    ToolbarItem("camera", "camera"),
    ToolbarItem("new_intersection", "create", "+"),
    ToolbarItem("new_place", "create", "P"),
    ToolbarItem("new_lane", "create", "L"),
    ToolbarItem("settings", "settings", "..."),
)


class Toolbar:
    """
    Vertical bar on the left with square icon buttons grouped by section.
    on_press(x, y) returns an action id or None.
    """

    def __init__(
        self,
        left: float,
        bottom: float,
        width: float = TOOLBAR_WIDTH,
        items: tuple[ToolbarItem, ...] = DEFAULT_TOOLBAR_ITEMS,
    ):
        self.left = left
        self.bottom = bottom
        self.width = width
        self.items = items
        self._button_size = TOOLBAR_BUTTON_SIZE
        self._gap = TOOLBAR_GAP
        self.active_action: str | None = None
        self.select_mode: str = SELECT_MODE_MAP
        self.camera_mode: str = CAMERA_MODE_PAN
        self.orbit_ccw: bool = False
        self._icons: dict[str, tuple[arcade.Sprite, arcade.SpriteList]] = {}
        self._fallbacks: dict[str, arcade.Text] = {}
        for item in items:
            self._fallbacks[item.action] = arcade.Text(
                item.fallback or item.action[:1],
                0, 0, color=LABEL_COLOR,
                font_size=16 if item.action == "settings" else 18,
                anchor_x="center", anchor_y="center",
            )

    def _group_blocks(self) -> list[list[ToolbarItem]]:
        by_group: dict[str, list[ToolbarItem]] = {}
        for item in self.items:
            by_group.setdefault(item.group, []).append(item)
        blocks: list[list[ToolbarItem]] = []
        for group in TOOLBAR_GROUP_ORDER:
            if group in by_group:
                blocks.append(by_group[group])
        for group, block in by_group.items():
            if group not in TOOLBAR_GROUP_ORDER:
                blocks.append(block)
        return blocks

    @property
    def height(self) -> float:
        pad = (self.width - self._button_size) / 2
        n = len(self.items)
        return n * self._button_size + max(0, n - 1) * self._gap + 2 * pad

    def _icon_from_tex(self, tex: arcade.Texture) -> tuple[arcade.Sprite, arcade.SpriteList]:
        tw = max(1, getattr(tex, "width", 64))
        th = max(1, getattr(tex, "height", 32))
        pad = 4
        scale = min((self._button_size - pad) / tw, (self._button_size - pad) / th)
        spr = arcade.Sprite(tex, scale=scale)
        lst = arcade.SpriteList()
        lst.append(spr)
        return spr, lst

    def set_icon(self, action: str, tex: arcade.Texture | None) -> None:
        if tex is None:
            self._icons.pop(action, None)
            return
        self._icons[action] = self._icon_from_tex(tex)

    def set_lane_icon(self, tex: arcade.Texture | None) -> None:
        self.set_icon("new_lane", tex)

    def set_place_icon(self, tex: arcade.Texture | None) -> None:
        self.set_icon("new_place", tex)

    def set_intersection_icon(self, tex: arcade.Texture | None) -> None:
        self.set_icon("new_intersection", tex)

    def _button_rects(self) -> list[tuple[float, float, float, float, str]]:
        pad = (self.width - self._button_size) / 2
        bx = self.left + pad
        y = self.bottom + self.height - self._button_size - pad
        rects: list[tuple[float, float, float, float, str]] = []
        for block in self._group_blocks():
            for item in block:
                rects.append((bx, y, self._button_size, self._button_size, item.action))
                y -= self._button_size + self._gap
        return rects

    def contains(self, x: float, y: float) -> bool:
        return (
            self.left <= x <= self.left + self.width
            and self.bottom <= y <= self.bottom + self.height
        )

    def on_press(self, x: float, y: float) -> str | None:
        for l, b, w, h, action in self._button_rects():
            if l <= x <= l + w and b <= y <= b + h:
                return action
        return None

    def button_rect(self, action: str) -> tuple[float, float, float, float] | None:
        for l, b, w, h, name in self._button_rects():
            if name == action:
                return (l, b, w, h)
        return None

    def draw(self) -> None:
        rect_filled(self.left, self.bottom, self.width, self.height, TOOLBAR_BG)
        rect_outline(self.left, self.bottom, self.width, self.height, TOOLBAR_BORDER, 1)
        for l, b, w, h, action in self._button_rects():
            fill = (95, 95, 110) if action == self.active_action else (70, 70, 80)
            border = (160, 160, 180) if action == self.active_action else (100, 100, 110)
            rect_filled(l, b, w, h, fill)
            rect_outline(l, b, w, h, border, 1)
            cx = l + w / 2
            cy = b + h / 2
            if action == "select":
                self._draw_pointer(cx, cy)
                continue
            if action == "camera":
                self._draw_camera_icon(cx, cy)
                continue
            icon = self._icons.get(action)
            if icon is not None:
                spr, lst = icon
                spr.center_x = cx
                spr.center_y = cy
                lst.draw(pixelated=True)
            else:
                fb = self._fallbacks[action]
                fb.x, fb.y = cx, cy
                fb.draw()

    def _draw_pointer(self, cx: float, cy: float) -> None:
        if self.select_mode == SELECT_MODE_CARS:
            fill = SELECT_POINTER_CARS_FILL
            stroke = SELECT_POINTER_CARS_STROKE
        else:
            fill = SELECT_POINTER_MAP_FILL
            stroke = SELECT_POINTER_MAP_STROKE
        pts = _pointer_polygon(cx, cy)
        arcade.draw_polygon_filled(pts, fill)
        arcade.draw_polygon_outline(pts, stroke, 2)

    def _draw_camera_icon(self, cx: float, cy: float) -> None:
        mode = self.camera_mode
        if mode == CAMERA_MODE_ZOOM:
            draw_zoom_icon(cx, cy)
        elif mode == CAMERA_MODE_ORBIT:
            draw_orbit_icon(cx, cy, ccw=self.orbit_ccw)
        else:
            draw_pan_arrows(cx, cy)


def _pointer_polygon(cx: float, cy: float) -> list[tuple[float, float]]:
    """Classic mouse arrow, tip toward the upper-left, centred on (cx, cy)."""
    # Tip, left edge, barb, then a single right-shoulder back to the tip.
    local = (
        (0.0, 10.0),
        (0.4, -6.0),
        (3.4, -2.4),
        (6.4, -8.8),
        (8.8, -7.0),
        (5.2, -1.2),
        (8.0, 3.2),
    )
    xs = [p[0] for p in local]
    ys = [p[1] for p in local]
    ox = (min(xs) + max(xs)) / 2.0
    oy = (min(ys) + max(ys)) / 2.0
    return [(cx + x - ox, cy + y - oy) for x, y in local]
