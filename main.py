"""
Stoplights entry point and window orchestration.
"""
import time
from pathlib import Path

import arcade

from render.camera import grid_to_screen, screen_to_grid
from render.color_grade import WorldColorGrade, is_identity_grade
from render.debug import visibility_fan_vertices
from render.selection import iso_aabb_silhouette, occupancy_aabb, rim_quads
from render.sprites import CarSpritePool, load_car_textures
from render.intersection_topology import (
    classify_intersection_sides,
    corner_quadrant_for_sides,
    straight_axis_for_intersection,
    tee_layout_for_sides,
)
from render.tiles import (
    TileSet,
    generate_corner_texture,
    generate_cross_texture,
    generate_straight_texture,
    generate_tee_texture,
)
from render.buildings import (
    buildings_dir,
    load_catalog,
    natural_sprite_scale,
    pack_all_places,
    south_vertex_screen,
    sprite_center_from_anchor,
)
from sim import places
from sim.constants import (
    CAR_DEFAULT,
    PLACE_LABEL_COLOR,
    TILE_H,
    TILE_W,
    VIS_ZONE_LENGTH_CELLS,
    VIS_ZONE_WIDTH_CELLS,
)
from sim.game import GameState
from sim import persistence, world
from sim.scenario import clamp_color_hue, clamp_color_sat
from sim.map_data import (
    aabb_cells,
    aabb_from_corners,
    aabb_from_edge_and_hover,
    bounds_from_center,
    build_lane_cells,
    intersection_size_for_hover,
    place_center_from_aabb,
    snap_cardinal_end,
    _direction_from_tiles,
)
from ui import (
    AddLaneDialog,
    CarDeetsDialog,
    DialogManager,
    IntersectionVarsDialog,
    LaneVarsDialog,
    NewIntersectionDialog,
    NewPlaceDialog,
    NumberBox,
    PlaceVarsDialog,
    SettingsDialog,
    SkeuoKeyChip,
    Toolbar,
    TOOLBAR_BOTTOM_DRAW,
    TOOLBAR_BOTTOM_IDLE,
    TOOLBAR_LEFT,
)

TICKS_PER_SECOND = 60
TICK_DT = 1.0 / TICKS_PER_SECOND
MAX_SUBSTEPS_PER_FRAME = 8
BUILDING_OUTLINE_WIDTH = 2
PLACE_LABEL_FONT_SIZE = 12
VIS_ZONE_COLOR = (60, 220, 100)
VIS_ZONE_COLOR_YELLOW = (220, 220, 80)
VIS_ZONE_COLOR_RED = (220, 80, 80)
VIS_ZONE_COLOR_WHITE = (220, 220, 220)
VIS_ZONE_COLOR_CYAN = (60, 220, 220)
VIS_ZONE_LINE_WIDTH = 1

MOVE_DURATION_BASE = 0.2

ZOOM_STEPS = 5
ZOOM_LEVEL_FIT = 0
ZOOM_LEVEL_MAX = 4
EDGE_PAN_MARGIN = 48


def _car_direction_index(car) -> int:
    if getattr(car, "pose_dir_index_8", None) is not None:
        return int(car.pose_dir_index_8) % 8
    d = world.lane_direction(getattr(car, "lane_index", -1))
    direction_map = {"N": 0, "E": 2, "S": 4, "W": 6}
    return direction_map.get(d, 0)


