"""
Stoplights — entry point.
Display layer: reads sim state, draws isometric grid, lanes (three places), cars.
Game loop: fixed timestep calls sim.tick(); no player input.
"""
import arcade

from sim.game import GameState
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

    def on_update(self, delta_time: float):
        self._tick_accumulator += delta_time
        while self._tick_accumulator >= TICK_DT:
            self._car_prev_cell = {id(c): c.current_cell() for c in self.game.cars}
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

        # Blue outlined buildings for each place (6×6 bounding box)
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

        # Cars as isometric cubes (small diamond / top face); interpolate between prev and curr for smooth motion
        CAR_DEFAULT = (220, 60, 60)
        CAR_SIZE = 6
        for car in self.game.cars:
            curr = car.current_cell()
            if curr is None:
                continue
            prev = self._car_prev_cell.get(id(car), curr)
            if prev is None:
                gx, gy = float(curr[0]), float(curr[1])
            else:
                blend = min(1.0, self._tick_accumulator / TICK_DT)
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


def main():
    window = StoplightsWindow()
    arcade.run()


if __name__ == "__main__":
    main()
