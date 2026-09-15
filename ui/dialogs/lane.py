"""Lane vars and add-lane dialogs."""
from __future__ import annotations

from typing import Callable

from sim import world
from ui.dialogs.base import Dialog
from ui.dialogs.layout import ParamLabel, dialog_height, form_row
from ui.theme import (
    DATUM_HEIGHT,
    DATUM_WIDTH,
    DIALOG_WIDTH,
    DROPDOWN_ROW_HEIGHT,
    FORM_GAP,
    ICON_BUTTON_SIZE,
    LABEL_COLOR,
    LANE_SPEED_VALUES,
    LANE_TYPE_LABELS,
    LANE_TYPE_VALUES,
    SLIDER_THUMB,
    SLIDER_TRACK,
    WARNING_COLOR,
)
from ui.widgets.buttons import CommitButton, RemoveButton
from ui.widgets.compass import CompassSelect
from ui.widgets.slider import Slider
from ui.widgets.text import DatumBox


class AddLaneDialog(Dialog):
    """Dialog for adding a new lane. Start/End tiles via CompassSelect, Commit creates the lane."""

    def __init__(
        self,
        x: float,
        y: float,
        game,
        on_commit: Callable[[], None] | None = None,
        on_tiles_change: Callable[[tuple[int, int], tuple[int, int]], None] | None = None,
    ):
        super().__init__(x, y, DIALOG_WIDTH, dialog_height(4), "New", kind="Lane")
        self._game = game
        self._on_commit = on_commit
        self._start_tile = (0, 0)
        self._end_tile = (1, 0)
        self._start_compass = CompassSelect(
            0, 0, 220, DROPDOWN_ROW_HEIGHT, self._start_tile,
            on_change=self._on_start_change,
        )
        self._end_compass = CompassSelect(
            0, 0, 220, DROPDOWN_ROW_HEIGHT, self._end_tile,
            on_change=self._on_end_change,
        )
        self._commit_btn = CommitButton(0, 0, on_click=self._do_commit)
        self._dir_datum = DatumBox()
        self.widgets = [self._start_compass, self._end_compass, self._commit_btn]
        self._start_label = ParamLabel("Start")
        self._end_label = ParamLabel("End")
        self._dir_label = ParamLabel("Direction")
        self.labels = [self._start_label, self._end_label, self._dir_label]
        self._on_tiles_change = on_tiles_change

    def set_tiles(self, start: tuple[int, int], end: tuple[int, int]) -> None:
        self._start_tile = start
        self._end_tile = end
        if not self._start_compass._focused:
            self._start_compass.set_value(start)
        if not self._end_compass._focused:
            self._end_compass.set_value(end)

    def _notify_tiles(self) -> None:
        if self._on_tiles_change:
            self._on_tiles_change(self._start_compass.value, self._end_compass.value)

    def _is_valid_lane(self) -> bool:
        start = self._start_compass.value
        end = self._end_compass.value
        return start[0] == end[0] or start[1] == end[1]

    def _direction_text(self) -> str:
        if not self._is_valid_lane():
            return "Invalid End Tile"
        start = self._start_compass.value
        end = self._end_compass.value
        if start[0] == end[0]:
            return "Northbound" if end[1] > start[1] else "Southbound"
        return "Eastbound" if end[0] > start[0] else "Westbound"

    def _on_start_change(self, new_start: tuple[int, int]) -> None:
        self._start_tile = new_start
        self._notify_tiles()

    def _on_end_change(self, new_end: tuple[int, int]) -> None:
        self._end_tile = new_end
        self._notify_tiles()

    def _do_commit(self) -> None:
        if not self._is_valid_lane():
            return
        from sim.places import LaneConfig
        idx = self._game.next_lane_index()
        start = self._start_compass.value
        end = self._end_compass.value
        self._game.lanes[idx] = LaneConfig(start_tile=start, end_tile=end)
        self._game.rebuild_world_from_config()
        if self._on_commit:
            self._on_commit()

    def _layout_widgets(self) -> None:
        r0 = form_row(self, 0)
        self._start_label.place(r0.label_x, r0.label_y)
        self._start_compass.rect = (r0.control_left, r0.control_bottom, r0.control_width, DATUM_HEIGHT)
        r1 = form_row(self, 1)
        self._end_label.place(r1.label_x, r1.label_y)
        self._end_compass.rect = (r1.control_left, r1.control_bottom, r1.control_width, DATUM_HEIGHT)
        r2 = form_row(self, 2)
        self._dir_label.place(r2.label_x, r2.label_y)
        self._dir_datum.rect = (r2.control_left, r2.control_bottom, r2.control_width, DATUM_HEIGHT)
        r3 = form_row(self, 3)
        self._commit_btn.rect = (r3.control_left, r3.control_bottom, ICON_BUTTON_SIZE, ICON_BUTTON_SIZE)

    def draw(self) -> None:
        self._dir_datum.set_value(self._direction_text())
        self._dir_datum.color = WARNING_COLOR if not self._is_valid_lane() else LABEL_COLOR
        super().draw()
        self._dir_datum.draw()


