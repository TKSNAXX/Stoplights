"""
Stoplights entry point and window orchestration.
"""
import math
import time
from pathlib import Path

import arcade

from render.camera import grid_to_screen, screen_to_grid
from render.debug import visibility_fan_vertices
from render.sprites import CarSpritePool, load_car_textures
from render.tiles import TileSet
from sim import places
from sim.constants import (
    CAR_DEFAULT,
    PLACE_LABEL_COLOR,
    VIS_ZONE_LENGTH_CELLS,
    VIS_ZONE_WIDTH_CELLS,
)
from sim.game import GameState
from sim.world import ALL_LANES, GRID_H, GRID_W, get_intersection_cells
from ui import CarDeetsDialog, DialogManager, PlaceVarsDialog, Slider

TICKS_PER_SECOND = 60
TICK_DT = 1.0 / TICKS_PER_SECOND
MAX_SUBSTEPS_PER_FRAME = 8
LANE_TO_DIRECTION_INDEX: list[int] = [0, 0, 4, 4, 6, 2, 2, 6]

BUILDING_OUTLINE_WIDTH = 2
PLACE_LABEL_FONT_SIZE = 12
VIS_ZONE_COLOR = (60, 220, 100)
VIS_ZONE_COLOR_YELLOW = (220, 220, 80)
VIS_ZONE_COLOR_RED = (220, 80, 80)
VIS_ZONE_COLOR_WHITE = (220, 220, 220)
VIS_ZONE_COLOR_CYAN = (60, 220, 220)
VIS_ZONE_LINE_WIDTH = 1

SLIDER_LEFT = 20
SLIDER_BOTTOM = 20
SLIDER_WIDTH = 200
SLIDER_HEIGHT = 24
SLIDER_COLOR = (100, 100, 100)
SLIDER_THUMB_COLOR = (180, 180, 180)
SLIDER_LABEL_FONT_SIZE = 14
TRAFFIC_STEPS = 10
TRAFFIC_DEFAULT_STEP = 2
SPEED_SLIDER_BOTTOM = SLIDER_BOTTOM + SLIDER_HEIGHT + 12
SPEED_STEPS = 9
SPEED_DEFAULT_STEP = 4
MOVE_DURATION_BASE = 0.2


def spawn_interval_for_step(step: int) -> float:
    step = max(0, min(TRAFFIC_STEPS - 1, step))
    k = (math.log10(5.0) - math.log10(2.0)) / -2
    return 2.0 * (10.0 ** ((step - TRAFFIC_DEFAULT_STEP) * k))


def speed_multiplier_for_step(step: int) -> float:
    step = max(0, min(SPEED_STEPS - 1, step))
    if step <= SPEED_DEFAULT_STEP:
        return 0.125 + (1.0 - 0.125) * step / SPEED_DEFAULT_STEP if SPEED_DEFAULT_STEP else 0.125
    return 1.0 + (2.0 - 1.0) * (step - SPEED_DEFAULT_STEP) / (SPEED_STEPS - 1 - SPEED_DEFAULT_STEP)


def _car_direction_index(car) -> int:
    if getattr(car, "pose_dir_index_8", None) is not None:
        return int(car.pose_dir_index_8) % 8
    return LANE_TO_DIRECTION_INDEX[min(max(0, car.lane_index), 7)]


