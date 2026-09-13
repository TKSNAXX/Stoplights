"""Two- or three-corner place create tool."""
from __future__ import annotations

from sim import places
from sim.map_data import aabb_cells, aabb_from_corners, aabb_from_edge_and_hover, place_center_from_aabb
from ui.dialogs.place import NewPlaceDialog
from ui.tools.base import Tool, draw_ghost_cells, readout_anchor
from ui.tools.host import ToolHost


class CreatePlaceTool(Tool):
    id = "new_place"

    def __init__(self, host: ToolHost) -> None:
        super().__init__(host)
        self._phase: str | None = None
        self._c1: tuple[int, int] | None = None
        self._c2: tuple[int, int] | None = None
        self._aabb: tuple[int, int, int, int] | None = None
        self._dialog: NewPlaceDialog | None = None

    @property
    def active_action(self) -> str | None:
        return "new_place" if self._phase is not None else None

    def enter(self) -> None:
        self._phase = "c1"
        self._c1 = None
        self._c2 = None
        self._aabb = None
        ax, ay = readout_anchor(self.host)
        dlg = NewPlaceDialog(
            ax, ay, self.host.game,
            on_commit=self._on_committed,
            on_geometry_change=self._on_geometry,
        )
        self._dialog = dlg
        dlg.set_on_close(lambda d: self._request_exit())
        self.host.dialogs.open(dlg)
        self.on_hover(self.host.mouse_x, self.host.mouse_y)

    def exit(self) -> None:
        dlg = self._dialog
        self._phase = None
        self._c1 = None
        self._c2 = None
        self._aabb = None
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

    def _on_geometry(self, center: tuple[int, int], width: int, length: int) -> None:
        if not self._phase:
            return
        x_lo = center[0] - width // 2
        y_lo = center[1] - length // 2
        self._aabb = (x_lo, y_lo, width, length)

    def _sync_dialog(self) -> None:
        if self._dialog is None or self._aabb is None:
            return
        x_lo, y_lo, w, h = self._aabb
        cx, cy = place_center_from_aabb(x_lo, y_lo, w, h)
        self._dialog.set_geometry((cx, cy), w, h)

    def on_hover(self, x: float, y: float) -> None:
        if not self._phase:
            return
        cell = self.host.grid_cell_at(x, y)
        if self._phase == "c1":
            self._c1 = cell
            self._aabb = aabb_from_corners(cell, cell)
        elif self._phase == "c2" and self._c1 is not None:
            self._aabb = aabb_from_corners(self._c1, cell)
        elif self._phase == "c3" and self._c1 is not None and self._c2 is not None:
            self._aabb = aabb_from_edge_and_hover(self._c1, self._c2, cell)
        self._sync_dialog()

    def can_pop(self) -> bool:
        return self._phase in ("c2", "c3")

    def pop(self) -> None:
        if self._phase == "c3":
            self._phase = "c2"
            self._c2 = None
            self.on_hover(self.host.mouse_x, self.host.mouse_y)
            return
        if self._phase == "c2":
            self._phase = "c1"
            self._c1 = None
            self.on_hover(self.host.mouse_x, self.host.mouse_y)

    def on_click(self, x: float, y: float) -> bool:
        if not self._phase:
            return False
        cell = self.host.grid_cell_at(x, y)
        if not self.host.cell_on_map(cell):
            self._request_exit()
            return True
        if self._phase == "c1":
            self._c1 = cell
            self._aabb = aabb_from_corners(cell, cell)
            self._phase = "c2"
            self._sync_dialog()
            return True
        if self._phase == "c2":
            c1 = self._c1 or cell
            same_x = cell[0] == c1[0]
            same_y = cell[1] == c1[1]
            if same_x and same_y:
                self._finish(aabb_from_corners(c1, cell))
                return True
            if same_x or same_y:
                self._c2 = cell
                self._phase = "c3"
                self._aabb = aabb_from_edge_and_hover(c1, cell, cell)
                self._sync_dialog()
                return True
            self._finish(aabb_from_corners(c1, cell))
            return True
        c1 = self._c1 or cell
        c2 = self._c2 or cell
        self._finish(aabb_from_edge_and_hover(c1, c2, cell))
        return True

    def _finish(self, aabb: tuple[int, int, int, int]) -> None:
        dlg = self._dialog
        name = dlg.try_name() if dlg is not None else None
        if name is None:
            return
        x_lo, y_lo, w, h = aabb
        cx, cy = place_center_from_aabb(x_lo, y_lo, w, h)
        self.host.game.places[name] = places.Place(
            center_x=cx, center_y=cy, width=w, length=h,
            building_kind=places.default_building_kind(name),
        )
        self.host.on_config_change(rebuild_world=True)
        self._request_exit()

    def draw_preview(self, center_x: float, center_y: float) -> None:
        if not self._phase or self._aabb is None:
            return
        x_lo, y_lo, w, h = self._aabb
        cells = aabb_cells(x_lo, y_lo, w, h)
        draw_ghost_cells(self.host, "place_zone", cells, center_x, center_y)
