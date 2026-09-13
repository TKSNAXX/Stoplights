"""Intersection vars and new-intersection dialogs."""
from __future__ import annotations

from typing import Callable

import arcade

from ui.dialogs.base import Dialog
from ui.theme import DROPDOWN_ROW_HEIGHT, LABEL_COLOR, NUMBER_BOX_HEIGHT
from ui.widgets.buttons import CommitButton, RemoveButton
from ui.widgets.compass import CompassSelect
from ui.widgets.text import NumberBox


def next_intersection_key(configs: dict) -> str:
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


class IntersectionVarsDialog(Dialog):
    """Dialog for editing intersection center and size. Overlay type is inferred. Remove for extra intersections only."""

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
        super().__init__(x, y, 220, 140, f"Intersection: {intersection_key}")
        self.intersection_key = intersection_key
        self._config = intersection_config
        self._game = game
        self._on_change = on_change
        self._on_commit = on_commit
        self._on_remove = on_remove
        self._can_remove = bool(game is not None and hasattr(game, "can_remove_intersection") and game.can_remove_intersection(intersection_key))

        cx = getattr(intersection_config, "center_x", 18)
        cy = getattr(intersection_config, "center_y", 24)
        size_val = getattr(intersection_config, "size_cells", 4)

        control_width = 140
        self._center_compass = CompassSelect(
            0, 0, control_width, DROPDOWN_ROW_HEIGHT, (cx, cy), on_change=lambda _: self._apply_config(),
        )
        self._size_box = NumberBox(0, 0, 100, NUMBER_BOX_HEIGHT, size_val, 2, 12, 2, on_change=lambda _: self._apply_config(), on_unfocus=self._apply_config)
        self._remove_btn = RemoveButton(0, 0, 70, 22, on_click=self._do_remove)

        self.widgets = [self._center_compass, self._size_box]
        if self._can_remove:
            self.widgets.append(self._remove_btn)
        self._type_label = arcade.Text("", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._center_label = arcade.Text("Center:", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._size_label = arcade.Text("", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")

    def _inferred_type(self) -> str:
        from sim import world
        from render.intersection_topology import classify_intersection_sides, overlay_type_for_sides

        cells_map = world.get_intersection_cells_map()
        cells = cells_map.get(self.intersection_key, [])
        active, _, _ = classify_intersection_sides(self.intersection_key, cells)
        return overlay_type_for_sides(active)

    def _apply_config(self) -> None:
        """Apply center and size from widgets to config and call on_commit."""
        new_cx, new_cy = self._center_compass.value
        new_size = max(2, min(12, self._size_box.value))
        if new_size % 2 != 0:
            new_size = (new_size // 2) * 2
        if (
            self._config.center_x == new_cx
            and self._config.center_y == new_cy
            and self._config.size_cells == new_size
        ):
            return
        self._config.center_x, self._config.center_y = new_cx, new_cy
        self._config.size_cells = new_size
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
        self._type_label.value = f"Type: {self._inferred_type()}"
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
        if self._dragging:
            return result
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
        on_geometry_change: Callable[[tuple[int, int], int], None] | None = None,
    ):
        key = next_intersection_key(game.intersections)
        super().__init__(x, y, 220, 150, f"New Intersection: {key}")
        self._game = game
        self._key = key
        self._on_commit = on_commit
        self._on_geometry_change = on_geometry_change

        control_width = 140
        self._center_compass = CompassSelect(
            0, 0, control_width, DROPDOWN_ROW_HEIGHT, (36, 48),
            on_change=lambda _: self._notify_geometry(),
        )
        self._size_box = NumberBox(
            0, 0, 100, NUMBER_BOX_HEIGHT, 2, 2, 12, 2,
            on_change=lambda _: self._notify_geometry(),
        )
        self._commit_btn = CommitButton(0, 0, 70, 22, on_click=self._do_commit)

        self.widgets = [self._center_compass, self._size_box, self._commit_btn]
        self._center_label = arcade.Text("Center:", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._size_label = arcade.Text("", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")

    def set_geometry(self, center: tuple[int, int], size: int) -> None:
        """Update readout from the map tool without fighting a focused field."""
        if not self._center_compass._focused:
            self._center_compass.set_value(center)
        if not self._size_box._focused:
            self._size_box.value = size
            self._size_box._text_buffer = str(size)

    def _notify_geometry(self) -> None:
        if self._on_geometry_change:
            size = max(2, min(12, self._size_box.value))
            if size % 2 != 0:
                size = (size // 2) * 2
            if size < 2:
                size = 2
            self._on_geometry_change(self._center_compass.value, size)

    def _do_commit(self) -> None:
        from sim import places
        center_x, center_y = self._center_compass.value
        cfg = places.IntersectionConfig(
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
        self._center_compass.rect = (control_left, content_top - 24, 140, DROPDOWN_ROW_HEIGHT)
        self._size_box.rect = (control_left, content_top - 50, box_w, NUMBER_BOX_HEIGHT)
        self._commit_btn.rect = (left, content_top - 82, 70, 22)
        self._center_label.x = left
        self._center_label.y = content_top - 12
        self._size_label.x = left
        self._size_label.y = content_top - 38

    def draw(self) -> None:
        self._layout_widgets()
        self._size_label.value = "Size:"
        super().draw()
        self._center_label.draw()
        self._size_label.draw()

    def on_mouse_press(self, x: float, y: float) -> bool:
        self._layout_widgets()
        return super().on_mouse_press(x, y)
