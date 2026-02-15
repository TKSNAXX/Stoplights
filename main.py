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
from sim.paths import path_position
from sim.places import is_turn_at_intersection
from sim.world import ALL_LANES, GRID_W, GRID_H, get_intersection_cells

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


# Four directions in screen space: N (grid +y), S (grid -y), E (grid +x), W (grid -x)
_CAR_DIR_N = (-TILE_W, TILE_H)
_CAR_DIR_S = (TILE_W, -TILE_H)
_CAR_DIR_E = (TILE_W, TILE_H)
_CAR_DIR_W = (-TILE_W, -TILE_H)
CAR_TRIANGLES_BY_DIRECTION: list[list[tuple[float, float]]] = [
    _car_triangle_shape(_CAR_DIR_N[0], _CAR_DIR_N[1]),  # 0 N (lanes 0,1)
    _car_triangle_shape(_CAR_DIR_S[0], _CAR_DIR_S[1]),  # 1 S (lanes 2,3)
    _car_triangle_shape(_CAR_DIR_E[0], _CAR_DIR_E[1]),  # 2 E (lanes 4,5)
    _car_triangle_shape(_CAR_DIR_W[0], _CAR_DIR_W[1]),  # 3 W (lanes 6,7)
]
# Lane index 0..7 -> direction index 0..3 (N,S,E,W) for sprite facing.
LANE_TO_DIRECTION_INDEX: list[int] = [0, 0, 1, 1, 3, 2, 2, 3]

# Display colors
GRID_COLOR = (70, 70, 70)
ROAD_GREY = (80, 80, 80)
LANE_UPWARD_GREY = (165, 165, 165)
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


def _car_direction_index(car) -> int:
    """Direction index 0..3 (N,S,E,W) for drawing: use exit lane when in intersection, else current lane."""
    lane = car.pending_out_lane_index if (getattr(car, "intersection_cell", None) and getattr(car, "pending_out_lane_index", None) is not None) else car.lane_index
    return LANE_TO_DIRECTION_INDEX[min(max(0, lane), 7)]