class LaneVarsDialog(Dialog):
    """Dialog for editing lane speed/type and start/end tiles."""

    def __init__(
        self,
        x: float,
        y: float,
        lane_index: int,
        lane_config,
        game=None,
        on_change: Callable[[], None] | None = None,
        on_remove: Callable[[], None] | None = None,
    ):
        self._game = game
        self._can_remove = bool(game is not None and hasattr(game, "can_remove_lane") and game.can_remove_lane(lane_index))
        super().__init__(
            x, y, DIALOG_WIDTH, dialog_height(8 if self._can_remove else 7),
            str(lane_index), kind="Lane",
        )
        self.lane_index = lane_index
        self._config = lane_config
        self._on_change = on_change
        self._on_remove = on_remove

        speed_step = self._step_for_speed(lane_config.speed_limit)
        type_step = self._step_for_type(lane_config.lane_type)
        self._speed_slider = Slider(0, 0, 220, DATUM_HEIGHT, len(LANE_SPEED_VALUES), speed_step, SLIDER_TRACK, SLIDER_THUMB)
        self._type_slider = Slider(0, 0, 220, DATUM_HEIGHT, len(LANE_TYPE_VALUES), type_step, SLIDER_TRACK, SLIDER_THUMB)
        self._speed_datum = DatumBox()
        self._type_datum = DatumBox()
        self._start_compass = CompassSelect(
            0, 0, 220, DROPDOWN_ROW_HEIGHT, getattr(lane_config, "start_tile", (0, 0)),
            on_change=self._on_start_change,
        )
        self._end_compass = CompassSelect(
            0, 0, 220, DROPDOWN_ROW_HEIGHT, getattr(lane_config, "end_tile", (0, 0)),
            on_change=lambda _v: self._sync_from_widgets(),
        )
        self._update_locked_axes()
        self._dir_datum = DatumBox()
        self._in_datum = DatumBox()
        self._out_datum = DatumBox()

        self.widgets = [
            self._speed_slider,
            self._type_slider,
            self._start_compass,
            self._end_compass,
        ]
        self._remove_btn = RemoveButton(0, 0, on_click=self._do_remove)
        if self._can_remove:
            self.widgets.append(self._remove_btn)
        self._speed_label = ParamLabel("Speed")
        self._type_label = ParamLabel("Type")
        self._start_label = ParamLabel("Start")
        self._end_label = ParamLabel("End")
        self._dir_label = ParamLabel("Direction")
        self._in_label = ParamLabel("Traffic In")
        self._out_label = ParamLabel("Traffic Out")
        self.labels = [
            self._speed_label, self._type_label, self._start_label, self._end_label,
            self._dir_label, self._in_label, self._out_label,
        ]

    def _update_locked_axes(self) -> None:
        start = self._start_compass.value
        end = self._end_compass.value
        self._start_compass.locked_axis = None
        if start == end:
            self._end_compass.locked_axis = None
        elif start[0] == end[0]:
            self._end_compass.locked_axis = "x"
        elif start[1] == end[1]:
            self._end_compass.locked_axis = "y"
        else:
            self._end_compass.locked_axis = None

    def _do_remove(self) -> None:
        if self._game is not None and self.lane_index in self._game.lanes:
            self._game.delete_lane(self.lane_index)
        if self._on_remove:
            self._on_remove()

    def _on_start_change(self, new_start: tuple[int, int]) -> None:
        old_start = self._config.start_tile
        delta = (new_start[0] - old_start[0], new_start[1] - old_start[1])
        if delta == (0, 0):
            self._sync_from_widgets()
            return
        old_end = self._end_compass.value
        if old_start[0] == old_end[0]:
            if delta[0] != 0:
                self._end_compass.set_value((old_end[0] + delta[0], old_end[1]))
        elif old_start[1] == old_end[1]:
            if delta[1] != 0:
                self._end_compass.set_value((old_end[0], old_end[1] + delta[1]))
        self._sync_from_widgets()

    def _step_for_speed(self, val: float) -> int:
        best = 0
        for i, v in enumerate(LANE_SPEED_VALUES):
            if abs(v - val) < abs(LANE_SPEED_VALUES[best] - val):
                best = i
        return best

    def _step_for_type(self, val: str) -> int:
        try:
            return LANE_TYPE_VALUES.index(val)
        except ValueError:
            return 0

    def _slider_row(self, index: int, label: ParamLabel, datum: DatumBox, slider: Slider) -> None:
        row = form_row(self, index)
        label.place(row.label_x, row.label_y)
        datum.rect = (row.control_left, row.control_bottom, DATUM_WIDTH, DATUM_HEIGHT)
        sl = row.control_left + DATUM_WIDTH + FORM_GAP
        sw = max(24, row.control_width - DATUM_WIDTH - FORM_GAP)
        slider.rect = (sl, row.control_bottom, sw, DATUM_HEIGHT)

    def _layout_widgets(self) -> None:
        self._slider_row(0, self._speed_label, self._speed_datum, self._speed_slider)
        self._slider_row(1, self._type_label, self._type_datum, self._type_slider)
        r2 = form_row(self, 2)
        self._start_label.place(r2.label_x, r2.label_y)
        self._start_compass.rect = (r2.control_left, r2.control_bottom, r2.control_width, DATUM_HEIGHT)
        r3 = form_row(self, 3)
        self._end_label.place(r3.label_x, r3.label_y)
        self._end_compass.rect = (r3.control_left, r3.control_bottom, r3.control_width, DATUM_HEIGHT)
        r4 = form_row(self, 4)
        self._dir_label.place(r4.label_x, r4.label_y)
        self._dir_datum.rect = (r4.control_left, r4.control_bottom, r4.control_width, DATUM_HEIGHT)
        r5 = form_row(self, 5)
        self._in_label.place(r5.label_x, r5.label_y)
        self._in_datum.rect = (r5.control_left, r5.control_bottom, r5.control_width, DATUM_HEIGHT)
        r6 = form_row(self, 6)
        self._out_label.place(r6.label_x, r6.label_y)
        self._out_datum.rect = (r6.control_left, r6.control_bottom, r6.control_width, DATUM_HEIGHT)
        if self._can_remove:
            r7 = form_row(self, 7)
            self._remove_btn.rect = (r7.control_left, r7.control_bottom, ICON_BUTTON_SIZE, ICON_BUTTON_SIZE)

    def draw(self) -> None:
        self._speed_datum.set_value(f"{LANE_SPEED_VALUES[self._speed_slider.value]:g}x")
        self._type_datum.set_value(LANE_TYPE_LABELS[self._type_slider.value])
        direction = world.lane_direction(self.lane_index)
        traffic_in = world.lane_traffic_in(self.lane_index) or "—"
        traffic_out = world.lane_traffic_out(self.lane_index) or "—"
        direction_map = {"N": "Northbound", "S": "Southbound", "E": "Eastbound", "W": "Westbound"}
        self._dir_datum.set_value(direction_map.get(direction, "—"))
        self._in_datum.set_value(str(traffic_in))
        self._out_datum.set_value(str(traffic_out))
        super().draw()
        self._speed_datum.draw()
        self._type_datum.draw()
        self._dir_datum.draw()
        self._in_datum.draw()
        self._out_datum.draw()

    def on_mouse_press(self, x: float, y: float) -> bool:
        self._layout_widgets()
        result = super().on_mouse_press(x, y)
        self._sync_from_widgets()
        return result

    def on_mouse_drag(self, x: float, y: float, dx: float, dy: float) -> bool:
        result = super().on_mouse_drag(x, y, dx, dy)
        if self._dragging:
            return result
        self._sync_from_widgets()
        return result

    def on_mouse_release(self, x: float, y: float) -> bool:
        result = super().on_mouse_release(x, y)
        self._sync_from_widgets()
        return result

    def _sync_from_widgets(self) -> None:
        speed = LANE_SPEED_VALUES[self._speed_slider.value]
        lane_type = LANE_TYPE_VALUES[self._type_slider.value]
        start = self._start_compass.value
        end = self._end_compass.value
        old_start = (int(self._config.start_tile[0]), int(self._config.start_tile[1]))
        old_end = (int(self._config.end_tile[0]), int(self._config.end_tile[1]))
        if (
            self._config.speed_limit == speed
            and self._config.lane_type == lane_type
            and old_start == start
            and old_end == end
        ):
            self._update_locked_axes()
            return
        self._config.speed_limit = speed
        self._config.lane_type = lane_type
        self._update_locked_axes()
        self._config.start_tile = start
        self._config.end_tile = end
        if self._on_change:
            self._on_change()
