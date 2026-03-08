"""
Generate intersection sprite (solid grey isometric rhombus, no path draws).
Matches lane tile character: h-biased diamond, ROAD_GREY, pixel-perfect.
Run once: python scripts/generate_intersection_sprite.py
"""
from pathlib import Path
from sim.constants import LANE_DOWNWARD_GREY, TILE_H, TILE_W

try:
    from PIL import Image, ImageDraw
except ImportError:
    raise SystemExit("Pillow required: pip install Pillow")

# Match main.py
ROAD_GREY = LANE_DOWNWARD_GREY

# Intersection spans 3x3 grid cells; diamond extends 1.5 cells from center
HALF_W = int(1.5 * TILE_W)  # 18
HALF_H = int(1.5 * TILE_H)  # 9
CENTER_X = HALF_W + 4
CENTER_Y = HALF_H + 2
W, H = CENTER_X * 2, CENTER_Y * 2


def diamond_vertices():
    """Diamond corners: top, right, bottom, left."""
    return [
        (CENTER_X, CENTER_Y - HALF_H),
        (CENTER_X + HALF_W, CENTER_Y),
        (CENTER_X, CENTER_Y + HALF_H),
        (CENTER_X - HALF_W, CENTER_Y),
    ]


def main():
    assets = Path(__file__).resolve().parent.parent / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.polygon(diamond_vertices(), fill=ROAD_GREY, outline=ROAD_GREY)
    img.save(assets / "intersection.png")
    print("Saved intersection.png")


if __name__ == "__main__":
    main()
