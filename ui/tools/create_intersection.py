"""Two-click centre-then-size intersection create tool."""
from __future__ import annotations

from sim import places
from sim.map_data import bounds_from_center, intersection_size_for_hover
from ui.dialogs.intersection import NewIntersectionDialog
from ui.tools.base import Tool, draw_ghost_cells, readout_anchor
from ui.tools.host import ToolHost


class CreateIntersectionTool(Tool):
    id = "new_intersection"

    def __init__(self, host: ToolHost) -> None:
        super().__init__(host)
        self._phase: str | None = None
        self._center: tuple[int, int] | None = None
        self._size: int | None = None
        self._dialog: NewIntersectionDialog | None = None

    @property
    def active_action(self) -> str | None:
        return "new_intersection" if self._phase is not None else None

    def enter(self) -> None:
        self._phase = "center"
        self._center = None
        self._size = None
        ax, ay = readout_anchor(self.host)
        dlg = NewIntersectionDialog(
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
        self._center = None
        self._size = None
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

    def _on_geometry(self, center: tuple[int, int], size: int) -> None:
        if not self._phase:
            return
        self._center = center
        self._size = size

    def _sync_dialog(self) -> None:
        if self._dialog is None or self._center is None or self._size is None:
            return
        self._dialog.set_geometry(self._center, self._size)

    def on_hover(self, x: float, y: float) -> None:
        if not self._phase:
            return
        cell = self.host.grid_cell_at(x, y)
        if self._phase == "center":
            self._center = cell
            self._size = 2
        elif self._center is not None:
            self._size = intersection_size_for_hover(self._center, cell)
        self._sync_dialog()

    def can_pop(self) -> bool:
        return self._phase == "size"

    def pop(self) -> None:
        if self._phase != "size":
            return
        self._phase = "center"
        self._center = None
        self._size = None
        self.on_hover(self.host.mouse_x, self.host.mouse_y)

    def on_click(self, x: float, y: float) -> bool:
        if not self._phase:
            return False
        cell = self.host.grid_cell_at(x, y)
        if not self.host.cell_on_map(cell):
            self._request_exit()
            return True
        if self._phase == "center":
            self._center = cell
            self._size = 2
            self._phase = "size"
            self._sync_dialog()
            return True
        self._size = intersection_size_for_hover(self._center or cell, cell)
        self._sync_dialog()
        self._finish()
        return True

    def _finish(self) -> None:
        center = self._center
        size = self._size
        dlg = self._dialog
        if center is None or size is None or dlg is None:
            self._request_exit()
            return
        size = max(2, min(12, int(size)))
        if size % 2 != 0:
            size = (size // 2) * 2
        if size < 2:
            size = 2
        self.host.game.intersections[dlg._key] = places.IntersectionConfig(
            center_x=center[0],
            center_y=center[1],
            size_cells=size,
        )
        self.host.on_config_change(rebuild_world=True)
        self._request_exit()

    def draw_preview(self, center_x: float, center_y: float) -> None:
        if not self._phase:
            return
        center = self._center
        size = self._size
        if center is None or size is None:
            return
        x_lo, x_hi, y_lo, y_hi = bounds_from_center(center[0], center[1], size)
        cells = [(gx, gy) for gx in range(x_lo, x_hi) for gy in range(y_lo, y_hi)]
        draw_ghost_cells(self.host, "road_cross", cells, center_x, center_y)
