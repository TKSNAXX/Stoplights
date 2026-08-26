"""
Stoplights entry point and window orchestration.
"""
import time
from pathlib import Path

import arcade

from render.camera import grid_to_screen, screen_to_grid
from render.debug import visibility_fan_vertices
from render.sprites import CarSpritePool, load_car_textures
from render.intersection_topology import (
    classify_intersection_sides,
    corner_quadrant_for_sides,
    straight_axis_for_intersection,
)
from render.tiles import TileSet, generate_corner_texture, generate_straight_texture
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
    Toolbar,
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
        self._toolbar = Toolbar(TOOLBAR_LEFT, self.height - 180)

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
        self._tile_sprite_list: arcade.SpriteList | None = None
        self._tile_cells: list[tuple[int, int]] = []

        self._car_textures_by_dir = load_car_textures(assets_dir)
        self._car_sprite_pool = CarSpritePool(self._car_textures_by_dir, scale=2.0) if self._car_textures_by_dir else None
        self._car_draw_order: list[object] = []

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
        return grid_to_screen(gx, gy, center_x, center_y, world.get_grid_w(), world.get_grid_h(), self._zoom_scale)

    def _screen_to_grid(self, sx: float, sy: float, center_x: float, center_y: float) -> tuple[float, float]:
        return screen_to_grid(sx, sy, center_x, center_y, world.get_grid_w(), world.get_grid_h(), self._zoom_scale)

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
        cfg = self.game.lane_configs.get(lane_index)
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
        for gy in range(world.get_grid_h()):
            for gx in range(world.get_grid_w()):
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
            cfg = self.game.intersection_configs.get(key)
            itype = cfg.intersection_type if cfg else places.INTERSECTION_TYPE_X
            size_cells = cfg.size_cells if cfg else 4
            active, _, _ = classify_intersection_sides(key, cells)
            centered_tex: arcade.Texture | None = None
            if itype == places.INTERSECTION_TYPE_CORNER:
                q = corner_quadrant_for_sides(active)
                centered_tex = generate_corner_texture(size_cells, quadrant=q)
            elif itype == places.INTERSECTION_TYPE_STRAIGHT:
                ax = straight_axis_for_intersection(key, cells, active)
                centered_tex = generate_straight_texture(size_cells, axis=ax)
            self._overlay_intersection(cells, centered_tex, road_cross_tex, center_x, center_y)

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

        cx_grid = (world.get_grid_w() - 1) / 2
        cy_grid = (world.get_grid_h() - 1) / 2
        self._cardinal_texts["N"].x, self._cardinal_texts["N"].y = self._to_screen(cx_grid, world.get_grid_h() - 1, center_x, center_y)
        self._cardinal_texts["S"].x, self._cardinal_texts["S"].y = self._to_screen(cx_grid, 0, center_x, center_y)
        self._cardinal_texts["E"].x, self._cardinal_texts["E"].y = self._to_screen(world.get_grid_w() - 1, cy_grid, center_x, center_y)
        self._cardinal_texts["W"].x, self._cardinal_texts["W"].y = self._to_screen(0, cy_grid, center_x, center_y)

    def _update_tile_positions(self, center_x: float, center_y: float) -> None:
        """Update sprite screen positions without rebuilding. Requires _tile_cells and _tile_sprite_list."""
        if self._tile_sprite_list is None or not self._tile_cells:
            return
        to_screen = self._to_screen
        for i, (gx, gy) in enumerate(self._tile_cells):
            sx, sy = to_screen(gx, gy, center_x, center_y)
            spr = self._tile_sprite_list[i]
            spr.center_x, spr.center_y = sx, sy

    def on_key_press(self, key: int, modifiers: int) -> None:
        fw = self._dialog_manager.get_focused_widget()
        if fw is not None:
            if fw.on_key_press(key):
                if key in (arcade.key.RETURN, arcade.key.TAB):
                    self._dialog_manager.set_focused_widget(None)
                return
        if key == arcade.key.ESCAPE:
            self._dialog_manager.close_top()
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

    def on_mouse_leave(self, x: float, y: float) -> None:
        self._mouse_in_window = False

    def on_resize(self, width: int, height: int) -> None:
        super().on_resize(width, height)
        self._toolbar.bottom = self.height - 180
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

        if self._tile_sprite_list is not None:
            self._tile_sprite_list.draw(pixelated=True)

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

        if self._car_sprite_pool is not None:
            active_police = [p for p in self.game.police_list if p.state in ("deploying", "holding", "returning")]
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
            for idx, (_, _, di, sx, sy, color) in enumerate(car_data):
                self._car_sprite_pool.set_sprite(idx, di, sx, sy, color)
            self._car_sprite_pool.sprite_list.draw(pixelated=True)

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

        draw_ms = (time.perf_counter() - draw_start) * 1000.0
        self._draw_ms_ema = draw_ms if self._draw_ms_ema <= 0.0 else (0.9 * self._draw_ms_ema + 0.1 * draw_ms)
        perf = self.game.get_perf_stats()
        self._perf_text.x = 10
        self._perf_text.y = self.height - 10
        self._perf_text.value = (
            f"FPS~{self._fps_ema:5.1f} substeps:{self._last_substeps} draw:{self._draw_ms_ema:5.2f}ms "
            f"cars:{perf['cars']} tiles:{len(self._tile_sprite_list or [])} tick:{float(perf['tick_ms_ema']):5.2f}ms "
            f"vis:{float(perf['visibility_ms_ema']):5.2f}ms checks:{perf['visibility_checks']} "
            f"pair:{float(perf['pair_ms_ema']):5.2f}ms checks:{perf['pair_checks']}"
        )
        self._perf_text.draw()

        self._toolbar.draw()
        self._dialog_manager.draw_all()

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
        """Return lane index (0-11) if (sx, sy) hits a lane cell, else None. Skips intersection cells."""
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
            toolbar_action = self._toolbar.on_press(x, y)
            if toolbar_action == "settings":
                dlg_x = TOOLBAR_LEFT + 56
                dlg_y = self.height / 2 + 100
                dlg = SettingsDialog(
                    dlg_x, dlg_y,
                    edge_pan_enabled=self._edge_pan_enabled,
                    on_edge_pan_change=lambda v: (
                        setattr(self, "_edge_pan_enabled", v),
                        persistence.request_debounced_save(),
                    ),
                )
                dlg.set_on_close(lambda d: self._dialog_manager.close(d))
                self._dialog_manager.open(dlg)
                return
            if toolbar_action == "new_place":
                dlg_x = TOOLBAR_LEFT + 56
                dlg_y = self.height / 2 + 100
                dlg = NewPlaceDialog(
                    dlg_x, dlg_y, self.game,
                    on_commit=lambda: (
                        self._on_config_change(),
                        self._dialog_manager.close(dlg),
                    ),
                )
                dlg.set_on_close(lambda d: self._dialog_manager.close(d))
                self._dialog_manager.open(dlg)
                return
            if toolbar_action == "new_intersection":
                dlg_x = TOOLBAR_LEFT + 56
                dlg_y = self.height / 2 + 100
                dlg = NewIntersectionDialog(
                    dlg_x, dlg_y, self.game,
                    on_commit=lambda: (
                        self._on_config_change(),
                        self._dialog_manager.close(dlg),
                    ),
                )
                dlg.set_on_close(lambda d: self._dialog_manager.close(d))
                self._dialog_manager.open(dlg)
                return
            if toolbar_action == "new_lane":
                dlg_x = TOOLBAR_LEFT + 56
                dlg_y = self.height / 2 + 100
                dlg = AddLaneDialog(
                    dlg_x, dlg_y, self.game,
                    on_commit=lambda: (
                        self._on_config_change(),
                        self._dialog_manager.close(dlg),
                    ),
                )
                dlg.set_on_close(lambda d: self._dialog_manager.close(d))
                self._dialog_manager.open(dlg)
                return
            place = self._place_at_screen(x, y)
            if place is not None:
                if place in self._place_dialogs:
                    self._dialog_manager.open(self._place_dialogs[place])
                else:
                    dlg = PlaceVarsDialog(
                        x - 120, y - 130, place,
                        self.game.place_configs[place],
                        self.game.place_geometry,
                        game=self.game,
                        on_change=self._on_config_change,
                        on_commit=lambda: self._on_config_change(rebuild_world=True),
                        on_remove=lambda: (
                            self._on_config_change(),
                            self._place_dialogs.pop(place, None),
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
            if lane_idx is not None and lane_idx in self.game.lane_configs:
                if lane_idx in self._lane_dialogs:
                    self._dialog_manager.open(self._lane_dialogs[lane_idx])
                else:
                    dlg = LaneVarsDialog(
                        x - 110, y - 70, lane_idx,
                        self.game.lane_configs[lane_idx],
                        self.game.place_geometry,
                        self.game.intersection_configs,
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
                        self.game.intersection_configs[inter_key],
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
