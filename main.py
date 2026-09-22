"""
Stoplights entry point and window orchestration.
"""
import time
from pathlib import Path

import arcade

from render.camera import (
    cardinal_label_anchors,
    display_dir_index,
    grid_to_screen,
    iso_depth,
    road_tile_key,
    screen_to_grid,
    view_south_cell,
)
from render.color_grade import WorldColorGrade, is_identity_grade
from render.debug import visibility_fan_vertices
from render.selection import iso_aabb_silhouette, occupancy_aabb, rim_quads
from render.sprites import CarSpritePool, load_car_textures
from render.lane_paint import paint_spec
from render.intersection_topology import (
    classify_intersection_sides,
    mixed_corner_leftovers,
    mouth_spans_by_edge,
    mouth_spans_local,
    overlay_type_for_sides,
    straight_axis_for_intersection,
    tee_layout_for_sides,
)
from render.tiles import (
    TileSet,
    generate_lane_paint_texture,
    generate_mixed_texture,
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
from sim.cars import nearest_car_in_radius
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
from ui.font import load_ui_font, ui_text
from ui.theme import set_ui_grade
from ui import (
    CameraController,
    CameraTool,
    CreateIntersectionTool,
    CreateLaneTool,
    CreatePlaceTool,
    DialogManager,
    FlashHint,
    IntersectionVarsDialog,
    LaneVarsDialog,
    PlaceVarsDialog,
    SelectTool,
    SettingsDialog,
    SkeuoKeyChip,
    Toolbar,
    ToolManager,
    TOOLBAR_BOTTOM_DRAW,
    TOOLBAR_BOTTOM_IDLE,
    TOOLBAR_HINT_GAP,
    TOOLBAR_LEFT,
    hint_for,
    hotkey_for_key,
)
from ui.chrome.camera_icons import draw_pan_arrows

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


def _car_direction_index(car) -> int:
    if getattr(car, "pose_dir_index_8", None) is not None:
        return int(car.pose_dir_index_8) % 8
    d = world.lane_direction(getattr(car, "lane_index", -1))
    direction_map = {"N": 0, "E": 2, "S": 4, "W": 6}
    return direction_map.get(d, 0)


class StoplightsWindow(arcade.Window):
    def __init__(self):
        super().__init__(800, 600, "Stoplights", resizable=True)
        load_ui_font()
        arcade.set_background_color(arcade.color.BLACK)
        self.game = GameState()
        self._edge_pan_enabled = True
        self._grass_close_enabled = True
        self._police_enabled = True
        self._color_hue = 0
        self._color_sat = 1.0
        self._color_grade = WorldColorGrade(self.ctx)
        persistence.load_config(self.game, window=self)
        self.game.police_enabled = self._police_enabled
        set_ui_grade(self._color_hue, self._color_sat)
        self.game.rebuild_world_from_config()
        self._tick_accumulator = 0.0
        self._sim_time = 0.0
        self._move_duration = MOVE_DURATION_BASE

        self._cached_center: tuple[float, float, float, int] | None = None
        self._place_texts: dict[str, arcade.Text] = {}
        self._cardinal_texts: dict[str, arcade.Text] = {}

        for place in self.game.spawn_places:
            self._place_texts[place] = ui_text(place, 0, 0, color=PLACE_LABEL_COLOR, size=PLACE_LABEL_FONT_SIZE, anchor_x="center", anchor_y="center")
        self._cardinal_texts = {
            "N": ui_text("N", 0, 0, color=PLACE_LABEL_COLOR, size=PLACE_LABEL_FONT_SIZE, anchor_x="center", anchor_y="bottom"),
            "S": ui_text("S", 0, 0, color=PLACE_LABEL_COLOR, size=PLACE_LABEL_FONT_SIZE, anchor_x="center", anchor_y="top"),
            "E": ui_text("E", 0, 0, color=PLACE_LABEL_COLOR, size=PLACE_LABEL_FONT_SIZE, anchor_x="right", anchor_y="center"),
            "W": ui_text("W", 0, 0, color=PLACE_LABEL_COLOR, size=PLACE_LABEL_FONT_SIZE, anchor_x="left", anchor_y="center"),
        }
        self._perf_text = ui_text("", 10, self.height - 10, color=PLACE_LABEL_COLOR, size=11, anchor_x="left", anchor_y="top")

        self._fps_ema = 0.0
        self._last_substeps = 0
        self._draw_ms_ema = 0.0
        self._show_visibility_fans = False

        self._dialog_manager = DialogManager(get_window_size=lambda: (self.width, self.height))
        self._place_dialogs: dict[str, PlaceVarsDialog] = {}
        self._lane_dialogs: dict[int, LaneVarsDialog] = {}
        self._intersection_dialogs: dict[str, IntersectionVarsDialog] = {}
        self._toolbar = Toolbar(TOOLBAR_LEFT, self.height - TOOLBAR_BOTTOM_IDLE)
        self._esc_chip = SkeuoKeyChip(hint_for("escape", "Esc"), side="left")
        self._back_chip = SkeuoKeyChip(hint_for("placement_pop", "<-"), side="right")
        self._select_hint = FlashHint()
        self._hint_action = "select"
        self._camera = CameraController()
        self._space_pan: str | None = None
        self._held_hotkeys: set[str] = set()
        self._mouse_x = 0.0
        self._mouse_y = 0.0
        self._mouse_in_window = False
        self._tool_manager = ToolManager(self, SelectTool(self))
        self._tool_manager.register("camera", CameraTool(self))
        self._tool_manager.register("new_lane", CreateLaneTool(self))
        self._tool_manager.register("new_place", CreatePlaceTool(self))
        self._tool_manager.register("new_intersection", CreateIntersectionTool(self))
        self._dialog_manager.on_isolate_toggle = self._toggle_dialog_isolate
        self._dialog_manager.on_empty = self._clear_dialog_isolate

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

    def _close_map_dialogs(self) -> None:
        for dlg in list(self._dialog_manager.iter_open()):
            if isinstance(dlg, SettingsDialog):
                continue
            dlg.dismiss()
        self._place_dialogs.clear()
        self._lane_dialogs.clear()
        self._intersection_dialogs.clear()
        self._place_texts.clear()

    def _on_save_map(self, name: str) -> bool:
        return persistence.save_named_map(self.game, name, window=self) is not None

    def _on_load_map(self, name: str) -> bool:
        if not persistence.load_named_map(self.game, name, window=self):
            return False
        self._close_map_dialogs()
        self._on_config_change(rebuild_world=True)
        return True

    def _on_new_game(self) -> None:
        persistence.new_game(self.game, window=self)
        self._close_map_dialogs()
        self._on_config_change(rebuild_world=True)

    def _on_place_renamed(self, old: str, new: str) -> None:
        """Rekey open dialog and map label after a place id change."""
        dlg = self._place_dialogs.pop(old, None)
        if dlg is not None:
            self._place_dialogs[new] = dlg
        label = self._place_texts.pop(old, None)
        if label is not None:
            label.value = new
            self._place_texts[new] = label

    @property
    def mouse_x(self) -> float:
        return self._mouse_x

    @property
    def mouse_y(self) -> float:
        return self._mouse_y

    @property
    def mouse_in_window(self) -> bool:
        return self._mouse_in_window

    @property
    def zoom_scale(self) -> float:
        return self._camera.zoom_scale

    @property
    def view_yaw_q(self) -> int:
        return self._camera.view_yaw_q

    @property
    def _zoom_scale(self) -> float:
        return self._camera.zoom_scale

    @_zoom_scale.setter
    def _zoom_scale(self, value: float) -> None:
        self._camera.zoom_scale = value

    @property
    def _cam_x(self) -> float:
        return self._camera.cam_x

    @_cam_x.setter
    def _cam_x(self, value: float) -> None:
        self._camera.cam_x = value

    @property
    def _cam_y(self) -> float:
        return self._camera.cam_y

    @_cam_y.setter
    def _cam_y(self, value: float) -> None:
        self._camera.cam_y = value

    @property
    def _zoom_level(self) -> int:
        return self._camera.zoom_level

    @_zoom_level.setter
    def _zoom_level(self, value: int) -> None:
        self._camera.zoom_level = value

    @property
    def grass_close_enabled(self) -> bool:
        return self._grass_close_enabled

    @property
    def dialogs(self):
        return self._dialog_manager

    @property
    def toolbar(self):
        return self._toolbar

    @property
    def tile_set(self):
        return self._tile_set

    @property
    def tool_manager(self) -> ToolManager:
        return self._tool_manager

    @property
    def window_size(self) -> tuple[float, float]:
        return (self.width, self.height)

    def grid_cell_at(self, sx: float, sy: float) -> tuple[int, int]:
        return self._grid_cell_at(sx, sy)

    def cell_on_map(self, cell: tuple[int, int]) -> bool:
        return self._cell_on_map(cell)

    def cell_is_grass(self, cell: tuple[int, int]) -> bool:
        return self._cell_is_grass(cell)

    def to_screen(self, gx: float, gy: float, center_x: float, center_y: float) -> tuple[float, float]:
        return self._to_screen(gx, gy, center_x, center_y)

    @property
    def pan_fly(self) -> bool:
        return self._camera.pan_fly

    @property
    def space_panning(self) -> bool:
        return self._space_pan is not None

    def toggle_pan_fly(self) -> str:
        self._camera.pan_fly = not self._camera.pan_fly
        if self._space_pan is not None:
            self._stop_space_pan()
            self._start_space_pan()
        elif not self._camera.pan_fly:
            self.end_camera_fly()
        return "Fly" if self._camera.pan_fly else "Grab"

    def begin_camera_grab(self, x: float, y: float) -> None:
        self._camera.begin_grab(x, y, self.width, self.height)

    def update_camera_grab(self, x: float, y: float) -> None:
        self._camera.update_grab(x, y, self.width, self.height)

    def end_camera_grab(self) -> None:
        self._camera.end_grab()

    def begin_camera_fly(self, x: float, y: float) -> None:
        self._camera.begin_fly(x, y)

    def end_camera_fly(self) -> None:
        self._camera.end_fly()

    def begin_zoom_drag(self, x: float, y: float) -> None:
        gx, gy = self._screen_to_grid(x, y, *self._effective_center())
        self._camera.begin_zoom_drag(y, gx, gy)

    def update_zoom_drag(self, x: float, y: float) -> None:
        if self._camera.update_zoom_drag(y, x, y, self.width, self.height):
            if self._car_sprite_pool is not None:
                self._car_sprite_pool.set_zoom_scale(self._zoom_scale)

    def end_zoom_drag(self) -> None:
        self._camera.end_zoom_drag()

    def orbit_camera_at(self, x: float, y: float, clockwise: bool) -> None:
        self._camera.orbit_at(x, y, clockwise, self.width, self.height)
        self._invalidate_draw_cache()

    def orbit_camera_about_cursor(self, clockwise: bool) -> None:
        self._camera.orbit_about(
            self._mouse_x, self._mouse_y, clockwise, self.width, self.height
        )
        self._invalidate_draw_cache()

    def zoom_camera_at_cursor(self, zoom_in: bool) -> None:
        scroll = 1 if zoom_in else -1
        if self._camera.handle_scroll(scroll, self._mouse_x, self._mouse_y, self.width, self.height):
            if self._car_sprite_pool is not None:
                self._car_sprite_pool.set_zoom_scale(self._zoom_scale)

    def _start_space_pan(self) -> None:
        if self._camera.pan_fly:
            self.begin_camera_fly(self._mouse_x, self._mouse_y)
            self._space_pan = "fly"
        else:
            self.begin_camera_grab(self._mouse_x, self._mouse_y)
            self._space_pan = "grab"

    def _stop_space_pan(self) -> None:
        if self._space_pan == "fly":
            self.end_camera_fly()
        elif self._space_pan == "grab":
            self.end_camera_grab()
        self._space_pan = None

    def _show_tool_hint(self, action: str, label: str | None) -> None:
        if not label:
            return
        self._hint_action = action
        self._select_hint.show(label)

    def _toggle_dialog_isolate(self) -> None:
        sel = self._tool_manager.select
        if not hasattr(sel, "isolate"):
            return
        sel.isolate = not bool(sel.isolate)
        self._show_tool_hint("select", "Isolate" if sel.isolate else "Default")

    def _clear_dialog_isolate(self) -> None:
        sel = self._tool_manager.select
        if getattr(sel, "isolate", False):
            sel.isolate = False

    def on_config_change(self, rebuild_world: bool = False) -> None:
        self._on_config_change(rebuild_world=rebuild_world)

    def sync_toolbar_bottom(self) -> None:
        self._sync_toolbar_bottom()

    def place_at_screen(self, sx: float, sy: float) -> str | None:
        return self._place_at_screen(sx, sy)

    def car_at_screen(self, sx: float, sy: float):
        return self._car_at_screen(sx, sy)

    def nearest_car_at_screen(self, sx: float, sy: float):
        center_x, center_y = self._effective_center()
        gx, gy = self._screen_to_grid(sx, sy, center_x, center_y)
        return nearest_car_in_radius(self.game.cars, gx, gy)

    def lane_at_screen(self, sx: float, sy: float) -> int | None:
        return self._lane_at_screen(sx, sy)

    def intersection_at_screen(self, sx: float, sy: float) -> str | None:
        return self._intersection_at_screen(sx, sy)

    def on_place_renamed(self, old: str, new: str) -> None:
        self._on_place_renamed(old, new)

    def forget_place_dialog(self, place: str) -> None:
        self._place_dialogs.pop(place, None)
        self._place_texts.pop(place, None)

    def forget_lane_dialog(self, lane_idx: int) -> None:
        self._lane_dialogs.pop(lane_idx, None)

    def forget_intersection_dialog(self, key: str) -> None:
        self._intersection_dialogs.pop(key, None)

    def cached_place_dialog(self, place: str):
        return self._place_dialogs.get(place)

    def store_place_dialog(self, place: str, dlg) -> None:
        self._place_dialogs[place] = dlg

    def cached_lane_dialog(self, lane_idx: int):
        return self._lane_dialogs.get(lane_idx)

    def store_lane_dialog(self, lane_idx: int, dlg) -> None:
        self._lane_dialogs[lane_idx] = dlg

    def cached_intersection_dialog(self, key: str):
        return self._intersection_dialogs.get(key)

    def store_intersection_dialog(self, key: str, dlg) -> None:
        self._intersection_dialogs[key] = dlg

    def _sync_toolbar_bottom(self) -> None:
        inset = TOOLBAR_BOTTOM_DRAW if self._draw_tool_active() else TOOLBAR_BOTTOM_IDLE
        self._toolbar.bottom = self.height - inset

    def _draw_tool_active(self) -> bool:
        return self._tool_manager.is_create_active()

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

    def _exit_active_draw_tool(self) -> None:
        self._tool_manager.activate_inspect()

    def _placement_can_pop(self) -> bool:
        return self._tool_manager.active.can_pop()

    def _placement_pop(self) -> None:
        self._tool_manager.active.pop()

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
        try:
            ctx.enable(ctx.BLEND)
            ctx.blend_func = (ctx.DST_COLOR, ctx.ZERO)
            for pts, color in shadows:
                arcade.draw_polygon_filled(pts, color)
            ctx.enable(ctx.BLEND)
            ctx.blend_func = (ctx.ONE, ctx.ONE_MINUS_SRC_COLOR)
            for pts, color in highlights:
                arcade.draw_polygon_filled(pts, color)
        finally:
            self._reset_world_blend()

    def _reset_world_blend(self) -> None:
        """Arcade polygon draws disable blending; sprites need it back."""
        ctx = self.ctx
        ctx.enable(ctx.BLEND)
        ctx.blend_func = ctx.BLEND_DEFAULT

    def _update_zoom_scale(self) -> None:
        """Compute zoom scale from current zoom level and window size."""
        self._camera.update_zoom_scale(self.width, self.height)

    def _effective_center(self) -> tuple[float, float]:
        return self._camera.effective_center(self.width, self.height)

    def _clamp_camera_bounds(self) -> None:
        """Clamp camera so the map cannot be panned to infinity."""
        self._camera.clamp(self.width, self.height)

    def _to_screen(self, gx: float, gy: float, center_x: float, center_y: float) -> tuple[float, float]:
        x_lo, y_lo, x_hi, y_hi = world.get_bounds()
        return grid_to_screen(
            gx, gy, center_x, center_y, x_lo, y_lo, x_hi, y_hi,
            self._zoom_scale, self._camera.view_yaw_q,
        )

    def _screen_to_grid(self, sx: float, sy: float, center_x: float, center_y: float) -> tuple[float, float]:
        x_lo, y_lo, x_hi, y_hi = world.get_bounds()
        return screen_to_grid(
            sx, sy, center_x, center_y, x_lo, y_lo, x_hi, y_hi,
            self._zoom_scale, self._camera.view_yaw_q,
        )

    def _lane_cell_texture(self, lane_index: int, gx: int, gy: int) -> arcade.Texture | None:
        heading = world.lane_direction(lane_index) or "N"
        display_dir, role_a, role_b, phase = paint_spec(
            heading, gx, gy, self._camera.view_yaw_q,
        )
        tex = generate_lane_paint_texture(display_dir, role_a, role_b, phase)
        if tex is not None:
            return tex
        return self._tile_set.get(road_tile_key(heading, self._camera.view_yaw_q))

    def _build_lane_cell_to_tex(self) -> dict[tuple[int, int], arcade.Texture | None]:
        lane_cell_to_tex: dict[tuple[int, int], arcade.Texture | None] = {}
        for lane_index in world.lane_ids():
            for gx, gy in world.get_lane_cells(lane_index):
                lane_cell_to_tex[(gx, gy)] = self._lane_cell_texture(lane_index, gx, gy)
        return lane_cell_to_tex

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
        self._cached_center = (center_x, center_y, self._zoom_scale, self._camera.view_yaw_q)
        self._tile_cells.clear()

        lane_cell_to_tex = self._build_lane_cell_to_tex()
        place_cells = self._collect_place_cells()

        self._tile_sprite_list = arcade.SpriteList()
        grass_tex = self._tile_set.get("grass")
        place_zone_tex = self._tile_set.get("place_zone")
        road_cross_tex = self._tile_set.get("road_cross")
        intersection_cells_map = world.get_intersection_cells_map()
        all_inter_cells = {c for cells in intersection_cells_map.values() for c in cells}
        x_lo, y_lo, x_hi, y_hi = world.get_bounds()
        for gy in range(y_lo, y_hi):
            for gx in range(x_lo, x_hi):
                cell = (gx, gy)
                if cell in all_inter_cells:
                    tex = grass_tex  # always grass under intersections; overlay drawn below
                elif cell in lane_cell_to_tex:
                    tex = lane_cell_to_tex[cell]
                elif cell in place_cells and place_zone_tex is not None:
                    tex = place_zone_tex
                else:
                    tex = grass_tex
                self._append_sprite_at(tex, gx, gy, center_x, center_y)

        for key, cells in intersection_cells_map.items():
            cfg = self.game.intersections.get(key)
            size_cells = cfg.size_cells if cfg else 4
            world_active, _, _ = classify_intersection_sides(
                key, cells, require_centre_two=False
            )
            yaw = self._camera.view_yaw_q
            family = overlay_type_for_sides(world_active)
            centered_tex: arcade.Texture | None = None
            paint_thru = bool(getattr(cfg, "paint_thru_lines", True)) if cfg else True
            if family != places.INTERSECTION_TYPE_NONE:
                spans = mouth_spans_by_edge(key, cells)
                world_ax = straight_axis_for_intersection(key, cells, world_active)
                axis, stem = tee_layout_for_sides(world_active, through_fallback=world_ax)
                leftovers = mixed_corner_leftovers(cells, spans, world_active)
                local = mouth_spans_local(cells, spans)
                centered_tex = generate_mixed_texture(
                    size_cells,
                    leftovers,
                    family,
                    axis=axis,
                    stem=stem,
                    yaw=yaw,
                    spans=local,
                    paint_thru_lines=paint_thru,
                    intersection_key=key,
                )
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
                self._place_texts[place] = ui_text(
                    place, 0, 0, color=PLACE_LABEL_COLOR, size=PLACE_LABEL_FONT_SIZE,
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
        yaw = self._camera.view_yaw_q
        self._cardinal_texts["N"].x, self._cardinal_texts["N"].y = self._to_screen(cx_grid, y_hi - 1, center_x, center_y)
        self._cardinal_texts["S"].x, self._cardinal_texts["S"].y = self._to_screen(cx_grid, y_lo, center_x, center_y)
        self._cardinal_texts["E"].x, self._cardinal_texts["E"].y = self._to_screen(x_hi - 1, cy_grid, center_x, center_y)
        self._cardinal_texts["W"].x, self._cardinal_texts["W"].y = self._to_screen(x_lo, cy_grid, center_x, center_y)
        for name, txt in self._cardinal_texts.items():
            ax, ay = cardinal_label_anchors(name, yaw)
            txt.anchor_x = ax
            txt.anchor_y = ay

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
        bounds = world.get_bounds()
        yaw = self._camera.view_yaw_q
        for inst, spr, defn in self._building_draw_items:
            plant = view_south_cell(
                inst.origin_x, inst.origin_y, inst.cells_e, inst.cells_n, *bounds, yaw
            )
            sx, sy = self._to_screen(plant[0], plant[1], center_x, center_y)
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
        hk = hotkey_for_key(key)
        if hk is None:
            return
        if hk.action in ("cycle_tool", "cam_space_pan", "cam_toggle_fly", "orbit_ccw", "orbit_cw"):
            if hk.action in self._held_hotkeys:
                return
            self._held_hotkeys.add(hk.action)
        if hk.action in ("select_toggle_mode", "select_toggle_overlay"):
            if fw is not None:
                return
            active = self._tool_manager.active
            if active.id == "select":
                sel = self._tool_manager.select
                if hk.action == "select_toggle_mode":
                    label = sel.toggle_mode()
                else:
                    label = sel.toggle_overlay()
                self._show_tool_hint("select", label)
            elif active.id == "camera":
                if hk.action == "select_toggle_mode":
                    label = active.toggle_mode()
                else:
                    label = active.toggle_overlay()
                self._show_tool_hint("camera", label)
            return
        if hk.action == "dialog_delete":
            if fw is not None:
                return
            self._dialog_manager.trigger_delete_top()
            return
        if hk.action == "cycle_tool":
            if fw is not None:
                return
            self._tool_manager.cycle_next()
            return
        if hk.action == "cam_space_pan":
            if fw is not None:
                return
            if self._space_pan is None:
                self._start_space_pan()
            return
        if hk.action == "cam_toggle_fly":
            if fw is not None:
                return
            label = self.toggle_pan_fly()
            self._show_tool_hint("camera", label)
            return
        if hk.action == "orbit_ccw":
            if fw is not None:
                return
            self.orbit_camera_about_cursor(clockwise=False)
            return
        if hk.action == "orbit_cw":
            if fw is not None:
                return
            self.orbit_camera_about_cursor(clockwise=True)
            return
        if hk.action == "zoom_in":
            if fw is not None:
                return
            self.zoom_camera_at_cursor(zoom_in=True)
            return
        if hk.action == "zoom_out":
            if fw is not None:
                return
            self.zoom_camera_at_cursor(zoom_in=False)
            return
        if hk.action == "escape":
            if self._draw_tool_active():
                self._exit_active_draw_tool()
            else:
                self._dialog_manager.close_top()
        elif hk.action == "placement_pop":
            if self._placement_can_pop():
                self._placement_pop()
        elif hk.action == "toggle_visibility_fans":
            self._show_visibility_fans = not self._show_visibility_fans
        elif hk.when == "camera":
            self._camera.handle_key_press(key)

    def on_text(self, text: str) -> None:
        fw = self._dialog_manager.get_focused_widget()
        on_text = getattr(fw, "on_text", None) if fw is not None else None
        if callable(on_text):
            on_text(text)

    def on_key_release(self, key: int, modifiers: int) -> None:
        hk = hotkey_for_key(key)
        if hk is not None:
            self._held_hotkeys.discard(hk.action)
        if key == arcade.key.SPACE:
            self._stop_space_pan()
        self._camera.handle_key_release(key)

    def on_mouse_scroll(self, x: int, y: int, scroll_x: int, scroll_y: int) -> None:
        if self._dialog_manager.contains_point(x, y):
            return
        if self._camera.handle_scroll(scroll_y, float(x), float(y), self.width, self.height):
            if self._car_sprite_pool is not None:
                self._car_sprite_pool.set_zoom_scale(self._zoom_scale)

    def on_mouse_motion(self, x: float, y: float, dx: float, dy: float) -> None:
        self._mouse_x = x
        self._mouse_y = y
        self._mouse_in_window = True
        self.update_camera_grab(x, y)
        if not self._dialog_manager.contains_point(x, y):
            self._tool_manager.active.on_hover(x, y)

    def on_mouse_leave(self, x: float, y: float) -> None:
        self._mouse_in_window = False
        self._tool_manager.active.on_hover(x, y)

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
        self._camera.update(
            delta_time,
            self.width,
            self.height,
            self._mouse_x,
            self._mouse_y,
            self._mouse_in_window,
            self._dialog_manager.contains_point(self._mouse_x, self._mouse_y),
            self._edge_pan_enabled,
        )
        self._select_hint.update(delta_time)
        if self._mouse_in_window:
            self._tool_manager.active.on_hover(self._mouse_x, self._mouse_y)
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
        yaw = self._camera.view_yaw_q
        needs_rebuild = cached is None or cached[2] != self._zoom_scale or cached[3] != yaw
        if needs_rebuild:
            self._rebuild_static_draw_cache(center_x, center_y)
        elif (center_x, center_y) != (cached[0], cached[1]):
            self._update_tile_positions(center_x, center_y)
            self._update_text_positions(center_x, center_y)
            self._cached_center = (center_x, center_y, self._zoom_scale, yaw)

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
                    self._place_texts[place] = ui_text(
                        place, 0, 0, color=PLACE_LABEL_COLOR, size=PLACE_LABEL_FONT_SIZE,
                        anchor_x="center", anchor_y="center",
                    )
                self._place_texts[place].draw()
        for txt in self._cardinal_texts.values():
            txt.draw()

        origin = self._camera.fly_origin
        if origin is not None:
            draw_pan_arrows(origin[0], origin[1], size=12.0)

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
        rect = self._toolbar.button_rect(self._hint_action)
        if rect is not None:
            l, b, w, h = rect
            self._select_hint.draw(l + w + TOOLBAR_HINT_GAP, b + h / 2)
        self._dialog_manager.isolate_active = bool(getattr(self._tool_manager.select, "isolate", False))
        self._dialog_manager.draw_all()

    def _draw_world_pass(self, center_x: float, center_y: float) -> None:
        """Tiles, draw ghosts, cars/buildings, then selection rims. Graded as a unit."""
        if self._tile_sprite_list is not None:
            self._tile_sprite_list.draw(pixelated=True)

        self._tool_manager.active.draw_preview(center_x, center_y)
        self._reset_world_blend()
        self._tool_manager.active.draw_floor(center_x, center_y)
        self._reset_world_blend()

        hide_overlay = bool(
            getattr(self._tool_manager.active, "hides_world_overlay", lambda: False)()
        )
        if not hide_overlay:
            bounds = world.get_bounds()
            yaw = self._camera.view_yaw_q
            overlay: list[tuple[float, int, arcade.Sprite]] = []
            for inst, spr, _defn in self._building_draw_items:
                plant = view_south_cell(
                    inst.origin_x, inst.origin_y, inst.cells_e, inst.cells_n, *bounds, yaw
                )
                overlay.append((iso_depth(plant[0], plant[1], *bounds, yaw), 1, spr))

            if self._car_sprite_pool is not None:
                active_police = [p for p in self.game.police_list if p.state in ("deploying", "holding", "diverting", "returning")]
                car_data: list[tuple[float, object, int, float, float, tuple[int, int, int], float]] = []
                for car in self.game.cars:
                    if car.pose_gx is None or car.pose_gy is None:
                        curr = car.current_cell()
                        if curr is None:
                            continue
                        gx, gy = float(curr[0]), float(curr[1])
                    else:
                        gx, gy = car.pose_gx, car.pose_gy
                    sx, sy = self._to_screen(gx, gy, center_x, center_y)
                    car_data.append((
                        iso_depth(gx, gy, *bounds, yaw),
                        car,
                        display_dir_index(_car_direction_index(car), yaw),
                        sx, sy,
                        getattr(car, "color", CAR_DEFAULT),
                        float(getattr(car, "pose_lean_deg", 0.0) or 0.0),
                    ))
                for police in active_police:
                    gx, gy, di = police.get_pose()
                    sx, sy = self._to_screen(gx, gy, center_x, center_y)
                    car_data.append((
                        iso_depth(gx, gy, *bounds, yaw),
                        police,
                        display_dir_index(di, yaw),
                        sx, sy,
                        police.get_light_color(),
                        0.0,
                    ))
                car_data.sort(key=lambda t: t[0], reverse=True)
                self._car_draw_order = [t[1] for t in car_data]
                self._car_sprite_pool.begin_frame(len(car_data))
                overlay_alpha = getattr(self._tool_manager.active, "overlay_car_alpha", None)
                for idx, (depth, entity, di, sx, sy, color, lean) in enumerate(car_data):
                    alpha = overlay_alpha(entity) if callable(overlay_alpha) else 255
                    self._car_sprite_pool.set_sprite(idx, di, sx, sy, color, alpha, lean)
                    overlay.append((depth, 0, self._car_sprite_pool.sprite_at(idx)))
            overlay.sort(key=lambda t: (t[0], t[1]), reverse=True)
            for _, _, spr in overlay:
                arcade.draw_sprite(spr, pixelated=True)
            self._reset_world_blend()

        self._draw_infra_selection_rims(center_x, center_y)

        if hide_overlay or not self._show_visibility_fans:
            return
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
        set_ui_grade(self._color_hue, self._color_sat)
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
        self._mouse_x = x
        self._mouse_y = y
        self._mouse_in_window = True
        if button != arcade.MOUSE_BUTTON_LEFT:
            return
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
        if toolbar_action:
            active = self._tool_manager.active
            if toolbar_action == active.id and hasattr(active, "toggle_mode"):
                self._show_tool_hint(toolbar_action, active.toggle_mode())
                return
            if self._tool_manager.toggle_action(toolbar_action):
                return
            if self._draw_tool_active():
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
                    police_enabled=self._police_enabled,
                    on_edge_pan_change=lambda v: (
                        setattr(self, "_edge_pan_enabled", v),
                        persistence.request_debounced_save(),
                    ),
                    on_grass_close_change=lambda v: (
                        setattr(self, "_grass_close_enabled", v),
                        persistence.request_debounced_save(),
                    ),
                    on_police_change=lambda v: (
                        setattr(self, "_police_enabled", v),
                        self.game.set_police_enabled(v),
                        persistence.request_debounced_save(),
                    ),
                    on_color_change=self._on_color_grade_change,
                    on_clear_cars=self.game.clear_cars,
                    on_save_map=self._on_save_map,
                    on_load_map=self._on_load_map,
                    on_new_game=self._on_new_game,
                )
                dlg.set_on_close(lambda d: self._dialog_manager.close(d))
                self._dialog_manager.open(dlg)
            return
        if self._tool_manager.active.on_press(x, y):
            return
        self._tool_manager.active.on_click(x, y)

    def on_mouse_drag(self, x: float, y: float, dx: float, dy: float, buttons: int, modifiers: int):
        self._mouse_x = x
        self._mouse_y = y
        self._mouse_in_window = True
        self.update_camera_grab(x, y)
        if buttons & arcade.MOUSE_BUTTON_LEFT:
            if self._dialog_manager.on_mouse_drag(x, y, dx, dy):
                return
            self._tool_manager.active.on_drag(x, y, dx, dy)

    def on_mouse_release(self, x: float, y: float, button: int, modifiers: int):
        self._mouse_x = x
        self._mouse_y = y
        if button == arcade.MOUSE_BUTTON_LEFT:
            self._dialog_manager.on_mouse_release(x, y)
            self._tool_manager.active.on_release(x, y)


def main():
    StoplightsWindow()
    arcade.run()


if __name__ == "__main__":
    main()