class StoplightsWindow(arcade.Window):
    def __init__(self):
        super().__init__(800, 600, "Stoplights")
        arcade.set_background_color(arcade.color.BLACK)
        self.game = GameState()
        self._tick_accumulator = 0.0
        self._sim_time = 0.0
        self._move_duration = MOVE_DURATION_BASE

        self._cached_center: tuple[float, float] | None = None
        self._place_polygons: dict[str, list[tuple[float, float]]] = {}
        self._place_texts: dict[str, arcade.Text] = {}
        self._cardinal_texts: dict[str, arcade.Text] = {}

        self._traffic_slider = Slider(
            SLIDER_LEFT, SLIDER_BOTTOM, SLIDER_WIDTH, SLIDER_HEIGHT, TRAFFIC_STEPS, TRAFFIC_DEFAULT_STEP, SLIDER_COLOR, SLIDER_THUMB_COLOR
        )
        self._speed_slider = Slider(
            SLIDER_LEFT, SPEED_SLIDER_BOTTOM, SLIDER_WIDTH, SLIDER_HEIGHT, SPEED_STEPS, SPEED_DEFAULT_STEP, SLIDER_COLOR, SLIDER_THUMB_COLOR
        )
        self._traffic_label = arcade.Text("", SLIDER_LEFT, SLIDER_BOTTOM + SLIDER_HEIGHT + 4, color=PLACE_LABEL_COLOR, font_size=SLIDER_LABEL_FONT_SIZE)
        self._speed_label = arcade.Text("", SLIDER_LEFT, SPEED_SLIDER_BOTTOM + SLIDER_HEIGHT + 4, color=PLACE_LABEL_COLOR, font_size=SLIDER_LABEL_FONT_SIZE)

        for place in places.PLACES:
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

        self._dialog_manager = DialogManager()
        self._place_dialogs: dict[str, PlaceVarsDialog] = {}

        self._cam_x = 0.0
        self._cam_y = 0.0
        self._pan_vx = 0.0
        self._pan_vy = 0.0
        self._key_left = self._key_right = self._key_up = self._key_down = False
        self._cam_pan_speed = 300.0

        assets_dir = Path(__file__).resolve().parent / "assets"
        self._tile_set = TileSet(assets_dir / "ortho")
        self._tile_sprite_list: arcade.SpriteList | None = None

        self._car_textures_by_dir = load_car_textures(assets_dir)
        self._car_sprite_pool = CarSpritePool(self._car_textures_by_dir, scale=1.5) if self._car_textures_by_dir else None
        self._car_draw_order: list[object] = []

        self._apply_speed_step(SPEED_DEFAULT_STEP)
        self._rebuild_static_draw_cache(self.width / 2, self.height / 2)

    def _effective_center(self) -> tuple[float, float]:
        return (self.width / 2 - self._cam_x, self.height / 2 - self._cam_y)

    def _to_screen(self, gx: float, gy: float, center_x: float, center_y: float) -> tuple[float, float]:
        return grid_to_screen(gx, gy, center_x, center_y, GRID_W, GRID_H)

    def _apply_traffic_step(self, step: int) -> None:
        self.game.spawn_interval = spawn_interval_for_step(max(0, min(TRAFFIC_STEPS - 1, step)))

    def _apply_speed_step(self, step: int) -> None:
        step = max(0, min(SPEED_STEPS - 1, step))
        self._move_duration = MOVE_DURATION_BASE / speed_multiplier_for_step(step)
        self.game.movement_every_n_ticks = 1

    def _rebuild_static_draw_cache(self, center_x: float, center_y: float) -> None:
        self._cached_center = (center_x, center_y)
        self._place_polygons.clear()

        inter_cells = set(get_intersection_cells())
        lane_cell_to_road: dict[tuple[int, int], str] = {}
        for lane_index, lane in enumerate(ALL_LANES):
            road_type = "road_ns" if lane_index in (0, 1, 2, 3) else "road_ew"
            for gx, gy in lane:
                lane_cell_to_road[(gx, gy)] = road_type

        self._tile_sprite_list = arcade.SpriteList()
        grass_tex = self._tile_set.get("grass")
        road_ns_tex = self._tile_set.get("road_ns")
        road_ew_tex = self._tile_set.get("road_ew")
        road_cross_tex = self._tile_set.get("road_cross")
        for gy in range(GRID_H):
            for gx in range(GRID_W):
                cell = (gx, gy)
                if cell in inter_cells and road_cross_tex is not None:
                    tex = road_cross_tex
                elif cell in lane_cell_to_road:
                    rt = lane_cell_to_road[cell]
                    tex = road_ns_tex if rt == "road_ns" else road_ew_tex
                else:
                    tex = grass_tex
                if tex is not None:
                    sx, sy = self._to_screen(gx, gy, center_x, center_y)
                    spr = arcade.Sprite(tex, scale=1.0)
                    spr.center_x, spr.center_y = sx, sy
                    self._tile_sprite_list.append(spr)

        for place in places.PLACES:
            cells = places.place_bounds(place)
            if not cells:
                continue
            min_gx = min(p[0] for p in cells)
            max_gx = max(p[0] for p in cells)
            min_gy = min(p[1] for p in cells)
            max_gy = max(p[1] for p in cells)
            corners = [(min_gx, min_gy), (max_gx + 1, min_gy), (max_gx + 1, max_gy + 1), (min_gx, max_gy + 1)]
            self._place_polygons[place] = [self._to_screen(gx, gy, center_x, center_y) for gx, gy in corners]
            sx, sy = self._to_screen((min_gx + max_gx + 1) / 2, (min_gy + max_gy + 1) / 2, center_x, center_y)
            self._place_texts[place].x, self._place_texts[place].y = sx, sy

        cx_grid = (GRID_W - 1) / 2
        cy_grid = (GRID_H - 1) / 2
        self._cardinal_texts["N"].x, self._cardinal_texts["N"].y = self._to_screen(cx_grid, GRID_H - 1, center_x, center_y)
        self._cardinal_texts["S"].x, self._cardinal_texts["S"].y = self._to_screen(cx_grid, 0, center_x, center_y)
        self._cardinal_texts["E"].x, self._cardinal_texts["E"].y = self._to_screen(GRID_W - 1, cy_grid, center_x, center_y)
        self._cardinal_texts["W"].x, self._cardinal_texts["W"].y = self._to_screen(0, cy_grid, center_x, center_y)

    def on_key_press(self, key: int, modifiers: int) -> None:
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

    def on_update(self, delta_time: float):
        if delta_time > 1e-9:
            fps_now = 1.0 / delta_time
            self._fps_ema = fps_now if self._fps_ema <= 0.0 else (0.9 * self._fps_ema + 0.1 * fps_now)
        vx = self._cam_pan_speed if self._key_right else (-self._cam_pan_speed if self._key_left else 0.0)
        vy = self._cam_pan_speed if self._key_down else (-self._cam_pan_speed if self._key_up else 0.0)
        self._cam_x += vx * delta_time
        self._cam_y += vy * delta_time
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
        if self._cached_center != (center_x, center_y):
            self._rebuild_static_draw_cache(center_x, center_y)

        if self._tile_sprite_list is not None:
            self._tile_sprite_list.draw(pixelated=True)

        for place in places.PLACES:
            if place in self._place_polygons:
                arcade.draw_polygon_outline(self._place_polygons[place], arcade.color.BLUE, BUILDING_OUTLINE_WIDTH)
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

        self._traffic_slider.draw()
        self._speed_slider.draw()
        self._traffic_label.value = f"Traffic: {self._traffic_slider.value + 1}/{TRAFFIC_STEPS}"
        self._traffic_label.draw()
        mult = speed_multiplier_for_step(self._speed_slider.value)
        self._speed_label.value = f"Speed: {mult:.1f}x" if mult >= 1.0 else f"Speed: 1/{int(1 / mult)}x" if (1 / mult) == int(1 / mult) else f"Speed: {mult:.2f}x"
        self._speed_label.draw()

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

        self._dialog_manager.draw_all()

    def _place_at_screen(self, sx: float, sy: float) -> str | None:
        """Return place name if (sx, sy) screen coords hit a place, else None."""
        center_x, center_y = self._effective_center()
        gx, gy = screen_to_grid(sx, sy, center_x, center_y, GRID_W, GRID_H)
        cell = (int(round(gx)), int(round(gy)))
        for place in places.PLACES:
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

    def on_mouse_press(self, x: float, y: float, button: int, modifiers: int):
        if button == arcade.MOUSE_BUTTON_LEFT:
            if self._dialog_manager.on_mouse_press(x, y):
                return
            place = self._place_at_screen(x, y)
            if place is not None:
                if place in self._place_dialogs:
                    self._dialog_manager.open(self._place_dialogs[place])
                else:
                    dlg = PlaceVarsDialog(
                        x - 110, y - 70, place,
                        self.game.place_configs[place],
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
            if self._traffic_slider.on_press(x, y):
                self._apply_traffic_step(self._traffic_slider.value)
            elif self._speed_slider.on_press(x, y):
                self._apply_speed_step(self._speed_slider.value)

    def on_mouse_drag(self, x: float, y: float, dx: float, dy: float, buttons: int, modifiers: int):
        if buttons & arcade.MOUSE_BUTTON_LEFT:
            if self._dialog_manager.on_mouse_drag(x, y, dx, dy):
                return
            if self._traffic_slider.on_drag(x):
                self._apply_traffic_step(self._traffic_slider.value)
            elif self._speed_slider.on_drag(x):
                self._apply_speed_step(self._speed_slider.value)

    def on_mouse_release(self, x: float, y: float, button: int, modifiers: int):
        if button == arcade.MOUSE_BUTTON_LEFT:
            self._dialog_manager.on_mouse_release(x, y)
            self._traffic_slider.on_release()
            self._speed_slider.on_release()


def main():
    StoplightsWindow()
    arcade.run()


if __name__ == "__main__":
    main()
