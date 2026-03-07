"""
Generate 8 car placeholder sprites (car_N.png … car_NW.png).
Each has a grey isometric rhombus "floor" (drawing guide) plus a wedge pre-oriented
for its direction. Erase the floor when finished with your art.
Run once: python scripts/generate_car_sprites.py
"""
import math
from pathlib import Path
from sim.constants import CAR_SIZE, CAR_TRIANGLE_BASE_HALF, TILE_H, TILE_W

try:
    from PIL import Image, ImageDraw
except ImportError:
    raise SystemExit("Pillow required: pip install Pillow")

# Match lane tile geometry (generate_lane_sprites.py)
CENTER_X = 16
CENTER_Y = 10
W, H = 32, 20
FLOOR_GREY = (80, 80, 80)
WEDGE_COLOR = (200, 200, 200)

# Eight directions: N, NE, E, SE, S, SW, W, NW (order matches main.py direction index 0..7)
DIRECTION_NAMES = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
DIRECTIONS = [
    (-TILE_W, TILE_H),    # N
    (0, 2 * TILE_H),      # NE
    (TILE_W, TILE_H),     # E
    (2 * TILE_W, 0),      # SE
    (TILE_W, -TILE_H),    # S
    (0, -2 * TILE_H),     # SW
    (-TILE_W, -TILE_H),   # W
    (-2 * TILE_W, 0),     # NW
]


def diamond_vertices():
    """Diamond corners: top, right, bottom, left."""
    return [
        (CENTER_X, CENTER_Y - TILE_H),
        (CENTER_X + TILE_W, CENTER_Y),
        (CENTER_X, CENTER_Y + TILE_H),
        (CENTER_X - TILE_W, CENTER_Y),
    ]


def wedge_vertices(dir_sx: float, dir_sy: float) -> list[tuple[float, float]]:
    """Return 3 vertices (tip, base_left, base_right) in pixel coords, centered at (CENTER_X, CENTER_Y)."""
    length = math.sqrt(dir_sx * dir_sx + dir_sy * dir_sy)
    if length < 1e-6:
        tx, ty = 0, CAR_SIZE
        perp_x, perp_y = 1, 0
    else:
        tx = dir_sx * CAR_SIZE / length
        ty = dir_sy * CAR_SIZE / length
        perp_x = dir_sy / length
        perp_y = -dir_sx / length
    b1_x = perp_x * CAR_TRIANGLE_BASE_HALF
    b1_y = perp_y * CAR_TRIANGLE_BASE_HALF
    return [
        (CENTER_X + tx, CENTER_Y + ty),
        (CENTER_X + b1_x, CENTER_Y + b1_y),
        (CENTER_X - b1_x, CENTER_Y - b1_y),
    ]


def main():
    assets = Path(__file__).resolve().parent.parent / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    for name, (dx, dy) in zip(DIRECTION_NAMES, DIRECTIONS):
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.polygon(diamond_vertices(), fill=FLOOR_GREY, outline=FLOOR_GREY)
        verts = wedge_vertices(dx, dy)
        draw.polygon(verts, fill=WEDGE_COLOR, outline=WEDGE_COLOR)
        img.save(assets / f"car_{name}.png")
        print(f"Saved car_{name}.png")

    print("Done. 8 car placeholders with floor guide. Erase the floor when finished.")


if __name__ == "__main__":
    main()
