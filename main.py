"""
Stoplights — entry point.
Display layer: reads sim state, draws isometric grid, lanes (three places), cars.
Game loop: fixed timestep calls sim.tick(); traffic slider for first interactive feature.
"""
import math
import time
from pathlib import Path
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
from sim.world import ALL_LANES, GRID_W, GRID_H, get_intersection_cells
from ui import Slider

# Sim ticks per second (higher cadence for smoother motion pacing).
TICKS_PER_SECOND = 60
TICK_DT = 1.0 / TICKS_PER_SECOND
MAX_SUBSTEPS_PER_FRAME = 8

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

# Visibility zone (debug): fan in grid space, 2 car-lengths long, 1 wide
VIS_ZONE_LENGTH_CELLS = 2.0
VIS_ZONE_WIDTH_CELLS = 1.0
VIS_ZONE_COLOR = (60, 220, 100)
VIS_ZONE_COLOR_YELLOW = (220, 220, 80)
VIS_ZONE_COLOR_RED = (220, 80, 80)
VIS_ZONE_COLOR_WHITE = (220, 220, 220)
VIS_ZONE_COLOR_CYAN = (60, 220, 220)
VIS_ZONE_LINE_WIDTH = 1

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


def _forward_right_vectors(dir_index_8: int) -> tuple[tuple[float, float], tuple[float, float]]:
    """Return (forward, right) unit vectors in grid space for dir_index_8 (0=N..7=NW)."""
    idx = dir_index_8 % 8
    angle = math.pi / 2 - idx * (math.pi / 4)
    fx = math.cos(angle)
    fy = math.sin(angle)
    rx = fy
    ry = -fx
    return ((fx, fy), (rx, ry))


def visibility_zone_band(
    observer_gx: float, observer_gy: float, dir_index_8: int,
    target_gx: float, target_gy: float, length: float, half_width: float
) -> str | None:
    """Return 'near' if target is in the closest half of the fan, 'far' if in the farthest half, None if outside.
    Fan is in front of observer; halves are split by length/2 along forward."""
    (fx, fy), (rx, ry) = _forward_right_vectors(dir_index_8)
    dx = target_gx - observer_gx
    dy = target_gy - observer_gy
    forward_dist = dx * fx + dy * fy
    lateral = abs(dx * rx + dy * ry)
    if forward_dist <= 0 or forward_dist > length or lateral > half_width:
        return None
    half_len = length / 2.0
    return "near" if forward_dist <= half_len else "far"


def visibility_fan_vertices(
    gx: float, gy: float, dir_index_8: int, length: float, half_width: float
) -> list[tuple[float, float]]:
    """Return 4 grid-space corners of the visibility fan: back_left, front_left, front_right, back_right.
    dir_index_8: 0=N, 1=NE, 2=E, 3=SE, 4=S, 5=SW, 6=W, 7=NW in grid (y up)."""
    (fx, fy), (rx, ry) = _forward_right_vectors(dir_index_8)
    back_center = (gx, gy)
    front_center = (gx + fx * length, gy + fy * length)
    back_left = (back_center[0] - rx * half_width, back_center[1] - ry * half_width)
    back_right = (back_center[0] + rx * half_width, back_center[1] + ry * half_width)
    front_left = (front_center[0] - rx * half_width, front_center[1] - ry * half_width)
    front_right = (front_center[0] + rx * half_width, front_center[1] + ry * half_width)
    return [back_left, front_left, front_right, back_right]


