"""Place vars and new-place dialogs."""
from __future__ import annotations

from typing import Callable

from ui.dialogs.base import Dialog
from ui.dialogs.layout import ParamLabel, dialog_height, form_row
from ui.theme import (
    DATUM_HEIGHT,
    DATUM_WIDTH,
    DIALOG_WIDTH,
    DROPDOWN_ROW_HEIGHT,
    FORM_GAP,
    ICON_BUTTON_GAP,
    ICON_BUTTON_SIZE,
    PLACE_ATTRACT_VALUES,
    PLACE_BUILDING_KIND_LABELS,
    PLACE_SPAWN_VALUES,
    SLIDER_ATTRACT,
    SLIDER_SPAWN,
    SLIDER_TRACK,
)
from ui.widgets.buttons import CommitButton, RemoveButton, ShuffleButton
from ui.widgets.compass import CompassSelect
from ui.widgets.dropdown import Dropdown
from ui.widgets.slider import Slider
from ui.widgets.text import DatumBox, NumberBox


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
        super().__init__(x, y, DIALOG_WIDTH, dialog_height(4), name, kind="Place", title_editable=True)
        self._game = game
        self._on_commit = on_commit
        self._on_geometry_change = on_geometry_change

        self._center_compass = CompassSelect(
            0, 0, 220, DROPDOWN_ROW_HEIGHT, (20, 20), on_change=lambda _: self._notify_geometry(),
        )
        self._w_box = NumberBox(0, 0, 100, DATUM_HEIGHT, 5, 1, 16, 1, on_change=lambda _: self._notify_geometry())
        self._l_box = NumberBox(0, 0, 100, DATUM_HEIGHT, 5, 1, 16, 1, on_change=lambda _: self._notify_geometry())
        self._commit_btn = CommitButton(0, 0, on_click=self._do_commit)

        self.widgets = [self._center_compass, self._w_box, self._l_box, self._commit_btn]
        self._center_label = ParamLabel("Center")
        self._w_label = ParamLabel("Width")
        self._l_label = ParamLabel("Length")
        self.labels = [self._center_label, self._w_label, self._l_label]

    def set_geometry(self, center: tuple[int, int], width: int, length: int) -> None:
        if not self._center_compass._focused:
            self._center_compass.set_value(center)
        if not self._w_box._focused:
            self._w_box.value = width
            self._w_box._text_buffer = str(width)
        if not self._l_box._focused:
            self._l_box.value = length
            self._l_box._text_buffer = str(length)

    def try_name(self) -> str | None:
        box = self._title_box
        if box is not None and box._focused:
            box.set_focus(False)
        name = (box.value.strip() if box is not None else self.title.strip())
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
        r0 = form_row(self, 0)
        self._center_label.place(r0.label_x, r0.label_y)
        self._center_compass.rect = (r0.control_left, r0.control_bottom, r0.control_width, DATUM_HEIGHT)
        r1 = form_row(self, 1)
        self._w_label.place(r1.label_x, r1.label_y)
        self._w_box.rect = (r1.control_left, r1.control_bottom, r1.control_width, DATUM_HEIGHT)
        r2 = form_row(self, 2)
        self._l_label.place(r2.label_x, r2.label_y)
        self._l_box.rect = (r2.control_left, r2.control_bottom, r2.control_width, DATUM_HEIGHT)
        r3 = form_row(self, 3)
        self._commit_btn.rect = (r3.control_left, r3.control_bottom, ICON_BUTTON_SIZE, ICON_BUTTON_SIZE)


