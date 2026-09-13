"""Idle inspect: click place / car / lane / intersection; grass close."""
from __future__ import annotations

from ui.dialogs.car import CarDeetsDialog
from ui.dialogs.intersection import IntersectionVarsDialog
from ui.dialogs.lane import LaneVarsDialog
from ui.dialogs.place import PlaceVarsDialog
from ui.tools.base import Tool
from ui.tools.host import ToolHost


class InspectTool(Tool):
    id = "inspect"

    def __init__(self, host: ToolHost) -> None:
        super().__init__(host)

    def on_click(self, x: float, y: float) -> bool:
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
        car = host.car_at_screen(x, y)
        if car is not None:
            dlg = CarDeetsDialog(x - 120, y - 55, car, host.game)
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
