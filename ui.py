"""
Lightweight reusable UI controls (Slider, Switch, Dialog).
Screen space: x right, y up. Rect is (left, bottom, width, height).
"""
from __future__ import annotations

from typing import Callable

import arcade
from draw_compat import rect_filled, rect_outline


NUMBER_BOX_HEIGHT = 22
NUMBER_BOX_ARROW_SIZE = 14


class NumberBox:
    """
    Integer input: [ text box ] [▲] [▼]. Typing or arrow buttons.
    Rect (left, bottom, width, height). step for arrow increment.
    """

    def __init__(
        self,
        left: float,
        bottom: float,
        width: float,
        height: float,
        value: int,
        min_val: int,
        max_val: int,
        step: int = 1,
        on_change: Callable[[int], None] | None = None,
        on_unfocus: Callable[[], None] | None = None,
    ):
        self.rect = (left, bottom, width, height)
        self.value = max(min_val, min(max_val, value))
        self.min_val = min_val
        self.max_val = max_val
        self.step = step
        self._on_change = on_change
        self._on_unfocus = on_unfocus
        self._focused = False
        self._text_buffer = str(self.value)
        self._text = arcade.Text(
            "", 0, 0, color=(220, 220, 220), font_size=11, anchor_x="left", anchor_y="center"
        )

    def contains(self, x: float, y: float) -> bool:
        left, bottom, width, height = self.rect
        return left <= x <= left + width and bottom <= y <= bottom + height

    def _box_rect(self) -> tuple[float, float, float, float]:
        """Text box portion: (left, bottom, width, height)."""
        left, bottom, width, height = self.rect
        arrow_w = NUMBER_BOX_ARROW_SIZE * 2
        return (left, bottom, width - arrow_w, height)

    def _up_arrow_rect(self) -> tuple[float, float, float, float]:
        left, bottom, width, height = self.rect
        box_w = width - NUMBER_BOX_ARROW_SIZE * 2
        return (left + box_w, bottom + height / 2, NUMBER_BOX_ARROW_SIZE, height / 2)

    def _down_arrow_rect(self) -> tuple[float, float, float, float]:
        left, bottom, width, height = self.rect
        box_w = width - NUMBER_BOX_ARROW_SIZE * 2
        return (left + box_w + NUMBER_BOX_ARROW_SIZE, bottom + height / 2, NUMBER_BOX_ARROW_SIZE, height / 2)

    def set_focus(self, focused: bool) -> None:
        if self._focused != focused:
            self._focused = focused
            if not focused:
                self._commit_text()
                if self._on_unfocus:
                    self._on_unfocus()

    def _commit_text(self) -> None:
        try:
            v = int(self._text_buffer)
            v = max(self.min_val, min(self.max_val, v))
            if v != self.value:
                self.value = v
                self._text_buffer = str(self.value)
                if self._on_change:
                    self._on_change(self.value)
        except ValueError:
            self._text_buffer = str(self.value)

    def _apply_step(self, delta: int) -> None:
        v = self.value + delta * self.step
        v = max(self.min_val, min(self.max_val, v))
        if v != self.value:
            self.value = v
            self._text_buffer = str(self.value)
            if self._on_change:
                self._on_change(self.value)

    def on_press(self, x: float, y: float) -> bool:
        if not self.contains(x, y):
            return False
        self.set_focus(True)
        l, b, w, h = self._up_arrow_rect()
        if l <= x <= l + w and b <= y <= b + h:
            self._apply_step(1)
            return True
        l, b, w, h = self._down_arrow_rect()
        if l <= x <= l + w and b <= y <= b + h:
            self._apply_step(-1)
            return True
        return True

    def on_key_press(self, key: int) -> bool:
        if not self._focused:
            return False
        # arcade.key constants
        if key == arcade.key.UP:
            self._apply_step(1)
            return True
        if key == arcade.key.DOWN:
            self._apply_step(-1)
            return True
        if key == arcade.key.RETURN or key == arcade.key.TAB:
            self.set_focus(False)
            return True
        if key == arcade.key.BACKSPACE:
            if self._text_buffer:
                self._text_buffer = self._text_buffer[:-1]
            return True
        # Digit or minus
        if 48 <= key <= 57:  # 0-9
            self._text_buffer += chr(key)
            return True
        if key == 45 and not self._text_buffer:  # minus for negative
            self._text_buffer = "-"
            return True
        return False

    def draw(self) -> None:
        left, bottom, width, height = self.rect
        box_w = width - NUMBER_BOX_ARROW_SIZE * 2
        rect_filled(left, bottom, box_w, height, (50, 50, 60))
        rect_outline(left, bottom, box_w, height, DIALOG_BORDER if self._focused else (80, 80, 90), 1)
        self._text.value = self._text_buffer if self._focused else str(self.value)
        self._text.x = left + 6
        self._text.y = bottom + height / 2
        self._text.draw()
        # Up arrow
        ul, ub, uw, uh = self._up_arrow_rect()
        rect_filled(ul, ub, uw, uh, (100, 100, 110))
        rect_outline(ul, ub, uw, uh, DIALOG_BORDER, 1)
        arrow_up = arcade.Text("▲", ul + uw / 2, ub + uh / 2, color=(180, 180, 180), font_size=10, anchor_x="center", anchor_y="center")
        arrow_up.draw()
        # Down arrow
        dl, db, dw, dh = self._down_arrow_rect()
        rect_filled(dl, db, dw, dh, (100, 100, 110))
        rect_outline(dl, db, dw, dh, DIALOG_BORDER, 1)
        arrow_dn = arcade.Text("▼", dl + dw / 2, db + dh / 2, color=(180, 180, 180), font_size=10, anchor_x="center", anchor_y="center")
        arrow_dn.draw()


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
        self._dialog_manager: DialogManager | None = None

    def set_dialog_manager(self, manager: "DialogManager") -> None:
        self._dialog_manager = manager

    def set_on_close(self, cb: callable) -> None:
        self._on_close = cb

    def clamp_to_window(self, window_w: float, window_h: float, margin: float = 8) -> None:
        """Adjust x, y so the entire dialog stays within window bounds with optional margin."""
        self.x = max(margin, min(window_w - self.width - margin, self.x))
        self.y = max(self.height + margin, min(window_h - margin, self.y))

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
            if self._dialog_manager:
                self._dialog_manager.set_focused_widget(None)
            return True
        for w in self.widgets:
            if hasattr(w, "on_press") and w.on_press(x, y):
                if self._dialog_manager and hasattr(w, "set_focus"):
                    self._dialog_manager.set_focused_widget(w)
                return True
        if self._dialog_manager:
            self._dialog_manager.set_focused_widget(None)
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

    def __init__(self, get_window_size: Callable[[], tuple[float, float]] | None = None):
        self._dialogs: list[Dialog] = []
        self._focused_widget: NumberBox | None = None
        self._get_window_size = get_window_size

    def set_focused_widget(self, widget: NumberBox | None) -> None:
        if self._focused_widget is not None and hasattr(self._focused_widget, "set_focus"):
            self._focused_widget.set_focus(False)
        self._focused_widget = widget
        if widget is not None and hasattr(widget, "set_focus"):
            widget.set_focus(True)

    def get_focused_widget(self) -> NumberBox | None:
        return self._focused_widget

    def open(self, dialog: Dialog) -> None:
        if dialog in self._dialogs:
            self._dialogs.remove(dialog)
        self._dialogs.append(dialog)
        dialog.set_dialog_manager(self)
        if self._get_window_size is not None:
            w, h = self._get_window_size()
            dialog.clamp_to_window(w, h)
        dialog.visible = True

    def close(self, dialog: Dialog) -> None:
        if dialog in self._dialogs:
            self._dialogs.remove(dialog)
        dialog.visible = False
        if self._focused_widget is not None:
            for w in dialog.widgets:
                if w is self._focused_widget:
                    self.set_focused_widget(None)
                    break

    def close_top(self) -> bool:
        if not self._dialogs:
            return False
        top = self._dialogs.pop()
        top.visible = False
        if self._focused_widget is not None:
            for w in top.widgets:
                if w is self._focused_widget:
                    self.set_focused_widget(None)
                    break
        return True

    def contains_point(self, x: float, y: float) -> bool:
        """True if (x, y) is over any visible dialog."""
        for d in self._dialogs:
            if d.visible and d.contains(x, y):
                return True
        return False

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


