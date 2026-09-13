"""Place vars and new-place dialogs."""
from __future__ import annotations

from typing import Callable

import arcade

from ui.dialogs.base import Dialog
from ui.theme import (
    DROPDOWN_ROW_HEIGHT,
    LABEL_COLOR,
    NUMBER_BOX_HEIGHT,
    PLACE_ATTRACT_VALUES,
    PLACE_BUILDING_KIND_LABELS,
    PLACE_SPAWN_VALUES,
)
from ui.widgets.buttons import CommitButton, RemoveButton, ShuffleButton
from ui.widgets.compass import CompassSelect
from ui.widgets.dropdown import Dropdown
from ui.widgets.slider import Slider
from ui.widgets.text import NumberBox, TextBox


def next_place_name(places_by_id: dict) -> str:
    """Return Place N where N is the next available index (1, 2, ...)."""
    seen = set()
    for k in places_by_id:
        if k.startswith("Place ") and k != "Place ":
            try:
                seen.add(int(k.split()[1]))
            except (ValueError, IndexError):
                pass
    n = 1
    while n in seen:
        n += 1
    return f"Place {n}"


class NewPlaceDialog(Dialog):
    """Dialog for creating a new place. Commit adds to game and closes."""

    def __init__(
        self,
        x: float,
        y: float,
        game,
        on_commit: Callable[[], None] | None = None,
        on_geometry_change: Callable[[tuple[int, int], int, int], None] | None = None,
    ):
        name = next_place_name(game.places)
        super().__init__(x, y, 220, 202, f"New Place: {name}")
        self._game = game
        self._on_commit = on_commit
        self._on_geometry_change = on_geometry_change

        control_width = 140
        self._name_box = TextBox(0, 0, 140, NUMBER_BOX_HEIGHT, name)
        self._center_compass = CompassSelect(
            0, 0, control_width, DROPDOWN_ROW_HEIGHT, (20, 20), on_change=lambda _: self._notify_geometry(),
        )
        self._w_box = NumberBox(0, 0, 100, NUMBER_BOX_HEIGHT, 5, 1, 16, 1, on_change=lambda _: self._notify_geometry())
        self._l_box = NumberBox(0, 0, 100, NUMBER_BOX_HEIGHT, 5, 1, 16, 1, on_change=lambda _: self._notify_geometry())
        self._commit_btn = CommitButton(0, 0, 70, 22, on_click=self._do_commit)

        self.widgets = [self._name_box, self._center_compass, self._w_box, self._l_box, self._commit_btn]
        self._name_label = arcade.Text("Name:", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._center_label = arcade.Text("Center:", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._w_label = arcade.Text("Width:", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._l_label = arcade.Text("Length:", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")

    def set_geometry(self, center: tuple[int, int], width: int, length: int) -> None:
        """Update readout from the map tool without fighting a focused field."""
        if not self._center_compass._focused:
            self._center_compass.set_value(center)
        if not self._w_box._focused:
            self._w_box.value = width
            self._w_box._text_buffer = str(width)
        if not self._l_box._focused:
            self._l_box.value = length
            self._l_box._text_buffer = str(length)

    def try_name(self) -> str | None:
        """Flush the name box; return a unique name or None if empty/colliding."""
        if self._name_box._focused:
            self._name_box.set_focus(False)
        name = self._name_box.value.strip()
        if not name or name in self._game.places or name in self._game.intersections:
            return None
        return name

    def _notify_geometry(self) -> None:
        if self._on_geometry_change:
            self._on_geometry_change(self._center_compass.value, self._w_box.value, self._l_box.value)

    def _do_commit(self) -> None:
        from sim import places
        from sim.places import PLACE_SIZE_MIN, PLACE_SIZE_MAX
        name = self.try_name()
        if name is None:
            return
        center_x, center_y = self._center_compass.value
        w = max(PLACE_SIZE_MIN, min(PLACE_SIZE_MAX, self._w_box.value))
        l = max(PLACE_SIZE_MIN, min(PLACE_SIZE_MAX, self._l_box.value))
        p = places.Place(
            center_x=center_x,
            center_y=center_y,
            width=w,
            length=l,
            building_kind=places.default_building_kind(name),
        )
        self._game.places[name] = p
        self._game.rebuild_world_from_config()
        if self._on_commit:
            self._on_commit()

    def _layout_widgets(self) -> None:
        left = self.x + 12
        content_top = self.y - 32
        box_w = 100
        control_left = left + 70
        self._name_box.rect = (control_left, content_top - 24, 140, NUMBER_BOX_HEIGHT)
        self._center_compass.rect = (control_left, content_top - 52, 140, DROPDOWN_ROW_HEIGHT)
        self._w_box.rect = (control_left, content_top - 78, box_w, NUMBER_BOX_HEIGHT)
        self._l_box.rect = (control_left, content_top - 104, box_w, NUMBER_BOX_HEIGHT)
        self._commit_btn.rect = (left, content_top - 136, 70, 22)
        self._name_label.x = left
        self._name_label.y = content_top - 12
        self._center_label.x = left
        self._center_label.y = content_top - 40
        self._w_label.x = left
        self._w_label.y = content_top - 66
        self._l_label.x = left
        self._l_label.y = content_top - 92

    def draw(self) -> None:
        self._layout_widgets()
        super().draw()
        self._name_label.draw()
        self._center_label.draw()
        self._w_label.draw()
        self._l_label.draw()

    def on_mouse_press(self, x: float, y: float) -> bool:
        self._layout_widgets()
        return super().on_mouse_press(x, y)


class PlaceVarsDialog(Dialog):
    """Dialog for editing place spawn, attract, and geometry. Changes apply live. Remove for extra places only."""

    def __init__(
        self,
        x: float,
        y: float,
        place: str,
        place_obj,
        game=None,
        on_change: Callable[[], None] | None = None,
        on_commit: Callable[[], None] | None = None,
        on_remove: Callable[[], None] | None = None,
        on_rename: Callable[[str, str], None] | None = None,
    ):
        from sim.places import BUILDING_KIND_VALUES, clamp_building_kind
        can_remove = bool(game is not None and hasattr(game, "can_remove_place") and game.can_remove_place(place))
        super().__init__(x, y, 240, 296 if can_remove else 268, f"Place: {place}")
        self.place = place
        self._place = place_obj
        self._game = game
        self._on_change = on_change
        self._on_commit = on_commit
        self._on_remove = on_remove
        self._on_rename = on_rename
        self._can_remove = can_remove

        spawn_step = self._step_for_spawn(place_obj.spawn_interval)
        attract_step = self._step_for_attract(place_obj.attract_weight)
        self._name_box = TextBox(0, 0, 140, NUMBER_BOX_HEIGHT, place, on_unfocus=self._commit_name)
        self._spawn_slider = Slider(0, 0, 160, 20, 5, spawn_step, (100, 100, 100), (180, 180, 180))
        self._attract_slider = Slider(0, 0, 160, 20, 5, attract_step, (100, 100, 100), (180, 180, 180))

        cx, cy, w, l = place_obj.center_x, place_obj.center_y, place_obj.width, place_obj.length
        control_width = 140
        self._center_compass = CompassSelect(
            0, 0, control_width, DROPDOWN_ROW_HEIGHT, (cx, cy), on_change=lambda _: self._apply_geometry(),
        )
        self._w_box = NumberBox(0, 0, 100, NUMBER_BOX_HEIGHT, w, 1, 16, 1, on_change=lambda _: self._apply_geometry(), on_unfocus=self._apply_geometry)
        self._l_box = NumberBox(0, 0, 100, NUMBER_BOX_HEIGHT, l, 1, 16, 1, on_change=lambda _: self._apply_geometry(), on_unfocus=self._apply_geometry)
        kind = clamp_building_kind(getattr(place_obj, "building_kind", None), place)
        kind_idx = 0 if kind not in BUILDING_KIND_VALUES else BUILDING_KIND_VALUES.index(kind)
        self._kind_dropdown = Dropdown(
            0, 0, 78, DROPDOWN_ROW_HEIGHT,
            list(PLACE_BUILDING_KIND_LABELS),
            initial_index=kind_idx,
            on_change=lambda _: self._apply_kind(),
        )
        self._shuffle_btn = ShuffleButton(0, 0, 56, DROPDOWN_ROW_HEIGHT, on_click=self._do_shuffle)
        self._remove_btn = RemoveButton(0, 0, 70, 22, on_click=self._do_remove)

        self.widgets = [
            self._name_box, self._spawn_slider, self._attract_slider, self._kind_dropdown,
            self._shuffle_btn, self._center_compass, self._w_box, self._l_box,
        ]
        if self._can_remove:
            self.widgets.append(self._remove_btn)
        self._name_label = arcade.Text("Name:", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._spawn_label = arcade.Text("", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._attract_label = arcade.Text("", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._kind_label = arcade.Text("Buildings:", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._center_label = arcade.Text("Center:", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._w_label = arcade.Text("Width:", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._l_label = arcade.Text("Length:", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")

    def _commit_name(self) -> None:
        """Rename this place id on unfocus. Collision or empty keeps the current id."""
        if self._game is None:
            return
        old = self.place
        used = self._game.rename_place(old, self._name_box.value)
        self._name_box.value = used
        self._name_box._text_buffer = used
        if used == old:
            return
        self.place = used
        self.title = f"Place: {used}"
        if self._on_rename:
            self._on_rename(old, used)
        if self._on_change:
            self._on_change()

    def _apply_geometry(self) -> None:
        """Apply geometry from CompassSelect and NumberBoxes, call on_commit."""
        from sim.places import PLACE_SIZE_MIN, PLACE_SIZE_MAX
        center_x, center_y = self._center_compass.value
        w = max(PLACE_SIZE_MIN, min(PLACE_SIZE_MAX, self._w_box.value))
        l = max(PLACE_SIZE_MIN, min(PLACE_SIZE_MAX, self._l_box.value))
        if (
            self._place.center_x == center_x
            and self._place.center_y == center_y
            and self._place.width == w
            and self._place.length == l
        ):
            return
        self._place.center_x = center_x
        self._place.center_y = center_y
        self._place.width = w
        self._place.length = l
        if self._on_commit:
            self._on_commit()

    def _apply_kind(self) -> None:
        from sim.places import BUILDING_KIND_VALUES, clamp_building_kind
        idx = self._kind_dropdown.value
        kind = BUILDING_KIND_VALUES[idx] if 0 <= idx < len(BUILDING_KIND_VALUES) else clamp_building_kind(None, self.place)
        if getattr(self._place, "building_kind", None) == kind:
            return
        self._place.building_kind = kind
        if self._on_commit:
            self._on_commit()
        elif self._on_change:
            self._on_change()

    def _do_shuffle(self) -> None:
        from render.buildings import load_catalog, shuffle_building_seed
        from sim.places import clamp_building_kind
        kind = clamp_building_kind(getattr(self._place, "building_kind", None), self.place)
        current = int(getattr(self._place, "building_seed", 0) or 0)
        defs = load_catalog(persist=False)
        self._place.building_seed = shuffle_building_seed(
            defs, kind, self.place, self._place.width, self._place.length, current,
        )
        if self._on_commit:
            self._on_commit()
        elif self._on_change:
            self._on_change()

    def _do_remove(self) -> None:
        """Remove this place from game and call on_remove."""
        if self._game is not None:
            if self.place in self._game.places:
                del self._game.places[self.place]
            self._game.rebuild_world_from_config()
        if self._on_remove:
            self._on_remove()

    def _step_for_spawn(self, val: float) -> int:
        best = 0
        for i, v in enumerate(PLACE_SPAWN_VALUES):
            if abs(v - val) < abs(PLACE_SPAWN_VALUES[best] - val):
                best = i
        return best

    def _step_for_attract(self, val: float) -> int:
        best = 0
        for i, v in enumerate(PLACE_ATTRACT_VALUES):
            if abs(v - val) < abs(PLACE_ATTRACT_VALUES[best] - val):
                best = i
        return best

    def _layout_widgets(self) -> None:
        left = self.x + 12
        content_top = self.y - 32
        box_w = 100
        control_left = left + 70
        self._name_box.rect = (control_left, content_top - 24, 140, NUMBER_BOX_HEIGHT)
        self._spawn_slider.rect = (left, content_top - 52, 160, 20)
        self._attract_slider.rect = (left, content_top - 80, 160, 20)
        self._kind_dropdown.rect = (control_left, content_top - 106, 78, DROPDOWN_ROW_HEIGHT)
        self._shuffle_btn.rect = (control_left + 84, content_top - 106, 56, DROPDOWN_ROW_HEIGHT)
        self._center_compass.rect = (control_left, content_top - 132, 140, DROPDOWN_ROW_HEIGHT)
        self._w_box.rect = (control_left, content_top - 158, box_w, NUMBER_BOX_HEIGHT)
        self._l_box.rect = (control_left, content_top - 184, box_w, NUMBER_BOX_HEIGHT)
        if self._can_remove:
            self._remove_btn.rect = (left, content_top - 216, 70, 22)
        self._name_label.x = left
        self._name_label.y = content_top - 12
        self._spawn_label.x = left
        self._spawn_label.y = content_top - 40
        self._attract_label.x = left
        self._attract_label.y = content_top - 68
        self._kind_label.x = left
        self._kind_label.y = content_top - 94
        self._center_label.x = left
        self._center_label.y = content_top - 120
        self._w_label.x = left
        self._w_label.y = content_top - 146
        self._l_label.x = left
        self._l_label.y = content_top - 172

    def draw(self) -> None:
        self._layout_widgets()
        self._spawn_label.value = f"Spawn: {PLACE_SPAWN_VALUES[self._spawn_slider.value]:.1f}s"
        self._attract_label.value = f"Attract: {PLACE_ATTRACT_VALUES[self._attract_slider.value]:.1f}x"
        super().draw()
        self._name_label.draw()
        self._spawn_label.draw()
        self._attract_label.draw()
        self._kind_label.draw()
        self._center_label.draw()
        self._w_label.draw()
        self._l_label.draw()

    def on_mouse_press(self, x: float, y: float) -> bool:
        self._layout_widgets()
        result = super().on_mouse_press(x, y)
        self._sync_from_sliders()
        return result

    def on_mouse_drag(self, x: float, y: float, dx: float, dy: float) -> bool:
        result = super().on_mouse_drag(x, y, dx, dy)
        if self._dragging:
            return result
        self._sync_from_sliders()
        return result

    def on_mouse_release(self, x: float, y: float) -> bool:
        result = super().on_mouse_release(x, y)
        self._sync_from_sliders()
        return result

    def _sync_from_sliders(self) -> None:
        spawn = PLACE_SPAWN_VALUES[self._spawn_slider.value]
        attract = PLACE_ATTRACT_VALUES[self._attract_slider.value]
        if self._place.spawn_interval == spawn and self._place.attract_weight == attract:
            return
        self._place.spawn_interval = spawn
        self._place.attract_weight = attract
        if self._on_change:
            self._on_change()
