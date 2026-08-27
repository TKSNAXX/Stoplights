"""
Lightweight reusable UI controls (Slider, Switch, Dropdown, Dialog).
Screen space: x right, y up. Rect is (left, bottom, width, height).
"""
from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

import arcade
import math
from draw_compat import rect_filled, rect_outline
from sim import world
from sim.constants import TILE_H, TILE_W


NUMBER_BOX_HEIGHT = 22
NUMBER_BOX_ARROW_SIZE = 14


@runtime_checkable
class FocusableWidget(Protocol):
    """Widget that can receive keyboard focus and key presses."""

    def set_focus(self, focused: bool) -> None: ...

    def on_key_press(self, key: int) -> bool: ...


@runtime_checkable
class ExpandedHitWidget(Protocol):
    """Widget that may capture clicks outside its base rect."""

    def expanded_contains(self, x: float, y: float) -> bool: ...


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


TEXT_BOX_MAX_LEN = 24


def _text_box_char_ok(ch: str) -> bool:
    return ch.isalnum() or ch in " -"


class TextBox:
    """Single-line text field. Focus to type. Rect (left, bottom, width, height)."""

    def __init__(
        self,
        left: float,
        bottom: float,
        width: float,
        height: float,
        value: str = "",
        on_change: Callable[[str], None] | None = None,
        on_unfocus: Callable[[], None] | None = None,
        max_len: int = TEXT_BOX_MAX_LEN,
    ):
        self.rect = (left, bottom, width, height)
        self.value = value
        self.max_len = max_len
        self._on_change = on_change
        self._on_unfocus = on_unfocus
        self._focused = False
        self._text_buffer = value
        self._text = arcade.Text(
            "", 0, 0, color=(220, 220, 220), font_size=11, anchor_x="left", anchor_y="center"
        )

    def contains(self, x: float, y: float) -> bool:
        left, bottom, width, height = self.rect
        return left <= x <= left + width and bottom <= y <= bottom + height

    def set_focus(self, focused: bool) -> None:
        if self._focused != focused:
            self._focused = focused
            if not focused:
                self._commit_text()
                if self._on_unfocus:
                    self._on_unfocus()

    def _commit_text(self) -> None:
        stripped = self._text_buffer.strip()
        if not stripped:
            self._text_buffer = self.value
            return
        if stripped != self.value:
            self.value = stripped
            self._text_buffer = stripped
            if self._on_change:
                self._on_change(self.value)

    def on_press(self, x: float, y: float) -> bool:
        if not self.contains(x, y):
            return False
        self.set_focus(True)
        return True

    def on_drag(self, x: float) -> bool:
        return False

    def on_release(self) -> bool:
        return False

    def on_key_press(self, key: int) -> bool:
        if not self._focused:
            return False
        if key == arcade.key.RETURN or key == arcade.key.TAB:
            self.set_focus(False)
            return True
        if key == arcade.key.BACKSPACE:
            if self._text_buffer:
                self._text_buffer = self._text_buffer[:-1]
            return True
        return False

    def on_text(self, text: str) -> None:
        if not self._focused:
            return
        for ch in text:
            if not _text_box_char_ok(ch):
                continue
            if len(self._text_buffer) >= self.max_len:
                break
            self._text_buffer += ch

    def draw(self) -> None:
        left, bottom, width, height = self.rect
        rect_filled(left, bottom, width, height, (50, 50, 60))
        rect_outline(left, bottom, width, height, DIALOG_BORDER if self._focused else (80, 80, 90), 1)
        self._text.value = self._text_buffer if self._focused else self.value
        self._text.x = left + 6
        self._text.y = bottom + height / 2
        self._text.draw()


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


DROPDOWN_ROW_HEIGHT = 20
LANEVARS_CAPTION_WIDTH = 65
LANEVARS_GAP = 8


