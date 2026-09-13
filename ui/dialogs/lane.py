"""Lane vars and add-lane dialogs."""
from __future__ import annotations

from typing import Callable

import arcade

from sim import world
from ui.dialogs.base import Dialog
from ui.theme import (
    DROPDOWN_ROW_HEIGHT,
    LABEL_COLOR,
    LANE_SPEED_VALUES,
    LANE_TYPE_VALUES,
    LANEVARS_CAPTION_WIDTH,
    LANEVARS_GAP,
)
from ui.widgets.buttons import CommitButton, RemoveButton
from ui.widgets.compass import CompassSelect
from ui.widgets.slider import Slider


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
        super().__init__(x, y, 320, 180, "Add Lane")
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
        self._commit_btn = CommitButton(0, 0, 70, 22, on_click=self._do_commit)
        self.widgets = [self._start_compass, self._end_compass, self._commit_btn]
        self._start_label = arcade.Text("Start:", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._end_label = arcade.Text("End:", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._status_label = arcade.Text("", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._on_tiles_change = on_tiles_change

    def set_tiles(self, start: tuple[int, int], end: tuple[int, int]) -> None:
        """Update compasses from the map tool without fighting a focused field."""
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
        """True if start and end form an orthogonal lane (same row or same column)."""
        start = self._start_compass.value
        end = self._end_compass.value
        return start[0] == end[0] or start[1] == end[1]

    def _direction_text(self) -> str:
        """Return direction string when valid, else 'invalid end lane'."""
        if not self._is_valid_lane():
            return "invalid end tile"
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
        left = self.x + 12
        control_left = left + LANEVARS_CAPTION_WIDTH + LANEVARS_GAP
        control_width = self.width - 24 - (control_left - self.x)
        content_top = self.y - 32
        self._start_label.x = left
        self._start_label.y = content_top - 12
        self._start_compass.rect = (control_left, content_top - 24, control_width, DROPDOWN_ROW_HEIGHT)
        self._end_label.x = left
        self._end_label.y = content_top - 40
        self._end_compass.rect = (control_left, content_top - 52, control_width, DROPDOWN_ROW_HEIGHT)
        self._status_label.x = left
        self._status_label.y = content_top - 72
        self._commit_btn.rect = (control_left, content_top - 104, 70, 22)

    def draw(self) -> None:
        self._layout_widgets()
        self._status_label.value = f"Direction: {self._direction_text()}"
        self._status_label.color = (220, 180, 100) if not self._is_valid_lane() else LABEL_COLOR
        super().draw()
        self._start_label.draw()
        self._end_label.draw()
        self._status_label.draw()


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
        height = 268 if self._can_remove else 240
        super().__init__(x, y, 320, height, f"Lane {lane_index}")
        self.lane_index = lane_index
        self._config = lane_config
        self._on_change = on_change
        self._on_remove = on_remove

        speed_step = self._step_for_speed(lane_config.speed_limit)
        type_step = self._step_for_type(lane_config.lane_type)
        self._speed_slider = Slider(0, 0, 220, 20, len(LANE_SPEED_VALUES), speed_step, (100, 100, 100), (180, 180, 180))
        self._type_slider = Slider(0, 0, 220, 20, len(LANE_TYPE_VALUES), type_step, (100, 100, 100), (180, 180, 180))
        self._start_compass = CompassSelect(
            0, 0, 220, DROPDOWN_ROW_HEIGHT, getattr(lane_config, "start_tile", (0, 0)),
            on_change=self._on_start_change,
        )
        self._end_compass = CompassSelect(
            0, 0, 220, DROPDOWN_ROW_HEIGHT, getattr(lane_config, "end_tile", (0, 0)),
            on_change=lambda _v: self._sync_from_widgets(),
        )
        self._update_locked_axes()

        self.widgets = [
            self._speed_slider,
            self._type_slider,
            self._start_compass,
            self._end_compass,
        ]
        self._remove_btn = RemoveButton(0, 0, 70, 22, on_click=self._do_remove)
        if self._can_remove:
            self.widgets.append(self._remove_btn)
        self._speed_label = arcade.Text("Speed:", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._type_label = arcade.Text("Type:", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._start_label = arcade.Text("Start:", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._end_label = arcade.Text("End:", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._dir_label = arcade.Text("", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._in_label = arcade.Text("", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._out_label = arcade.Text("", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")

    def _update_locked_axes(self) -> None:
        """End moves only along the lane (parallel). Start has full movement.
        When end == start, allow any direction so user can change orientation."""
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
        """Delete this lane and call on_remove."""
        if self._game is not None and self.lane_index in self._game.lanes:
            self._game.delete_lane(self.lane_index)
        if self._on_remove:
            self._on_remove()

    def _on_start_change(self, new_start: tuple[int, int]) -> None:
        """When Start moves perpendicular, also move End by the same delta to keep lane collinear."""
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

    def _layout_widgets(self) -> None:
        left = self.x + 12
        control_left = left + LANEVARS_CAPTION_WIDTH + LANEVARS_GAP
        control_width = self.width - 24 - (control_left - self.x)
        content_top = self.y - 32
        row = 0
        self._speed_label.x = left
        self._speed_label.y = content_top - 12 - row * 28
        self._speed_slider.rect = (control_left, content_top - 24 - row * 28, control_width, 20)
        row += 1
        self._type_label.x = left
        self._type_label.y = content_top - 12 - row * 28
        self._type_slider.rect = (control_left, content_top - 24 - row * 28, control_width, 20)
        row += 1
        self._start_label.x = left
        self._start_label.y = content_top - 12 - row * 28
        self._start_compass.rect = (control_left, content_top - 24 - row * 28, control_width, DROPDOWN_ROW_HEIGHT)
        row += 1
        self._end_label.x = left
        self._end_label.y = content_top - 12 - row * 28
        self._end_compass.rect = (control_left, content_top - 24 - row * 28, control_width, DROPDOWN_ROW_HEIGHT)
        row += 1
        info_top = content_top - 24 - row * 28 - 16
        self._dir_label.x = left
        self._dir_label.y = info_top
        self._in_label.x = left
        self._in_label.y = info_top - 20
        self._out_label.x = left
        self._out_label.y = info_top - 40
        if self._can_remove:
            self._remove_btn.rect = (left, info_top - 64, 70, 22)

    def draw(self) -> None:
        self._layout_widgets()
        direction = world.lane_direction(self.lane_index)
        traffic_in = world.lane_traffic_in(self.lane_index) or "-"
        traffic_out = world.lane_traffic_out(self.lane_index) or "-"
        direction_map = {"N": "Northbound", "S": "Southbound", "E": "Eastbound", "W": "Westbound"}
        self._dir_label.value = f"Direction: {direction_map.get(direction, '-')}"
        self._in_label.value = f"Traffic in: {traffic_in}"
        self._out_label.value = f"Traffic out: {traffic_out}"
        super().draw()
        self._speed_label.draw()
        self._type_label.draw()
        self._start_label.draw()
        self._end_label.draw()
        self._dir_label.draw()
        self._in_label.draw()
        self._out_label.draw()

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
