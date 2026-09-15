"""Default exclusive tool: Map vs Cars select, Isolate and Awareness overlays."""
from __future__ import annotations

import arcade

from render.selection import grid_rect_screen_quad, mouth_half_rect, sister_seam_rect
from sim import world
from sim.cars import car_grid_pose
from sim.constants import TILE_H, TILE_W
from ui.dialogs.car import CarDeetsDialog
from ui.dialogs.intersection import IntersectionVarsDialog
from ui.dialogs.lane import LaneVarsDialog
from ui.dialogs.place import PlaceVarsDialog
from ui.theme import (
    CAR_HOVER_RING,
    CAR_SELECT_RING,
    ISOLATE_TINT_BLUE,
    ISOLATE_TINT_GREEN,
    ISOLATE_TINT_RED,
    SELECT_MODE_CARS,
    SELECT_MODE_MAP,
)
from ui.tools.base import Tool
from ui.tools.host import ToolHost

MODE_MAP = SELECT_MODE_MAP
MODE_CARS = SELECT_MODE_CARS


class SelectTool(Tool):
    id = "select"

    def __init__(self, host: ToolHost) -> None:
        super().__init__(host)
        self.mode = MODE_MAP
        self.isolate = False
        self.awareness = False
        self.hover_car = None
        self._alpha_full: set[int] | None = None

    @property
    def active_action(self) -> str | None:
        return "select"

    def enter(self) -> None:
        self.host.toolbar.select_mode = self.mode

    def hides_world_overlay(self) -> bool:
        return self.mode == MODE_MAP and self.isolate and any(self.host.dialogs.iter_open())

    def awareness_active(self) -> bool:
        return self.mode == MODE_CARS and self.awareness

    def toggle_mode(self) -> str:
        self.mode = MODE_CARS if self.mode == MODE_MAP else MODE_MAP
        self.hover_car = None
        self._alpha_full = None
        self.host.toolbar.select_mode = self.mode
        return "Cars" if self.mode == MODE_CARS else "Map"

    def toggle_overlay(self) -> str | None:
        if self.mode == MODE_MAP:
            if not any(self.host.dialogs.iter_open()):
                return None
            self.isolate = not self.isolate
            return "Isolate" if self.isolate else "Default"
        self.awareness = not self.awareness
        self._alpha_full = None
        return "Awareness" if self.awareness else "Default"

    def on_hover(self, x: float, y: float) -> None:
        if self.mode != MODE_CARS or not self.host.mouse_in_window:
            self.hover_car = None
            return
        if self.host.dialogs.contains_point(x, y) or self.host.toolbar.contains(x, y):
            self.hover_car = None
            return
        self.hover_car = self.host.nearest_car_at_screen(x, y)

    def on_click(self, x: float, y: float) -> bool:
        if self.mode == MODE_CARS:
            return self._click_cars(x, y)
        return self._click_map(x, y)

    def draw_preview(self, center_x: float, center_y: float) -> None:
        self._alpha_full = None
        if self.mode != MODE_MAP or not self.isolate:
            return
        zoom = self.host.zoom_scale
        hw = TILE_W * zoom
        hh = TILE_H * zoom
        seams_drawn: set[frozenset[int]] = set()
        for dlg in self.host.dialogs.iter_open():
            if isinstance(dlg, LaneVarsDialog):
                self._tint_lane(dlg.lane_index, seams_drawn, center_x, center_y, hw, hh)
            elif isinstance(dlg, PlaceVarsDialog):
                self._tint_node(dlg.place, center_x, center_y, hw, hh)
            elif isinstance(dlg, IntersectionVarsDialog):
                self._tint_node(dlg.intersection_key, center_x, center_y, hw, hh)

    def draw_floor(self, center_x: float, center_y: float) -> None:
        if self.mode != MODE_CARS:
            return
        selected = {id(c): c for c in self._selected_cars()}
        hover = self.hover_car
        if hover is not None and id(hover) not in selected:
            self._draw_car_ring(hover, CAR_HOVER_RING, center_x, center_y)
        for car in selected.values():
            self._draw_car_ring(car, CAR_SELECT_RING, center_x, center_y)

    def overlay_car_alpha(self, entity) -> int:
        if self.mode != MODE_CARS or not self.awareness:
            return 255
        selected = self.top_selected_car()
        if selected is None:
            return 255
        if self._alpha_full is None:
            observed = self.host.game.observed_cars_for(selected)
            self._alpha_full = {id(selected)}
            for other in observed:
                self._alpha_full.add(id(other))
        return 255 if id(entity) in self._alpha_full else 128

    def top_selected_car(self):
        cars = self._selected_cars()
        return cars[-1] if cars else None

    def _selected_cars(self) -> list:
        out: list = []
        live = self.host.game.cars
        for dlg in self.host.dialogs.iter_open():
            if not isinstance(dlg, CarDeetsDialog):
                continue
            car = dlg.car
            if any(car is c for c in live):
                out.append(car)
        return out

    def _click_map(self, x: float, y: float) -> bool:
        host = self.host
        place = host.place_at_screen(x, y)
        if place is not None:
            existing = host.cached_place_dialog(place)
            if existing is not None:
                host.dialogs.open(existing)
            else:
                dlg = PlaceVarsDialog(
                    x - 120, y - 130, place,
                    host.game.places[place],
                    game=host.game,
                    on_change=host.on_config_change,
                    on_commit=lambda: host.on_config_change(rebuild_world=True),
                    on_rename=host.on_place_renamed,
                    on_remove=lambda: (
                        host.on_config_change(),
                        host.forget_place_dialog(dlg.place),
                        host.dialogs.close(dlg),
                    ),
                )
                host.store_place_dialog(place, dlg)
                dlg.set_on_close(lambda d: host.dialogs.close(d))
                host.dialogs.open(dlg)
            return True
        lane_idx = host.lane_at_screen(x, y)
        if lane_idx is not None and lane_idx in host.game.lanes:
            existing = host.cached_lane_dialog(lane_idx)
            if existing is not None:
                host.dialogs.open(existing)
            else:
                dlg = LaneVarsDialog(
                    x - 110, y - 70, lane_idx,
                    host.game.lanes[lane_idx],
                    game=host.game,
                    on_change=lambda: host.on_config_change(rebuild_world=True),
                    on_remove=lambda: (
                        host.on_config_change(),
                        host.forget_lane_dialog(lane_idx),
                        host.dialogs.close(dlg),
                    ),
                )
                host.store_lane_dialog(lane_idx, dlg)
                dlg.set_on_close(lambda d: host.dialogs.close(d))
                host.dialogs.open(dlg)
            return True
        inter_key = host.intersection_at_screen(x, y)
        if inter_key is not None:
            existing = host.cached_intersection_dialog(inter_key)
            if existing is not None:
                host.dialogs.open(existing)
            else:
                dlg = IntersectionVarsDialog(
                    x - 110, y - 50, inter_key,
                    host.game.intersections[inter_key],
                    game=host.game,
                    on_commit=lambda: host.on_config_change(rebuild_world=True),
                    on_remove=lambda: (
                        host.on_config_change(),
                        host.forget_intersection_dialog(inter_key),
                        host.dialogs.close(dlg),
                    ),
                )
                host.store_intersection_dialog(inter_key, dlg)
                dlg.set_on_close(lambda d: host.dialogs.close(d))
                host.dialogs.open(dlg)
            return True
        if host.grass_close_enabled and host.cell_is_grass(host.grid_cell_at(x, y)):
            host.dialogs.close_all()
            return True
        return False

    def _click_cars(self, x: float, y: float) -> bool:
        host = self.host
        car = host.nearest_car_at_screen(x, y)
        if car is not None:
            self._open_car_dialog(x, y, car)
            return True
        self._close_car_dialogs()
        return True

    def _open_car_dialog(self, x: float, y: float, car) -> None:
        for dlg in self.host.dialogs.iter_open():
            if isinstance(dlg, CarDeetsDialog) and dlg.car is car:
                self.host.dialogs.open(dlg)
                return
        dlg = CarDeetsDialog(x - 120, y - 55, car, self.host.game)
        dlg.set_on_close(lambda d: self.host.dialogs.close(d))
        self.host.dialogs.open(dlg)

    def _close_car_dialogs(self) -> None:
        for dlg in list(self.host.dialogs.iter_open()):
            if isinstance(dlg, CarDeetsDialog):
                closer = getattr(dlg, "_on_close", None)
                if closer:
                    closer(dlg)
                else:
                    self.host.dialogs.close(dlg)

    def _tint_lane(
        self,
        lane_index: int,
        seams_drawn: set[frozenset[int]],
        center_x: float,
        center_y: float,
        hw: float,
        hh: float,
    ) -> None:
        """Mouths green/red, half-length on a little sister, plus the blue seam."""
        kind = world.sister_kind(lane_index)
        direction = world.lane_direction(lane_index)
        start, end = world.lane_start_end_cells(lane_index)
        for cell, color, at_exit in (
            (start, ISOLATE_TINT_GREEN, False),
            (end, ISOLATE_TINT_RED, True),
        ):
            if cell is None:
                continue
            rect = (
                mouth_half_rect(cell, direction, at_exit)
                if kind == world.SISTER_LITTLE
                else None
            )
            if rect is None:
                self._tint_cell(cell, color, center_x, center_y, hw, hh)
            else:
                self._tint_rect(rect, color, center_x, center_y)

        sister = world.sister_lane(lane_index)
        if kind is None or sister is None:
            return
        pair = frozenset({lane_index, sister})
        if pair in seams_drawn:
            return
        seams_drawn.add(pair)
        self._tint_seam(lane_index, sister, kind, center_x, center_y)

    def _tint_seam(
        self,
        lane_index: int,
        sister: int,
        kind: str,
        center_x: float,
        center_y: float,
    ) -> None:
        little, big = (
            (lane_index, sister) if kind == world.SISTER_LITTLE else (sister, lane_index)
        )
        cells = world.get_lane_cells(little)
        big_cells = world.get_lane_cells(big)
        direction = world.lane_direction(little)
        if not cells or not big_cells or not direction:
            return
        other_perp = big_cells[0][0] if direction in ("N", "S") else big_cells[0][1]
        rect = sister_seam_rect(cells[0], cells[-1], direction, other_perp)
        if rect is not None:
            self._tint_rect(rect, ISOLATE_TINT_BLUE, center_x, center_y)

    def _tint_rect(
        self,
        rect: tuple[float, float, float, float],
        color: tuple[int, int, int, int],
        center_x: float,
        center_y: float,
    ) -> None:
        pts = grid_rect_screen_quad(
            rect, lambda gx, gy: self.host.to_screen(gx, gy, center_x, center_y)
        )
        arcade.draw_polygon_filled(pts, color)

    def _tint_node(self, node: str, center_x: float, center_y: float, hw: float, hh: float) -> None:
        entrances, exits = world.node_entrance_exit_cells(node)
        for cell in entrances:
            self._tint_cell(cell, ISOLATE_TINT_GREEN, center_x, center_y, hw, hh)
        for cell in exits:
            self._tint_cell(cell, ISOLATE_TINT_RED, center_x, center_y, hw, hh)

    def _tint_cell(
        self,
        cell: tuple[int, int],
        color: tuple[int, int, int, int],
        center_x: float,
        center_y: float,
        hw: float,
        hh: float,
    ) -> None:
        sx, sy = self.host.to_screen(float(cell[0]), float(cell[1]), center_x, center_y)
        arcade.draw_polygon_filled(
            [(sx, sy + hh), (sx + hw, sy), (sx, sy - hh), (sx - hw, sy)],
            color,
        )

    def _draw_car_ring(self, car, color, center_x: float, center_y: float) -> None:
        pose = car_grid_pose(car)
        if pose is None:
            return
        sx, sy = self.host.to_screen(pose[0], pose[1], center_x, center_y)
        zoom = self.host.zoom_scale
        arcade.draw_ellipse_filled(
            sx, sy,
            2.0 * TILE_W * zoom,
            2.0 * TILE_H * zoom,
            color,
        )


InspectTool = SelectTool
