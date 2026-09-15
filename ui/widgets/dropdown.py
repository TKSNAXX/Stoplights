"""Option selector dropdown."""
from __future__ import annotations

from typing import Callable

from draw_compat import ipx, rect_filled
from ui.font import ui_text
from ui.theme import (
    DATUM_FILL,
    DATUM_PAD_X,
    DROPDOWN_ROW_HEIGHT,
    FONT_DATUM,
    MUTED_COLOR,
)
from ui.widgets.icons import draw_icon
from ui.widgets.text import draw_datum


class Dropdown:
    """
    Option selector: current value in a datum box; click to expand list.
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
        self._text = ui_text("", size=FONT_DATUM, color=MUTED_COLOR, anchor_x="left", anchor_y="center")
        self._option_texts: list = []
        self._option_texts_key: tuple[str, ...] | None = None

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
        return self.contains(x, y)

    def set_value(self, index: int) -> None:
        idx = max(0, min(index, len(self.options) - 1))
        if idx != self.value:
            self.value = idx
            if self._on_change:
                self._on_change(self.value)

    def draw(self) -> None:
        left, bottom, width, height = self.rect
        left, bottom, width, height = ipx(left), ipx(bottom), ipx(width), ipx(height)
        draw_datum(left, bottom, width, height)
        self._text.value = self.options[self.value] if self.options else "-"
        self._text.x = left + DATUM_PAD_X
        self._text.y = bottom + height / 2
        self._text.draw()
        chev = 12
        draw_icon("down", left + width - chev - 4, bottom + (height - chev) / 2, chev, MUTED_COLOR)

    def _ensure_option_texts(self) -> None:
        key = tuple(self.options)
        if key == self._option_texts_key:
            return
        self._option_texts_key = key
        self._option_texts = [
            ui_text(opt, size=FONT_DATUM, color=MUTED_COLOR, anchor_x="left", anchor_y="center")
            for opt in self.options
        ]

    def draw_expanded_list(self) -> None:
        if not self._open or not self.options:
            return
        self._ensure_option_texts()
        left, bottom, width, height = self.rect
        left, bottom, width, height = ipx(left), ipx(bottom), ipx(width), ipx(height)
        list_top = bottom + height
        for i, opt in enumerate(self.options):
            row_bottom = list_top - (i + 1) * DROPDOWN_ROW_HEIGHT
            fill = (48, 48, 58) if i == self.value else DATUM_FILL
            rect_filled(left, row_bottom, width, DROPDOWN_ROW_HEIGHT, fill)
            item_text = self._option_texts[i]
            item_text.value = opt
            item_text.x = left + DATUM_PAD_X
            item_text.y = row_bottom + DROPDOWN_ROW_HEIGHT / 2
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
