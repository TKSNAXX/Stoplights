"""
Lightweight reusable UI controls (Slider, Switch, Dialog).
Screen space: x right, y up. Rect is (left, bottom, width, height).
"""
from __future__ import annotations

from typing import Callable

import arcade
from draw_compat import rect_filled, rect_outline


class Slider:
    """Horizontal step slider. Rect (left, bottom, width, height). value is 0..num_steps-1."""

    def __init__(
        self,
        left: float,
        bottom: float,
        width: float,
        height: float,
        num_steps: int,
        initial_step: int = 0,
        bar_color: tuple[int, int, int] = (100, 100, 100),
        thumb_color: tuple[int, int, int] = (180, 180, 180),
    ):
        self.rect = (left, bottom, width, height)
        self.num_steps = max(1, num_steps)
        self.value = max(0, min(initial_step, self.num_steps - 1))
        self.bar_color = bar_color
        self.thumb_color = thumb_color
        self._dragging = False

    def contains(self, x: float, y: float) -> bool:
        left, bottom, width, height = self.rect
        return left <= x <= left + width and bottom <= y <= bottom + height

    def step_from_x(self, x: float) -> int:
        left, _, width, _ = self.rect
        t = (x - left) / width if width > 0 else 0
        t = max(0.0, min(1.0, t))
        return int(t * (self.num_steps - 1) + 0.5) if self.num_steps > 1 else 0

    def set_step(self, step: int) -> None:
        self.value = max(0, min(self.num_steps - 1, step))

    def draw(self) -> None:
        left, bottom, width, height = self.rect
        bar_height = min(height * 0.35, 8)
        bar_center_y = bottom + height / 2
        bar_bottom = bar_center_y - bar_height / 2
        rect_filled(left, bar_bottom, width, bar_height, self.bar_color)
        thumb_w = 16
        thumb_h = height - 4
        t = self.value / (self.num_steps - 1) if self.num_steps > 1 else 0
        thumb_left = left + thumb_w / 2 + t * (width - thumb_w) - thumb_w / 2
        if self.num_steps <= 1:
            thumb_left = left + (width - thumb_w) / 2
        rect_filled(thumb_left, bottom + 2, thumb_w, thumb_h, self.thumb_color)

    def on_press(self, x: float, y: float) -> bool:
        if not self.contains(x, y):
            return False
        self._dragging = True
        self.set_step(self.step_from_x(x))
        return True

    def on_drag(self, x: float) -> bool:
        if not self._dragging:
            return False
        self.set_step(self.step_from_x(x))
        return True

    def on_release(self) -> bool:
        if not self._dragging:
            return False
        self._dragging = False
        return True


TITLE_BAR_HEIGHT = 24
DIALOG_BG = (45, 45, 55)
DIALOG_TITLE_BG = (60, 60, 75)
DIALOG_BORDER = (100, 100, 120)
X_BUTTON_SIZE = 18


