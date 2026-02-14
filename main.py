"""
Stoplights — entry point.
Display layer: reads sim state, draws isometric grid, one lane, two places (Housing, Office), cars.
Game loop: fixed timestep calls sim.tick(); no player input.
"""
import arcade

from sim.game import GameState
from sim import places
from sim.world import ALL_LANES, GRID_W, GRID_H

# Sim ticks per second
TICKS_PER_SECOND = 15
TICK_DT = 1.0 / TICKS_PER_SECOND

# Isometric tile half-size in pixels (diamond: width 2*TILE_W, height 2*TILE_H)
TILE_W = 12
TILE_H = 6

# Display colors
GRID_COLOR = (70, 70, 70)
ROAD_GREY = (80, 80, 80)
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

    def on_update(self, delta_time: float):
        self._tick_accumulator += delta_time
        while self._tick_accumulator >= TICK_DT:
            self.game.tick(TICK_DT)
            self._tick_accumulator -= TICK_DT

    def on_draw(self):
        self.clear()
        center_x = self.width / 2
        center_y = self.height / 2

        # Lane lines (one lane: Housing -> Office)
        LANE_WIDTH = 4
        for lane in ALL_LANES:
            for i in range(len(lane) - 1):
                gx1, gy1 = lane[i]
                gx2, gy2 = lane[i + 1]
                sx1, sy1 = grid_to_screen(gx1, gy1, center_x, center_y)
                sx2, sy2 = grid_to_screen(gx2, gy2, center_x, center_y)
                arcade.draw_line(sx1, sy1, sx2, sy2, ROAD_GREY, LANE_WIDTH)

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
