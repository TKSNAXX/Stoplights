"""
Stoplights — entry point.
Display layer: reads sim state, draws isometric grid, lanes (three places), cars.
Game loop: fixed timestep calls sim.tick(); traffic slider for first interactive feature.
"""
import math
import arcade

# Arcade 3.x moved rectangles to arcade.draw.rect; 2.x has draw_rectangle_filled on arcade
try:
    from arcade.draw.rect import draw_lbwh_rectangle_filled as _draw_rect_filled
    def _rect_filled(center_x: float, center_y: float, width: float, height: float, color):
        _draw_rect_filled(center_x - width / 2, center_y - height / 2, width, height, color)
except ImportError:
    _rect_filled = arcade.draw_rectangle_filled

from sim.game import GameState
from sim import places
from sim.paths import path_direction_index_8, path_position
from sim.world import ALL_LANES, GRID_W, GRID_H, get_intersection_cells
from ui import Slider, Switch

# Sim ticks per second (high rate for smooth interpolation; movement runs every Nth tick for half speed)
TICKS_PER_SECOND = 120
TICK_DT = 1.0 / TICKS_PER_SECOND

# Isometric tile half-size in pixels (diamond: width 2*TILE_W, height 2*TILE_H)
TILE_W = 12
TILE_H = 6

# Car: isosceles triangle, four pre-generated shapes (tip in direction of travel)
CAR_SIZE = 10  # distance from center to tip (bigger, longer aspect)
CAR_TRIANGLE_BASE_HALF = 2  # half-width of base (narrower = more arrow-like)


def _car_triangle_shape(dir_sx: float, dir_sy: float) -> list[tuple[float, float]]:
    """Build isosceles triangle as 3 (dx, dy) offsets: tip along (dir_sx, dir_sy) at CAR_SIZE, base perpendicular."""
    length = math.sqrt(dir_sx * dir_sx + dir_sy * dir_sy)
    if length < 1e-6:
        return [(0, CAR_SIZE), (-CAR_TRIANGLE_BASE_HALF, -CAR_TRIANGLE_BASE_HALF), (CAR_TRIANGLE_BASE_HALF, -CAR_TRIANGLE_BASE_HALF)]
    tx = dir_sx * CAR_SIZE / length
    ty = dir_sy * CAR_SIZE / length
    # Perpendicular (for base): (dir_sy, -dir_sx) normalized
    perp_x = dir_sy / length
    perp_y = -dir_sx / length
    b1_x = perp_x * CAR_TRIANGLE_BASE_HALF
    b1_y = perp_y * CAR_TRIANGLE_BASE_HALF
    return [(tx, ty), (b1_x, b1_y), (-b1_x, -b1_y)]


# Eight directions in screen space: N, NE, E, SE, S, SW, W, NW
_CAR_DIR_N = (-TILE_W, TILE_H)
_CAR_DIR_S = (TILE_W, -TILE_H)
_CAR_DIR_E = (TILE_W, TILE_H)
_CAR_DIR_W = (-TILE_W, -TILE_H)
_CAR_DIR_NE = (0, 2 * TILE_H)
_CAR_DIR_SE = (2 * TILE_W, 0)
_CAR_DIR_SW = (0, -2 * TILE_H)
_CAR_DIR_NW = (-2 * TILE_W, 0)
CAR_TRIANGLES_BY_DIRECTION: list[list[tuple[float, float]]] = [
    _car_triangle_shape(_CAR_DIR_N[0], _CAR_DIR_N[1]),   # 0 N
    _car_triangle_shape(_CAR_DIR_NE[0], _CAR_DIR_NE[1]),  # 1 NE
    _car_triangle_shape(_CAR_DIR_E[0], _CAR_DIR_E[1]),   # 2 E
    _car_triangle_shape(_CAR_DIR_SE[0], _CAR_DIR_SE[1]),  # 3 SE
    _car_triangle_shape(_CAR_DIR_S[0], _CAR_DIR_S[1]),   # 4 S
    _car_triangle_shape(_CAR_DIR_SW[0], _CAR_DIR_SW[1]),  # 5 SW
    _car_triangle_shape(_CAR_DIR_W[0], _CAR_DIR_W[1]),   # 6 W
    _car_triangle_shape(_CAR_DIR_NW[0], _CAR_DIR_NW[1]),  # 7 NW
]
# Lane index 0..7 -> direction index 0..7 (N,S,E,W map to 0,4,2,6) for sprite facing.
LANE_TO_DIRECTION_INDEX: list[int] = [0, 0, 4, 4, 6, 2, 2, 6]  # N,S,E,W

