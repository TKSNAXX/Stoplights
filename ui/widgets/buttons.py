"""Simple labelled buttons."""
from __future__ import annotations

from typing import Callable

import arcade

from draw_compat import rect_filled, rect_outline
from ui.theme import LABEL_COLOR


class CommitButton:
    """Simple clickable Commit button. Rect (left, bottom, width, height)."""

    def __init__(self, left: float, bottom: float, width: float, height: float, on_click: Callable[[], None] | None = None):
        self.rect = (left, bottom, width, height)
        self._on_click = on_click
        self._text = arcade.Text("Commit", 0, 0, color=LABEL_COLOR, font_size=11, anchor_x="center", anchor_y="center")

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
        self._text = arcade.Text("Remove", 0, 0, color=LABEL_COLOR, font_size=11, anchor_x="center", anchor_y="center")

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


class ShuffleButton:
    """Neutral Shuffle button for re-seeding place buildings."""

    def __init__(self, left: float, bottom: float, width: float, height: float, on_click: Callable[[], None] | None = None):
        self.rect = (left, bottom, width, height)
        self._on_click = on_click
        self._text = arcade.Text("Shuffle", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="center", anchor_y="center")

    def contains(self, x: float, y: float) -> bool:
        left, bottom, width, height = self.rect
        return left <= x <= left + width and bottom <= y <= bottom + height

    def draw(self) -> None:
        left, bottom, width, height = self.rect
        rect_filled(left, bottom, width, height, (90, 90, 100))
        rect_outline(left, bottom, width, height, (120, 120, 130), 1)
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