class Dropdown:
    """
    Option selector: shows current value in a box; click to expand list, click option to select.
    Rect (left, bottom, width, height). options is list[str]; value is selected index.
    """

    def __init__(
        self,
        left: float,
        bottom: float,
        width: float,
        height: float,
        options: list[str],
        initial_index: int = 0,
        on_change: Callable[[int], None] | None = None,
    ):
        self.rect = (left, bottom, width, height)
        self.options = options if options else [""]
        self.value = max(0, min(initial_index, len(self.options) - 1))
        self._on_change = on_change
        self._open = False
        self._text = arcade.Text(
            "", 0, 0, color=(220, 220, 220), font_size=10,
            anchor_x="left", anchor_y="center",
        )

    def contains(self, x: float, y: float) -> bool:
        left, bottom, width, height = self.rect
        if left <= x <= left + width and bottom <= y <= bottom + height:
            return True
        if self._open and len(self.options) > 0:
            list_top = bottom + height
            list_height = len(self.options) * DROPDOWN_ROW_HEIGHT
            list_bottom = list_top - list_height
            if left <= x <= left + width and list_bottom <= y <= list_top:
                return True
        return False

    @property
    def is_open(self) -> bool:
        return self._open

    def expanded_contains(self, x: float, y: float) -> bool:
        """Public expanded hit area (includes open list rows)."""
        return self.contains(x, y)

    def set_value(self, index: int) -> None:
        idx = max(0, min(index, len(self.options) - 1))
        if idx != self.value:
            self.value = idx
            if self._on_change:
                self._on_change(self.value)

    def draw(self) -> None:
        left, bottom, width, height = self.rect
        rect_filled(left, bottom, width, height, (70, 70, 85))
        rect_outline(left, bottom, width, height, (100, 100, 120), 1)
        self._text.value = self.options[self.value] if self.options else "-"
        self._text.x = left + 6
        self._text.y = bottom + height / 2
        self._text.draw()
        arrow = arcade.Text("▼", left + width - 12, bottom + height / 2,
                            color=(180, 180, 180), font_size=9, anchor_x="center", anchor_y="center")
        arrow.draw()

    def draw_expanded_list(self) -> None:
        """Draw open option rows on top of sibling widgets; Dialog calls this after all widget.draw()."""
        if not self._open or not self.options:
            return
        left, bottom, width, height = self.rect
        list_top = bottom + height
        for i, opt in enumerate(self.options):
            row_bottom = list_top - (i + 1) * DROPDOWN_ROW_HEIGHT
            rect_filled(left, row_bottom, width, DROPDOWN_ROW_HEIGHT, (55, 55, 65))
            rect_outline(left, row_bottom, width, DROPDOWN_ROW_HEIGHT, (80, 80, 95), 1)
            if i == self.value:
                rect_filled(left + 1, row_bottom + 1, width - 2, DROPDOWN_ROW_HEIGHT - 2, (90, 90, 110))
            item_text = arcade.Text(opt, left + 6, row_bottom + DROPDOWN_ROW_HEIGHT / 2,
                                    color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
            item_text.draw()

    def on_press(self, x: float, y: float) -> bool:
        if not self.contains(x, y):
            return False
        left, bottom, width, height = self.rect
        if self._open and len(self.options) > 0:
            list_top = bottom + height
            for i in range(len(self.options)):
                row_bottom = list_top - (i + 1) * DROPDOWN_ROW_HEIGHT
                row_top = row_bottom + DROPDOWN_ROW_HEIGHT
                if left <= x <= left + width and row_bottom <= y <= row_top:
                    self.set_value(i)
                    self._open = False
                    return True
            self._open = False
            return True
        self._open = True
        return True

    def on_drag(self, x: float) -> bool:
        return False

    def on_release(self) -> bool:
        return False


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
        self._on_close: Callable | None = None
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

    def extended_contains(self, x: float, y: float) -> bool:
        """True if point is in dialog rect or in any open dropdown's expanded list."""
        if self.contains(x, y):
            return True
        for w in self.widgets:
            if isinstance(w, ExpandedHitWidget) and w.expanded_contains(x, y):
                return True
        return False

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
        for w in self.widgets:
            if isinstance(w, Dropdown) and w.is_open:
                w.draw_expanded_list()

    def on_mouse_press(self, x: float, y: float) -> bool:
        if not self.extended_contains(x, y) or not self.visible:
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
            if w.on_press(x, y):
                if self._dialog_manager and isinstance(w, FocusableWidget):
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
            if w.on_drag(x):
                return True
        return False

    def on_mouse_release(self, x: float, y: float) -> bool:
        if self._dragging:
            self._dragging = False
            self._drag_start = None
            return True
        for w in self.widgets:
            if w.on_release():
                return True
        return False


class DialogManager:
    """Manages open dialogs: z-order, input routing, draw."""

    def __init__(self, get_window_size: Callable[[], tuple[float, float]] | None = None):
        self._dialogs: list[Dialog] = []
        self._focused_widget: FocusableWidget | None = None
        self._get_window_size = get_window_size

    def set_focused_widget(self, widget: FocusableWidget | None) -> None:
        if self._focused_widget is not None:
            self._focused_widget.set_focus(False)
        self._focused_widget = widget
        if widget is not None:
            widget.set_focus(True)

    def get_focused_widget(self) -> FocusableWidget | None:
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
        """True if (x, y) is over any visible dialog (including open dropdowns)."""
        for d in self._dialogs:
            if d.visible and d.extended_contains(x, y):
                return True
        return False

    def on_mouse_press(self, x: float, y: float) -> bool:
        for i in range(len(self._dialogs) - 1, -1, -1):
            d = self._dialogs[i]
            if d.extended_contains(x, y) and d.visible:
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
# Intersection type: x (cross), corner, straight (dual lane through), tee
INTERSECTION_TYPE_VALUES = ("x", "corner", "straight", "tee")


def _intersection_type_index(intersection_type: str) -> int:
    try:
        return INTERSECTION_TYPE_VALUES.index(intersection_type)
    except ValueError:
        return 0
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
    """Dialog for editing intersection type, center, and size. Changes apply live. Remove for extra intersections only."""

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
        super().__init__(x, y, 220, 160, f"Intersection: {intersection_key}")
        self.intersection_key = intersection_key
        self._config = intersection_config
        self._game = game
        self._on_change = on_change
        self._on_commit = on_commit
        self._on_remove = on_remove
        self._can_remove = bool(game is not None and hasattr(game, "can_remove_intersection") and game.can_remove_intersection(intersection_key))

        type_idx = _intersection_type_index(getattr(intersection_config, "intersection_type", "x"))
        cx = getattr(intersection_config, "center_x", 18)
        cy = getattr(intersection_config, "center_y", 24)
        size_val = getattr(intersection_config, "size_cells", 4)

        self._type_dropdown = Dropdown(
            0, 0, 140, DROPDOWN_ROW_HEIGHT,
            list(INTERSECTION_TYPE_VALUES),
            initial_index=type_idx,
            on_change=lambda _: self._apply_config(),
        )
        control_width = 140
        self._center_compass = CompassSelect(
            0, 0, control_width, DROPDOWN_ROW_HEIGHT, (cx, cy), on_change=lambda _: self._apply_config(),
        )
        self._size_box = NumberBox(0, 0, 100, NUMBER_BOX_HEIGHT, size_val, 2, 12, 2, on_change=lambda _: self._apply_config(), on_unfocus=self._apply_config)
        self._remove_btn = RemoveButton(0, 0, 70, 22, on_click=self._do_remove)

        self.widgets = [self._type_dropdown, self._center_compass, self._size_box]
        if self._can_remove:
            self.widgets.append(self._remove_btn)
        self._type_label = arcade.Text("", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._center_label = arcade.Text("Center:", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._size_label = arcade.Text("", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")

    def _apply_config(self) -> None:
        """Apply type, center, size from widgets to config and call on_commit."""
        self._config.intersection_type = INTERSECTION_TYPE_VALUES[self._type_dropdown.value]
        self._config.center_x, self._config.center_y = self._center_compass.value
        self._config.size_cells = max(2, min(12, self._size_box.value))
        if self._config.size_cells % 2 != 0:
            self._config.size_cells = (self._config.size_cells // 2) * 2
        if self._on_commit:
            self._on_commit()

    def _do_remove(self) -> None:
        """Remove this intersection from game and call on_remove."""
        if self._game is not None and self.intersection_key in self._game.intersections:
            del self._game.intersections[self.intersection_key]
            self._game.rebuild_world_from_config()
        if self._on_remove:
            self._on_remove()

    def _layout_widgets(self) -> None:
        left = self.x + 12
        content_top = self.y - 32
        box_w = 100
        control_left = left + 70
        self._type_dropdown.rect = (control_left, content_top - 24, 140, DROPDOWN_ROW_HEIGHT)
        self._center_compass.rect = (control_left, content_top - 48, 140, DROPDOWN_ROW_HEIGHT)
        self._size_box.rect = (control_left, content_top - 74, box_w, NUMBER_BOX_HEIGHT)
        if self._can_remove:
            self._remove_btn.rect = (left, content_top - 100, 70, 22)
        self._type_label.x = left
        self._type_label.y = content_top - 12
        self._center_label.x = left
        self._center_label.y = content_top - 36
        self._size_label.x = left
        self._size_label.y = content_top - 62

    def draw(self) -> None:
        self._layout_widgets()
        self._type_label.value = f"Type: {INTERSECTION_TYPE_VALUES[self._type_dropdown.value]}"
        self._size_label.value = "Size:"
        super().draw()
        self._type_label.draw()
        self._center_label.draw()
        self._size_label.draw()

    def on_mouse_press(self, x: float, y: float) -> bool:
        self._layout_widgets()
        result = super().on_mouse_press(x, y)
        self._apply_config()
        return result

    def on_mouse_drag(self, x: float, y: float, dx: float, dy: float) -> bool:
        result = super().on_mouse_drag(x, y, dx, dy)
        self._apply_config()
        return result

    def on_mouse_release(self, x: float, y: float) -> bool:
        result = super().on_mouse_release(x, y)
        self._apply_config()
        return result


class NewIntersectionDialog(Dialog):
    """Dialog for creating a new intersection. Commit adds to game and closes."""

    def __init__(
        self,
        x: float,
        y: float,
        game,
        on_commit: Callable[[], None] | None = None,
    ):
        key = _next_intersection_key(game.intersections)
        super().__init__(x, y, 220, 174, f"New Intersection: {key}")
        self._game = game
        self._key = key
        self._on_commit = on_commit

        self._type_dropdown = Dropdown(
            0, 0, 140, DROPDOWN_ROW_HEIGHT,
            list(INTERSECTION_TYPE_VALUES),
            initial_index=0,
            on_change=None,
        )
        control_width = 140
        self._center_compass = CompassSelect(
            0, 0, control_width, DROPDOWN_ROW_HEIGHT, (36, 48), on_change=None,
        )
        self._size_box = NumberBox(0, 0, 100, NUMBER_BOX_HEIGHT, 4, 2, 12, 2)
        self._commit_btn = CommitButton(0, 0, 70, 22, on_click=self._do_commit)

        self.widgets = [self._type_dropdown, self._center_compass, self._size_box, self._commit_btn]
        self._type_label = arcade.Text("", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._center_label = arcade.Text("Center:", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._size_label = arcade.Text("", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")

    def _do_commit(self) -> None:
        from sim import places
        center_x, center_y = self._center_compass.value
        cfg = places.IntersectionConfig(
            intersection_type=INTERSECTION_TYPE_VALUES[self._type_dropdown.value],
            center_x=center_x,
            center_y=center_y,
            size_cells=max(2, min(12, self._size_box.value)),
        )
        if cfg.size_cells % 2 != 0:
            cfg.size_cells = (cfg.size_cells // 2) * 2
        self._game.intersections[self._key] = cfg
        self._game.rebuild_world_from_config()
        if self._on_commit:
            self._on_commit()

    def _layout_widgets(self) -> None:
        left = self.x + 12
        content_top = self.y - 32
        box_w = 100
        control_left = left + 70
        self._type_dropdown.rect = (control_left, content_top - 24, 140, DROPDOWN_ROW_HEIGHT)
        self._center_compass.rect = (control_left, content_top - 48, 140, DROPDOWN_ROW_HEIGHT)
        self._size_box.rect = (control_left, content_top - 74, box_w, NUMBER_BOX_HEIGHT)
        self._commit_btn.rect = (left, content_top - 106, 70, 22)
        self._type_label.x = left
        self._type_label.y = content_top - 12
        self._center_label.x = left
        self._center_label.y = content_top - 36
        self._size_label.x = left
        self._size_label.y = content_top - 62

    def draw(self) -> None:
        self._layout_widgets()
        self._type_label.value = f"Type: {INTERSECTION_TYPE_VALUES[self._type_dropdown.value]}"
        self._size_label.value = "Size:"
        super().draw()
        self._type_label.draw()
        self._center_label.draw()
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
        on_geometry_change: Callable[[tuple[int, int], int, int], None] | None = None,
    ):
        name = _next_place_name(game.places)
        super().__init__(x, y, 220, 202, f"New Place: {name}")
        self._game = game
        self._on_commit = on_commit
        self._on_geometry_change = on_geometry_change

        control_width = 140
        self._name_box = TextBox(0, 0, 140, NUMBER_BOX_HEIGHT, name)
        self._center_compass = CompassSelect(
            0, 0, control_width, DROPDOWN_ROW_HEIGHT, (20, 20), on_change=lambda _: self._notify_geometry(),
        )
        self._w_box = NumberBox(0, 0, 100, NUMBER_BOX_HEIGHT, 5, 1, 16, 1, on_change=lambda _: self._notify_geometry())
        self._l_box = NumberBox(0, 0, 100, NUMBER_BOX_HEIGHT, 5, 1, 16, 1, on_change=lambda _: self._notify_geometry())
        self._commit_btn = CommitButton(0, 0, 70, 22, on_click=self._do_commit)

        self.widgets = [self._name_box, self._center_compass, self._w_box, self._l_box, self._commit_btn]
        self._name_label = arcade.Text("Name:", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._center_label = arcade.Text("Center:", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._w_label = arcade.Text("Width:", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._l_label = arcade.Text("Length:", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")

    def set_geometry(self, center: tuple[int, int], width: int, length: int) -> None:
        """Update readout from the map tool without fighting a focused field."""
        if not self._center_compass._focused:
            self._center_compass.set_value(center)
        if not self._w_box._focused:
            self._w_box.value = width
            self._w_box._text_buffer = str(width)
        if not self._l_box._focused:
            self._l_box.value = length
            self._l_box._text_buffer = str(length)

    def try_name(self) -> str | None:
        """Flush the name box; return a unique name or None if empty/colliding."""
        if self._name_box._focused:
            self._name_box.set_focus(False)
        name = self._name_box.value.strip()
        if not name or name in self._game.places or name in self._game.intersections:
            return None
        return name

    def _notify_geometry(self) -> None:
        if self._on_geometry_change:
            self._on_geometry_change(self._center_compass.value, self._w_box.value, self._l_box.value)

    def _do_commit(self) -> None:
        from sim import places
        from sim.places import PLACE_SIZE_MIN, PLACE_SIZE_MAX
        name = self.try_name()
        if name is None:
            return
        center_x, center_y = self._center_compass.value
        w = max(PLACE_SIZE_MIN, min(PLACE_SIZE_MAX, self._w_box.value))
        l = max(PLACE_SIZE_MIN, min(PLACE_SIZE_MAX, self._l_box.value))
        p = places.Place(
            center_x=center_x,
            center_y=center_y,
            width=w,
            length=l,
        )
        self._game.places[name] = p
        self._game.rebuild_world_from_config()
        if self._on_commit:
            self._on_commit()

    def _layout_widgets(self) -> None:
        left = self.x + 12
        content_top = self.y - 32
        box_w = 100
        control_left = left + 70
        self._name_box.rect = (control_left, content_top - 24, 140, NUMBER_BOX_HEIGHT)
        self._center_compass.rect = (control_left, content_top - 52, 140, DROPDOWN_ROW_HEIGHT)
        self._w_box.rect = (control_left, content_top - 78, box_w, NUMBER_BOX_HEIGHT)
        self._l_box.rect = (control_left, content_top - 104, box_w, NUMBER_BOX_HEIGHT)
        self._commit_btn.rect = (left, content_top - 136, 70, 22)
        self._name_label.x = left
        self._name_label.y = content_top - 12
        self._center_label.x = left
        self._center_label.y = content_top - 40
        self._w_label.x = left
        self._w_label.y = content_top - 66
        self._l_label.x = left
        self._l_label.y = content_top - 92

    def draw(self) -> None:
        self._layout_widgets()
        super().draw()
        self._name_label.draw()
        self._center_label.draw()
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


def _next_place_name(places_by_id: dict) -> str:
    """Return Place N where N is the next available index (1, 2, ...)."""
    seen = set()
    for k in places_by_id:
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
    """Dialog for editing place spawn, attract, and geometry. Changes apply live. Remove for extra places only."""

    def __init__(
        self,
        x: float,
        y: float,
        place: str,
        place_obj,
        game=None,
        on_change: Callable[[], None] | None = None,
        on_commit: Callable[[], None] | None = None,
        on_remove: Callable[[], None] | None = None,
        on_rename: Callable[[str, str], None] | None = None,
    ):
        super().__init__(x, y, 240, 240, f"Place: {place}")
        self.place = place
        self._place = place_obj
        self._game = game
        self._on_change = on_change
        self._on_commit = on_commit
        self._on_remove = on_remove
        self._on_rename = on_rename
        self._can_remove = bool(game is not None and hasattr(game, "can_remove_place") and game.can_remove_place(place))

        spawn_step = self._step_for_spawn(place_obj.spawn_interval)
        attract_step = self._step_for_attract(place_obj.attract_weight)
        self._name_box = TextBox(0, 0, 140, NUMBER_BOX_HEIGHT, place, on_unfocus=self._commit_name)
        self._spawn_slider = Slider(0, 0, 160, 20, 5, spawn_step, (100, 100, 100), (180, 180, 180))
        self._attract_slider = Slider(0, 0, 160, 20, 5, attract_step, (100, 100, 100), (180, 180, 180))

        cx, cy, w, l = place_obj.center_x, place_obj.center_y, place_obj.width, place_obj.length
        control_width = 140
        self._center_compass = CompassSelect(
            0, 0, control_width, DROPDOWN_ROW_HEIGHT, (cx, cy), on_change=lambda _: self._apply_geometry(),
        )
        self._w_box = NumberBox(0, 0, 100, NUMBER_BOX_HEIGHT, w, 1, 16, 1, on_change=lambda _: self._apply_geometry(), on_unfocus=self._apply_geometry)
        self._l_box = NumberBox(0, 0, 100, NUMBER_BOX_HEIGHT, l, 1, 16, 1, on_change=lambda _: self._apply_geometry(), on_unfocus=self._apply_geometry)
        self._remove_btn = RemoveButton(0, 0, 70, 22, on_click=self._do_remove)

        self.widgets = [
            self._name_box, self._spawn_slider, self._attract_slider,
            self._center_compass, self._w_box, self._l_box,
        ]
        if self._can_remove:
            self.widgets.append(self._remove_btn)
        self._name_label = arcade.Text("Name:", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._spawn_label = arcade.Text("", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._attract_label = arcade.Text("", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._center_label = arcade.Text("Center:", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._w_label = arcade.Text("Width:", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._l_label = arcade.Text("Length:", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")

    def _commit_name(self) -> None:
        """Rename this place id on unfocus. Collision or empty keeps the current id."""
        if self._game is None:
            return
        old = self.place
        used = self._game.rename_place(old, self._name_box.value)
        self._name_box.value = used
        self._name_box._text_buffer = used
        if used == old:
            return
        self.place = used
        self.title = f"Place: {used}"
        if self._on_rename:
            self._on_rename(old, used)
        if self._on_change:
            self._on_change()

    def _apply_geometry(self) -> None:
        """Apply geometry from CompassSelect and NumberBoxes, call on_commit."""
        from sim.places import PLACE_SIZE_MIN, PLACE_SIZE_MAX
        center_x, center_y = self._center_compass.value
        w = max(PLACE_SIZE_MIN, min(PLACE_SIZE_MAX, self._w_box.value))
        l = max(PLACE_SIZE_MIN, min(PLACE_SIZE_MAX, self._l_box.value))
        self._place.center_x = center_x
        self._place.center_y = center_y
        self._place.width = w
        self._place.length = l
        if self._on_commit:
            self._on_commit()

    def _do_remove(self) -> None:
        """Remove this place from game and call on_remove."""
        if self._game is not None:
            if self.place in self._game.places:
                del self._game.places[self.place]
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
        control_left = left + 70
        self._name_box.rect = (control_left, content_top - 24, 140, NUMBER_BOX_HEIGHT)
        self._spawn_slider.rect = (left, content_top - 52, 160, 20)
        self._attract_slider.rect = (left, content_top - 80, 160, 20)
        self._center_compass.rect = (control_left, content_top - 106, 140, DROPDOWN_ROW_HEIGHT)
        self._w_box.rect = (control_left, content_top - 132, box_w, NUMBER_BOX_HEIGHT)
        self._l_box.rect = (control_left, content_top - 158, box_w, NUMBER_BOX_HEIGHT)
        if self._can_remove:
            self._remove_btn.rect = (left, content_top - 190, 70, 22)
        self._name_label.x = left
        self._name_label.y = content_top - 12
        self._spawn_label.x = left
        self._spawn_label.y = content_top - 40
        self._attract_label.x = left
        self._attract_label.y = content_top - 68
        self._center_label.x = left
        self._center_label.y = content_top - 94
        self._w_label.x = left
        self._w_label.y = content_top - 120
        self._l_label.x = left
        self._l_label.y = content_top - 146

    def draw(self) -> None:
        self._layout_widgets()
        self._spawn_label.value = f"Spawn: {PLACE_SPAWN_VALUES[self._spawn_slider.value]:.1f}s"
        self._attract_label.value = f"Attract: {PLACE_ATTRACT_VALUES[self._attract_slider.value]:.1f}x"
        super().draw()
        self._name_label.draw()
        self._spawn_label.draw()
        self._attract_label.draw()
        self._center_label.draw()
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
        self._place.spawn_interval = PLACE_SPAWN_VALUES[self._spawn_slider.value]
        self._place.attract_weight = PLACE_ATTRACT_VALUES[self._attract_slider.value]
        if self._on_change:
            self._on_change()


# Iso direction vectors from grid_to_screen (grid N/S/E/W -> screen directions)
_COMPASS_ISO_DIRS: dict[str, tuple[float, float]] = {
    "W": (-TILE_W, -TILE_H),
    "E": (TILE_W, TILE_H),
    "N": (-TILE_W, TILE_H),
    "S": (TILE_W, -TILE_H),
}


class CompassSelect:
    """
    Tile selector control.
    Displays (x, y) plus directional buttons in one row: W, E, N, S.
    Coordinates are keyboard-editable. Arrow icons use iso projection.
    locked_axis:
      - "x": disable E/W (x fixed)
      - "y": disable N/S (y fixed)
      - None: all enabled
    """

    def __init__(
        self,
        left: float,
        bottom: float,
        width: float,
        height: float,
        value: tuple[int, int],
        on_change: Callable[[tuple[int, int]], None] | None = None,
        locked_axis: str | None = None,
        min_val: int = -200,
        max_val: int = 200,
    ):
        self.rect = (left, bottom, width, height)
        self.value = (int(value[0]), int(value[1]))
        self.locked_axis = locked_axis
        self._on_change = on_change
        self._min_val = min_val
        self._max_val = max_val
        self._focused = False
        self._text_buffer = f"{self.value[0]}, {self.value[1]}"
        self._text = arcade.Text("", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")

    def set_value(self, value: tuple[int, int]) -> None:
        self.value = (int(value[0]), int(value[1]))
        self._text_buffer = f"{self.value[0]}, {self.value[1]}"

    def set_focus(self, focused: bool) -> None:
        if self._focused != focused:
            self._focused = focused
            if not focused:
                self._commit_text()

    def _box_rect(self) -> tuple[float, float, float, float]:
        """Text box portion: (left, bottom, width, height)."""
        left, bottom, width, height = self.rect
        text_w = min(64.0, width * 0.35)
        return (left, bottom, text_w + 6, height)

    def _commit_text(self) -> None:
        parts = self._text_buffer.replace(",", " ").split()
        try:
            vx = int(parts[0]) if len(parts) >= 1 else self.value[0]
            vy = int(parts[1]) if len(parts) >= 2 else self.value[1]
            vx = max(self._min_val, min(self._max_val, vx))
            vy = max(self._min_val, min(self._max_val, vy))
            nv = (vx, vy)
            if nv != self.value:
                self.value = nv
                if self._on_change:
                    self._on_change(self.value)
        except (ValueError, IndexError):
            pass
        self._text_buffer = f"{self.value[0]}, {self.value[1]}"

    def _button_defs(self) -> list[tuple[str, str, tuple[int, int]]]:
        return [
            ("W", "", (-1, 0)),
            ("E", "", (1, 0)),
            ("N", "", (0, 1)),
            ("S", "", (0, -1)),
        ]

    def _button_rect(self, idx: int) -> tuple[float, float, float, float]:
        left, bottom, width, height = self.rect
        text_w = min(64.0, width * 0.35)
        btn_left = left + text_w + 6
        btn_width_total = max(40.0, width - (btn_left - left))
        btn_w = max(18.0, btn_width_total / 4 - 2)
        return (btn_left + idx * (btn_w + 2), bottom, btn_w, height)

    def _is_disabled(self, key: str) -> bool:
        if self.locked_axis == "x":
            return key in ("W", "E")
        if self.locked_axis == "y":
            return key in ("N", "S")
        return False

    def _draw_iso_arrow(self, cx: float, cy: float, key: str, color: tuple[int, int, int]) -> None:
        """Draw arrow with head and tail pointing in iso direction for key."""
        dx, dy = _COMPASS_ISO_DIRS[key]
        length = math.hypot(dx, dy)
        if length < 0.01:
            return
        dx, dy = dx / length, dy / length
        perp_x = -dy
        perp_y = dx
        head_size = 7.0
        base_half = 5.0
        tail_len = 5.0
        tail_half = 1.5
        tip_x = cx + dx * head_size
        tip_y = cy + dy * head_size
        base_x = cx - dx * head_size * 0.3
        base_y = cy - dy * head_size * 0.3
        v1 = (base_x + perp_x * base_half, base_y + perp_y * base_half)
        v2 = (base_x - perp_x * base_half, base_y - perp_y * base_half)
        arcade.draw_triangle_filled(
            tip_x, tip_y,
            v1[0], v1[1],
            v2[0], v2[1],
            color,
        )
        tail_tip_x = cx - dx * (head_size * 0.3 + tail_len)
        tail_tip_y = cy - dy * (head_size * 0.3 + tail_len)
        t1 = (base_x + perp_x * tail_half, base_y + perp_y * tail_half)
        t2 = (base_x - perp_x * tail_half, base_y - perp_y * tail_half)
        arcade.draw_triangle_filled(
            tail_tip_x, tail_tip_y,
            t1[0], t1[1],
            t2[0], t2[1],
            color,
        )

    def contains(self, x: float, y: float) -> bool:
        left, bottom, width, height = self.rect
        return left <= x <= left + width and bottom <= y <= bottom + height

    def on_press(self, x: float, y: float) -> bool:
        if not self.contains(x, y):
            return False
        bx, by, bw, bh = self._box_rect()
        if bx <= x <= bx + bw and by <= y <= by + bh:
            self.set_focus(True)
            return True
        for i, (key, _label, delta) in enumerate(self._button_defs()):
            l, b, w, h = self._button_rect(i)
            if l <= x <= l + w and b <= y <= b + h:
                if self._is_disabled(key):
                    return True
                nx = self.value[0] + delta[0]
                ny = self.value[1] + delta[1]
                nx = max(self._min_val, min(self._max_val, nx))
                ny = max(self._min_val, min(self._max_val, ny))
                self.value = (nx, ny)
                self._text_buffer = f"{self.value[0]}, {self.value[1]}"
                if self._on_change:
                    self._on_change(self.value)
                return True
        return True

    def on_key_press(self, key: int) -> bool:
        if not self._focused:
            return False
        if key == arcade.key.RETURN or key == arcade.key.TAB:
            self.set_focus(False)
            return True
        if key == arcade.key.BACKSPACE:
            if self._text_buffer:
                self._text_buffer = self._text_buffer[:-1]
            return True
        if 48 <= key <= 57:
            self._text_buffer += chr(key)
            return True
        if key == arcade.key.COMMA:
            self._text_buffer += ","
            return True
        if key == arcade.key.SPACE:
            self._text_buffer += " "
            return True
        if key == arcade.key.MINUS or key == 45:
            if not self._text_buffer or self._text_buffer[-1] in ", ":
                self._text_buffer += "-"
            return True
        return False

    def on_drag(self, x: float) -> bool:
        return False

    def on_release(self) -> bool:
        return False

    def draw(self) -> None:
        left, bottom, width, height = self.rect
        bx, by, bw, bh = self._box_rect()
        rect_filled(bx, by, bw, bh, (50, 50, 60))
        rect_outline(bx, by, bw, bh, DIALOG_BORDER if self._focused else (80, 80, 90), 1)
        self._text.value = self._text_buffer if self._focused else f"({self.value[0]}, {self.value[1]})"
        self._text.x = left + 2
        self._text.y = bottom + height / 2
        self._text.draw()
        for i, (key, _label, _delta) in enumerate(self._button_defs()):
            l, b, w, h = self._button_rect(i)
            disabled = self._is_disabled(key)
            bg = (70, 70, 80) if not disabled else (52, 52, 58)
            border = (100, 100, 115) if not disabled else (78, 78, 88)
            fg = (220, 220, 220) if not disabled else (130, 130, 140)
            rect_filled(l, b, w, h, bg)
            rect_outline(l, b, w, h, border, 1)
            self._draw_iso_arrow(l + w / 2, b + h / 2, key, fg)


class AddLaneDialog(Dialog):
    """Dialog for adding a new lane. Start/End tiles via CompassSelect, Commit creates the lane."""

    def __init__(
        self,
        x: float,
        y: float,
        game,
        on_commit: Callable[[], None] | None = None,
        on_tiles_change: Callable[[tuple[int, int], tuple[int, int]], None] | None = None,
    ):
        super().__init__(x, y, 320, 180, "Add Lane")
        self._game = game
        self._on_commit = on_commit
        self._start_tile = (0, 0)
        self._end_tile = (1, 0)
        self._start_compass = CompassSelect(
            0, 0, 220, DROPDOWN_ROW_HEIGHT, self._start_tile,
            on_change=self._on_start_change,
        )
        self._end_compass = CompassSelect(
            0, 0, 220, DROPDOWN_ROW_HEIGHT, self._end_tile,
            on_change=self._on_end_change,
        )
        self._commit_btn = CommitButton(0, 0, 70, 22, on_click=self._do_commit)
        self.widgets = [self._start_compass, self._end_compass, self._commit_btn]
        self._start_label = arcade.Text("Start:", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._end_label = arcade.Text("End:", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._status_label = arcade.Text("", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._on_tiles_change = on_tiles_change

    def set_tiles(self, start: tuple[int, int], end: tuple[int, int]) -> None:
        """Update compasses from the map tool without fighting a focused field."""
        self._start_tile = start
        self._end_tile = end
        if not self._start_compass._focused:
            self._start_compass.set_value(start)
        if not self._end_compass._focused:
            self._end_compass.set_value(end)

    def _notify_tiles(self) -> None:
        if self._on_tiles_change:
            self._on_tiles_change(self._start_compass.value, self._end_compass.value)

    def _is_valid_lane(self) -> bool:
        """True if start and end form an orthogonal lane (same row or same column)."""
        start = self._start_compass.value
        end = self._end_compass.value
        return start[0] == end[0] or start[1] == end[1]

    def _direction_text(self) -> str:
        """Return direction string when valid, else 'invalid end lane'."""
        if not self._is_valid_lane():
            return "invalid end tile"
        start = self._start_compass.value
        end = self._end_compass.value
        if start[0] == end[0]:
            return "Northbound" if end[1] > start[1] else "Southbound"
        return "Eastbound" if end[0] > start[0] else "Westbound"

    def _on_start_change(self, new_start: tuple[int, int]) -> None:
        self._start_tile = new_start
        self._notify_tiles()

    def _on_end_change(self, new_end: tuple[int, int]) -> None:
        self._end_tile = new_end
        self._notify_tiles()

    def _do_commit(self) -> None:
        if not self._is_valid_lane():
            return
        from sim.places import LaneConfig
        idx = self._game.next_lane_index()
        start = self._start_compass.value
        end = self._end_compass.value
        self._game.lanes[idx] = LaneConfig(start_tile=start, end_tile=end)
        self._game.rebuild_world_from_config()
        if self._on_commit:
            self._on_commit()

    def _layout_widgets(self) -> None:
        left = self.x + 12
        control_left = left + LANEVARS_CAPTION_WIDTH + LANEVARS_GAP
        control_width = self.width - 24 - (control_left - self.x)
        content_top = self.y - 32
        self._start_label.x = left
        self._start_label.y = content_top - 12
        self._start_compass.rect = (control_left, content_top - 24, control_width, DROPDOWN_ROW_HEIGHT)
        self._end_label.x = left
        self._end_label.y = content_top - 40
        self._end_compass.rect = (control_left, content_top - 52, control_width, DROPDOWN_ROW_HEIGHT)
        self._status_label.x = left
        self._status_label.y = content_top - 72
        self._commit_btn.rect = (control_left, content_top - 104, 70, 22)

    def draw(self) -> None:
        self._layout_widgets()
        self._status_label.value = f"Direction: {self._direction_text()}"
        self._status_label.color = (220, 180, 100) if not self._is_valid_lane() else (220, 220, 220)
        super().draw()
        self._start_label.draw()
        self._end_label.draw()
        self._status_label.draw()


class LaneVarsDialog(Dialog):
    """Dialog for editing lane speed/type and start/end tiles."""

    def __init__(
        self,
        x: float,
        y: float,
        lane_index: int,
        lane_config,
        game=None,
        on_change: Callable[[], None] | None = None,
        on_remove: Callable[[], None] | None = None,
    ):
        self._game = game
        self._can_remove = bool(game is not None and hasattr(game, "can_remove_lane") and game.can_remove_lane(lane_index))
        height = 268 if self._can_remove else 240
        super().__init__(x, y, 320, height, f"Lane {lane_index}")
        self.lane_index = lane_index
        self._config = lane_config
        self._on_change = on_change
        self._on_remove = on_remove

        speed_step = self._step_for_speed(lane_config.speed_limit)
        type_step = self._step_for_type(lane_config.lane_type)
        self._speed_slider = Slider(0, 0, 220, 20, len(LANE_SPEED_VALUES), speed_step, (100, 100, 100), (180, 180, 180))
        self._type_slider = Slider(0, 0, 220, 20, len(LANE_TYPE_VALUES), type_step, (100, 100, 100), (180, 180, 180))
        self._start_compass = CompassSelect(
            0, 0, 220, DROPDOWN_ROW_HEIGHT, getattr(lane_config, "start_tile", (0, 0)),
            on_change=self._on_start_change,
        )
        self._end_compass = CompassSelect(
            0, 0, 220, DROPDOWN_ROW_HEIGHT, getattr(lane_config, "end_tile", (0, 0)),
            on_change=lambda _v: self._sync_from_widgets(),
        )
        self._update_locked_axes()

        self.widgets = [
            self._speed_slider,
            self._type_slider,
            self._start_compass,
            self._end_compass,
        ]
        self._remove_btn = RemoveButton(0, 0, 70, 22, on_click=self._do_remove)
        if self._can_remove:
            self.widgets.append(self._remove_btn)
        self._speed_label = arcade.Text("Speed:", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._type_label = arcade.Text("Type:", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._start_label = arcade.Text("Start:", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._end_label = arcade.Text("End:", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._dir_label = arcade.Text("", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._in_label = arcade.Text("", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")
        self._out_label = arcade.Text("", 0, 0, color=(220, 220, 220), font_size=10, anchor_x="left", anchor_y="center")

    def _update_locked_axes(self) -> None:
        """End moves only along the lane (parallel). Start has full movement.
        When end == start, allow any direction so user can change orientation."""
        start = self._start_compass.value
        end = self._end_compass.value
        self._start_compass.locked_axis = None  # Start: full movement
        if start == end:
            # Same tile: allow any direction to pick new orientation
            self._end_compass.locked_axis = None
        elif start[0] == end[0]:
            # N-S lane: End moves N/S only (along lane)
            self._end_compass.locked_axis = "x"  # grey out E/W
        elif start[1] == end[1]:
            # E-W lane: End moves E/W only (along lane)
            self._end_compass.locked_axis = "y"  # grey out N/S
        else:
            self._end_compass.locked_axis = None

    def _do_remove(self) -> None:
        """Delete this lane and call on_remove."""
        if self._game is not None and self.lane_index in self._game.lanes:
            self._game.delete_lane(self.lane_index)
        if self._on_remove:
            self._on_remove()

    def _on_start_change(self, new_start: tuple[int, int]) -> None:
        """When Start moves perpendicular, also move End by the same delta to keep lane collinear."""
        old_start = self._config.start_tile
        delta = (new_start[0] - old_start[0], new_start[1] - old_start[1])
        if delta == (0, 0):
            self._sync_from_widgets()
            return
        # Only apply delta to End when it was a perpendicular move
        old_end = self._end_compass.value
        if old_start[0] == old_end[0]:
            # N-S lane: perpendicular = change in X
            if delta[0] != 0:
                self._end_compass.set_value((old_end[0] + delta[0], old_end[1]))
        elif old_start[1] == old_end[1]:
            # E-W lane: perpendicular = change in Y
            if delta[1] != 0:
                self._end_compass.set_value((old_end[0], old_end[1] + delta[1]))
        self._sync_from_widgets()

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
        control_left = left + LANEVARS_CAPTION_WIDTH + LANEVARS_GAP
        control_width = self.width - 24 - (control_left - self.x)
        content_top = self.y - 32
        row = 0
        # Captions left, controls right
        self._speed_label.x = left
        self._speed_label.y = content_top - 12 - row * 28
        self._speed_slider.rect = (control_left, content_top - 24 - row * 28, control_width, 20)
        row += 1
        self._type_label.x = left
        self._type_label.y = content_top - 12 - row * 28
        self._type_slider.rect = (control_left, content_top - 24 - row * 28, control_width, 20)
        row += 1
        self._start_label.x = left
        self._start_label.y = content_top - 12 - row * 28
        self._start_compass.rect = (control_left, content_top - 24 - row * 28, control_width, DROPDOWN_ROW_HEIGHT)
        row += 1
        self._end_label.x = left
        self._end_label.y = content_top - 12 - row * 28
        self._end_compass.rect = (control_left, content_top - 24 - row * 28, control_width, DROPDOWN_ROW_HEIGHT)
        row += 1
        # Info block: clear gap below end row, then 20px per line
        info_top = content_top - 24 - row * 28 - 16
        self._dir_label.x = left
        self._dir_label.y = info_top
        self._in_label.x = left
        self._in_label.y = info_top - 20
        self._out_label.x = left
        self._out_label.y = info_top - 40
        if self._can_remove:
            self._remove_btn.rect = (left, info_top - 64, 70, 22)

    def draw(self) -> None:
        self._layout_widgets()
        direction = world.lane_direction(self.lane_index)
        traffic_in = world.lane_traffic_in(self.lane_index) or "-"
        traffic_out = world.lane_traffic_out(self.lane_index) or "-"
        direction_map = {"N": "Northbound", "S": "Southbound", "E": "Eastbound", "W": "Westbound"}
        self._dir_label.value = f"Direction: {direction_map.get(direction, '-')}"
        self._in_label.value = f"Traffic in: {traffic_in}"
        self._out_label.value = f"Traffic out: {traffic_out}"
        super().draw()
        self._speed_label.draw()
        self._type_label.draw()
        self._start_label.draw()
        self._end_label.draw()
        self._dir_label.draw()
        self._in_label.draw()
        self._out_label.draw()

    def on_mouse_press(self, x: float, y: float) -> bool:
        self._layout_widgets()
        result = super().on_mouse_press(x, y)
        self._sync_from_widgets()
        return result

    def on_mouse_drag(self, x: float, y: float, dx: float, dy: float) -> bool:
        result = super().on_mouse_drag(x, y, dx, dy)
        self._sync_from_widgets()
        return result

    def on_mouse_release(self, x: float, y: float) -> bool:
        result = super().on_mouse_release(x, y)
        self._sync_from_widgets()
        return result

    def _sync_from_widgets(self) -> None:
        self._config.speed_limit = LANE_SPEED_VALUES[self._speed_slider.value]
        self._config.lane_type = LANE_TYPE_VALUES[self._type_slider.value]
        start = self._start_compass.value
        end = self._end_compass.value
        self._update_locked_axes()
        self._config.start_tile = start
        self._config.end_tile = end
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
TOOLBAR_BOTTOM_IDLE = 180
TOOLBAR_BOTTOM_DRAW = 220

ESC_CHIP_LEFT = 8
ESC_CHIP_MARGIN_TOP = 8
ESC_CHIP_WIDTH = 48
ESC_CHIP_HEIGHT = 28
ESC_CHIP_MARGIN_SIDE = 8


class SkeuoKeyChip:
    """Skeuomorphic keyboard-key control. side is 'left' or 'right' (top of the window)."""

    def __init__(self, label: str, side: str = "left"):
        self._side = side
        self._label = arcade.Text(
            label, 0, 0, color=(30, 30, 35), font_size=12, anchor_x="center", anchor_y="center"
        )

    def rect(self, window_width: float, window_height: float) -> tuple[float, float, float, float]:
        bottom = window_height - ESC_CHIP_MARGIN_TOP - ESC_CHIP_HEIGHT
        if self._side == "right":
            left = window_width - ESC_CHIP_MARGIN_SIDE - ESC_CHIP_WIDTH
        else:
            left = ESC_CHIP_LEFT
        return (left, bottom, ESC_CHIP_WIDTH, ESC_CHIP_HEIGHT)

    def contains(self, x: float, y: float, window_width: float, window_height: float) -> bool:
        left, bottom, width, height = self.rect(window_width, window_height)
        return left <= x <= left + width and bottom <= y <= bottom + height

    def draw(self, window_width: float, window_height: float) -> None:
        left, bottom, width, height = self.rect(window_width, window_height)
        rect_filled(left, bottom, width, height, (70, 70, 80))
        rect_filled(left + 1, bottom + 4, width - 2, height - 5, (200, 200, 210))
        rect_outline(left, bottom, width, height, (110, 110, 125), 1)
        self._label.x = left + width / 2
        self._label.y = bottom + height / 2 + 1
        self._label.draw()


class Toolbar:
    """
    Vertical bar on the left with square icon buttons.
    on_press(x, y) returns "settings", "new_intersection", "new_place", "new_lane", or None.
    """

    def __init__(self, left: float, bottom: float, width: float = TOOLBAR_WIDTH):
        self.left = left
        self.bottom = bottom
        self.width = width
        self._button_size = TOOLBAR_BUTTON_SIZE
        self._gap = TOOLBAR_GAP
        padding = (width - self._button_size) / 2
        self._height = 4 * self._button_size + 3 * self._gap + 2 * padding
        self.active_action: str | None = None
        self._lane_icon_list: arcade.SpriteList | None = None
        self._lane_icon_sprite: arcade.Sprite | None = None
        self._place_icon_list: arcade.SpriteList | None = None
        self._place_icon_sprite: arcade.Sprite | None = None

        self._settings_icon = arcade.Text("...", 0, 0, color=(220, 220, 220), font_size=16, anchor_x="center", anchor_y="center")
        self._inter_icon = arcade.Text("+", 0, 0, color=(220, 220, 220), font_size=18, anchor_x="center", anchor_y="center")
        self._place_fallback = arcade.Text("P", 0, 0, color=(220, 220, 220), font_size=18, anchor_x="center", anchor_y="center")
        self._lane_fallback = arcade.Text("L", 0, 0, color=(220, 220, 220), font_size=18, anchor_x="center", anchor_y="center")

    def _icon_from_tex(self, tex: arcade.Texture) -> tuple[arcade.Sprite, arcade.SpriteList]:
        tw = max(1, getattr(tex, "width", 64))
        th = max(1, getattr(tex, "height", 32))
        pad = 4
        scale = min((self._button_size - pad) / tw, (self._button_size - pad) / th)
        spr = arcade.Sprite(tex, scale=scale)
        lst = arcade.SpriteList()
        lst.append(spr)
        return spr, lst

    def set_lane_icon(self, tex: arcade.Texture | None) -> None:
        """Use an iso road texture as the new-lane button icon."""
        if tex is None:
            self._lane_icon_list = None
            self._lane_icon_sprite = None
            return
        self._lane_icon_sprite, self._lane_icon_list = self._icon_from_tex(tex)

    def set_place_icon(self, tex: arcade.Texture | None) -> None:
        """Use the green iso place_zone tile as the new-place button icon."""
        if tex is None:
            self._place_icon_list = None
            self._place_icon_sprite = None
            return
        self._place_icon_sprite, self._place_icon_list = self._icon_from_tex(tex)

    def _button_rects(self) -> list[tuple[float, float, float, float, str]]:
        """Return list of (left, bottom, width, height, action) for each button."""
        pad = (self.width - self._button_size) / 2
        bx = self.left + pad
        top_btn_bottom = self.bottom + self._height - self._button_size - pad
        return [
            (bx, top_btn_bottom, self._button_size, self._button_size, "new_intersection"),
            (bx, top_btn_bottom - self._button_size - self._gap, self._button_size, self._button_size, "new_place"),
            (bx, top_btn_bottom - 2 * (self._button_size + self._gap), self._button_size, self._button_size, "new_lane"),
            (bx, self.bottom + pad, self._button_size, self._button_size, "settings"),
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
            fill = (95, 95, 110) if action == self.active_action else (70, 70, 80)
            border = (160, 160, 180) if action == self.active_action else (100, 100, 110)
            rect_filled(l, b, w, h, fill)
            rect_outline(l, b, w, h, border, 1)
            cx = l + w / 2
            cy = b + h / 2
            if action == "settings":
                self._settings_icon.x, self._settings_icon.y = cx, cy
                self._settings_icon.draw()
            elif action == "new_intersection":
                self._inter_icon.x, self._inter_icon.y = cx, cy
                self._inter_icon.draw()
            elif action == "new_lane":
                if self._lane_icon_sprite is not None and self._lane_icon_list is not None:
                    self._lane_icon_sprite.center_x = cx
                    self._lane_icon_sprite.center_y = cy
                    self._lane_icon_list.draw(pixelated=True)
                else:
                    self._lane_fallback.x, self._lane_fallback.y = cx, cy
                    self._lane_fallback.draw()
            elif action == "new_place":
                if self._place_icon_sprite is not None and self._place_icon_list is not None:
                    self._place_icon_sprite.center_x = cx
                    self._place_icon_sprite.center_y = cy
                    self._place_icon_list.draw(pixelated=True)
                else:
                    self._place_fallback.x, self._place_fallback.y = cx, cy
                    self._place_fallback.draw()
            else:
                self._place_fallback.x, self._place_fallback.y = cx, cy
                self._place_fallback.draw()