# Display colors
GRID_COLOR = (45, 45, 45)
ROAD_GREY = (80, 80, 80)
LANE_UPWARD_GREY = (95, 95, 95)
LANE_DOWNWARD_GREY = (80, 80, 80)
BUILDING_OUTLINE_WIDTH = 2
PLACE_LABEL_COLOR = (220, 220, 220)
PLACE_LABEL_FONT_SIZE = 12
# Intersection path overlay (drawn on top of intersection)
INTERSECTION_PATH_COLOR = (70, 70, 90)
INTERSECTION_PATH_WIDTH = 1
INTERSECTION_PATH_SAMPLES = 20

# Traffic slider (custom): bottom-left
SLIDER_LEFT = 20
SLIDER_BOTTOM = 20
SLIDER_WIDTH = 200
SLIDER_HEIGHT = 24
SLIDER_BAR_HEIGHT = 8
SLIDER_COLOR = (100, 100, 100)
SLIDER_THUMB_COLOR = (180, 180, 180)
SLIDER_LABEL_FONT_SIZE = 14

# Place spawn switch (below place label)
PLACE_SWITCH_WIDTH = 32
PLACE_SWITCH_HEIGHT = 14
PLACE_SWITCH_OFFSET_Y = 20

TRAFFIC_STEPS = 10  # 0..9; step 2 = current default
TRAFFIC_DEFAULT_STEP = 2

# Speed slider: above traffic slider; 1/8x to 2x
SPEED_SLIDER_BOTTOM = SLIDER_BOTTOM + SLIDER_HEIGHT + 12  # traffic at 20, speed at 56
SPEED_STEPS = 9  # 0..8; step 4 = 1x default
SPEED_DEFAULT_STEP = 4
MOVEMENT_BASE_TICKS = 16  # 1x = run movement every 16 ticks
MOVE_DURATION_BASE = 0.2  # 1x interpolation duration (sec)


def spawn_interval_for_step(step: int) -> float:
    """Log scale: step 2 = 2.0 s, step 0 = ~5 s, step 9 = ~0.08 s."""
    step = max(0, min(TRAFFIC_STEPS - 1, step))
    k = (math.log10(5.0) - math.log10(2.0)) / -2  # so interval(0) ≈ 5
    return 2.0 * (10.0 ** ((step - TRAFFIC_DEFAULT_STEP) * k))


def speed_multiplier_for_step(step: int) -> float:
    """Piecewise linear: step 0 = 1/8x, step 4 = 1x, step 8 = 2x."""
    step = max(0, min(SPEED_STEPS - 1, step))
    if step <= SPEED_DEFAULT_STEP:
        # 0.125 at step 0, 1.0 at step 4
        return 0.125 + (1.0 - 0.125) * step / SPEED_DEFAULT_STEP if SPEED_DEFAULT_STEP else 0.125
    # 1.0 at step 4, 2.0 at step 8
    return 1.0 + (2.0 - 1.0) * (step - SPEED_DEFAULT_STEP) / (SPEED_STEPS - 1 - SPEED_DEFAULT_STEP)


