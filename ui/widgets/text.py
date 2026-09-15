"""TextBox, NumberBox, and read-only DatumBox."""
from __future__ import annotations

from typing import Callable

import arcade

from draw_compat import ipx, rect_filled
from ui.font import ui_text
from ui.theme import (
    DATUM_FILL,
    DATUM_HEIGHT,
    DATUM_PAD_X,
    DATUM_WIDTH,
    FONT_DATUM,
    ICON_BUTTON_BG,
    ICON_BUTTON_FG,
    ICON_BUTTON_GAP,
    ICON_BUTTON_SIZE,
    LABEL_COLOR,
    TEXT_BOX_MAX_LEN,
)
from ui.widgets.icons import draw_icon


def draw_datum(left: float, bottom: float, width: float, height: float) -> None:
    rect_filled(ipx(left), ipx(bottom), ipx(width), ipx(height), DATUM_FILL)


class DatumBox:
    """Read-only dark square datum. Optional wrap for long values."""

    def __init__(self, left: float = 0, bottom: float = 0, width: float = DATUM_WIDTH, height: float = DATUM_HEIGHT, value: str = "", wrap: bool = False):
        self.rect = (left, bottom, width, height)
        self.value = value
        self.wrap = wrap
        self.color = LABEL_COLOR
        kwargs = dict(anchor_x="left", anchor_y="center", color=LABEL_COLOR)
        if wrap:
            kwargs["multiline"] = True
            kwargs["width"] = max(8, ipx(width) - DATUM_PAD_X * 2)
            kwargs["anchor_y"] = "top"
        self._text = ui_text(value, size=FONT_DATUM, **kwargs)

    def set_value(self, value: str) -> None:
        self.value = value

    def draw(self) -> None:
        left, bottom, width, height = self.rect
        left, bottom, width, height = ipx(left), ipx(bottom), ipx(width), ipx(height)
        draw_datum(left, bottom, width, height)
        self._text.color = self.color
        self._text.value = self.value
        if self.wrap:
            self._text.width = max(8, width - DATUM_PAD_X * 2)
            self._text.x = left + DATUM_PAD_X
            self._text.y = bottom + height - 4
        else:
            self._text.x = left + DATUM_PAD_X
            self._text.y = bottom + height / 2
        self._text.draw()


class NumberBox:
    """Integer input: dark datum plus two white stepper squares to the right."""

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
        datum_width: float = DATUM_WIDTH,
    ):
        self.rect = (left, bottom, width, height)
        self.value = max(min_val, min(max_val, value))
        self.min_val = min_val
        self.max_val = max_val
        self.step = step
        self.datum_width = datum_width
        self._on_change = on_change
        self._on_unfocus = on_unfocus
        self._focused = False
        self._text_buffer = str(self.value)
        self._text = ui_text("", size=FONT_DATUM, color=LABEL_COLOR, anchor_x="left", anchor_y="center")

    def contains(self, x: float, y: float) -> bool:
        left, bottom, width, height = self.rect
        total_w = self.datum_width + ICON_BUTTON_GAP + ICON_BUTTON_SIZE * 2 + ICON_BUTTON_GAP
        return left <= x <= left + min(width, total_w) and bottom <= y <= bottom + height

    def _box_rect(self) -> tuple[float, float, float, float]:
        left, bottom, _, height = self.rect
        return (left, bottom, self.datum_width, height)

    def _up_arrow_rect(self) -> tuple[float, float, float, float]:
        left, bottom, _, height = self.rect
        x = left + self.datum_width + ICON_BUTTON_GAP
        y = bottom + (height - ICON_BUTTON_SIZE) / 2
        return (x, y, ICON_BUTTON_SIZE, ICON_BUTTON_SIZE)

    def _down_arrow_rect(self) -> tuple[float, float, float, float]:
        left, bottom, _, height = self.rect
        x = left + self.datum_width + ICON_BUTTON_GAP + ICON_BUTTON_SIZE + ICON_BUTTON_GAP
        y = bottom + (height - ICON_BUTTON_SIZE) / 2
        return (x, y, ICON_BUTTON_SIZE, ICON_BUTTON_SIZE)

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
        bl, bb, bw, bh = self._box_rect()
        draw_datum(bl, bb, bw, bh)
        self._text.value = self._text_buffer if self._focused else str(self.value)
        self._text.x = ipx(bl) + DATUM_PAD_X
        self._text.y = ipx(bb + bh / 2)
        self._text.draw()
        for rect, kind in ((self._up_arrow_rect(), "up"), (self._down_arrow_rect(), "down")):
            l, b, w, h = rect
            s = ipx(min(w, h))
            l, b = ipx(l), ipx(b)
            rect_filled(l, b, s, s, ICON_BUTTON_BG)
            draw_icon(kind, l, b, s, ICON_BUTTON_FG)


def _text_box_char_ok(ch: str) -> bool:
    return ch.isalnum() or ch in " -"


class TextBox:
    """Text field. chrome=True draws a dark datum; False is borderless (header title)."""

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
        chrome: bool = True,
        font_size: int = FONT_DATUM,
        align: str = "left",
    ):
        self.rect = (left, bottom, width, height)
        self.value = value
        self.max_len = max_len
        self.chrome = chrome
        self._align = align
        self._on_change = on_change
        self._on_unfocus = on_unfocus
        self._focused = False
        self._text_buffer = value
        self._text = ui_text(
            "",
            size=font_size,
            color=LABEL_COLOR,
            anchor_x="center" if align == "center" else "left",
            anchor_y="center",
        )

    def set_on_unfocus(self, cb: Callable[[], None] | None) -> None:
        self._on_unfocus = cb

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
        left, bottom, width, height = ipx(left), ipx(bottom), ipx(width), ipx(height)
        if self.chrome:
            draw_datum(left, bottom, width, height)
        display = self._text_buffer if self._focused else self.value
        self._text.value = display
        if self._align == "center":
            self._text.x = left + width / 2
        else:
            self._text.x = left + DATUM_PAD_X
        self._text.y = bottom + height / 2
        self._text.draw()
        if self._focused:
            tw = float(getattr(self._text, "content_width", 0) or 0)
            if self._align == "center":
                cx = left + width / 2 + tw / 2 + 2
            else:
                cx = left + DATUM_PAD_X + tw + 2
            rect_filled(cx, bottom + 4, 1, height - 8, LABEL_COLOR)
