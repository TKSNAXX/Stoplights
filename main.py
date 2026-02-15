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

from sim.game import GameState, MOVEMENT_EVERY_N_TICKS
from sim import places
from sim.world import ALL_LANES, GRID_W, GRID_H, get_intersection_cells

# Sim ticks per second (high rate for smooth interpolation; movement runs every Nth tick for half speed)
TICKS_PER_SECOND = 120
TICK_DT = 1.0 / TICKS_PER_SECOND

# Isometric tile half-size in pixels (diamond: width 2*TILE_W, height 2*TILE_H)
TILE_W = 12
TILE_H = 6

# Display colors
GRID_COLOR = (70, 70, 70)
ROAD_GREY = (80, 80, 80)
LANE_UPWARD_GREY = (165, 165, 165)
LANE_DOWNWARD_GREY = (80, 80, 80)
BUILDING_OUTLINE_WIDTH = 2
PLACE_LABEL_COLOR = (220, 220, 220)
PLACE_LABEL_FONT_SIZE = 12

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


def spawn_interval_for_step(step: int) -> float:
    """Log scale: step 2 = 2.0 s, step 0 = ~5 s, step 9 = ~0.08 s."""
    step = max(0, min(TRAFFIC_STEPS - 1, step))
    k = (math.log10(5.0) - math.log10(2.0)) / -2  # so interval(0) ≈ 5
    return 2.0 * (10.0 ** ((step - TRAFFIC_DEFAULT_STEP) * k))


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


class StoplightsWindow(arcade.Window):
    def __init__(self):
        super().__init__(800, 600, "Stoplights")
        arcade.set_background_color(arcade.color.BLACK)
        self.game = GameState()
        self._tick_accumulator = 0.0
        self._car_prev_cell: dict[int, tuple[int, int] | None] = {}
        self._time = 0.0
        self._last_movement_time: float | None = None
        # Interpolation duration (sec) for each cell move; slightly longer for smoother ease-in
        self._move_duration = 0.2
        # Traffic slider: step 0..9, default 2 (display "3 of 10")
        self._traffic_step = TRAFFIC_DEFAULT_STEP
        self._slider_dragging = False
        # Reusable Text for slider label (avoids slow draw_text per frame)
        self._traffic_label = arcade.Text(
            "",
            SLIDER_LEFT,
            SLIDER_BOTTOM + SLIDER_HEIGHT + 4,
            color=PLACE_LABEL_COLOR,
            font_size=SLIDER_LABEL_FONT_SIZE,
        )

    def _slider_step_from_x(self, x: float) -> int:
        """Map screen x to step 0..TRAFFIC_STEPS-1."""
        t = (x - SLIDER_LEFT) / SLIDER_WIDTH
        t = max(0.0, min(1.0, t))
        return int(t * (TRAFFIC_STEPS - 1) + 0.5) if TRAFFIC_STEPS > 1 else 0

    def _apply_traffic_step(self, step: int) -> None:
        step = max(0, min(TRAFFIC_STEPS - 1, step))
        self._traffic_step = step
        self.game.spawn_interval = spawn_interval_for_step(step)

    def on_update(self, delta_time: float):
        self._time += delta_time
        self._tick_accumulator += delta_time
        while self._tick_accumulator >= TICK_DT:
            # Snapshot only before a movement tick so prev isn't overwritten by no-op ticks
            if (self.game._tick_count % MOVEMENT_EVERY_N_TICKS) == (MOVEMENT_EVERY_N_TICKS - 1):
                self._car_prev_cell = {id(c): c.current_cell() for c in self.game.cars}
                self._last_movement_time = self._time
            self.game.tick(TICK_DT)
            self._tick_accumulator -= TICK_DT

    def on_draw(self):
        self.clear()
        center_x = self.width / 2
        center_y = self.height / 2

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

        # Dark grey isometric grid lines
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

        # Cars: interpolate prev -> curr over _move_duration with smoothstep (Mini Metro style)
        CAR_DEFAULT = (220, 60, 60)
        CAR_SIZE = 6
        for car in self.game.cars:
            curr = car.current_cell()
            if curr is None:
                continue
            prev = self._car_prev_cell.get(id(car), curr)
            if prev is None or self._last_movement_time is None:
                gx, gy = float(curr[0]), float(curr[1])
            else:
                elapsed = self._time - self._last_movement_time
                blend = smoothstep(min(1.0, elapsed / self._move_duration))
                gx = prev[0] + blend * (curr[0] - prev[0])
                gy = prev[1] + blend * (curr[1] - prev[1])
            sx, sy = grid_to_screen(gx, gy, center_x, center_y)
            color = getattr(car, "color", CAR_DEFAULT)
            arcade.draw_polygon_filled(
                [
                    (sx, sy + CAR_SIZE),
                    (sx + CAR_SIZE, sy),
                    (sx, sy - CAR_SIZE),
                    (sx - CAR_SIZE, sy),
                ],
                color,
            )

        # Traffic slider (custom): bar + thumb + label "Traffic: X/10"
        bar_y = SLIDER_BOTTOM + (SLIDER_HEIGHT - SLIDER_BAR_HEIGHT) / 2
        _rect_filled(SLIDER_LEFT + SLIDER_WIDTH / 2, bar_y, SLIDER_WIDTH, SLIDER_BAR_HEIGHT, SLIDER_COLOR)
        thumb_w = 16
        thumb_x = SLIDER_LEFT + thumb_w / 2 + (self._traffic_step / max(1, TRAFFIC_STEPS - 1)) * (SLIDER_WIDTH - thumb_w) if TRAFFIC_STEPS > 1 else SLIDER_LEFT + thumb_w / 2
        _rect_filled(thumb_x, bar_y, thumb_w, SLIDER_HEIGHT - 4, SLIDER_THUMB_COLOR)
        self._traffic_label.value = f"Traffic: {self._traffic_step + 1}/{TRAFFIC_STEPS}"
        self._traffic_label.draw()

    def on_mouse_press(self, x: float, y: float, button: int, modifiers: int):
        if button != arcade.MOUSE_BUTTON_LEFT:
            return
        if SLIDER_LEFT <= x <= SLIDER_LEFT + SLIDER_WIDTH and SLIDER_BOTTOM <= y <= SLIDER_BOTTOM + SLIDER_HEIGHT:
            self._slider_dragging = True
            self._apply_traffic_step(self._slider_step_from_x(x))

    def on_mouse_drag(self, x: float, y: float, dx: float, dy: float, buttons: int, modifiers: int):
        if self._slider_dragging and (buttons & arcade.MOUSE_BUTTON_LEFT):
            self._apply_traffic_step(self._slider_step_from_x(x))

    def on_mouse_release(self, x: float, y: float, button: int, modifiers: int):
        if button == arcade.MOUSE_BUTTON_LEFT:
            self._slider_dragging = False


def main():
    window = StoplightsWindow()
    arcade.run()


if __name__ == "__main__":
    main()