class StoplightsWindow(arcade.Window):
    def __init__(self):
        super().__init__(800, 600, "Stoplights")
        arcade.set_background_color(arcade.color.BLACK)
        self.game = GameState()
        self._tick_accumulator = 0.0
        self._car_prev_cell: dict[int, tuple[int, int] | None] = {}
        self._car_prev_path_t: dict[int, float] = {}  # path_t before last movement tick (for path interpolation)
        self._car_move_duration: dict[int, float] = {}  # per-car duration for current move (2x for turn at inter)
        self._time = 0.0
        self._last_movement_time: float | None = None
        # Interpolation duration (sec) for each cell move; slightly longer for smoother ease-in
        self._move_duration = 0.2
        # Traffic slider: step 0..9, default 2 (display "3 of 10")
        self._traffic_step = TRAFFIC_DEFAULT_STEP
        self._slider_dragging = False
        # Speed slider: step 0..8, default 4 (1x)
        self._speed_step = SPEED_DEFAULT_STEP
        self._speed_slider_dragging = False
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

    def _slider_step_from_x(self, x: float) -> int:
        """Map screen x to step 0..TRAFFIC_STEPS-1."""
        t = (x - SLIDER_LEFT) / SLIDER_WIDTH
        t = max(0.0, min(1.0, t))
        return int(t * (TRAFFIC_STEPS - 1) + 0.5) if TRAFFIC_STEPS > 1 else 0

    def _apply_traffic_step(self, step: int) -> None:
        step = max(0, min(TRAFFIC_STEPS - 1, step))
        self._traffic_step = step
        self.game.spawn_interval = spawn_interval_for_step(step)

    def _speed_step_from_x(self, x: float) -> int:
        """Map screen x to speed step 0..SPEED_STEPS-1."""
        t = (x - SLIDER_LEFT) / SLIDER_WIDTH
        t = max(0.0, min(1.0, t))
        return int(t * (SPEED_STEPS - 1) + 0.5) if SPEED_STEPS > 1 else 0

    def _apply_speed_step(self, step: int) -> None:
        step = max(0, min(SPEED_STEPS - 1, step))
        self._speed_step = step
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
                self._car_prev_path_t = {id(c): c.path_t for c in self.game.cars if c.path_t is not None}
                self._last_movement_time = self._time
            self.game.tick(TICK_DT)
            if was_movement_tick:
                inter_set = frozenset(get_intersection_cells())
                for car in self.game.cars:
                    # Cars on path: duration 2x only for turns (straight stays 1x)
                    if car.path_t is not None and car.pending_out_lane_index is not None:
                        is_turn = is_turn_at_intersection(car.lane_index, car.pending_out_lane_index)
                        self._car_move_duration[id(car)] = 2.0 * self._move_duration if is_turn else self._move_duration
                        continue
                    prev = self._car_prev_cell.get(id(car))
                    curr = car.current_cell()
                    if prev is None or curr is None or prev == curr:
                        continue
                    in_inter_prev = prev in inter_set
                    in_inter_curr = curr in inter_set
                    if curr in inter_set:
                        is_turn = car.pending_out_lane_index is not None and is_turn_at_intersection(car.lane_index, car.pending_out_lane_index)
                    elif prev in inter_set and curr not in inter_set:
                        is_turn = getattr(car, "entered_intersection_as_turn", False)
                    else:
                        is_turn = False
                    duration = 2.0 * self._move_duration if ((in_inter_prev or in_inter_curr) and is_turn) else self._move_duration
                    self._car_move_duration[id(car)] = duration
                    if curr not in inter_set:
                        car.entered_intersection_as_turn = False
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

        # Cars: interpolate prev -> curr; on path use path_position with blended path_t
        CAR_DEFAULT = (220, 60, 60)
        for car in self.game.cars:
            curr = car.current_cell()
            if curr is None:
                continue
            # On intersection path: position from path with blended t
            if car.path_t is not None and car.intersection_cell is not None and car.pending_out_lane_index is not None:
                prev_t = self._car_prev_path_t.get(id(car), car.path_t)
                elapsed = self._time - self._last_movement_time if self._last_movement_time is not None else 0.0
                duration = self._car_move_duration.get(id(car), self._move_duration)
                blend = smoothstep(min(1.0, elapsed / duration)) if duration > 0 else 1.0
                blended_t = prev_t + blend * (car.path_t - prev_t)
                gx, gy = path_position(car.lane_index, car.pending_out_lane_index, blended_t)
            else:
                prev = self._car_prev_cell.get(id(car), curr)
                if prev is None or self._last_movement_time is None:
                    gx, gy = float(curr[0]), float(curr[1])
                else:
                    elapsed = self._time - self._last_movement_time
                    duration = self._car_move_duration.get(id(car), self._move_duration)
                    blend = smoothstep(min(1.0, elapsed / duration))
                    gx = prev[0] + blend * (curr[0] - prev[0])
                    gy = prev[1] + blend * (curr[1] - prev[1])
            sx, sy = grid_to_screen(gx, gy, center_x, center_y)
            color = getattr(car, "color", CAR_DEFAULT)
            direction_index = _car_direction_index(car)
            triangle = CAR_TRIANGLES_BY_DIRECTION[direction_index]
            points = [(sx + dx, sy + dy) for (dx, dy) in triangle]
            arcade.draw_polygon_filled(points, color)

        # Speed slider (custom): bar + thumb + label "Speed: 1x" etc.
        speed_bar_y = SPEED_SLIDER_BOTTOM + (SLIDER_HEIGHT - SLIDER_BAR_HEIGHT) / 2
        _rect_filled(SLIDER_LEFT + SLIDER_WIDTH / 2, speed_bar_y, SLIDER_WIDTH, SLIDER_BAR_HEIGHT, SLIDER_COLOR)
        thumb_w = 16
        speed_thumb_x = SLIDER_LEFT + thumb_w / 2 + (self._speed_step / max(1, SPEED_STEPS - 1)) * (SLIDER_WIDTH - thumb_w) if SPEED_STEPS > 1 else SLIDER_LEFT + thumb_w / 2
        _rect_filled(speed_thumb_x, speed_bar_y, thumb_w, SLIDER_HEIGHT - 4, SLIDER_THUMB_COLOR)
        mult = speed_multiplier_for_step(self._speed_step)
        if mult >= 1.0:
            speed_str = f"Speed: {int(mult)}x" if mult == int(mult) else f"Speed: {mult:.1f}x"
        else:
            speed_str = f"Speed: 1/{int(1/mult)}x" if (1/mult) == int(1/mult) else f"Speed: {mult:.2f}x"
        self._speed_label.value = speed_str
        self._speed_label.draw()

        # Traffic slider (custom): bar + thumb + label "Traffic: X/10"
        bar_y = SLIDER_BOTTOM + (SLIDER_HEIGHT - SLIDER_BAR_HEIGHT) / 2
        _rect_filled(SLIDER_LEFT + SLIDER_WIDTH / 2, bar_y, SLIDER_WIDTH, SLIDER_BAR_HEIGHT, SLIDER_COLOR)
        thumb_x = SLIDER_LEFT + thumb_w / 2 + (self._traffic_step / max(1, TRAFFIC_STEPS - 1)) * (SLIDER_WIDTH - thumb_w) if TRAFFIC_STEPS > 1 else SLIDER_LEFT + thumb_w / 2
        _rect_filled(thumb_x, bar_y, thumb_w, SLIDER_HEIGHT - 4, SLIDER_THUMB_COLOR)
        self._traffic_label.value = f"Traffic: {self._traffic_step + 1}/{TRAFFIC_STEPS}"
        self._traffic_label.draw()

    def on_mouse_press(self, x: float, y: float, button: int, modifiers: int):
        if button != arcade.MOUSE_BUTTON_LEFT:
            return
        if SLIDER_LEFT <= x <= SLIDER_LEFT + SLIDER_WIDTH:
            if SPEED_SLIDER_BOTTOM <= y <= SPEED_SLIDER_BOTTOM + SLIDER_HEIGHT:
                self._speed_slider_dragging = True
                self._apply_speed_step(self._speed_step_from_x(x))
            elif SLIDER_BOTTOM <= y <= SLIDER_BOTTOM + SLIDER_HEIGHT:
                self._slider_dragging = True
                self._apply_traffic_step(self._slider_step_from_x(x))

    def on_mouse_drag(self, x: float, y: float, dx: float, dy: float, buttons: int, modifiers: int):
        if not (buttons & arcade.MOUSE_BUTTON_LEFT):
            return
        if self._speed_slider_dragging:
            self._apply_speed_step(self._speed_step_from_x(x))
        elif self._slider_dragging:
            self._apply_traffic_step(self._slider_step_from_x(x))

    def on_mouse_release(self, x: float, y: float, button: int, modifiers: int):
        if button == arcade.MOUSE_BUTTON_LEFT:
            self._speed_slider_dragging = False
            self._slider_dragging = False


def main():
    window = StoplightsWindow()
    arcade.run()


if __name__ == "__main__":
    main()