class PlaceVarsDialog(Dialog):
    """Dialog for editing place spawn, attract, and geometry. Changes apply live."""

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
        super().__init__(
            x, y, DIALOG_WIDTH, dialog_height(7), place,
            kind="Place", title_editable=True,
        )
        self.place = place
        self._place = place_obj
        self._game = game
        self._on_change = on_change
        self._on_commit = on_commit
        self._on_remove = on_remove
        self._on_rename = on_rename
        self._can_remove = can_remove
        if self._title_box is not None:
            self._title_box.set_on_unfocus(self._commit_name)

        spawn_step = self._step_for_spawn(place_obj.spawn_interval)
        attract_step = self._step_for_attract(place_obj.attract_weight)
        self._spawn_slider = Slider(0, 0, 160, DATUM_HEIGHT, 5, spawn_step, SLIDER_TRACK, SLIDER_SPAWN)
        self._attract_slider = Slider(0, 0, 160, DATUM_HEIGHT, 5, attract_step, SLIDER_TRACK, SLIDER_ATTRACT)
        self._spawn_datum = DatumBox()
        self._attract_datum = DatumBox()

        cx, cy, w, l = place_obj.center_x, place_obj.center_y, place_obj.width, place_obj.length
        self._center_compass = CompassSelect(
            0, 0, 220, DROPDOWN_ROW_HEIGHT, (cx, cy), on_change=lambda _: self._apply_geometry(),
        )
        self._w_box = NumberBox(0, 0, 100, DATUM_HEIGHT, w, 1, 16, 1, on_change=lambda _: self._apply_geometry(), on_unfocus=self._apply_geometry)
        self._l_box = NumberBox(0, 0, 100, DATUM_HEIGHT, l, 1, 16, 1, on_change=lambda _: self._apply_geometry(), on_unfocus=self._apply_geometry)
        kind = clamp_building_kind(getattr(place_obj, "building_kind", None), place)
        kind_idx = 0 if kind not in BUILDING_KIND_VALUES else BUILDING_KIND_VALUES.index(kind)
        self._kind_dropdown = Dropdown(
            0, 0, 78, DROPDOWN_ROW_HEIGHT,
            list(PLACE_BUILDING_KIND_LABELS),
            initial_index=kind_idx,
            on_change=lambda _: self._apply_kind(),
        )
        self._shuffle_btn = ShuffleButton(0, 0, on_click=self._do_shuffle)
        self._remove_btn = RemoveButton(0, 0, on_click=self._do_remove)
        self._remove_btn.enabled = can_remove

        self.widgets = [
            self._spawn_slider, self._attract_slider, self._kind_dropdown,
            self._shuffle_btn, self._center_compass, self._w_box, self._l_box,
            self._remove_btn,
        ]
        self._spawn_label = ParamLabel("Spawn")
        self._attract_label = ParamLabel("Attract")
        self._kind_label = ParamLabel("Buildings")
        self._center_label = ParamLabel("Center")
        self._w_label = ParamLabel("Width")
        self._l_label = ParamLabel("Length")
        self.labels = [
            self._spawn_label, self._attract_label, self._kind_label,
            self._center_label, self._w_label, self._l_label,
        ]

    def _commit_name(self) -> None:
        if self._game is None or self._title_box is None:
            return
        old = self.place
        used = self._game.rename_place(old, self._title_box.value)
        self._title_box.value = used
        self._title_box._text_buffer = used
        if used == old:
            return
        self.place = used
        self.title = used
        if self._on_rename:
            self._on_rename(old, used)
        if self._on_change:
            self._on_change()

    def _apply_geometry(self) -> None:
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
        if self._game is None or not self._can_remove:
            return
        self._game.delete_place(self.place)
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

    def _place_slider_row(self, index: int, label: ParamLabel, datum: DatumBox, slider: Slider) -> None:
        row = form_row(self, index)
        label.place(row.label_x, row.label_y)
        datum.rect = (row.control_left, row.control_bottom, DATUM_WIDTH, DATUM_HEIGHT)
        sl = row.control_left + DATUM_WIDTH + FORM_GAP
        sw = max(24, row.control_width - DATUM_WIDTH - FORM_GAP)
        slider.rect = (sl, row.control_bottom, sw, DATUM_HEIGHT)

    def _layout_widgets(self) -> None:
        self._place_slider_row(0, self._spawn_label, self._spawn_datum, self._spawn_slider)
        self._place_slider_row(1, self._attract_label, self._attract_datum, self._attract_slider)
        r2 = form_row(self, 2)
        self._kind_label.place(r2.label_x, r2.label_y)
        dd_w = max(48, r2.control_width - ICON_BUTTON_SIZE - ICON_BUTTON_GAP)
        self._kind_dropdown.rect = (r2.control_left, r2.control_bottom, dd_w, DATUM_HEIGHT)
        self._shuffle_btn.rect = (
            r2.control_left + dd_w + ICON_BUTTON_GAP, r2.control_bottom, ICON_BUTTON_SIZE, ICON_BUTTON_SIZE,
        )
        r3 = form_row(self, 3)
        self._center_label.place(r3.label_x, r3.label_y)
        self._center_compass.rect = (r3.control_left, r3.control_bottom, r3.control_width, DATUM_HEIGHT)
        r4 = form_row(self, 4)
        self._w_label.place(r4.label_x, r4.label_y)
        self._w_box.rect = (r4.control_left, r4.control_bottom, r4.control_width, DATUM_HEIGHT)
        r5 = form_row(self, 5)
        self._l_label.place(r5.label_x, r5.label_y)
        self._l_box.rect = (r5.control_left, r5.control_bottom, r5.control_width, DATUM_HEIGHT)
        r6 = form_row(self, 6)
        self._remove_btn.rect = (r6.control_left, r6.control_bottom, ICON_BUTTON_SIZE, ICON_BUTTON_SIZE)

    def draw(self) -> None:
        self._spawn_datum.set_value(f"{PLACE_SPAWN_VALUES[self._spawn_slider.value]:.1f}s")
        self._attract_datum.set_value(f"{PLACE_ATTRACT_VALUES[self._attract_slider.value]:.1f}x")
        super().draw()
        self._spawn_datum.draw()
        self._attract_datum.draw()

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
