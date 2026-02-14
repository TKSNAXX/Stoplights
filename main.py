"""
Stoplights — entry point.
Display layer: reads sim state, draws isometric grid, lanes, intersection, cars.
Game loop: fixed timestep calls sim.tick(); no player input.
"""
import arcade

from sim.game import GameState
from sim.world import ALL_LANES, GRID_W, GRID_H

# Sim ticks per second
TICKS_PER_SECOND = 15
TICK_DT = 1.0 / TICKS_PER_SECOND

# Isometric tile half-size in pixels (diamond: width 2*TILE_W, height 2*TILE_H)
TILE_W = 12
TILE_H = 6


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

    def on_update(self, delta_time: float):
        self._tick_accumulator += delta_time
        while self._tick_accumulator >= TICK_DT:
            self.game.tick(TICK_DT)
            self._tick_accumulator -= TICK_DT

    def on_draw(self):
        self.clear()
        center_x = self.width / 2
        center_y = self.height / 2

        # Grey filled intersection (2×2): corners of block in grid (16,16)-(18,18)
        inter_corners = [(16, 16), (18, 16), (18, 18), (16, 18)]
        pts = [grid_to_screen(gx, gy, center_x, center_y) for gx, gy in inter_corners]
        arcade.draw_polygon_filled(pts, (80, 80, 80))

        # Broad grey lines for lanes (isometric segments)
        LANE_WIDTH = 4
        GREY = (100, 100, 100)
        for lane in ALL_LANES:
            for i in range(len(lane) - 1):
                gx1, gy1 = lane[i]
                gx2, gy2 = lane[i + 1]
                sx1, sy1 = grid_to_screen(gx1, gy1, center_x, center_y)
                sx2, sy2 = grid_to_screen(gx2, gy2, center_x, center_y)
                arcade.draw_line(sx1, sy1, sx2, sy2, GREY, LANE_WIDTH)

        # White isometric grid lines on black
        for gx in range(GRID_W + 1):
            for gy in range(GRID_H):
                sx1, sy1 = grid_to_screen(gx, gy, center_x, center_y)
                sx2, sy2 = grid_to_screen(gx, gy + 1, center_x, center_y)
                arcade.draw_line(sx1, sy1, sx2, sy2, arcade.color.WHITE, 1)
        for gy in range(GRID_H + 1):
            for gx in range(GRID_W):
                sx1, sy1 = grid_to_screen(gx, gy, center_x, center_y)
                sx2, sy2 = grid_to_screen(gx + 1, gy, center_x, center_y)
                arcade.draw_line(sx1, sy1, sx2, sy2, arcade.color.WHITE, 1)

        # Cars as red isometric cubes (small diamond / top face)
        CAR_RED = (220, 60, 60)
        CAR_SIZE = 6
        for car in self.game.cars:
            cell = car.current_cell()
            if cell is None:
                continue
            sx, sy = grid_to_screen(cell[0], cell[1], center_x, center_y)
            # Isometric top of cube: diamond centered at (sx, sy)
            arcade.draw_polygon_filled(
                [
                    (sx, sy + CAR_SIZE),
                    (sx + CAR_SIZE, sy),
                    (sx, sy - CAR_SIZE),
                    (sx - CAR_SIZE, sy),
                ],
                CAR_RED,
            )


def main():
    window = StoplightsWindow()
    arcade.run()


if __name__ == "__main__":
    main()