class Dialog:
    """Base dialog: draggable, title bar, X close. Position (x, y) is top-left in screen coords."""

    def __init__(self, x: float, y: float, width: float, height: float, title: str):
        self.x = x
        self.y = y  # top edge
        self.width = width
        self.height = height
        self.title = title
        self.visible = True
        self.widgets: list = []
        self._dragging = False
        self._drag_start: tuple[float, float] | None = None
        self._on_close: callable | None = None

    def set_on_close(self, cb: callable) -> None:
        self._on_close = cb

    def _bottom(self) -> float:
        return self.y - self.height

    def contains(self, x: float, y: float) -> bool:
        left = self.x
        bottom = self._bottom()
        return left <= x <= left + self.width and bottom <= y <= self.y

    def _x_button_rect(self) -> tuple[float, float, float, float]:
        """(left, bottom, width, height) for X button."""
        left = self.x + self.width - X_BUTTON_SIZE - 4
        bottom = self.y - TITLE_BAR_HEIGHT + (TITLE_BAR_HEIGHT - X_BUTTON_SIZE) / 2
        return (left, bottom, X_BUTTON_SIZE, X_BUTTON_SIZE)

    def _title_bar_contains(self, x: float, y: float) -> bool:
        left = self.x
        bottom = self.y - TITLE_BAR_HEIGHT
        return left <= x <= left + self.width and bottom <= y <= self.y

    def _x_button_contains(self, x: float, y: float) -> bool:
        l, b, w, h = self._x_button_rect()
        return l <= x <= l + w and b <= y <= b + h

    def _layout_widgets(self) -> None:
        """Override in subclasses to position widgets. Called before draw and when position changes."""
        pass

    def draw(self) -> None:
        if not self.visible:
            return
        self._layout_widgets()
        left = self.x
        bottom = self._bottom()
        rect_filled(left, bottom, self.width, self.height, DIALOG_BG)
        rect_outline(left, bottom, self.width, self.height, DIALOG_BORDER, 1)
        rect_filled(left, self.y - TITLE_BAR_HEIGHT, self.width, TITLE_BAR_HEIGHT, DIALOG_TITLE_BG)
        title_text = arcade.Text(
            self.title, left + 8, bottom + self.height - TITLE_BAR_HEIGHT / 2 - 4,
            color=(220, 220, 220), font_size=12, anchor_x="left", anchor_y="center",
        )
        title_text.draw()
        xl, xb, xw, xh = self._x_button_rect()
        rect_filled(xl, xb, xw, xh, (120, 80, 80))
        x_text = arcade.Text("X", xl + xw / 2, xb + xh / 2, color=(220, 220, 220), font_size=11, anchor_x="center", anchor_y="center")
        x_text.draw()
        for w in self.widgets:
            w.draw()

    def on_mouse_press(self, x: float, y: float) -> bool:
        if not self.contains(x, y) or not self.visible:
            return False
        self._layout_widgets()
        if self._x_button_contains(x, y):
            self.visible = False
            if self._on_close:
                self._on_close(self)
            return True
        if self._title_bar_contains(x, y):
            self._dragging = True
            self._drag_start = (self.x - x, self.y - y)
            return True
        for w in self.widgets:
            if hasattr(w, "on_press") and w.on_press(x, y):
                return True
        return True

    def on_mouse_drag(self, x: float, y: float, dx: float, dy: float) -> bool:
        if self._dragging and self._drag_start is not None:
            self.x = x + self._drag_start[0]
            self.y = y + self._drag_start[1]
            return True
        for w in self.widgets:
            if hasattr(w, "on_drag") and w.on_drag(x):
                return True
        return False

    def on_mouse_release(self, x: float, y: float) -> bool:
        if self._dragging:
            self._dragging = False
            self._drag_start = None
            return True
        for w in self.widgets:
            if hasattr(w, "on_release") and w.on_release():
                return True
        return False


class DialogManager:
    """Manages open dialogs: z-order, input routing, draw."""

    def __init__(self):
        self._dialogs: list[Dialog] = []

    def open(self, dialog: Dialog) -> None:
        if dialog in self._dialogs:
            self._dialogs.remove(dialog)
        self._dialogs.append(dialog)
        dialog.visible = True

    def close(self, dialog: Dialog) -> None:
        if dialog in self._dialogs:
            self._dialogs.remove(dialog)
        dialog.visible = False

    def close_top(self) -> bool:
        if not self._dialogs:
            return False
        top = self._dialogs.pop()
        top.visible = False
        return True

    def on_mouse_press(self, x: float, y: float) -> bool:
        for i in range(len(self._dialogs) - 1, -1, -1):
            d = self._dialogs[i]
            if d.contains(x, y) and d.visible:
                if i < len(self._dialogs) - 1:
                    self._dialogs.pop(i)
                    self._dialogs.append(d)
                return d.on_mouse_press(x, y)
        return False

    def on_mouse_drag(self, x: float, y: float, dx: float, dy: float) -> bool:
        if not self._dialogs:
            return False
        top = self._dialogs[-1]
        return top.on_mouse_drag(x, y, dx, dy)

    def on_mouse_release(self, x: float, y: float) -> bool:
        if not self._dialogs:
            return False
        top = self._dialogs[-1]
        return top.on_mouse_release(x, y)

    def draw_all(self) -> None:
        for d in self._dialogs:
            if d.visible:
                d.draw()


# Spawn interval steps: 0.5, 1, 2, 4, 8 seconds
PLACE_SPAWN_VALUES = (0.5, 1.0, 2.0, 4.0, 8.0)
# Attract weight steps: 0.2, 0.5, 1.0, 2.0, 5.0
PLACE_ATTRACT_VALUES = (0.2, 0.5, 1.0, 2.0, 5.0)
# Lane speed limit steps: 0.5, 0.75, 1.0, 1.25, 1.5
LANE_SPEED_VALUES = (0.5, 0.75, 1.0, 1.25, 1.5)
# Lane type: normal, passing (more types in future)
LANE_TYPE_VALUES = ("normal", "passing")
# Intersection type: x (cross), corner
INTERSECTION_TYPE_VALUES = ("x", "corner")
# Intersection size: 2, 4, 6, 8, 10, 12 cells
INTERSECTION_SIZE_VALUES = (2, 4, 6, 8, 10, 12)


