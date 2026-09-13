"""Option selector dropdown."""
from __future__ import annotations

from typing import Callable

import arcade

from draw_compat import rect_filled, rect_outline
from ui.theme import DROPDOWN_ROW_HEIGHT, LABEL_COLOR, MUTED_COLOR


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
            "", 0, 0, color=LABEL_COLOR, font_size=10,
            anchor_x="left", anchor_y="center",
        )
        self._arrow = arcade.Text(
            "▼", 0, 0, color=MUTED_COLOR, font_size=9, anchor_x="center", anchor_y="center"
        )
        self._option_texts: list[arcade.Text] = []
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
        self._arrow.x = left + width - 12
        self._arrow.y = bottom + height / 2
        self._arrow.draw()

    def _ensure_option_texts(self) -> None:
        key = tuple(self.options)
        if key == self._option_texts_key:
            return
        self._option_texts_key = key
        self._option_texts = [
            arcade.Text(opt, 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
            for opt in self.options
        ]

    def draw_expanded_list(self) -> None:
        """Draw open option rows on top of sibling widgets; Dialog calls this after all widget.draw()."""
        if not self._open or not self.options:
            return
        self._ensure_option_texts()
        left, bottom, width, height = self.rect
        list_top = bottom + height
        for i, opt in enumerate(self.options):
            row_bottom = list_top - (i + 1) * DROPDOWN_ROW_HEIGHT
            rect_filled(left, row_bottom, width, DROPDOWN_ROW_HEIGHT, (55, 55, 65))
            rect_outline(left, row_bottom, width, DROPDOWN_ROW_HEIGHT, (80, 80, 95), 1)
            if i == self.value:
                rect_filled(left + 1, row_bottom + 1, width - 2, DROPDOWN_ROW_HEIGHT - 2, (90, 90, 110))
            item_text = self._option_texts[i]
            item_text.value = opt
            item_text.x = left + 6
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
