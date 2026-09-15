"""Intersection vars and new-intersection dialogs."""
from __future__ import annotations

from typing import Callable

from ui.dialogs.base import Dialog
from ui.dialogs.layout import ParamLabel, dialog_height, form_row
from ui.theme import DATUM_HEIGHT, DIALOG_WIDTH, DROPDOWN_ROW_HEIGHT, ICON_BUTTON_SIZE
from ui.widgets.buttons import CommitButton, RemoveButton
from ui.widgets.compass import CompassSelect
from ui.widgets.text import DatumBox, NumberBox


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
        self._can_remove = bool(
            game is not None and hasattr(game, "can_remove_intersection") and game.can_remove_intersection(intersection_key)
        )
        super().__init__(
            x, y, DIALOG_WIDTH, dialog_height(4 if self._can_remove else 3),
            intersection_key, kind="Intersection",
        )
        self.intersection_key = intersection_key
        self._config = intersection_config
        self._game = game
        self._on_change = on_change
        self._on_commit = on_commit
        self._on_remove = on_remove

        cx = getattr(intersection_config, "center_x", 18)
        cy = getattr(intersection_config, "center_y", 24)
        size_val = getattr(intersection_config, "size_cells", 4)

        self._type_datum = DatumBox()
        self._center_compass = CompassSelect(
            0, 0, 140, DROPDOWN_ROW_HEIGHT, (cx, cy), on_change=lambda _: self._apply_config(),
        )
        self._size_box = NumberBox(
            0, 0, 100, DATUM_HEIGHT, size_val, 2, 12, 2,
            on_change=lambda _: self._apply_config(), on_unfocus=self._apply_config,
        )
        self._remove_btn = RemoveButton(0, 0, on_click=self._do_remove)

        self.widgets = [self._center_compass, self._size_box]
        if self._can_remove:
            self.widgets.append(self._remove_btn)
        self._type_label = ParamLabel("Type")
        self._center_label = ParamLabel("Center")
        self._size_label = ParamLabel("Size")
        self.labels = [self._type_label, self._center_label, self._size_label]

    def _inferred_type(self) -> str:
        from sim import world
        from render.intersection_topology import classify_intersection_sides, overlay_type_for_sides

        cells_map = world.get_intersection_cells_map()
        cells = cells_map.get(self.intersection_key, [])
        active, _, _ = classify_intersection_sides(self.intersection_key, cells)
        raw = overlay_type_for_sides(active)
        return (raw or "none").replace("_", " ").title()

    def _apply_config(self) -> None:
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
        if self._game is not None and self.intersection_key in self._game.intersections:
            del self._game.intersections[self.intersection_key]
            self._game.rebuild_world_from_config()
        if self._on_remove:
            self._on_remove()

    def _layout_widgets(self) -> None:
        r0 = form_row(self, 0)
        self._type_label.place(r0.label_x, r0.label_y)
        self._type_datum.rect = (r0.control_left, r0.control_bottom, r0.control_width, DATUM_HEIGHT)
        r1 = form_row(self, 1)
        self._center_label.place(r1.label_x, r1.label_y)
        self._center_compass.rect = (r1.control_left, r1.control_bottom, r1.control_width, DATUM_HEIGHT)
        r2 = form_row(self, 2)
        self._size_label.place(r2.label_x, r2.label_y)
        self._size_box.rect = (r2.control_left, r2.control_bottom, r2.control_width, DATUM_HEIGHT)
        if self._can_remove:
            r3 = form_row(self, 3)
            self._remove_btn.rect = (r3.control_left, r3.control_bottom, ICON_BUTTON_SIZE, ICON_BUTTON_SIZE)

    def draw(self) -> None:
        self._type_datum.set_value(self._inferred_type())
        super().draw()
        self._type_datum.draw()

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
        super().__init__(x, y, DIALOG_WIDTH, dialog_height(3), key, kind="Intersection")
        self._game = game
        self._key = key
        self._on_commit = on_commit
        self._on_geometry_change = on_geometry_change

        self._center_compass = CompassSelect(
            0, 0, 140, DROPDOWN_ROW_HEIGHT, (36, 48),
            on_change=lambda _: self._notify_geometry(),
        )
        self._size_box = NumberBox(
            0, 0, 100, DATUM_HEIGHT, 2, 2, 12, 2,
            on_change=lambda _: self._notify_geometry(),
        )
        self._commit_btn = CommitButton(0, 0, on_click=self._do_commit)

        self.widgets = [self._center_compass, self._size_box, self._commit_btn]
        self._center_label = ParamLabel("Center")
        self._size_label = ParamLabel("Size")
        self.labels = [self._center_label, self._size_label]

    def set_geometry(self, center: tuple[int, int], size: int) -> None:
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
        r0 = form_row(self, 0)
        self._center_label.place(r0.label_x, r0.label_y)
        self._center_compass.rect = (r0.control_left, r0.control_bottom, r0.control_width, DATUM_HEIGHT)
        r1 = form_row(self, 1)
        self._size_label.place(r1.label_x, r1.label_y)
        self._size_box.rect = (r1.control_left, r1.control_bottom, r1.control_width, DATUM_HEIGHT)
        r2 = form_row(self, 2)
        self._commit_btn.rect = (r2.control_left, r2.control_bottom, ICON_BUTTON_SIZE, ICON_BUTTON_SIZE)
