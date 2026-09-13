"""Two-click cardinal lane create tool."""
from __future__ import annotations

from sim import places
from sim.map_data import build_lane_cells, snap_cardinal_end, _direction_from_tiles
from ui.dialogs.lane import AddLaneDialog
from ui.tools.base import Tool, draw_ghost_cells, readout_anchor
from ui.tools.host import ToolHost


class CreateLaneTool(Tool):
    id = "new_lane"

    def __init__(self, host: ToolHost) -> None:
        super().__init__(host)
        self._phase: str | None = None
        self._start: tuple[int, int] | None = None
        self._end: tuple[int, int] | None = None
        self._dialog: AddLaneDialog | None = None

    @property
    def active_action(self) -> str | None:
        return "new_lane" if self._phase is not None else None

    def enter(self) -> None:
        self._phase = "start"
        self._start = None
        self._end = None
        ax, ay = readout_anchor(self.host)
        dlg = AddLaneDialog(
            ax, ay, self.host.game,
            on_commit=self._on_committed,
            on_tiles_change=self._on_tiles,
        )
        self._dialog = dlg
        dlg.set_on_close(lambda d: self._request_exit())
        self.host.dialogs.open(dlg)
        self.on_hover(self.host.mouse_x, self.host.mouse_y)

    def exit(self) -> None:
        dlg = self._dialog
        self._phase = None
        self._start = None
        self._end = None
        self._dialog = None
        if dlg is not None:
            self.host.dialogs.close(dlg)

    def _request_exit(self) -> None:
        from ui.tools.manager import ToolManager
        mgr = getattr(self.host, "tool_manager", None)
        if isinstance(mgr, ToolManager):
            mgr.activate_inspect()
        else:
            self.exit()

    def _on_committed(self) -> None:
        self.host.on_config_change()
        self._request_exit()

    def _on_tiles(self, start: tuple[int, int], end: tuple[int, int]) -> None:
        if not self._phase:
            return
        if self._phase == "start":
            self._start = start
            self._end = start
        else:
            self._start = start
            self._end = end

    def on_hover(self, x: float, y: float) -> None:
        if not self._phase:
            return
        cell = self.host.grid_cell_at(x, y)
        if self._phase == "start":
            self._start = cell
            self._end = cell
            if self._dialog is not None:
                self._dialog.set_tiles(cell, cell)
            return
        if self._start is None:
            return
        end = snap_cardinal_end(self._start, cell)
        self._end = end
        if self._dialog is not None:
            self._dialog.set_tiles(self._start, end)

    def can_pop(self) -> bool:
        return self._phase == "end"

    def pop(self) -> None:
        if self._phase != "end":
            return
        self._phase = "start"
        self._start = None
        self.on_hover(self.host.mouse_x, self.host.mouse_y)

    def on_click(self, x: float, y: float) -> bool:
        if not self._phase:
            return False
        cell = self.host.grid_cell_at(x, y)
        if not self.host.cell_on_map(cell):
            self._request_exit()
            return True
        if self._phase == "start":
            self._start = cell
            self._end = cell
            self._phase = "end"
            if self._dialog is not None:
                self._dialog.set_tiles(cell, cell)
            return True
        end = snap_cardinal_end(self._start or cell, cell)
        self._end = end
        self._finish()
        return True

    def _finish(self) -> None:
        start = self._start
        end = self._end
        if start is None or end is None:
            self._request_exit()
            return
        idx = self.host.game.next_lane_index()
        self.host.game.lanes[idx] = places.LaneConfig(start_tile=start, end_tile=end)
        self.host.on_config_change(rebuild_world=True)
        self._request_exit()

    def draw_preview(self, center_x: float, center_y: float) -> None:
        if not self._phase:
            return
        start = self._start
        end = self._end
        if start is None or end is None:
            return
        cells = build_lane_cells(start, end)
        if not cells:
            return
        direction = _direction_from_tiles(start, end)
        if direction == "S":
            key = "road_s"
        elif direction == "E":
            key = "road_e"
        elif direction == "W":
            key = "road_w"
        else:
            key = "road_n"
        draw_ghost_cells(self.host, key, cells, center_x, center_y)
