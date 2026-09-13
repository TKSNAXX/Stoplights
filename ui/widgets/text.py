"""TextBox and NumberBox."""
from __future__ import annotations

from typing import Callable

import arcade

from draw_compat import rect_filled, rect_outline
from ui.theme import (
    DIALOG_BORDER,
    NUMBER_BOX_ARROW_SIZE,
    TEXT_BOX_MAX_LEN,
    LABEL_COLOR,
    MUTED_COLOR,
    WIDGET_BORDER,
    WIDGET_FILL,
)


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
            "", 0, 0, color=LABEL_COLOR, font_size=11, anchor_x="left", anchor_y="center"
        )
        self._arrow_up = arcade.Text(
            "▲", 0, 0, color=MUTED_COLOR, font_size=10, anchor_x="center", anchor_y="center"
        )
        self._arrow_dn = arcade.Text(
            "▼", 0, 0, color=MUTED_COLOR, font_size=10, anchor_x="center", anchor_y="center"
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
        if 48 <= key <= 57:
            self._text_buffer += chr(key)
            return True
        if key == 45 and not self._text_buffer:
            self._text_buffer = "-"
            return True
        return False

    def on_drag(self, x: float) -> bool:
        return False

    def on_release(self) -> bool:
        return False

    def draw(self) -> None:
        left, bottom, width, height = self.rect
        box_w = width - NUMBER_BOX_ARROW_SIZE * 2
        rect_filled(left, bottom, box_w, height, WIDGET_FILL)
        rect_outline(left, bottom, box_w, height, DIALOG_BORDER if self._focused else WIDGET_BORDER, 1)
        self._text.value = self._text_buffer if self._focused else str(self.value)
        self._text.x = left + 6
        self._text.y = bottom + height / 2
        self._text.draw()
        ul, ub, uw, uh = self._up_arrow_rect()
        rect_filled(ul, ub, uw, uh, (100, 100, 110))
        rect_outline(ul, ub, uw, uh, DIALOG_BORDER, 1)
        self._arrow_up.x = ul + uw / 2
        self._arrow_up.y = ub + uh / 2
        self._arrow_up.draw()
        dl, db, dw, dh = self._down_arrow_rect()
        rect_filled(dl, db, dw, dh, (100, 100, 110))
        rect_outline(dl, db, dw, dh, DIALOG_BORDER, 1)
        self._arrow_dn.x = dl + dw / 2
        self._arrow_dn.y = db + dh / 2
        self._arrow_dn.draw()


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
            "", 0, 0, color=LABEL_COLOR, font_size=11, anchor_x="left", anchor_y="center"
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
        rect_filled(left, bottom, width, height, WIDGET_FILL)
        rect_outline(left, bottom, width, height, DIALOG_BORDER if self._focused else WIDGET_BORDER, 1)
        self._text.value = self._text_buffer if self._focused else self.value
        self._text.x = left + 6
        self._text.y = bottom + height / 2
        self._text.draw()
