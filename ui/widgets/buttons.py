"""White square icon buttons."""
from __future__ import annotations

from typing import Callable

from draw_compat import ipx, rect_filled
from ui.theme import (
    ICON_BUTTON_BG,
    ICON_BUTTON_DISABLED_BG,
    ICON_BUTTON_DISABLED_FG,
    ICON_BUTTON_FG,
    ICON_BUTTON_SIZE,
)
from ui.widgets.icons import draw_icon


class IconButton:
    """White square, dark-grey icon. Rect (left, bottom, width, height); drawn as a square."""

    def __init__(
        self,
        left: float,
        bottom: float,
        width: float = ICON_BUTTON_SIZE,
        height: float = ICON_BUTTON_SIZE,
        *,
        kind: str,
        on_click: Callable[[], None] | None = None,
        enabled: bool = True,
    ):
        self.rect = (left, bottom, width, height)
        self.kind = kind
        self._on_click = on_click
        self.enabled = enabled

    def contains(self, x: float, y: float) -> bool:
        left, bottom, width, height = self.rect
        s = min(width, height)
        return left <= x <= left + s and bottom <= y <= bottom + s

    def draw(self) -> None:
        left, bottom, width, height = self.rect
        s = ipx(min(width, height))
        left, bottom = ipx(left), ipx(bottom)
        bg = ICON_BUTTON_BG if self.enabled else ICON_BUTTON_DISABLED_BG
        fg = ICON_BUTTON_FG if self.enabled else ICON_BUTTON_DISABLED_FG
        rect_filled(left, bottom, s, s, bg)
        draw_icon(self.kind, left, bottom, s, fg)

    def on_press(self, x: float, y: float) -> bool:
        if not self.contains(x, y):
            return False
        if self.enabled and self._on_click:
            self._on_click()
        return True

    def on_drag(self, x: float) -> bool:
        return False

    def on_release(self) -> bool:
        return False


class CommitButton(IconButton):
    def __init__(self, left: float, bottom: float, width: float = ICON_BUTTON_SIZE, height: float = ICON_BUTTON_SIZE, on_click: Callable[[], None] | None = None):
        super().__init__(left, bottom, width, height, kind="commit", on_click=on_click)


class RemoveButton(IconButton):
    def __init__(self, left: float, bottom: float, width: float = ICON_BUTTON_SIZE, height: float = ICON_BUTTON_SIZE, on_click: Callable[[], None] | None = None):
        super().__init__(left, bottom, width, height, kind="remove", on_click=on_click)


class ShuffleButton(IconButton):
    def __init__(self, left: float, bottom: float, width: float = ICON_BUTTON_SIZE, height: float = ICON_BUTTON_SIZE, on_click: Callable[[], None] | None = None):
        super().__init__(left, bottom, width, height, kind="shuffle", on_click=on_click)