class CommitButton:
    """Simple clickable Commit button. Rect (left, bottom, width, height)."""

    def __init__(self, left: float, bottom: float, width: float, height: float, on_click: Callable[[], None] | None = None):
        self.rect = (left, bottom, width, height)
        self._on_click = on_click
        self._text = arcade.Text("Commit", 0, 0, color=(220, 220, 220), font_size=11, anchor_x="center", anchor_y="center")

    def contains(self, x: float, y: float) -> bool:
        left, bottom, width, height = self.rect
        return left <= x <= left + width and bottom <= y <= bottom + height

    def draw(self) -> None:
        left, bottom, width, height = self.rect
        rect_filled(left, bottom, width, height, (80, 120, 80))
        rect_outline(left, bottom, width, height, (100, 140, 100), 1)
        self._text.x = left + width / 2
        self._text.y = bottom + height / 2
        self._text.draw()

    def on_press(self, x: float, y: float) -> bool:
        if not self.contains(x, y):
            return False
        if self._on_click:
            self._on_click()
        return True

    def on_drag(self, x: float) -> bool:
        return False

    def on_release(self) -> bool:
        return False


class IntersectionVarsDialog(Dialog):
    """Dialog for editing intersection type (x vs corner) and size. Commit applies size."""

    def __init__(
        self,
        x: float,
        y: float,
        intersection_key: str,
        intersection_config,
        on_change: Callable[[], None] | None = None,
        on_commit: Callable[[], None] | None = None,
    ):
        super().__init__(x, y, 220, 150, f"Intersection: {intersection_key}")
        self.intersection_key = intersection_key
        self._config = intersection_config
        self._on_change = on_change
        self._on_commit = on_commit

        type_step = INTERSECTION_TYPE_VALUES.index(
            getattr(intersection_config, "intersection_type", "x")
        )
        size_val = getattr(intersection_config, "size_cells", 4)
        size_step = min(
            range(len(INTERSECTION_SIZE_VALUES)),
            key=lambda i: abs(INTERSECTION_SIZE_VALUES[i] - size_val),
        )

        self._type_slider = Slider(
            0, 0, 160, 20,
            len(INTERSECTION_TYPE_VALUES), type_step,
            (100, 100, 100), (180, 180, 180),
        )
        self._size_slider = Slider(
            0, 0, 160, 20,
            len(INTERSECTION_SIZE_VALUES), size_step,
            (100, 100, 100), (180, 180, 180),
        )
        self._commit_btn = CommitButton(0, 0, 70, 22, on_click=self._do_commit)

        self.widgets = [self._type_slider, self._size_slider, self._commit_btn]
        self._type_label = arcade.Text("", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._size_label = arcade.Text("", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")

    def _do_commit(self) -> None:
        """Apply size from slider to config and call on_commit."""
        self._config.size_cells = INTERSECTION_SIZE_VALUES[self._size_slider.value]
        if self._on_commit:
            self._on_commit()

    def _layout_widgets(self) -> None:
        left = self.x + 12
        content_top = self.y - 32
        self._type_slider.rect = (left, content_top - 24, 160, 20)
        self._size_slider.rect = (left, content_top - 52, 160, 20)
        self._commit_btn.rect = (left, content_top - 82, 70, 22)
        self._type_label.x = left
        self._type_label.y = content_top - 12
        self._size_label.x = left
        self._size_label.y = content_top - 40

    def draw(self) -> None:
        self._layout_widgets()
        self._type_label.value = f"Type: {INTERSECTION_TYPE_VALUES[self._type_slider.value]}"
        self._size_label.value = f"Size: {INTERSECTION_SIZE_VALUES[self._size_slider.value]}"
        super().draw()
        self._type_label.draw()
        self._size_label.draw()

    def on_mouse_press(self, x: float, y: float) -> bool:
        self._layout_widgets()
        result = super().on_mouse_press(x, y)
        self._sync_from_sliders()
        return result

    def on_mouse_drag(self, x: float, y: float, dx: float, dy: float) -> bool:
        result = super().on_mouse_drag(x, y, dx, dy)
        self._sync_from_sliders()
        return result

    def on_mouse_release(self, x: float, y: float) -> bool:
        result = super().on_mouse_release(x, y)
        self._sync_from_sliders()
        return result

    def _sync_from_sliders(self) -> None:
        self._config.intersection_type = INTERSECTION_TYPE_VALUES[self._type_slider.value]
        # size_cells only applied on Commit; slider value shown for preview
        if self._on_change:
            self._on_change()


class PlaceVarsDialog(Dialog):
    """Dialog for editing place spawn rate and attract weight."""

    def __init__(self, x: float, y: float, place: str, place_config, on_change: Callable[[], None] | None = None):
        super().__init__(x, y, 220, 140, f"Place: {place}")
        self.place = place
        self._config = place_config
        self._on_change = on_change
        # Sliders will be positioned by _layout_widgets
        spawn_step = self._step_for_spawn(place_config.spawn_interval)
        attract_step = self._step_for_attract(place_config.attract_weight)
        self._spawn_slider = Slider(0, 0, 160, 20, 5, spawn_step, (100, 100, 100), (180, 180, 180))
        self._attract_slider = Slider(0, 0, 160, 20, 5, attract_step, (100, 100, 100), (180, 180, 180))
        self.widgets = [self._spawn_slider, self._attract_slider]
        self._spawn_label = arcade.Text("", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._attract_label = arcade.Text("", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")

    def _step_for_spawn(self, val: float) -> int:
        best = 0
        for i, v in enumerate(PLACE_SPAWN_VALUES):
            if abs(v - val) < abs(PLACE_SPAWN_VALUES[best] - val):
                best = i
        return best

    def _step_for_attract(self, val: float) -> int:
        best = 0
        for i, v in enumerate(PLACE_ATTRACT_VALUES):
            if abs(v - val) < abs(PLACE_ATTRACT_VALUES[best] - val):
                best = i
        return best

    def _layout_widgets(self) -> None:
        left = self.x + 12
        content_top = self.y - 32
        self._spawn_slider.rect = (left, content_top - 24, 160, 20)
        self._attract_slider.rect = (left, content_top - 52, 160, 20)
        self._spawn_label.x = left
        self._spawn_label.y = content_top - 12
        self._attract_label.x = left
        self._attract_label.y = content_top - 40

    def draw(self) -> None:
        self._layout_widgets()
        self._spawn_label.value = f"Spawn: {PLACE_SPAWN_VALUES[self._spawn_slider.value]:.1f}s"
        self._attract_label.value = f"Attract: {PLACE_ATTRACT_VALUES[self._attract_slider.value]:.1f}x"
        super().draw()
        self._spawn_label.draw()
        self._attract_label.draw()

    def on_mouse_press(self, x: float, y: float) -> bool:
        self._layout_widgets()
        result = super().on_mouse_press(x, y)
        self._sync_from_sliders()
        return result

    def on_mouse_drag(self, x: float, y: float, dx: float, dy: float) -> bool:
        result = super().on_mouse_drag(x, y, dx, dy)
        self._sync_from_sliders()
        return result

    def on_mouse_release(self, x: float, y: float) -> bool:
        result = super().on_mouse_release(x, y)
        self._sync_from_sliders()
        return result

    def _sync_from_sliders(self) -> None:
        self._config.spawn_interval = PLACE_SPAWN_VALUES[self._spawn_slider.value]
        self._config.attract_weight = PLACE_ATTRACT_VALUES[self._attract_slider.value]
        if self._on_change:
            self._on_change()


class LaneVarsDialog(Dialog):
    """Dialog for editing lane speed limit and type (not yet wired to car movement)."""

    def __init__(self, x: float, y: float, lane_index: int, lane_config, on_change: Callable[[], None] | None = None):
        super().__init__(x, y, 220, 130, f"Lane {lane_index}")
        self.lane_index = lane_index
        self._config = lane_config
        self._on_change = on_change
        speed_step = self._step_for_speed(lane_config.speed_limit)
        type_step = self._step_for_type(lane_config.lane_type)
        self._speed_slider = Slider(0, 0, 160, 20, len(LANE_SPEED_VALUES), speed_step, (100, 100, 100), (180, 180, 180))
        self._type_slider = Slider(0, 0, 160, 20, len(LANE_TYPE_VALUES), type_step, (100, 100, 100), (180, 180, 180))
        self.widgets = [self._speed_slider, self._type_slider]
        self._speed_label = arcade.Text("", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._type_label = arcade.Text("", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")

    def _step_for_speed(self, val: float) -> int:
        best = 0
        for i, v in enumerate(LANE_SPEED_VALUES):
            if abs(v - val) < abs(LANE_SPEED_VALUES[best] - val):
                best = i
        return best

    def _step_for_type(self, val: str) -> int:
        try:
            return LANE_TYPE_VALUES.index(val)
        except ValueError:
            return 0

    def _layout_widgets(self) -> None:
        left = self.x + 12
        content_top = self.y - 32
        self._speed_slider.rect = (left, content_top - 24, 160, 20)
        self._type_slider.rect = (left, content_top - 52, 160, 20)
        self._speed_label.x = left
        self._speed_label.y = content_top - 12
        self._type_label.x = left
        self._type_label.y = content_top - 40

    def draw(self) -> None:
        self._layout_widgets()
        self._speed_label.value = f"Speed limit: {LANE_SPEED_VALUES[self._speed_slider.value]:.2f}x"
        self._type_label.value = f"Type: {LANE_TYPE_VALUES[self._type_slider.value]}"
        super().draw()
        self._speed_label.draw()
        self._type_label.draw()

    def on_mouse_press(self, x: float, y: float) -> bool:
        self._layout_widgets()
        result = super().on_mouse_press(x, y)
        self._sync_from_sliders()
        return result

    def on_mouse_drag(self, x: float, y: float, dx: float, dy: float) -> bool:
        result = super().on_mouse_drag(x, y, dx, dy)
        self._sync_from_sliders()
        return result

    def on_mouse_release(self, x: float, y: float) -> bool:
        result = super().on_mouse_release(x, y)
        self._sync_from_sliders()
        return result

    def _sync_from_sliders(self) -> None:
        self._config.speed_limit = LANE_SPEED_VALUES[self._speed_slider.value]
        self._config.lane_type = LANE_TYPE_VALUES[self._type_slider.value]
        if self._on_change:
            self._on_change()


class CarDeetsDialog(Dialog):
    """Read-only dialog showing car speed, origin, destination."""

    def __init__(self, x: float, y: float, car, game) -> None:
        super().__init__(x, y, 200, 90, "Car details")
        self._car = car
        self._game = game
        self._origin_label = arcade.Text("", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._dest_label = arcade.Text("", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._speed_label = arcade.Text("", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")

    def _layout_widgets(self) -> None:
        pass  # No interactive widgets

    def draw(self) -> None:
        left = self.x + 12
        content_top = self.y - 32
        self._origin_label.x = left
        self._origin_label.y = content_top - 12
        self._dest_label.x = left
        self._dest_label.y = content_top - 28
        self._speed_label.x = left
        self._speed_label.y = content_top - 44

        if self._car in self._game.cars:
            self._origin_label.value = f"Origin: {self._car.origin}"
            self._dest_label.value = f"Destination: {self._car.destination}"
            self._speed_label.value = f"Speed: {self._car.base_speed_multiplier:.2f}x"
        else:
            self._origin_label.value = "Car departed"
            self._dest_label.value = ""
            self._speed_label.value = ""

        super().draw()
        self._origin_label.draw()
        self._dest_label.draw()
        self._speed_label.draw()


class Switch:
    """Boolean toggle. Rect (left, bottom, width, height). value is True/False."""

    def __init__(
        self,
        left: float,
        bottom: float,
        width: float,
        height: float,
        initial_value: bool = True,
        bar_color: tuple[int, int, int] = (100, 100, 100),
        thumb_color: tuple[int, int, int] = (180, 180, 180),
    ):
        self.rect = (left, bottom, width, height)
        self.value = initial_value
        self.bar_color = bar_color
        self.thumb_color = thumb_color
        label_color = (220, 220, 220)
        self._text_on = arcade.Text(
            "On", 0, 0, color=label_color, font_size=10,
            anchor_x="center", anchor_y="center",
        )
        self._text_off = arcade.Text(
            "Off", 0, 0, color=label_color, font_size=10,
            anchor_x="center", anchor_y="center",
        )

    def contains(self, x: float, y: float) -> bool:
        left, bottom, width, height = self.rect
        return left <= x <= left + width and bottom <= y <= bottom + height

    def toggle(self) -> bool:
        self.value = not self.value
        return self.value

    def draw(self) -> None:
        left, bottom, width, height = self.rect
        color = self.thumb_color if self.value else self.bar_color
        rect_filled(left, bottom, width, height, color)
        cx = left + width / 2
        cy = bottom + height / 2
        if self.value:
            self._text_on.x, self._text_on.y = cx, cy
            self._text_on.draw()
        else:
            self._text_off.x, self._text_off.y = cx, cy
            self._text_off.draw()