class RemoveButton:
    """Destructive Remove button. Rect (left, bottom, width, height)."""

    def __init__(self, left: float, bottom: float, width: float, height: float, on_click: Callable[[], None] | None = None):
        self.rect = (left, bottom, width, height)
        self._on_click = on_click
        self._text = arcade.Text("Remove", 0, 0, color=(220, 220, 220), font_size=11, anchor_x="center", anchor_y="center")

    def contains(self, x: float, y: float) -> bool:
        left, bottom, width, height = self.rect
        return left <= x <= left + width and bottom <= y <= bottom + height

    def draw(self) -> None:
        left, bottom, width, height = self.rect
        rect_filled(left, bottom, width, height, (120, 80, 80))
        rect_outline(left, bottom, width, height, (140, 100, 100), 1)
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
    """Dialog for editing intersection type, center, and size. Commit applies all. Remove for extra intersections only."""

    def __init__(
        self,
        x: float,
        y: float,
        intersection_key: str,
        intersection_config,
        game=None,
        on_change: Callable[[], None] | None = None,
        on_commit: Callable[[], None] | None = None,
        on_remove: Callable[[], None] | None = None,
    ):
        super().__init__(x, y, 220, 200, f"Intersection: {intersection_key}")
        self.intersection_key = intersection_key
        self._config = intersection_config
        self._game = game
        self._on_change = on_change
        self._on_commit = on_commit
        self._on_remove = on_remove
        self._can_remove = intersection_key not in ("main", "bypass") and game is not None

        type_step = INTERSECTION_TYPE_VALUES.index(
            getattr(intersection_config, "intersection_type", "x")
        )
        cx = getattr(intersection_config, "center_x", 18)
        cy = getattr(intersection_config, "center_y", 24)
        size_val = getattr(intersection_config, "size_cells", 4)

        self._type_slider = Slider(
            0, 0, 160, 20,
            len(INTERSECTION_TYPE_VALUES), type_step,
            (100, 100, 100), (180, 180, 180),
        )
        self._cx_box = NumberBox(0, 0, 100, NUMBER_BOX_HEIGHT, cx, -100, 200, 1)
        self._cy_box = NumberBox(0, 0, 100, NUMBER_BOX_HEIGHT, cy, -100, 200, 1)
        self._size_box = NumberBox(0, 0, 100, NUMBER_BOX_HEIGHT, size_val, 2, 12, 2)
        self._commit_btn = CommitButton(0, 0, 70, 22, on_click=self._do_commit)
        self._remove_btn = RemoveButton(0, 0, 70, 22, on_click=self._do_remove)

        self.widgets = [self._type_slider, self._cx_box, self._cy_box, self._size_box, self._commit_btn]
        if self._can_remove:
            self.widgets.append(self._remove_btn)
        self._type_label = arcade.Text("", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._cx_label = arcade.Text("", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._cy_label = arcade.Text("", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._size_label = arcade.Text("", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")

    def _do_commit(self) -> None:
        """Apply type, center, size from widgets to config and call on_commit."""
        self._config.intersection_type = INTERSECTION_TYPE_VALUES[self._type_slider.value]
        self._config.center_x = self._cx_box.value
        self._config.center_y = self._cy_box.value
        self._config.size_cells = max(2, min(12, self._size_box.value))
        if self._config.size_cells % 2 != 0:
            self._config.size_cells = (self._config.size_cells // 2) * 2
        if self._on_commit:
            self._on_commit()

    def _do_remove(self) -> None:
        """Remove this intersection from game and call on_remove."""
        if self._game is not None and self.intersection_key in self._game.intersection_configs:
            del self._game.intersection_configs[self.intersection_key]
            self._game.rebuild_world_from_config()
        if self._on_remove:
            self._on_remove()

    def _layout_widgets(self) -> None:
        left = self.x + 12
        content_top = self.y - 32
        box_w = 100
        self._type_slider.rect = (left, content_top - 24, 160, 20)
        self._cx_box.rect = (left + 70, content_top - 48, box_w, NUMBER_BOX_HEIGHT)
        self._cy_box.rect = (left + 70, content_top - 74, box_w, NUMBER_BOX_HEIGHT)
        self._size_box.rect = (left + 70, content_top - 100, box_w, NUMBER_BOX_HEIGHT)
        self._commit_btn.rect = (left, content_top - 132, 70, 22)
        if self._can_remove:
            self._remove_btn.rect = (left + 76, content_top - 132, 70, 22)
        self._type_label.x = left
        self._type_label.y = content_top - 12
        self._cx_label.x = left
        self._cx_label.y = content_top - 36
        self._cy_label.x = left
        self._cy_label.y = content_top - 62
        self._size_label.x = left
        self._size_label.y = content_top - 88

    def draw(self) -> None:
        self._layout_widgets()
        self._type_label.value = f"Type: {INTERSECTION_TYPE_VALUES[self._type_slider.value]}"
        self._cx_label.value = "Center X:"
        self._cy_label.value = "Center Y:"
        self._size_label.value = "Size:"
        super().draw()
        self._type_label.draw()
        self._cx_label.draw()
        self._cy_label.draw()
        self._size_label.draw()

    def on_mouse_press(self, x: float, y: float) -> bool:
        self._layout_widgets()
        return super().on_mouse_press(x, y)

    def on_mouse_drag(self, x: float, y: float, dx: float, dy: float) -> bool:
        return super().on_mouse_drag(x, y, dx, dy)

    def on_mouse_release(self, x: float, y: float) -> bool:
        return super().on_mouse_release(x, y)


class NewIntersectionDialog(Dialog):
    """Dialog for creating a new intersection. Commit adds to game and closes."""

    def __init__(
        self,
        x: float,
        y: float,
        game,
        on_commit: Callable[[], None] | None = None,
    ):
        key = _next_intersection_key(game.intersection_configs)
        super().__init__(x, y, 220, 200, f"New Intersection: {key}")
        self._game = game
        self._key = key
        self._on_commit = on_commit

        self._type_slider = Slider(
            0, 0, 160, 20,
            len(INTERSECTION_TYPE_VALUES), 0,
            (100, 100, 100), (180, 180, 180),
        )
        self._cx_box = NumberBox(0, 0, 100, NUMBER_BOX_HEIGHT, 36, -100, 200, 1)
        self._cy_box = NumberBox(0, 0, 100, NUMBER_BOX_HEIGHT, 48, -100, 200, 1)
        self._size_box = NumberBox(0, 0, 100, NUMBER_BOX_HEIGHT, 4, 2, 12, 2)
        self._commit_btn = CommitButton(0, 0, 70, 22, on_click=self._do_commit)

        self.widgets = [self._type_slider, self._cx_box, self._cy_box, self._size_box, self._commit_btn]
        self._type_label = arcade.Text("", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._cx_label = arcade.Text("", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._cy_label = arcade.Text("", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._size_label = arcade.Text("", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")

    def _do_commit(self) -> None:
        from sim import places
        cfg = places.IntersectionConfig(
            intersection_type=INTERSECTION_TYPE_VALUES[self._type_slider.value],
            center_x=self._cx_box.value,
            center_y=self._cy_box.value,
            size_cells=max(2, min(12, self._size_box.value)),
        )
        if cfg.size_cells % 2 != 0:
            cfg.size_cells = (cfg.size_cells // 2) * 2
        self._game.intersection_configs[self._key] = cfg
        self._game.rebuild_world_from_config()
        if self._on_commit:
            self._on_commit()

    def _layout_widgets(self) -> None:
        left = self.x + 12
        content_top = self.y - 32
        box_w = 100
        self._type_slider.rect = (left, content_top - 24, 160, 20)
        self._cx_box.rect = (left + 70, content_top - 48, box_w, NUMBER_BOX_HEIGHT)
        self._cy_box.rect = (left + 70, content_top - 74, box_w, NUMBER_BOX_HEIGHT)
        self._size_box.rect = (left + 70, content_top - 100, box_w, NUMBER_BOX_HEIGHT)
        self._commit_btn.rect = (left, content_top - 132, 70, 22)
        self._type_label.x = left
        self._type_label.y = content_top - 12
        self._cx_label.x = left
        self._cx_label.y = content_top - 36
        self._cy_label.x = left
        self._cy_label.y = content_top - 62
        self._size_label.x = left
        self._size_label.y = content_top - 88

    def draw(self) -> None:
        self._layout_widgets()
        self._type_label.value = f"Type: {INTERSECTION_TYPE_VALUES[self._type_slider.value]}"
        self._cx_label.value = "Center X:"
        self._cy_label.value = "Center Y:"
        self._size_label.value = "Size:"
        super().draw()
        self._type_label.draw()
        self._cx_label.draw()
        self._cy_label.draw()
        self._size_label.draw()

    def on_mouse_press(self, x: float, y: float) -> bool:
        self._layout_widgets()
        return super().on_mouse_press(x, y)


class NewPlaceDialog(Dialog):
    """Dialog for creating a new place. Commit adds to game and closes."""

    def __init__(
        self,
        x: float,
        y: float,
        game,
        on_commit: Callable[[], None] | None = None,
    ):
        name = _next_place_name(game.place_geometry)
        super().__init__(x, y, 220, 200, f"New Place: {name}")
        self._game = game
        self._name = name
        self._on_commit = on_commit

        self._cx_box = NumberBox(0, 0, 100, NUMBER_BOX_HEIGHT, 20, -100, 200, 1)
        self._cy_box = NumberBox(0, 0, 100, NUMBER_BOX_HEIGHT, 20, -100, 200, 1)
        self._w_box = NumberBox(0, 0, 100, NUMBER_BOX_HEIGHT, 5, 1, 16, 1)
        self._l_box = NumberBox(0, 0, 100, NUMBER_BOX_HEIGHT, 5, 1, 16, 1)
        self._commit_btn = CommitButton(0, 0, 70, 22, on_click=self._do_commit)

        self.widgets = [self._cx_box, self._cy_box, self._w_box, self._l_box, self._commit_btn]
        self._cx_label = arcade.Text("Center X:", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._cy_label = arcade.Text("Center Y:", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._w_label = arcade.Text("Width:", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._l_label = arcade.Text("Length:", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")

    def _do_commit(self) -> None:
        from sim import places
        from sim.places import PLACE_SIZE_MIN, PLACE_SIZE_MAX
        w = max(PLACE_SIZE_MIN, min(PLACE_SIZE_MAX, self._w_box.value))
        l = max(PLACE_SIZE_MIN, min(PLACE_SIZE_MAX, self._l_box.value))
        g = places.PlaceGeometry(
            center_x=self._cx_box.value,
            center_y=self._cy_box.value,
            width=w,
            length=l,
        )
        self._game.place_geometry[self._name] = g
        self._game.place_configs[self._name] = places.PlaceConfig()
        self._game.rebuild_world_from_config()
        if self._on_commit:
            self._on_commit()

    def _layout_widgets(self) -> None:
        left = self.x + 12
        content_top = self.y - 32
        box_w = 100
        self._cx_box.rect = (left + 70, content_top - 24, box_w, NUMBER_BOX_HEIGHT)
        self._cy_box.rect = (left + 70, content_top - 50, box_w, NUMBER_BOX_HEIGHT)
        self._w_box.rect = (left + 70, content_top - 76, box_w, NUMBER_BOX_HEIGHT)
        self._l_box.rect = (left + 70, content_top - 102, box_w, NUMBER_BOX_HEIGHT)
        self._commit_btn.rect = (left, content_top - 134, 70, 22)
        self._cx_label.x = left
        self._cx_label.y = content_top - 12
        self._cy_label.x = left
        self._cy_label.y = content_top - 38
        self._w_label.x = left
        self._w_label.y = content_top - 64
        self._l_label.x = left
        self._l_label.y = content_top - 90

    def draw(self) -> None:
        self._layout_widgets()
        super().draw()
        self._cx_label.draw()
        self._cy_label.draw()
        self._w_label.draw()
        self._l_label.draw()

    def on_mouse_press(self, x: float, y: float) -> bool:
        self._layout_widgets()
        return super().on_mouse_press(x, y)


def _next_intersection_key(configs: dict) -> str:
    """Return intersection_N where N is the next available index (2, 3, ...)."""
    seen = set()
    for k in configs:
        if k.startswith("intersection_") and k != "intersection_":
            try:
                seen.add(int(k.split("_")[1]))
            except (ValueError, IndexError):
                pass
    n = 2
    while n in seen:
        n += 1
    return f"intersection_{n}"


def _next_place_name(place_geometry: dict) -> str:
    """Return Place N where N is the next available index (1, 2, ...)."""
    seen = set()
    for k in place_geometry:
        if k.startswith("Place ") and k != "Place ":
            try:
                seen.add(int(k.split()[1]))
            except (ValueError, IndexError):
                pass
    n = 1
    while n in seen:
        n += 1
    return f"Place {n}"


class PlaceVarsDialog(Dialog):
    """Dialog for editing place spawn, attract, and geometry. Geometry requires Commit. Remove for extra places only."""

    def __init__(
        self,
        x: float,
        y: float,
        place: str,
        place_config,
        place_geometry: dict,
        game=None,
        on_change: Callable[[], None] | None = None,
        on_commit: Callable[[], None] | None = None,
        on_remove: Callable[[], None] | None = None,
    ):
        super().__init__(x, y, 240, 260, f"Place: {place}")
        self.place = place
        self._config = place_config
        self._place_geometry = place_geometry
        self._game = game
        self._on_change = on_change
        self._on_commit = on_commit
        self._on_remove = on_remove
        from sim import places as sim_places
        self._can_remove = place not in sim_places.PLACES and game is not None

        spawn_step = self._step_for_spawn(place_config.spawn_interval)
        attract_step = self._step_for_attract(place_config.attract_weight)
        self._spawn_slider = Slider(0, 0, 160, 20, 5, spawn_step, (100, 100, 100), (180, 180, 180))
        self._attract_slider = Slider(0, 0, 160, 20, 5, attract_step, (100, 100, 100), (180, 180, 180))

        g = place_geometry.get(place)
        if g is not None:
            cx, cy, w, l = g.center_x, g.center_y, g.width, g.length
        else:
            cx, cy, w, l = 0, 0, 5, 5
        self._cx_box = NumberBox(0, 0, 100, NUMBER_BOX_HEIGHT, cx, -100, 200, 1)
        self._cy_box = NumberBox(0, 0, 100, NUMBER_BOX_HEIGHT, cy, -100, 200, 1)
        self._w_box = NumberBox(0, 0, 100, NUMBER_BOX_HEIGHT, w, 1, 16, 1)
        self._l_box = NumberBox(0, 0, 100, NUMBER_BOX_HEIGHT, l, 1, 16, 1)
        self._commit_btn = CommitButton(0, 0, 70, 22, on_click=self._do_commit)
        self._remove_btn = RemoveButton(0, 0, 70, 22, on_click=self._do_remove)

        self.widgets = [
            self._spawn_slider, self._attract_slider,
            self._cx_box, self._cy_box, self._w_box, self._l_box,
            self._commit_btn,
        ]
        if self._can_remove:
            self.widgets.append(self._remove_btn)
        self._spawn_label = arcade.Text("", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._attract_label = arcade.Text("", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._cx_label = arcade.Text("Center X:", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._cy_label = arcade.Text("Center Y:", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._w_label = arcade.Text("Width:", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._l_label = arcade.Text("Length:", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")

    def _do_commit(self) -> None:
        """Apply geometry from NumberBoxes and call on_commit."""
        from sim.places import PlaceGeometry, PLACE_SIZE_MIN, PLACE_SIZE_MAX
        w = max(PLACE_SIZE_MIN, min(PLACE_SIZE_MAX, self._w_box.value))
        l = max(PLACE_SIZE_MIN, min(PLACE_SIZE_MAX, self._l_box.value))
        self._place_geometry[self.place] = PlaceGeometry(
            center_x=self._cx_box.value,
            center_y=self._cy_box.value,
            width=w,
            length=l,
        )
        if self._on_commit:
            self._on_commit()

    def _do_remove(self) -> None:
        """Remove this place from game and call on_remove."""
        if self._game is not None:
            if self.place in self._game.place_geometry:
                del self._game.place_geometry[self.place]
            if self.place in self._game.place_configs:
                del self._game.place_configs[self.place]
            self._game.rebuild_world_from_config()
        if self._on_remove:
            self._on_remove()

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
        box_w = 100
        self._spawn_slider.rect = (left, content_top - 24, 160, 20)
        self._attract_slider.rect = (left, content_top - 52, 160, 20)
        self._cx_box.rect = (left + 70, content_top - 78, box_w, NUMBER_BOX_HEIGHT)
        self._cy_box.rect = (left + 70, content_top - 104, box_w, NUMBER_BOX_HEIGHT)
        self._w_box.rect = (left + 70, content_top - 130, box_w, NUMBER_BOX_HEIGHT)
        self._l_box.rect = (left + 70, content_top - 156, box_w, NUMBER_BOX_HEIGHT)
        self._commit_btn.rect = (left, content_top - 188, 70, 22)
        if self._can_remove:
            self._remove_btn.rect = (left + 76, content_top - 188, 70, 22)
        self._spawn_label.x = left
        self._spawn_label.y = content_top - 12
        self._attract_label.x = left
        self._attract_label.y = content_top - 40
        self._cx_label.x = left
        self._cx_label.y = content_top - 66
        self._cy_label.x = left
        self._cy_label.y = content_top - 92
        self._w_label.x = left
        self._w_label.y = content_top - 118
        self._l_label.x = left
        self._l_label.y = content_top - 144

    def draw(self) -> None:
        self._layout_widgets()
        self._spawn_label.value = f"Spawn: {PLACE_SPAWN_VALUES[self._spawn_slider.value]:.1f}s"
        self._attract_label.value = f"Attract: {PLACE_ATTRACT_VALUES[self._attract_slider.value]:.1f}x"
        super().draw()
        self._spawn_label.draw()
        self._attract_label.draw()
        self._cx_label.draw()
        self._cy_label.draw()
        self._w_label.draw()
        self._l_label.draw()

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

    def on_press(self, x: float, y: float) -> bool:
        if not self.contains(x, y):
            return False
        self.toggle()
        return True

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


class SettingsDialog(Dialog):
    """Dialog for global settings. Edge pan toggle."""

    def __init__(
        self,
        x: float,
        y: float,
        edge_pan_enabled: bool,
        on_edge_pan_change: Callable[[bool], None] | None = None,
    ):
        super().__init__(x, y, 220, 90, "Settings")
        self._on_edge_pan_change = on_edge_pan_change
        self._switch = Switch(0, 0, 50, 24, initial_value=edge_pan_enabled)
        self._label = arcade.Text("Edge pan", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self.widgets = [self._switch]

    def _layout_widgets(self) -> None:
        left = self.x + 12
        content_top = self.y - 32
        label_w = 60
        self._label.x = left
        self._label.y = content_top - 12
        self._switch.rect = (left + label_w, content_top - 24, 50, 24)

    def draw(self) -> None:
        self._layout_widgets()
        super().draw()
        self._label.draw()

    def on_mouse_press(self, x: float, y: float) -> bool:
        self._layout_widgets()
        result = super().on_mouse_press(x, y)
        if self._switch.contains(x, y) and self._on_edge_pan_change:
            self._on_edge_pan_change(self._switch.value)
        return result


TOOLBAR_LEFT = 8
TOOLBAR_WIDTH = 44
TOOLBAR_BUTTON_SIZE = 36
TOOLBAR_GAP = 4
TOOLBAR_BG = (50, 50, 60)
TOOLBAR_BORDER = (80, 80, 90)


class Toolbar:
    """
    Vertical bar on the left with square icon buttons.
    on_press(x, y) returns "settings", "new_intersection", "new_place", or None.
    """

    def __init__(self, left: float, bottom: float, width: float = TOOLBAR_WIDTH):
        self.left = left
        self.bottom = bottom
        self.width = width
        self._button_size = TOOLBAR_BUTTON_SIZE
        self._gap = TOOLBAR_GAP
        padding = (width - self._button_size) / 2
        self._height = 3 * self._button_size + 2 * self._gap + 2 * padding

        self._settings_icon = arcade.Text("...", 0, 0, color=(220, 220, 220), font_size=16, anchor_x="center", anchor_y="center")
        self._inter_icon = arcade.Text("+", 0, 0, color=(220, 220, 220), font_size=18, anchor_x="center", anchor_y="center")
        self._place_icon = arcade.Text("P", 0, 0, color=(220, 220, 220), font_size=18, anchor_x="center", anchor_y="center")

    def _button_rects(self) -> list[tuple[float, float, float, float, str]]:
        """Return list of (left, bottom, width, height, action) for each button."""
        pad = (self.width - self._button_size) / 2
        bx = self.left + pad
        top_btn_bottom = self.bottom + self._height - self._button_size - pad
        mid_btn_bottom = top_btn_bottom - self._button_size - self._gap
        bot_btn_bottom = self.bottom + pad
        return [
            (bx, top_btn_bottom, self._button_size, self._button_size, "new_intersection"),
            (bx, mid_btn_bottom, self._button_size, self._button_size, "new_place"),
            (bx, bot_btn_bottom, self._button_size, self._button_size, "settings"),
        ]

    def contains(self, x: float, y: float) -> bool:
        return (
            self.left <= x <= self.left + self.width
            and self.bottom <= y <= self.bottom + self._height
        )

    def on_press(self, x: float, y: float) -> str | None:
        for l, b, w, h, action in self._button_rects():
            if l <= x <= l + w and b <= y <= b + h:
                return action
        return None

    def draw(self) -> None:
        rect_filled(self.left, self.bottom, self.width, self._height, TOOLBAR_BG)
        rect_outline(self.left, self.bottom, self.width, self._height, TOOLBAR_BORDER, 1)
        for l, b, w, h, action in self._button_rects():
            rect_filled(l, b, w, h, (70, 70, 80))
            rect_outline(l, b, w, h, (100, 100, 110), 1)
            cx = l + w / 2
            cy = b + h / 2
            if action == "settings":
                self._settings_icon.x, self._settings_icon.y = cx, cy
                self._settings_icon.draw()
            elif action == "new_intersection":
                self._inter_icon.x, self._inter_icon.y = cx, cy
                self._inter_icon.draw()
            else:
                self._place_icon.x, self._place_icon.y = cx, cy
                self._place_icon.draw()
