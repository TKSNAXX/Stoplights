"""Widget protocols. Screen space: x right, y up. Rect is (left, bottom, width, height)."""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Widget(Protocol):
    """Duck-typed control hosted by a dialog."""

    def contains(self, x: float, y: float) -> bool: ...

    def on_press(self, x: float, y: float) -> bool: ...

    def on_drag(self, x: float) -> bool: ...

    def on_release(self) -> bool: ...

    def draw(self) -> None: ...


@runtime_checkable
class FocusableWidget(Protocol):
    """Widget that can receive keyboard focus and key presses."""

    def set_focus(self, focused: bool) -> None: ...

    def on_key_press(self, key: int) -> bool: ...


@runtime_checkable
class ExpandedHitWidget(Protocol):
    """Widget that may capture clicks outside its base rect."""

    def expanded_contains(self, x: float, y: float) -> bool: ...