def _car_direction_index(car, path_t: float | None = None) -> int:
    """Direction index 0..7 from continuous pose; lane fallback uses cardinal mapping."""
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
        # Base segment duration for unified continuous movement.
        self._move_duration = 0.2
        self._cached_center: tuple[float, float] | None = None
        self._intersection_polygon: list[tuple[float, float]] = []
        self._intersection_path_lines: list[tuple[float, float, float, float]] = []
        self._lane_lines: list[tuple[float, float, float, float, tuple[int, int, int]]] = []
        self._place_polygons: dict[str, list[tuple[float, float]]] = {}
        self._place_label_positions: dict[str, tuple[float, float]] = {}
        self._place_texts: dict[str, arcade.Text] = {}
        self._cardinal_texts: dict[str, arcade.Text] = {}
        # Sliders (reusable UI)
        self._traffic_slider = Slider(
            SLIDER_LEFT, SLIDER_BOTTOM, SLIDER_WIDTH, SLIDER_HEIGHT,
            TRAFFIC_STEPS, TRAFFIC_DEFAULT_STEP, SLIDER_COLOR, SLIDER_THUMB_COLOR,
        )
        self._speed_slider = Slider(
            SLIDER_LEFT, SPEED_SLIDER_BOTTOM, SLIDER_WIDTH, SLIDER_HEIGHT,
            SPEED_STEPS, SPEED_DEFAULT_STEP, SLIDER_COLOR, SLIDER_THUMB_COLOR,
        )
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
        for place in places.PLACES:
            self._place_texts[place] = arcade.Text(
                place, 0, 0, color=PLACE_LABEL_COLOR, font_size=PLACE_LABEL_FONT_SIZE,
                anchor_x="center", anchor_y="center",
            )
        self._cardinal_texts = {
            "N": arcade.Text("N", 0, 0, color=PLACE_LABEL_COLOR, font_size=PLACE_LABEL_FONT_SIZE, anchor_x="center", anchor_y="bottom"),
            "S": arcade.Text("S", 0, 0, color=PLACE_LABEL_COLOR, font_size=PLACE_LABEL_FONT_SIZE, anchor_x="center", anchor_y="top"),
            "E": arcade.Text("E", 0, 0, color=PLACE_LABEL_COLOR, font_size=PLACE_LABEL_FONT_SIZE, anchor_x="right", anchor_y="center"),
            "W": arcade.Text("W", 0, 0, color=PLACE_LABEL_COLOR, font_size=PLACE_LABEL_FONT_SIZE, anchor_x="left", anchor_y="center"),
        }
        self._perf_text = arcade.Text(
            "", 10, self.height - 10, color=PLACE_LABEL_COLOR, font_size=11,
            anchor_x="left", anchor_y="top",
        )
        self._fps_ema = 0.0
        self._last_substeps = 0
        self._draw_ms_ema = 0.0
        self._show_visibility_fans = False
        # Static grid background (800x600 PNG)
        grid_path = Path(__file__).resolve().parent / "assets" / "grid_background.png"
        self._grid_texture = arcade.load_texture(str(grid_path)) if grid_path.exists() else None
        self._apply_speed_step(SPEED_DEFAULT_STEP)  # sync movement_every_n_ticks and _move_duration
        self._rebuild_static_draw_cache(self.width / 2, self.height / 2)

    def _apply_traffic_step(self, step: int) -> None:
        step = max(0, min(TRAFFIC_STEPS - 1, step))
        self.game.spawn_interval = spawn_interval_for_step(step)

    def _apply_speed_step(self, step: int) -> None:
        step = max(0, min(SPEED_STEPS - 1, step))
        mult = speed_multiplier_for_step(step)
        self.game.movement_every_n_ticks = 1
        self._move_duration = MOVE_DURATION_BASE / mult

    def _rebuild_static_draw_cache(self, center_x: float, center_y: float) -> None:
        self._cached_center = (center_x, center_y)
        self._intersection_polygon = []
        self._intersection_path_lines = []
        self._lane_lines = []
        self._place_polygons = {}
        self._place_label_positions = {}

        inter_cells = get_intersection_cells()
        if inter_cells:
            min_gx = min(p[0] for p in inter_cells)
            max_gx = max(p[0] for p in inter_cells)
            min_gy = min(p[1] for p in inter_cells)
            max_gy = max(p[1] for p in inter_cells)
            inter_corners = [(min_gx, min_gy), (max_gx + 1, min_gy), (max_gx + 1, max_gy + 1), (min_gx, max_gy + 1)]
            self._intersection_polygon = [grid_to_screen(gx, gy, center_x, center_y) for gx, gy in inter_corners]

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
                    self._intersection_path_lines.append((sx1, sy1, sx2, sy2))

        for lane_index, lane in enumerate(ALL_LANES):
            color = LANE_UPWARD_GREY if lane_index in places.LANE_UPWARD_INDICES else LANE_DOWNWARD_GREY
            for i in range(len(lane) - 1):
                gx1, gy1 = lane[i]
                gx2, gy2 = lane[i + 1]
                sx1, sy1 = grid_to_screen(gx1, gy1, center_x, center_y)
                sx2, sy2 = grid_to_screen(gx2, gy2, center_x, center_y)
                self._lane_lines.append((sx1, sy1, sx2, sy2, color))

        for place in places.PLACES:
            cells = places.place_bounds(place)
            if not cells:
                continue
            min_gx = min(p[0] for p in cells)
            max_gx = max(p[0] for p in cells)
            min_gy = min(p[1] for p in cells)
            max_gy = max(p[1] for p in cells)
            corners = [(min_gx, min_gy), (max_gx + 1, min_gy), (max_gx + 1, max_gy + 1), (min_gx, max_gy + 1)]
            pts = [grid_to_screen(gx, gy, center_x, center_y) for gx, gy in corners]
            self._place_polygons[place] = pts
            center_gx = (min_gx + max_gx + 1) / 2
            center_gy = (min_gy + max_gy + 1) / 2
            sx, sy = grid_to_screen(center_gx, center_gy, center_x, center_y)
            self._place_label_positions[place] = (sx, sy)
            if place in self._place_texts:
                self._place_texts[place].x = sx
                self._place_texts[place].y = sy

        cx_grid = (GRID_W - 1) / 2
        cy_grid = (GRID_H - 1) / 2
        sx_n, sy_n = grid_to_screen(cx_grid, GRID_H - 1, center_x, center_y)
        sx_s, sy_s = grid_to_screen(cx_grid, 0, center_x, center_y)
        sx_e, sy_e = grid_to_screen(GRID_W - 1, cy_grid, center_x, center_y)
        sx_w, sy_w = grid_to_screen(0, cy_grid, center_x, center_y)
        self._cardinal_texts["N"].x, self._cardinal_texts["N"].y = sx_n, sy_n
        self._cardinal_texts["S"].x, self._cardinal_texts["S"].y = sx_s, sy_s
        self._cardinal_texts["E"].x, self._cardinal_texts["E"].y = sx_e, sy_e
        self._cardinal_texts["W"].x, self._cardinal_texts["W"].y = sx_w, sy_w

    def on_key_press(self, key: int, modifiers: int) -> None:
        if key == arcade.key.V:
            self._show_visibility_fans = not self._show_visibility_fans

    def on_update(self, delta_time: float):
        if delta_time > 1e-9:
            fps_now = 1.0 / delta_time
            alpha = 0.1
            if self._fps_ema <= 0.0:
                self._fps_ema = fps_now
            else:
                self._fps_ema = (1.0 - alpha) * self._fps_ema + alpha * fps_now
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
        center_x = self.width / 2
        center_y = self.height / 2
        if self._cached_center != (center_x, center_y):
            self._rebuild_static_draw_cache(center_x, center_y)

        # Static grid background (800x600 PNG) before overlays.
        if self._grid_texture is not None:
            arcade.draw_texture_rect(
                self._grid_texture,
                arcade.LRBT(0, self.width, 0, self.height),
            )

        # Grey filled intersection midway.
        if self._intersection_polygon:
            arcade.draw_polygon_filled(self._intersection_polygon, ROAD_GREY)

        # Intersection paths.
        for sx1, sy1, sx2, sy2 in self._intersection_path_lines:
            arcade.draw_line(sx1, sy1, sx2, sy2, INTERSECTION_PATH_COLOR, INTERSECTION_PATH_WIDTH)

        # Lane lines.
        lane_width = 4
        for sx1, sy1, sx2, sy2, color in self._lane_lines:
            arcade.draw_line(sx1, sy1, sx2, sy2, color, lane_width)

        # Place outlines and labels.
        for place in places.PLACES:
            if place not in self._place_polygons:
                continue
            arcade.draw_polygon_outline(self._place_polygons[place], arcade.color.BLUE, BUILDING_OUTLINE_WIDTH)
            if place in self._place_texts:
                self._place_texts[place].draw()

        # Cardinal direction labels.
        for txt in self._cardinal_texts.values():
            txt.draw()

        # Cars: render from simulation-provided continuous pose.
        CAR_DEFAULT = (220, 60, 60)
        for car in self.game.cars:
            if car.pose_gx is None or car.pose_gy is None:
                curr = car.current_cell()
                if curr is None:
                    continue
                gx, gy = float(curr[0]), float(curr[1])
            else:
                gx, gy = car.pose_gx, car.pose_gy
            sx, sy = grid_to_screen(gx, gy, center_x, center_y)
            color = getattr(car, "color", CAR_DEFAULT)
            direction_index = _car_direction_index(car)
            triangle = CAR_TRIANGLES_BY_DIRECTION[direction_index]
            points = [(sx + dx, sy + dy) for (dx, dy) in triangle]
            arcade.draw_polygon_filled(points, color)

        # Police cars (when active)
        for police in self.game.police_list:
            if police.state in ("deploying", "holding", "returning"):
                gx, gy, di = police.get_pose()
                sx, sy = grid_to_screen(gx, gy, center_x, center_y)
                color = police.get_light_color()
                triangle = CAR_TRIANGLES_BY_DIRECTION[di % 8]
                points = [(sx + dx, sy + dy) for (dx, dy) in triangle]
                arcade.draw_polygon_filled(points, color)

        # Visibility zone wireframe (debug: press V to toggle); color from sim visibility_state
        if self._show_visibility_fans:
            half = VIS_ZONE_WIDTH_CELLS / 2.0
            for car in self.game.cars:
                gx = getattr(car, "pose_gx", None)
                gy = getattr(car, "pose_gy", None)
                di = getattr(car, "pose_dir_index_8", None)
                if gx is None or gy is None:
                    curr = car.current_cell()
                    if curr is None:
                        continue
                    gx, gy = float(curr[0]), float(curr[1])
                if di is None:
                    di = _car_direction_index(car)
                verts = visibility_fan_vertices(gx, gy, di, VIS_ZONE_LENGTH_CELLS, half)
                state = getattr(car, "visibility_state", "green")
                fan_color = (
                    VIS_ZONE_COLOR_RED if state == "red"
                    else (VIS_ZONE_COLOR_YELLOW if state == "yellow"
                    else (VIS_ZONE_COLOR_WHITE if state == "white"
                    else (VIS_ZONE_COLOR_CYAN if state == "cyan" else VIS_ZONE_COLOR)))
                )
                screen_pts = [grid_to_screen(vx, vy, center_x, center_y) for vx, vy in verts]
                arcade.draw_polygon_outline(screen_pts, fan_color, VIS_ZONE_LINE_WIDTH)

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

        draw_ms = (time.perf_counter() - draw_start) * 1000.0
        alpha = 0.1
        if self._draw_ms_ema <= 0.0:
            self._draw_ms_ema = draw_ms
        else:
            self._draw_ms_ema = (1.0 - alpha) * self._draw_ms_ema + alpha * draw_ms
        perf = self.game.get_perf_stats()
        static_line_draws = len(self._intersection_path_lines) + len(self._lane_lines)
        self._perf_text.x = 10
        self._perf_text.y = self.height - 10
        self._perf_text.value = (
            f"FPS~{self._fps_ema:5.1f} substeps:{self._last_substeps} draw:{self._draw_ms_ema:5.2f}ms "
            f"cars:{perf['cars']} lines:{static_line_draws} tick:{float(perf['tick_ms_ema']):5.2f}ms "
            f"vis:{float(perf['visibility_ms_ema']):5.2f}ms checks:{perf['visibility_checks']} "
            f"pair:{float(perf['pair_ms_ema']):5.2f}ms checks:{perf['pair_checks']}"
        )
        self._perf_text.draw()

    def on_mouse_press(self, x: float, y: float, button: int, modifiers: int):
        if button != arcade.MOUSE_BUTTON_LEFT:
            return
        if self._traffic_slider.on_press(x, y):
            self._apply_traffic_step(self._traffic_slider.value)
            return
        if self._speed_slider.on_press(x, y):
            self._apply_speed_step(self._speed_slider.value)
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