class StoplightsWindow(arcade.Window):
    def __init__(self):
        super().__init__(800, 600, "Stoplights", resizable=True)
        arcade.set_background_color(arcade.color.BLACK)
        self.game = GameState()
        self._edge_pan_enabled = True
        self._grass_close_enabled = True
        self._color_hue = 0
        self._color_sat = 1.0
        self._color_grade = WorldColorGrade(self.ctx)
        persistence.load_config(self.game, window=self)
        self.game.rebuild_world_from_config()
        self._tick_accumulator = 0.0
        self._sim_time = 0.0
        self._move_duration = MOVE_DURATION_BASE

        self._cached_center: tuple[float, float, float] | None = None
        self._place_texts: dict[str, arcade.Text] = {}
        self._cardinal_texts: dict[str, arcade.Text] = {}

        for place in self.game.spawn_places:
            self._place_texts[place] = arcade.Text(place, 0, 0, color=PLACE_LABEL_COLOR, font_size=PLACE_LABEL_FONT_SIZE, anchor_x="center", anchor_y="center")
        self._cardinal_texts = {
            "N": arcade.Text("N", 0, 0, color=PLACE_LABEL_COLOR, font_size=PLACE_LABEL_FONT_SIZE, anchor_x="center", anchor_y="bottom"),
            "S": arcade.Text("S", 0, 0, color=PLACE_LABEL_COLOR, font_size=PLACE_LABEL_FONT_SIZE, anchor_x="center", anchor_y="top"),
            "E": arcade.Text("E", 0, 0, color=PLACE_LABEL_COLOR, font_size=PLACE_LABEL_FONT_SIZE, anchor_x="right", anchor_y="center"),
            "W": arcade.Text("W", 0, 0, color=PLACE_LABEL_COLOR, font_size=PLACE_LABEL_FONT_SIZE, anchor_x="left", anchor_y="center"),
        }
        self._perf_text = arcade.Text("", 10, self.height - 10, color=PLACE_LABEL_COLOR, font_size=11, anchor_x="left", anchor_y="top")

        self._fps_ema = 0.0
        self._last_substeps = 0
        self._draw_ms_ema = 0.0
        self._show_visibility_fans = False

        self._dialog_manager = DialogManager(get_window_size=lambda: (self.width, self.height))
        self._place_dialogs: dict[str, PlaceVarsDialog] = {}
        self._lane_dialogs: dict[int, LaneVarsDialog] = {}
        self._intersection_dialogs: dict[str, IntersectionVarsDialog] = {}
        self._toolbar = Toolbar(TOOLBAR_LEFT, self.height - TOOLBAR_BOTTOM_IDLE)
        self._esc_chip = SkeuoKeyChip("Esc", side="left")
        self._back_chip = SkeuoKeyChip("<-", side="right")
        self._lane_draw: str | None = None
        self._lane_draw_start: tuple[int, int] | None = None
        self._lane_draw_end: tuple[int, int] | None = None
        self._lane_draw_dialog: AddLaneDialog | None = None
        self._place_draw: str | None = None
        self._place_c1: tuple[int, int] | None = None
        self._place_c2: tuple[int, int] | None = None
        self._place_aabb: tuple[int, int, int, int] | None = None
        self._place_draw_dialog: NewPlaceDialog | None = None
        self._ix_draw: str | None = None
        self._ix_center: tuple[int, int] | None = None
        self._ix_size: int | None = None
        self._ix_draw_dialog: NewIntersectionDialog | None = None

        self._cam_x = 0.0
        self._cam_y = 0.0
        self._key_left = self._key_right = self._key_up = self._key_down = False
        self._cam_pan_speed = 300.0

        self._zoom_level = ZOOM_LEVEL_FIT
        self._zoom_scale = 1.0
        self._mouse_x = 0.0
        self._mouse_y = 0.0
        self._mouse_in_window = False

        assets_dir = Path(__file__).resolve().parent / "assets"
        self._tile_set = TileSet(assets_dir / "ortho")
        self._toolbar.set_lane_icon(self._tile_set.get("road_n"))
        self._toolbar.set_place_icon(self._tile_set.get("place_zone"))
        self._toolbar.set_intersection_icon(self._tile_set.get("road_cross"))
        self._tile_sprite_list: arcade.SpriteList | None = None
        self._tile_cells: list[tuple[int, int]] = []

        self._car_textures_by_dir = load_car_textures(assets_dir)
        self._car_sprite_pool = CarSpritePool(self._car_textures_by_dir, scale=2.0) if self._car_textures_by_dir else None
        self._car_draw_order: list[object] = []

        self._building_defs = load_catalog(persist=True)
        self._building_defs_by_id = {d.asset_id: d for d in self._building_defs}
        self._building_textures: dict[str, arcade.Texture] = {}
        root = buildings_dir()
        for d in self._building_defs:
            try:
                self._building_textures[d.asset_id] = arcade.load_texture(str(root / d.file))
            except Exception as e:
                print(f"[Buildings] Failed to load '{d.asset_id}': {e}")
        self._building_draw_items: list[tuple[object, arcade.Sprite, object]] = []

        self._update_zoom_scale()
        if self._car_sprite_pool is not None:
            self._car_sprite_pool.set_zoom_scale(self._zoom_scale)
        self._rebuild_static_draw_cache(self.width / 2, self.height / 2)

    def _invalidate_draw_cache(self) -> None:
        """Force tile cache rebuild on next draw (e.g. when lane config changes)."""
        self._cached_center = None

    def _on_config_change(self, rebuild_world: bool = False) -> None:
        """Handle config changes consistently: optional world rebuild, cache invalidate, save."""
        if rebuild_world:
            self.game.rebuild_world_from_config()
        self._invalidate_draw_cache()
        persistence.request_debounced_save()

    def _on_place_renamed(self, old: str, new: str) -> None:
        """Rekey open dialog and map label after a place id change."""
        dlg = self._place_dialogs.pop(old, None)
        if dlg is not None:
            self._place_dialogs[new] = dlg
        label = self._place_texts.pop(old, None)
        if label is not None:
            label.value = new
            self._place_texts[new] = label

    def _sync_toolbar_bottom(self) -> None:
        inset = TOOLBAR_BOTTOM_DRAW if self._draw_tool_active() else TOOLBAR_BOTTOM_IDLE
        self._toolbar.bottom = self.height - inset

    def _draw_tool_active(self) -> bool:
        return bool(self._lane_draw or self._place_draw or self._ix_draw)

    def _grid_cell_at(self, sx: float, sy: float) -> tuple[int, int]:
        center_x, center_y = self._effective_center()
        gx, gy = self._screen_to_grid(sx, sy, center_x, center_y)
        return (int(round(gx)), int(round(gy)))

    def _cell_on_map(self, cell: tuple[int, int]) -> bool:
        x_lo, y_lo, x_hi, y_hi = world.get_bounds()
        return x_lo <= cell[0] < x_hi and y_lo <= cell[1] < y_hi

    def _cell_is_grass(self, cell: tuple[int, int]) -> bool:
        """True for an on-map cell with no place, lane, or intersection occupancy."""
        if not self._cell_on_map(cell):
            return False
        if world.get_intersection_at_cell(cell) is not None:
            return False
        gx, gy = cell
        for rect in world.get_place_rects().values():
            x0 = int(rect.get("x", 0))
            y0 = int(rect.get("y", 0))
            w = int(rect.get("w", 0))
            h = int(rect.get("h", 0))
            if x0 <= gx < x0 + w and y0 <= gy < y0 + h:
                return False
        for i in world.lane_ids():
            if cell in world.get_lane_cells(i):
                return False
        return True

    def _enter_lane_draw(self) -> None:
        self._lane_draw = "start"
        self._lane_draw_start = None
        self._lane_draw_end = None
        self._toolbar.active_action = "new_lane"
        self._sync_toolbar_bottom()
        dlg_x = TOOLBAR_LEFT + 56
        dlg_y = self.height / 2 + 100
        dlg = AddLaneDialog(
            dlg_x, dlg_y, self.game,
            on_commit=self._on_lane_draw_committed,
            on_tiles_change=self._on_lane_draw_tiles,
        )
        self._lane_draw_dialog = dlg
        dlg.set_on_close(lambda d: self._exit_lane_draw())
        self._dialog_manager.open(dlg)
        self._update_lane_draw_hover()

    def _exit_lane_draw(self) -> None:
        if self._lane_draw is None and self._lane_draw_dialog is None:
            return
        dlg = self._lane_draw_dialog
        self._lane_draw = None
        self._lane_draw_start = None
        self._lane_draw_end = None
        self._lane_draw_dialog = None
        self._toolbar.active_action = None
        self._sync_toolbar_bottom()
        if dlg is not None:
            self._dialog_manager.close(dlg)

    def _on_lane_draw_committed(self) -> None:
        self._on_config_change()
        self._exit_lane_draw()

    def _on_lane_draw_tiles(self, start: tuple[int, int], end: tuple[int, int]) -> None:
        if not self._lane_draw:
            return
        if self._lane_draw == "start":
            self._lane_draw_start = start
            self._lane_draw_end = start
        else:
            self._lane_draw_start = start
            self._lane_draw_end = end

    def _update_lane_draw_hover(self) -> None:
        if not self._lane_draw:
            return
        cell = self._grid_cell_at(self._mouse_x, self._mouse_y)
        if self._lane_draw == "start":
            self._lane_draw_start = cell
            self._lane_draw_end = cell
            if self._lane_draw_dialog is not None:
                self._lane_draw_dialog.set_tiles(cell, cell)
            return
        if self._lane_draw_start is None:
            return
        end = snap_cardinal_end(self._lane_draw_start, cell)
        self._lane_draw_end = end
        if self._lane_draw_dialog is not None:
            self._lane_draw_dialog.set_tiles(self._lane_draw_start, end)

    def _finish_lane_from_map(self) -> None:
        start = self._lane_draw_start
        end = self._lane_draw_end
        if start is None or end is None:
            self._exit_lane_draw()
            return
        idx = self.game.next_lane_index()
        self.game.lanes[idx] = places.LaneConfig(start_tile=start, end_tile=end)
        self._on_config_change(rebuild_world=True)
        self._exit_lane_draw()

    def _draw_lane_preview(self, center_x: float, center_y: float) -> None:
        if not self._lane_draw or not self._mouse_in_window:
            return
        start = self._lane_draw_start
        end = self._lane_draw_end
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
        tex = self._tile_set.get(key)
        if tex is None:
            return
        lst = arcade.SpriteList()
        for gx, gy in cells:
            spr = arcade.Sprite(tex, scale=self._zoom_scale)
            spr.center_x, spr.center_y = self._to_screen(gx, gy, center_x, center_y)
            spr.alpha = 170
            lst.append(spr)
        lst.draw(pixelated=True)

    def _exit_active_draw_tool(self) -> None:
        if self._lane_draw is not None or self._lane_draw_dialog is not None:
            self._exit_lane_draw()
        if self._place_draw is not None or self._place_draw_dialog is not None:
            self._exit_place_draw()
        if self._ix_draw is not None or self._ix_draw_dialog is not None:
            self._exit_ix_draw()

    def _placement_can_pop(self) -> bool:
        return self._place_draw in ("c2", "c3") or self._lane_draw == "end" or self._ix_draw == "size"

    def _placement_pop(self) -> None:
        if self._place_draw == "c3":
            self._place_draw = "c2"
            self._place_c2 = None
            self._update_place_draw_hover()
            return
        if self._place_draw == "c2":
            self._place_draw = "c1"
            self._place_c1 = None
            self._update_place_draw_hover()
            return
        if self._lane_draw == "end":
            self._lane_draw = "start"
            self._lane_draw_start = None
            self._update_lane_draw_hover()
            return
        if self._ix_draw == "size":
            self._ix_draw = "center"
            self._ix_center = None
            self._ix_size = None
            self._update_ix_draw_hover()

    def _enter_place_draw(self) -> None:
        self._place_draw = "c1"
        self._place_c1 = None
        self._place_c2 = None
        self._place_aabb = None
        self._toolbar.active_action = "new_place"
        self._sync_toolbar_bottom()
        dlg_x = TOOLBAR_LEFT + 56
        dlg_y = self.height / 2 + 100
        dlg = NewPlaceDialog(
            dlg_x, dlg_y, self.game,
            on_commit=self._on_place_draw_committed,
            on_geometry_change=self._on_place_draw_geometry,
        )
        self._place_draw_dialog = dlg
        dlg.set_on_close(lambda d: self._exit_place_draw())
        self._dialog_manager.open(dlg)
        self._update_place_draw_hover()

    def _exit_place_draw(self) -> None:
        if self._place_draw is None and self._place_draw_dialog is None:
            return
        dlg = self._place_draw_dialog
        self._place_draw = None
        self._place_c1 = None
        self._place_c2 = None
        self._place_aabb = None
        self._place_draw_dialog = None
        self._toolbar.active_action = None
        self._sync_toolbar_bottom()
        if dlg is not None:
            self._dialog_manager.close(dlg)

    def _on_place_draw_committed(self) -> None:
        self._on_config_change()
        self._exit_place_draw()

    def _on_place_draw_geometry(self, center: tuple[int, int], width: int, length: int) -> None:
        if not self._place_draw:
            return
        x_lo = center[0] - width // 2
        y_lo = center[1] - length // 2
        self._place_aabb = (x_lo, y_lo, width, length)

    def _sync_place_dialog_geometry(self) -> None:
        if self._place_draw_dialog is None or self._place_aabb is None:
            return
        x_lo, y_lo, w, h = self._place_aabb
        cx, cy = place_center_from_aabb(x_lo, y_lo, w, h)
        self._place_draw_dialog.set_geometry((cx, cy), w, h)

    def _update_place_draw_hover(self) -> None:
        if not self._place_draw:
            return
        cell = self._grid_cell_at(self._mouse_x, self._mouse_y)
        if self._place_draw == "c1":
            self._place_c1 = cell
            self._place_aabb = aabb_from_corners(cell, cell)
        elif self._place_draw == "c2" and self._place_c1 is not None:
            self._place_aabb = aabb_from_corners(self._place_c1, cell)
        elif self._place_draw == "c3" and self._place_c1 is not None and self._place_c2 is not None:
            self._place_aabb = aabb_from_edge_and_hover(self._place_c1, self._place_c2, cell)
        self._sync_place_dialog_geometry()

    def _finish_place_from_aabb(self, aabb: tuple[int, int, int, int]) -> None:
        dlg = self._place_draw_dialog
        name = dlg.try_name() if dlg is not None else None
        if name is None:
            return
        x_lo, y_lo, w, h = aabb
        cx, cy = place_center_from_aabb(x_lo, y_lo, w, h)
        self.game.places[name] = places.Place(
            center_x=cx, center_y=cy, width=w, length=h,
            building_kind=places.default_building_kind(name),
        )
        self._on_config_change(rebuild_world=True)
        self._exit_place_draw()

    def _draw_place_preview(self, center_x: float, center_y: float) -> None:
        if not self._place_draw or not self._mouse_in_window or self._place_aabb is None:
            return
        tex = self._tile_set.get("place_zone")
        if tex is None:
            return
        x_lo, y_lo, w, h = self._place_aabb
        cells = aabb_cells(x_lo, y_lo, w, h)
        if not cells:
            return
        lst = arcade.SpriteList()
        for gx, gy in cells:
            spr = arcade.Sprite(tex, scale=self._zoom_scale)
            spr.center_x, spr.center_y = self._to_screen(gx, gy, center_x, center_y)
            spr.alpha = 170
            lst.append(spr)
        lst.draw(pixelated=True)

    def _enter_ix_draw(self) -> None:
        self._ix_draw = "center"
        self._ix_center = None
        self._ix_size = None
        self._toolbar.active_action = "new_intersection"
        self._sync_toolbar_bottom()
        dlg_x = TOOLBAR_LEFT + 56
        dlg_y = self.height / 2 + 100
        dlg = NewIntersectionDialog(
            dlg_x, dlg_y, self.game,
            on_commit=self._on_ix_draw_committed,
            on_geometry_change=self._on_ix_draw_geometry,
        )
        self._ix_draw_dialog = dlg
        dlg.set_on_close(lambda d: self._exit_ix_draw())
        self._dialog_manager.open(dlg)
        self._update_ix_draw_hover()

    def _exit_ix_draw(self) -> None:
        if self._ix_draw is None and self._ix_draw_dialog is None:
            return
        dlg = self._ix_draw_dialog
        self._ix_draw = None
        self._ix_center = None
        self._ix_size = None
        self._ix_draw_dialog = None
        self._toolbar.active_action = None
        self._sync_toolbar_bottom()
        if dlg is not None:
            self._dialog_manager.close(dlg)

    def _on_ix_draw_committed(self) -> None:
        self._on_config_change()
        self._exit_ix_draw()

    def _on_ix_draw_geometry(self, center: tuple[int, int], size: int) -> None:
        if not self._ix_draw:
            return
        self._ix_center = center
        self._ix_size = size

    def _sync_ix_dialog_geometry(self) -> None:
        if self._ix_draw_dialog is None or self._ix_center is None or self._ix_size is None:
            return
        self._ix_draw_dialog.set_geometry(self._ix_center, self._ix_size)

    def _update_ix_draw_hover(self) -> None:
        if not self._ix_draw:
            return
        cell = self._grid_cell_at(self._mouse_x, self._mouse_y)
        if self._ix_draw == "center":
            self._ix_center = cell
            self._ix_size = 2
        elif self._ix_center is not None:
            self._ix_size = intersection_size_for_hover(self._ix_center, cell)
        self._sync_ix_dialog_geometry()

    def _finish_ix_from_map(self) -> None:
        center = self._ix_center
        size = self._ix_size
        dlg = self._ix_draw_dialog
        if center is None or size is None or dlg is None:
            self._exit_ix_draw()
            return
        size = max(2, min(12, int(size)))
        if size % 2 != 0:
            size = (size // 2) * 2
        if size < 2:
            size = 2
        self.game.intersections[dlg._key] = places.IntersectionConfig(
            intersection_type=dlg.current_type(),
            center_x=center[0],
            center_y=center[1],
            size_cells=size,
        )
        self._on_config_change(rebuild_world=True)
        self._exit_ix_draw()

    def _draw_ix_preview(self, center_x: float, center_y: float) -> None:
        if not self._ix_draw or not self._mouse_in_window:
            return
        center = self._ix_center
        size = self._ix_size
        if center is None or size is None:
            return
        tex = self._tile_set.get("road_cross")
        if tex is None:
            return
        x_lo, x_hi, y_lo, y_hi = bounds_from_center(center[0], center[1], size)
        cells = [(gx, gy) for gx in range(x_lo, x_hi) for gy in range(y_lo, y_hi)]
        if not cells:
            return
        lst = arcade.SpriteList()
        for gx, gy in cells:
            spr = arcade.Sprite(tex, scale=self._zoom_scale)
            spr.center_x, spr.center_y = self._to_screen(gx, gy, center_x, center_y)
            spr.alpha = 170
            lst.append(spr)
        lst.draw(pixelated=True)

    def _infra_occupancy_cells(self, dlg):
        if isinstance(dlg, PlaceVarsDialog):
            return places.place_bounds(dlg.place)
        if isinstance(dlg, LaneVarsDialog):
            return world.get_lane_cells(dlg.lane_index)
        if isinstance(dlg, IntersectionVarsDialog):
            return world.get_intersection_cells_by_key(dlg.intersection_key)
        return None

    def _draw_infra_selection_rims(self, center_x: float, center_y: float) -> None:
        half_w = TILE_W * self._zoom_scale
        half_h = TILE_H * self._zoom_scale

        def cell_center(gx: int, gy: int) -> tuple[float, float]:
            return self._to_screen(gx, gy, center_x, center_y)

        shadows: list = []
        highlights: list = []
        for dlg in self._dialog_manager.iter_open():
            cells = self._infra_occupancy_cells(dlg)
            if not cells:
                continue
            aabb = occupancy_aabb(cells)
            if aabb is None:
                continue
            x_lo, y_lo, w, h = aabb
            poly = iso_aabb_silhouette(x_lo, y_lo, w, h, cell_center, half_w, half_h)
            s, hlt = rim_quads(poly)
            shadows.extend(s)
            highlights.extend(hlt)
        if not shadows and not highlights:
            return
        ctx = self.ctx
        prev = ctx.blend_func
        try:
            ctx.blend_func = (ctx.DST_COLOR, ctx.ZERO)
            for pts, color in shadows:
                arcade.draw_polygon_filled(pts, color)
            ctx.blend_func = (ctx.ONE, ctx.ONE_MINUS_SRC_COLOR)
            for pts, color in highlights:
                arcade.draw_polygon_filled(pts, color)
        finally:
            ctx.blend_func = prev

    def _update_zoom_scale(self) -> None:
        """Compute zoom scale from current zoom level and window size."""
        map_w = (world.get_grid_w() + world.get_grid_h()) * TILE_W
        map_h = (world.get_grid_w() + world.get_grid_h()) * TILE_H
        scale_min = min(self.width / map_w, self.height / map_h)
        scale_max = self.height / (4 * 2 * TILE_H)
        level = max(0, min(ZOOM_LEVEL_MAX, self._zoom_level))
        if scale_max <= scale_min or level == 0:
            self._zoom_scale = scale_min
        else:
            self._zoom_scale = scale_min * (scale_max / scale_min) ** (level / ZOOM_LEVEL_MAX)

    def _effective_center(self) -> tuple[float, float]:
        return (self.width / 2 - self._cam_x, self.height / 2 - self._cam_y)

    def _clamp_camera_bounds(self) -> None:
        """Clamp _cam_x, _cam_y so the map cannot be panned to infinity."""
        z = self._zoom_scale
        map_w = (world.get_grid_w() + world.get_grid_h() - 2) * TILE_W * z * 1.5
        map_h = (world.get_grid_w() + world.get_grid_h() - 2) * TILE_H * z * 1.5
        max_cam_x = max(0, map_w / 2 - self.width / 2)
        max_cam_y = max(0, map_h / 2 - self.height / 2)
        self._cam_x = max(-max_cam_x, min(max_cam_x, self._cam_x))
        self._cam_y = max(-max_cam_y, min(max_cam_y, self._cam_y))

    def _to_screen(self, gx: float, gy: float, center_x: float, center_y: float) -> tuple[float, float]:
        x_lo, y_lo, x_hi, y_hi = world.get_bounds()
        return grid_to_screen(gx, gy, center_x, center_y, x_lo, y_lo, x_hi, y_hi, self._zoom_scale)

    def _screen_to_grid(self, sx: float, sy: float, center_x: float, center_y: float) -> tuple[float, float]:
        x_lo, y_lo, x_hi, y_hi = world.get_bounds()
        return screen_to_grid(sx, sy, center_x, center_y, x_lo, y_lo, x_hi, y_hi, self._zoom_scale)

    def _lane_road_type(self, lane_index: int) -> str:
        """Return texture key for lane base tile (normal/passing)."""
        direction = world.lane_direction(lane_index)
        if direction == "N":
            base = "road_n"
        elif direction == "S":
            base = "road_s"
        elif direction == "E":
            base = "road_e"
        elif direction == "W":
            base = "road_w"
        else:
            base = "road_n"
        cfg = self.game.lanes.get(lane_index)
        suffix = "_pass" if cfg and cfg.lane_type == places.LANE_TYPE_PASSING else ""
        return base + suffix if self._tile_set.get(base + suffix) else base

    def _build_lane_cell_to_road(self) -> dict[tuple[int, int], str]:
        lane_cell_to_road: dict[tuple[int, int], str] = {}
        for lane_index in world.lane_ids():
            lane = world.get_lane_cells(lane_index)
            road_type = self._lane_road_type(lane_index)
            for gx, gy in lane:
                lane_cell_to_road[(gx, gy)] = road_type
        return lane_cell_to_road

    def _collect_place_cells(self) -> set[tuple[int, int]]:
        place_cells: set[tuple[int, int]] = set()
        for place in world.get_place_rects():
            place_cells.update(places.place_bounds(place))
        return place_cells

    def _append_sprite_at(self, tex: arcade.Texture | None, gx: float, gy: float, center_x: float, center_y: float) -> None:
        if tex is None or self._tile_sprite_list is None:
            return
        sx, sy = self._to_screen(gx, gy, center_x, center_y)
        spr = arcade.Sprite(tex, scale=self._zoom_scale)
        spr.center_x, spr.center_y = sx, sy
        self._tile_sprite_list.append(spr)
        self._tile_cells.append((gx, gy))

    def _append_centered_sprite_for_cells(
        self,
        tex: arcade.Texture | None,
        cells: list[tuple[int, int]],
        center_x: float,
        center_y: float,
    ) -> None:
        if tex is None or not cells:
            return
        cx = sum(c[0] for c in cells) / len(cells)
        cy = sum(c[1] for c in cells) / len(cells)
        self._append_sprite_at(tex, cx, cy, center_x, center_y)

    def _overlay_intersection(
        self,
        cells: list[tuple[int, int]],
        centered_overlay_tex: arcade.Texture | None,
        road_cross_tex: arcade.Texture | None,
        center_x: float,
        center_y: float,
    ) -> None:
        if centered_overlay_tex is not None:
            self._append_centered_sprite_for_cells(centered_overlay_tex, cells, center_x, center_y)
            return
        for gx, gy in cells:
            self._append_sprite_at(road_cross_tex, gx, gy, center_x, center_y)

    def _rebuild_static_draw_cache(self, center_x: float, center_y: float) -> None:
        self._cached_center = (center_x, center_y, self._zoom_scale)
        self._tile_cells.clear()

        lane_cell_to_road = self._build_lane_cell_to_road()
        place_cells = self._collect_place_cells()

        self._tile_sprite_list = arcade.SpriteList()
        grass_tex = self._tile_set.get("grass")
        place_zone_tex = self._tile_set.get("place_zone")
        road_tex: dict[str, arcade.Texture | None] = {
            "road_n": self._tile_set.get("road_n"),
            "road_s": self._tile_set.get("road_s"),
            "road_e": self._tile_set.get("road_e"),
            "road_w": self._tile_set.get("road_w"),
            "road_n_pass": self._tile_set.get("road_n_pass"),
            "road_s_pass": self._tile_set.get("road_s_pass"),
            "road_e_pass": self._tile_set.get("road_e_pass"),
            "road_w_pass": self._tile_set.get("road_w_pass"),
        }
        road_cross_tex = self._tile_set.get("road_cross")
        intersection_cells_map = world.get_intersection_cells_map()
        all_inter_cells = {c for cells in intersection_cells_map.values() for c in cells}
        x_lo, y_lo, x_hi, y_hi = world.get_bounds()
        for gy in range(y_lo, y_hi):
            for gx in range(x_lo, x_hi):
                cell = (gx, gy)
                if cell in all_inter_cells:
                    tex = grass_tex  # always grass under intersections; overlay drawn below
                elif cell in lane_cell_to_road:
                    rt = lane_cell_to_road[cell]
                    tex = road_tex.get(rt)
                elif cell in place_cells and place_zone_tex is not None:
                    tex = place_zone_tex
                else:
                    tex = grass_tex
                self._append_sprite_at(tex, gx, gy, center_x, center_y)

        for key, cells in intersection_cells_map.items():
            cfg = self.game.intersections.get(key)
            itype = places.clamp_intersection_type(
                cfg.intersection_type if cfg else places.INTERSECTION_TYPE_CROSS
            )
            size_cells = cfg.size_cells if cfg else 4
            active, _, _ = classify_intersection_sides(key, cells)
            centered_tex: arcade.Texture | None = None
            if itype == places.INTERSECTION_TYPE_NONE:
                pass
            elif itype == places.INTERSECTION_TYPE_CROSS:
                centered_tex = generate_cross_texture(size_cells)
            elif itype == places.INTERSECTION_TYPE_CORNER:
                q = corner_quadrant_for_sides(active)
                centered_tex = generate_corner_texture(size_cells, quadrant=q)
            elif itype == places.INTERSECTION_TYPE_STRAIGHT:
                ax = straight_axis_for_intersection(key, cells, active)
                centered_tex = generate_straight_texture(size_cells, axis=ax)
            elif itype == places.INTERSECTION_TYPE_TEE:
                ax = straight_axis_for_intersection(key, cells, active)
                axis, stem = tee_layout_for_sides(active, through_fallback=ax)
                centered_tex = generate_tee_texture(size_cells, axis=axis, stem=stem)
            self._overlay_intersection(cells, centered_tex, road_cross_tex, center_x, center_y)

        self._rebuild_building_sprites(center_x, center_y)
        self._update_text_positions(center_x, center_y)

    def _update_text_positions(self, center_x: float, center_y: float) -> None:
        """Update place and cardinal text screen positions."""
        for place in world.get_place_rects():
            cells = places.place_bounds(place)
            if not cells:
                continue
            if place not in self._place_texts:
                self._place_texts[place] = arcade.Text(
                    place, 0, 0, color=PLACE_LABEL_COLOR, font_size=PLACE_LABEL_FONT_SIZE,
                    anchor_x="center", anchor_y="center",
                )
            min_gx = min(p[0] for p in cells)
            max_gx = max(p[0] for p in cells)
            min_gy = min(p[1] for p in cells)
            max_gy = max(p[1] for p in cells)
            sx, sy = self._to_screen((min_gx + max_gx + 1) / 2, (min_gy + max_gy + 1) / 2, center_x, center_y)
            self._place_texts[place].x, self._place_texts[place].y = sx, sy

        x_lo, y_lo, x_hi, y_hi = world.get_bounds()
        cx_grid = (x_lo + x_hi - 1) / 2
        cy_grid = (y_lo + y_hi - 1) / 2
        self._cardinal_texts["N"].x, self._cardinal_texts["N"].y = self._to_screen(cx_grid, y_hi - 1, center_x, center_y)
        self._cardinal_texts["S"].x, self._cardinal_texts["S"].y = self._to_screen(cx_grid, y_lo, center_x, center_y)
        self._cardinal_texts["E"].x, self._cardinal_texts["E"].y = self._to_screen(x_hi - 1, cy_grid, center_x, center_y)
        self._cardinal_texts["W"].x, self._cardinal_texts["W"].y = self._to_screen(x_lo, cy_grid, center_x, center_y)

    def _update_tile_positions(self, center_x: float, center_y: float) -> None:
        """Update sprite screen positions without rebuilding. Requires _tile_cells and _tile_sprite_list."""
        if self._tile_sprite_list is not None and self._tile_cells:
            to_screen = self._to_screen
            for i, (gx, gy) in enumerate(self._tile_cells):
                sx, sy = to_screen(gx, gy, center_x, center_y)
                spr = self._tile_sprite_list[i]
                spr.center_x, spr.center_y = sx, sy
        self._update_building_positions(center_x, center_y)

    def _rebuild_building_sprites(self, center_x: float, center_y: float) -> None:
        """Pack lots and allocate sprites when the tile cache rebuilds."""
        packed = pack_all_places(world.get_place_rects(), self.game.places, self._building_defs)
        items: list[tuple[object, arcade.Sprite, object]] = []
        for inst in packed:
            defn = self._building_defs_by_id.get(inst.asset_id)
            tex = self._building_textures.get(inst.asset_id)
            if defn is None or tex is None:
                continue
            scale = natural_sprite_scale(defn) * inst.fit_scale * self._zoom_scale
            spr = arcade.Sprite(tex, scale=scale)
            items.append((inst, spr, defn))
        self._building_draw_items = items
        self._update_building_positions(center_x, center_y)

    def _update_building_positions(self, center_x: float, center_y: float) -> None:
        zoom = self._zoom_scale
        for inst, spr, defn in self._building_draw_items:
            sx, sy = self._to_screen(inst.origin_x, inst.origin_y, center_x, center_y)
            south_sx, south_sy = south_vertex_screen(sx, sy, zoom)
            scale = natural_sprite_scale(defn) * inst.fit_scale * zoom
            spr.scale = scale
            cx, cy = sprite_center_from_anchor(south_sx, south_sy, defn, scale)
            spr.center_x, spr.center_y = cx, cy

    def on_key_press(self, key: int, modifiers: int) -> None:
        fw = self._dialog_manager.get_focused_widget()
        if fw is not None:
            if key == arcade.key.ESCAPE:
                self._dialog_manager.set_focused_widget(None)
                return
            if fw.on_key_press(key):
                if key in (arcade.key.RETURN, arcade.key.TAB):
                    self._dialog_manager.set_focused_widget(None)
                return
        if key == arcade.key.ESCAPE:
            if self._draw_tool_active():
                self._exit_active_draw_tool()
            else:
                self._dialog_manager.close_top()
        elif key == arcade.key.BACKSPACE:
            if self._placement_can_pop():
                self._placement_pop()
        elif key == arcade.key.V:
            self._show_visibility_fans = not self._show_visibility_fans
        elif key == arcade.key.LEFT:
            self._key_left = True
        elif key == arcade.key.RIGHT:
            self._key_right = True
        elif key == arcade.key.UP:
            self._key_up = True
        elif key == arcade.key.DOWN:
            self._key_down = True

    def on_text(self, text: str) -> None:
        fw = self._dialog_manager.get_focused_widget()
        on_text = getattr(fw, "on_text", None) if fw is not None else None
        if callable(on_text):
            on_text(text)

    def on_key_release(self, key: int, modifiers: int) -> None:
        if key == arcade.key.LEFT:
            self._key_left = False
        elif key == arcade.key.RIGHT:
            self._key_right = False
        elif key == arcade.key.UP:
            self._key_up = False
        elif key == arcade.key.DOWN:
            self._key_down = False

    def on_mouse_scroll(self, x: int, y: int, scroll_x: int, scroll_y: int) -> None:
        if self._dialog_manager.contains_point(x, y):
            return
        if scroll_y > 0:
            self._zoom_level = min(ZOOM_LEVEL_MAX, self._zoom_level + 1)
        elif scroll_y < 0:
            self._zoom_level = max(ZOOM_LEVEL_FIT, self._zoom_level - 1)
        self._update_zoom_scale()
        if self._car_sprite_pool is not None:
            self._car_sprite_pool.set_zoom_scale(self._zoom_scale)

    def on_mouse_motion(self, x: float, y: float, dx: float, dy: float) -> None:
        self._mouse_x = x
        self._mouse_y = y
        self._mouse_in_window = True
        if not self._dialog_manager.contains_point(x, y):
            self._update_lane_draw_hover()
            self._update_place_draw_hover()
            self._update_ix_draw_hover()

    def on_mouse_leave(self, x: float, y: float) -> None:
        self._mouse_in_window = False

    def on_resize(self, width: int, height: int) -> None:
        super().on_resize(width, height)
        self._sync_toolbar_bottom()
        self._update_zoom_scale()
        if self._car_sprite_pool is not None:
            self._car_sprite_pool.set_zoom_scale(self._zoom_scale)

    def on_close(self) -> None:
        persistence.save_config(self.game, window=self)
        super().on_close()

    def on_update(self, delta_time: float):
        persistence.tick_debounced_save(self.game, delta_time, window=self)
        if delta_time > 1e-9:
            fps_now = 1.0 / delta_time
            self._fps_ema = fps_now if self._fps_ema <= 0.0 else (0.9 * self._fps_ema + 0.1 * fps_now)
        vx = self._cam_pan_speed if self._key_right else (-self._cam_pan_speed if self._key_left else 0.0)
        vy = self._cam_pan_speed if self._key_up else (-self._cam_pan_speed if self._key_down else 0.0)
        # Edge pan (only when enabled, mouse in window, and not over a dialog; pan toward cursor when near edge)
        if self._edge_pan_enabled and self._mouse_in_window and not self._dialog_manager.contains_point(self._mouse_x, self._mouse_y):
            if self._mouse_x < EDGE_PAN_MARGIN:
                vx -= self._cam_pan_speed
            elif self._mouse_x > self.width - EDGE_PAN_MARGIN:
                vx += self._cam_pan_speed
            if self._mouse_y < EDGE_PAN_MARGIN:
                vy -= self._cam_pan_speed
            elif self._mouse_y > self.height - EDGE_PAN_MARGIN:
                vy += self._cam_pan_speed
        self._cam_x += vx * delta_time
        self._cam_y += vy * delta_time
        self._clamp_camera_bounds()
        self._tick_accumulator += delta_time
        substeps = 0
        while self._tick_accumulator >= TICK_DT and substeps < MAX_SUBSTEPS_PER_FRAME:
            self._sim_time += TICK_DT
            self.game.tick(TICK_DT, self._sim_time, self._move_duration)
            self._tick_accumulator -= TICK_DT
            substeps += 1
        self._last_substeps = substeps
        if substeps >= MAX_SUBSTEPS_PER_FRAME and self._tick_accumulator >= TICK_DT:
            self._tick_accumulator = min(self._tick_accumulator, TICK_DT)

    def on_draw(self):
        draw_start = time.perf_counter()
        self.clear()
        center_x, center_y = self._effective_center()
        cached = self._cached_center
        needs_rebuild = cached is None or cached[2] != self._zoom_scale
        if needs_rebuild:
            self._rebuild_static_draw_cache(center_x, center_y)
        elif (center_x, center_y) != (cached[0], cached[1]):
            self._update_tile_positions(center_x, center_y)
            self._update_text_positions(center_x, center_y)
            self._cached_center = (center_x, center_y, self._zoom_scale)

        grade_world = not is_identity_grade(self._color_hue, self._color_sat)
        if grade_world:
            self._color_grade.begin(self.width, self.height)
            self.default_camera.use()
        self._draw_world_pass(center_x, center_y)
        if grade_world:
            self._color_grade.end_and_blit(self._color_hue, self._color_sat)
            self.use()
            self.default_camera.use()

        for place in world.get_place_rects():
            if places.place_bounds(place):
                if place not in self._place_texts:
                    self._place_texts[place] = arcade.Text(
                        place, 0, 0, color=PLACE_LABEL_COLOR, font_size=PLACE_LABEL_FONT_SIZE,
                        anchor_x="center", anchor_y="center",
                    )
                self._place_texts[place].draw()
        for txt in self._cardinal_texts.values():
            txt.draw()

        draw_ms = (time.perf_counter() - draw_start) * 1000.0
        self._draw_ms_ema = draw_ms if self._draw_ms_ema <= 0.0 else (0.9 * self._draw_ms_ema + 0.1 * draw_ms)
        perf = self.game.get_perf_stats()
        self._perf_text.x = 64 if self._draw_tool_active() else 10
        self._perf_text.y = self.height - 10
        self._perf_text.value = (
            f"FPS~{self._fps_ema:5.1f} substeps:{self._last_substeps} draw:{self._draw_ms_ema:5.2f}ms "
            f"cars:{perf['cars']} tiles:{len(self._tile_sprite_list or [])} tick:{float(perf['tick_ms_ema']):5.2f}ms "
            f"vis:{float(perf['visibility_ms_ema']):5.2f}ms checks:{perf['visibility_checks']} "
            f"pair:{float(perf['pair_ms_ema']):5.2f}ms checks:{perf['pair_checks']}"
        )
        self._perf_text.draw()

        if self._draw_tool_active():
            self._esc_chip.draw(self.width, self.height)
        if self._placement_can_pop():
            self._back_chip.draw(self.width, self.height)
        self._toolbar.draw()
        self._dialog_manager.draw_all()

    def _draw_world_pass(self, center_x: float, center_y: float) -> None:
        """Tiles, draw ghosts, selection rims, cars, visibility fans. Graded as a unit."""
        if self._tile_sprite_list is not None:
            self._tile_sprite_list.draw(pixelated=True)

        self._draw_lane_preview(center_x, center_y)
        self._draw_place_preview(center_x, center_y)
        self._draw_ix_preview(center_x, center_y)
        self._draw_infra_selection_rims(center_x, center_y)

        overlay: list[tuple[float, int, arcade.Sprite]] = []
        for inst, spr, _defn in self._building_draw_items:
            overlay.append((inst.depth, 1, spr))

        if self._car_sprite_pool is not None:
            active_police = [p for p in self.game.police_list if p.state in ("deploying", "holding", "diverting", "returning")]
            car_data: list[tuple[float, object, int, float, float, tuple[int, int, int]]] = []
            for car in self.game.cars:
                if car.pose_gx is None or car.pose_gy is None:
                    curr = car.current_cell()
                    if curr is None:
                        continue
                    gx, gy = float(curr[0]), float(curr[1])
                else:
                    gx, gy = car.pose_gx, car.pose_gy
                sx, sy = self._to_screen(gx, gy, center_x, center_y)
                car_data.append((gx + gy, car, _car_direction_index(car), sx, sy, getattr(car, "color", CAR_DEFAULT)))
            for police in active_police:
                gx, gy, di = police.get_pose()
                sx, sy = self._to_screen(gx, gy, center_x, center_y)
                car_data.append((gx + gy, police, di, sx, sy, police.get_light_color()))
            car_data.sort(key=lambda t: t[0], reverse=True)
            self._car_draw_order = [t[1] for t in car_data]
            self._car_sprite_pool.begin_frame(len(car_data))
            for idx, (depth, _, di, sx, sy, color) in enumerate(car_data):
                self._car_sprite_pool.set_sprite(idx, di, sx, sy, color)
                overlay.append((depth, 0, self._car_sprite_pool.sprite_at(idx)))
        overlay.sort(key=lambda t: (t[0], t[1]), reverse=True)
        for _, _, spr in overlay:
            arcade.draw_sprite(spr, pixelated=True)

        if self._show_visibility_fans:
            half = VIS_ZONE_WIDTH_CELLS / 2.0
            for car in self.game.cars:
                gx = car.pose_gx
                gy = car.pose_gy
                di = car.pose_dir_index_8
                if gx is None or gy is None:
                    curr = car.current_cell()
                    if curr is None:
                        continue
                    gx, gy = float(curr[0]), float(curr[1])
                verts = visibility_fan_vertices(gx, gy, di, VIS_ZONE_LENGTH_CELLS, half)
                state = car.visibility_state
                fan_color = VIS_ZONE_COLOR_RED if state == "red" else VIS_ZONE_COLOR_YELLOW if state == "yellow" else VIS_ZONE_COLOR_WHITE if state == "white" else VIS_ZONE_COLOR_CYAN if state == "cyan" else VIS_ZONE_COLOR
                screen_pts = [self._to_screen(vx, vy, center_x, center_y) for vx, vy in verts]
                arcade.draw_polygon_outline(screen_pts, fan_color, VIS_ZONE_LINE_WIDTH)

    def _on_color_grade_change(self, hue: int, sat: float) -> None:
        self._color_hue = clamp_color_hue(hue)
        self._color_sat = clamp_color_sat(sat)
        persistence.request_debounced_save()

    def _place_at_screen(self, sx: float, sy: float) -> str | None:
        """Return place name if (sx, sy) screen coords hit a place, else None."""
        center_x, center_y = self._effective_center()
        gx, gy = self._screen_to_grid(sx, sy, center_x, center_y)
        cell = (int(round(gx)), int(round(gy)))
        for place in world.get_place_rects():
            if cell in places.place_bounds(place):
                return place
        return None

    def _car_at_screen(self, sx: float, sy: float):
        """Return car if (sx, sy) hits a car sprite, else None. Checks topmost first."""
        if self._car_sprite_pool is None or not self._car_draw_order:
            return None
        n = len(self._car_draw_order)
        for i in range(n - 1, -1, -1):
            spr = self._car_sprite_pool._pool[i]
            if spr.alpha > 0 and spr.left <= sx <= spr.right and spr.bottom <= sy <= spr.top:
                entity = self._car_draw_order[i]
                return entity if entity in self.game.cars else None
        return None

    def _lane_at_screen(self, sx: float, sy: float) -> int | None:
        """Return stable lane id if (sx, sy) hits a lane cell, else None. Skips intersection cells."""
        center_x, center_y = self._effective_center()
        gx, gy = self._screen_to_grid(sx, sy, center_x, center_y)
        cell = (int(round(gx)), int(round(gy)))
        if world.get_intersection_at_cell(cell) is not None:
            return None
        for i in world.lane_ids():
            lane = world.get_lane_cells(i)
            if cell in lane:
                return i
        return None

    def _intersection_at_screen(self, sx: float, sy: float) -> str | None:
        """Return 'main', 'bypass', or extra intersection key if (sx, sy) hits an intersection cell, else None."""
        center_x, center_y = self._effective_center()
        gx, gy = self._screen_to_grid(sx, sy, center_x, center_y)
        cell = (int(round(gx)), int(round(gy)))
        return world.get_intersection_at_cell(cell)

    def on_mouse_press(self, x: float, y: float, button: int, modifiers: int):
        if button == arcade.MOUSE_BUTTON_LEFT:
            if not self._dialog_manager.contains_point(x, y):
                self._dialog_manager.set_focused_widget(None)
            if self._dialog_manager.on_mouse_press(x, y):
                return
            if self._draw_tool_active() and self._esc_chip.contains(x, y, self.width, self.height):
                self._exit_active_draw_tool()
                return
            if self._placement_can_pop() and self._back_chip.contains(x, y, self.width, self.height):
                self._placement_pop()
                return
            toolbar_action = self._toolbar.on_press(x, y)
            if toolbar_action == "new_lane":
                if self._lane_draw:
                    self._exit_lane_draw()
                else:
                    self._exit_active_draw_tool()
                    self._enter_lane_draw()
                return
            if toolbar_action == "new_place":
                if self._place_draw:
                    self._exit_place_draw()
                else:
                    self._exit_active_draw_tool()
                    self._enter_place_draw()
                return
            if toolbar_action == "new_intersection":
                if self._ix_draw:
                    self._exit_ix_draw()
                else:
                    self._exit_active_draw_tool()
                    self._enter_ix_draw()
                return
            if toolbar_action and self._draw_tool_active():
                self._exit_active_draw_tool()
            if toolbar_action == "settings":
                dlg_x = TOOLBAR_LEFT + 56
                dlg_y = self.height / 2 + 100
                dlg = SettingsDialog(
                    dlg_x, dlg_y,
                    edge_pan_enabled=self._edge_pan_enabled,
                    grass_close_enabled=self._grass_close_enabled,
                    color_hue=self._color_hue,
                    color_sat=self._color_sat,
                    on_edge_pan_change=lambda v: (
                        setattr(self, "_edge_pan_enabled", v),
                        persistence.request_debounced_save(),
                    ),
                    on_grass_close_change=lambda v: (
                        setattr(self, "_grass_close_enabled", v),
                        persistence.request_debounced_save(),
                    ),
                    on_color_change=self._on_color_grade_change,
                )
                dlg.set_on_close(lambda d: self._dialog_manager.close(d))
                self._dialog_manager.open(dlg)
                return
            if self._lane_draw:
                cell = self._grid_cell_at(x, y)
                if not self._cell_on_map(cell):
                    self._exit_lane_draw()
                    return
                if self._lane_draw == "start":
                    self._lane_draw_start = cell
                    self._lane_draw_end = cell
                    self._lane_draw = "end"
                    if self._lane_draw_dialog is not None:
                        self._lane_draw_dialog.set_tiles(cell, cell)
                    return
                end = snap_cardinal_end(self._lane_draw_start or cell, cell)
                self._lane_draw_end = end
                self._finish_lane_from_map()
                return
            if self._place_draw:
                cell = self._grid_cell_at(x, y)
                if not self._cell_on_map(cell):
                    self._exit_place_draw()
                    return
                if self._place_draw == "c1":
                    self._place_c1 = cell
                    self._place_aabb = aabb_from_corners(cell, cell)
                    self._place_draw = "c2"
                    self._sync_place_dialog_geometry()
                    return
                if self._place_draw == "c2":
                    c1 = self._place_c1 or cell
                    same_x = cell[0] == c1[0]
                    same_y = cell[1] == c1[1]
                    if same_x and same_y:
                        self._finish_place_from_aabb(aabb_from_corners(c1, cell))
                        return
                    if same_x or same_y:
                        self._place_c2 = cell
                        self._place_draw = "c3"
                        self._place_aabb = aabb_from_edge_and_hover(c1, cell, cell)
                        self._sync_place_dialog_geometry()
                        return
                    self._finish_place_from_aabb(aabb_from_corners(c1, cell))
                    return
                c1 = self._place_c1 or cell
                c2 = self._place_c2 or cell
                self._finish_place_from_aabb(aabb_from_edge_and_hover(c1, c2, cell))
                return
            if self._ix_draw:
                cell = self._grid_cell_at(x, y)
                if not self._cell_on_map(cell):
                    self._exit_ix_draw()
                    return
                if self._ix_draw == "center":
                    self._ix_center = cell
                    self._ix_size = 2
                    self._ix_draw = "size"
                    self._sync_ix_dialog_geometry()
                    return
                self._ix_size = intersection_size_for_hover(self._ix_center or cell, cell)
                self._sync_ix_dialog_geometry()
                self._finish_ix_from_map()
                return
            place = self._place_at_screen(x, y)
            if place is not None:
                if place in self._place_dialogs:
                    self._dialog_manager.open(self._place_dialogs[place])
                else:
                    dlg = PlaceVarsDialog(
                        x - 120, y - 130, place,
                        self.game.places[place],
                        game=self.game,
                        on_change=self._on_config_change,
                        on_commit=lambda: self._on_config_change(rebuild_world=True),
                        on_rename=self._on_place_renamed,
                        on_remove=lambda: (
                            self._on_config_change(),
                            self._place_dialogs.pop(dlg.place, None),
                            self._place_texts.pop(dlg.place, None),
                            self._dialog_manager.close(dlg),
                        ),
                    )
                    self._place_dialogs[place] = dlg
                    dlg.set_on_close(lambda d: self._dialog_manager.close(d))
                    self._dialog_manager.open(dlg)
                return
            car = self._car_at_screen(x, y)
            if car is not None:
                dlg = CarDeetsDialog(x - 100, y - 45, car, self.game)
                dlg.set_on_close(lambda d: self._dialog_manager.close(d))
                self._dialog_manager.open(dlg)
                return
            lane_idx = self._lane_at_screen(x, y)
            if lane_idx is not None and lane_idx in self.game.lanes:
                if lane_idx in self._lane_dialogs:
                    self._dialog_manager.open(self._lane_dialogs[lane_idx])
                else:
                    dlg = LaneVarsDialog(
                        x - 110, y - 70, lane_idx,
                        self.game.lanes[lane_idx],
                        game=self.game,
                        on_change=lambda: self._on_config_change(rebuild_world=True),
                        on_remove=lambda: (
                            self._on_config_change(),
                            self._lane_dialogs.pop(lane_idx, None),
                            self._dialog_manager.close(dlg),
                        ),
                    )
                    self._lane_dialogs[lane_idx] = dlg
                    dlg.set_on_close(lambda d: self._dialog_manager.close(d))
                    self._dialog_manager.open(dlg)
                return
            inter_key = self._intersection_at_screen(x, y)
            if inter_key is not None:
                if inter_key in self._intersection_dialogs:
                    self._dialog_manager.open(self._intersection_dialogs[inter_key])
                else:
                    dlg = IntersectionVarsDialog(
                        x - 110, y - 50, inter_key,
                        self.game.intersections[inter_key],
                        game=self.game,
                        on_commit=lambda: self._on_config_change(rebuild_world=True),
                        on_remove=lambda: (
                            self._on_config_change(),
                            self._intersection_dialogs.pop(inter_key, None),
                            self._dialog_manager.close(dlg),
                        ),
                    )
                    self._intersection_dialogs[inter_key] = dlg
                    dlg.set_on_close(lambda d: self._dialog_manager.close(d))
                    self._dialog_manager.open(dlg)
                return
            if self._grass_close_enabled and self._cell_is_grass(self._grid_cell_at(x, y)):
                self._dialog_manager.close_all()
                return

    def on_mouse_drag(self, x: float, y: float, dx: float, dy: float, buttons: int, modifiers: int):
        if buttons & arcade.MOUSE_BUTTON_LEFT:
            self._dialog_manager.on_mouse_drag(x, y, dx, dy)

    def on_mouse_release(self, x: float, y: float, button: int, modifiers: int):
        if button == arcade.MOUSE_BUTTON_LEFT:
            self._dialog_manager.on_mouse_release(x, y)


def main():
    StoplightsWindow()
    arcade.run()


if __name__ == "__main__":
    main()