def smoothstep(t: float) -> float:
    """Smooth easing: 0 at 0, 1 at 1, smooth in between (Mini Metro style)."""
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def grid_to_screen(gx: float, gy: float, center_x: float, center_y: float) -> tuple[float, float]:
    """Isometric projection: grid (gx, gy) -> screen (sx, sy). Grid center maps to (center_x, center_y)."""
    cx = (GRID_W - 1) / 2
    cy = (GRID_H - 1) / 2
    sx = center_x + (gx - gy) * TILE_W
    sy = center_y + (gx + gy - cx - cy) * TILE_H
    return (sx, sy)


def _car_direction_index(car, path_t: float | None = None) -> int:
    """Direction index 0..7 when on path (8-way), 0..3 when on lane (4-way)."""
    if path_t is not None and getattr(car, "path_entry_time", None) is not None and getattr(car, "path_duration", None) is not None and getattr(car, "pending_out_lane_index", None) is not None:
        return path_direction_index_8(car.lane_index, car.pending_out_lane_index, path_t)
    return LANE_TO_DIRECTION_INDEX[min(max(0, car.lane_index), 7)]


class StoplightsWindow(arcade.Window):
    def __init__(self):
        super().__init__(800, 600, "Stoplights")
        arcade.set_background_color(arcade.color.BLACK)
        self.game = GameState()
        self._tick_accumulator = 0.0
        self._car_prev_cell: dict[int, tuple[int, int] | None] = {}
        self._car_move_duration: dict[int, float] = {}  # per-car duration for lane cell-to-cell moves
        self._time = 0.0
        self._last_movement_time: float | None = None
        # Interpolation duration (sec) for each cell move; slightly longer for smoother ease-in
        self._move_duration = 0.2
        # Sliders (reusable UI)
        self._traffic_slider = Slider(
            SLIDER_LEFT, SLIDER_BOTTOM, SLIDER_WIDTH, SLIDER_HEIGHT,
            TRAFFIC_STEPS, TRAFFIC_DEFAULT_STEP, SLIDER_COLOR, SLIDER_THUMB_COLOR,
        )
        self._speed_slider = Slider(
            SLIDER_LEFT, SPEED_SLIDER_BOTTOM, SLIDER_WIDTH, SLIDER_HEIGHT,
            SPEED_STEPS, SPEED_DEFAULT_STEP, SLIDER_COLOR, SLIDER_THUMB_COLOR,
        )
        self._place_switches: dict[str, Switch] = {
            place: Switch(0, 0, PLACE_SWITCH_WIDTH, PLACE_SWITCH_HEIGHT,
                          initial_value=self.game.spawn_enabled.get(place, True),
                          bar_color=SLIDER_COLOR, thumb_color=SLIDER_THUMB_COLOR)
            for place in places.PLACES
        }
        # Reusable Text for slider labels (avoids slow draw_text per frame)
        self._traffic_label = arcade.Text(
            "",
            SLIDER_LEFT,
            SLIDER_BOTTOM + SLIDER_HEIGHT + 4,
            color=PLACE_LABEL_COLOR,
            font_size=SLIDER_LABEL_FONT_SIZE,
        )
        self._speed_label = arcade.Text(
            "",
            SLIDER_LEFT,
            SPEED_SLIDER_BOTTOM + SLIDER_HEIGHT + 4,
            color=PLACE_LABEL_COLOR,
            font_size=SLIDER_LABEL_FONT_SIZE,
        )
        self._apply_speed_step(SPEED_DEFAULT_STEP)  # sync movement_every_n_ticks and _move_duration

    def _place_switch_rect(self, place: str, center_x: float, center_y: float) -> tuple[float, float, float, float]:
        """Screen rect (left, bottom, width, height) for this place's spawn switch."""
        cells = places.place_bounds(place)
        if not cells:
            return (0, 0, PLACE_SWITCH_WIDTH, PLACE_SWITCH_HEIGHT)
        min_gx = min(p[0] for p in cells)
        max_gx = max(p[0] for p in cells)
        min_gy = min(p[1] for p in cells)
        max_gy = max(p[1] for p in cells)
        center_gx = (min_gx + max_gx + 1) / 2
        center_gy = (min_gy + max_gy + 1) / 2
        sx, sy = grid_to_screen(center_gx, center_gy, center_x, center_y)
        left = sx - PLACE_SWITCH_WIDTH / 2
        bottom = sy - PLACE_SWITCH_OFFSET_Y - PLACE_SWITCH_HEIGHT / 2
        return (left, bottom, PLACE_SWITCH_WIDTH, PLACE_SWITCH_HEIGHT)

    def _apply_traffic_step(self, step: int) -> None:
        step = max(0, min(TRAFFIC_STEPS - 1, step))
        self.game.spawn_interval = spawn_interval_for_step(step)

    def _apply_speed_step(self, step: int) -> None:
        step = max(0, min(SPEED_STEPS - 1, step))
        mult = speed_multiplier_for_step(step)
        self.game.movement_every_n_ticks = max(1, round(MOVEMENT_BASE_TICKS / mult))
        self._move_duration = MOVE_DURATION_BASE / mult

    def on_update(self, delta_time: float):
        self._time += delta_time
        self._tick_accumulator += delta_time
        while self._tick_accumulator >= TICK_DT:
            n = self.game.movement_every_n_ticks
            was_movement_tick = (self.game._tick_count % n) == (n - 1)
            if was_movement_tick:
                self._car_prev_cell = {id(c): c.current_cell() for c in self.game.cars}
                self._last_movement_time = self._time
            self.game.tick(TICK_DT, self._time, self._move_duration)
            if was_movement_tick:
                for car in self.game.cars:
                    prev = self._car_prev_cell.get(id(car))
                    curr = car.current_cell()
                    if prev is None or curr is None or prev == curr:
                        continue
                    # Lane cell-to-cell move: use base duration for interpolation
                    self._car_move_duration[id(car)] = self._move_duration
            self._tick_accumulator -= TICK_DT

    def on_draw(self):
        self.clear()
        center_x = self.width / 2
        center_y = self.height / 2

        # Dark grey isometric grid lines (under everything)
        for gx in range(GRID_W + 1):
            for gy in range(GRID_H):
                sx1, sy1 = grid_to_screen(gx, gy, center_x, center_y)
                sx2, sy2 = grid_to_screen(gx, gy + 1, center_x, center_y)
                arcade.draw_line(sx1, sy1, sx2, sy2, GRID_COLOR, 1)
        for gy in range(GRID_H + 1):
            for gx in range(GRID_W):
                sx1, sy1 = grid_to_screen(gx, gy, center_x, center_y)
                sx2, sy2 = grid_to_screen(gx + 1, gy, center_x, center_y)
                arcade.draw_line(sx1, sy1, sx2, sy2, GRID_COLOR, 1)

        # Grey filled intersection (2×2) midway
        inter_cells = get_intersection_cells()
        if inter_cells:
            min_gx = min(p[0] for p in inter_cells)
            max_gx = max(p[0] for p in inter_cells)
            min_gy = min(p[1] for p in inter_cells)
            max_gy = max(p[1] for p in inter_cells)
            inter_corners = [(min_gx, min_gy), (max_gx + 1, min_gy), (max_gx + 1, max_gy + 1), (min_gx, max_gy + 1)]
            pts = [grid_to_screen(gx, gy, center_x, center_y) for gx, gy in inter_corners]
            arcade.draw_polygon_filled(pts, ROAD_GREY)

        # Intersection paths: sample each valid (in, out) path and draw polyline on top of intersection
        n_samples = max(2, INTERSECTION_PATH_SAMPLES)
        for in_lane in places.IN_LANE_INDICES:
            for out_lane in places.OUT_LANE_INDICES:
                if not places.is_valid_intersection_path(in_lane, out_lane):
                    continue
                path_pts = []
                for i in range(n_samples):
                    t = i / (n_samples - 1)
                    gx, gy = path_position(in_lane, out_lane, t)
                    sx, sy = grid_to_screen(gx, gy, center_x, center_y)
                    path_pts.append((sx, sy))
                for j in range(len(path_pts) - 1):
                    sx1, sy1 = path_pts[j]
                    sx2, sy2 = path_pts[j + 1]
                    arcade.draw_line(sx1, sy1, sx2, sy2, INTERSECTION_PATH_COLOR, INTERSECTION_PATH_WIDTH)

        # Lane lines: upward (Housing->Office) = lighter grey, downward (Office->Housing) = darker
        LANE_WIDTH = 4
        for lane_index, lane in enumerate(ALL_LANES):
            color = LANE_UPWARD_GREY if lane_index in places.LANE_UPWARD_INDICES else LANE_DOWNWARD_GREY
            for i in range(len(lane) - 1):
                gx1, gy1 = lane[i]
                gx2, gy2 = lane[i + 1]
                sx1, sy1 = grid_to_screen(gx1, gy1, center_x, center_y)
                sx2, sy2 = grid_to_screen(gx2, gy2, center_x, center_y)
                arcade.draw_line(sx1, sy1, sx2, sy2, color, LANE_WIDTH)

        # Place outlines: 5×5 bounding box at the end of each road (from place_bounds)
        for place in places.PLACES:
            cells = places.place_bounds(place)
            if not cells:
                continue
            min_gx = min(p[0] for p in cells)
            max_gx = max(p[0] for p in cells)
            min_gy = min(p[1] for p in cells)
            max_gy = max(p[1] for p in cells)
            corners = [
                (min_gx, min_gy),
                (max_gx + 1, min_gy),
                (max_gx + 1, max_gy + 1),
                (min_gx, max_gy + 1),
            ]
            pts = [grid_to_screen(gx, gy, center_x, center_y) for gx, gy in corners]
            arcade.draw_polygon_outline(pts, arcade.color.BLUE, BUILDING_OUTLINE_WIDTH)
            center_gx = (min_gx + max_gx + 1) / 2
            center_gy = (min_gy + max_gy + 1) / 2
            sx, sy = grid_to_screen(center_gx, center_gy, center_x, center_y)
            arcade.draw_text(
                place, sx, sy, PLACE_LABEL_COLOR, PLACE_LABEL_FONT_SIZE,
                anchor_x="center", anchor_y="center",
            )
            # Spawn switch below place label
            switch = self._place_switches[place]
            switch.rect = self._place_switch_rect(place, center_x, center_y)
            switch.value = self.game.spawn_enabled.get(place, True)
            switch.draw()

        # Cardinal direction labels at map edges (N/S/E/W)
        cx_grid = (GRID_W - 1) / 2
        cy_grid = (GRID_H - 1) / 2
        sx_n, sy_n = grid_to_screen(cx_grid, GRID_H - 1, center_x, center_y)
        sx_s, sy_s = grid_to_screen(cx_grid, 0, center_x, center_y)
        sx_e, sy_e = grid_to_screen(GRID_W - 1, cy_grid, center_x, center_y)
        sx_w, sy_w = grid_to_screen(0, cy_grid, center_x, center_y)
        arcade.draw_text("N", sx_n, sy_n, PLACE_LABEL_COLOR, PLACE_LABEL_FONT_SIZE, anchor_x="center", anchor_y="bottom")
        arcade.draw_text("S", sx_s, sy_s, PLACE_LABEL_COLOR, PLACE_LABEL_FONT_SIZE, anchor_x="center", anchor_y="top")
        arcade.draw_text("E", sx_e, sy_e, PLACE_LABEL_COLOR, PLACE_LABEL_FONT_SIZE, anchor_x="right", anchor_y="center")
        arcade.draw_text("W", sx_w, sy_w, PLACE_LABEL_COLOR, PLACE_LABEL_FONT_SIZE, anchor_x="left", anchor_y="center")

        # Cars: interpolate prev -> curr on lane; on path use time-based path_t; just-exited snap to curr
        CAR_DEFAULT = (220, 60, 60)
        for car in self.game.cars:
            curr = car.current_cell()
            if curr is None:
                continue
            path_t_for_direction: float | None = None
            # On intersection path: position from path_t = (time - path_entry_time) / path_duration
            if car.path_entry_time is not None and car.path_duration is not None and car.intersection_cell is not None and car.pending_out_lane_index is not None:
                path_t = (self._time - car.path_entry_time) / car.path_duration
                path_t = max(0.0, min(1.0, path_t))
                path_t_for_direction = path_t
                gx, gy = path_position(car.lane_index, car.pending_out_lane_index, path_t)
            # Just exited path this frame: draw at curr to avoid jump back to slot
            elif getattr(car, "exited_path_in_lane", None) is not None and getattr(car, "exited_path_out_lane", None) is not None:
                gx, gy = float(curr[0]), float(curr[1])
            else:
                prev = self._car_prev_cell.get(id(car), curr)
                inter_set = frozenset(get_intersection_cells())
                if prev is None or self._last_movement_time is None:
                    gx, gy = float(curr[0]), float(curr[1])
                elif prev in inter_set and curr not in inter_set:
                    gx, gy = float(curr[0]), float(curr[1])
                else:
                    elapsed = self._time - self._last_movement_time
                    duration = self._car_move_duration.get(id(car), self._move_duration)
                    blend = smoothstep(min(1.0, elapsed / duration))
                    gx = prev[0] + blend * (curr[0] - prev[0])
                    gy = prev[1] + blend * (curr[1] - prev[1])
            sx, sy = grid_to_screen(gx, gy, center_x, center_y)
            color = getattr(car, "color", CAR_DEFAULT)
            direction_index = _car_direction_index(car, path_t_for_direction)
            triangle = CAR_TRIANGLES_BY_DIRECTION[direction_index]
            points = [(sx + dx, sy + dy) for (dx, dy) in triangle]
            arcade.draw_polygon_filled(points, color)

        # Sliders (reusable UI) + labels
        self._traffic_slider.draw()
        self._speed_slider.draw()
        self._traffic_label.value = f"Traffic: {self._traffic_slider.value + 1}/{TRAFFIC_STEPS}"
        self._traffic_label.draw()
        mult = speed_multiplier_for_step(self._speed_slider.value)
        if mult >= 1.0:
            speed_str = f"Speed: {int(mult)}x" if mult == int(mult) else f"Speed: {mult:.1f}x"
        else:
            speed_str = f"Speed: 1/{int(1/mult)}x" if (1/mult) == int(1/mult) else f"Speed: {mult:.2f}x"
        self._speed_label.value = speed_str
        self._speed_label.draw()

    def on_mouse_press(self, x: float, y: float, button: int, modifiers: int):
        if button != arcade.MOUSE_BUTTON_LEFT:
            return
        center_x = self.width / 2
        center_y = self.height / 2
        if self._traffic_slider.on_press(x, y):
            self._apply_traffic_step(self._traffic_slider.value)
            return
        if self._speed_slider.on_press(x, y):
            self._apply_speed_step(self._speed_slider.value)
            return
        for place in places.PLACES:
            switch = self._place_switches[place]
            switch.rect = self._place_switch_rect(place, center_x, center_y)
            if switch.contains(x, y):
                switch.toggle()
                self.game.spawn_enabled[place] = switch.value
                return

    def on_mouse_drag(self, x: float, y: float, dx: float, dy: float, buttons: int, modifiers: int):
        if not (buttons & arcade.MOUSE_BUTTON_LEFT):
            return
        if self._traffic_slider.on_drag(x):
            self._apply_traffic_step(self._traffic_slider.value)
            return
        if self._speed_slider.on_drag(x):
            self._apply_speed_step(self._speed_slider.value)

    def on_mouse_release(self, x: float, y: float, button: int, modifiers: int):
        if button == arcade.MOUSE_BUTTON_LEFT:
            self._traffic_slider.on_release()
            self._speed_slider.on_release()


def main():
    window = StoplightsWindow()
    arcade.run()


if __name__ == "__main__":
    main()
