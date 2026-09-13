"""Dialog chrome and z-order manager."""
from __future__ import annotations

from typing import Callable

import arcade

from draw_compat import rect_filled, rect_outline
from ui.theme import (
    DIALOG_BG,
    DIALOG_BORDER,
    DIALOG_TITLE_BG,
    LABEL_COLOR,
    TITLE_BAR_HEIGHT,
    X_BUTTON_SIZE,
)
from ui.widgets.dropdown import Dropdown
from ui.widgets.protocols import ExpandedHitWidget, FocusableWidget


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
        self._title_text = arcade.Text(
            title, 0, 0, color=LABEL_COLOR, font_size=12, anchor_x="left", anchor_y="center",
        )
        self._x_text = arcade.Text(
            "X", 0, 0, color=LABEL_COLOR, font_size=11, anchor_x="center", anchor_y="center",
        )

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
        self._title_text.value = self.title
        self._title_text.x = left + 8
        self._title_text.y = bottom + self.height - TITLE_BAR_HEIGHT / 2 - 4
        self._title_text.draw()
        xl, xb, xw, xh = self._x_button_rect()
        rect_filled(xl, xb, xw, xh, (120, 80, 80))
        self._x_text.x = xl + xw / 2
        self._x_text.y = xb + xh / 2
        self._x_text.draw()
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

    def close_all(self) -> None:
        """Dismiss every open dialog (same cleanup as the X button)."""
        for d in list(self._dialogs):
            d.visible = False
            if d._on_close:
                d._on_close(d)
            elif d in self._dialogs:
                self.close(d)
        self._dialogs.clear()
        self.set_focused_widget(None)

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

    def iter_open(self):
        """Visible dialogs, bottom to top."""
        for d in self._dialogs:
            if d.visible:
                yield d

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
