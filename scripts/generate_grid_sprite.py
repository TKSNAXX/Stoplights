"""
One-off script to generate assets/grid_background.png at 800x600.
Near-black background, thin isometric grid lines matching main.py projection.
Run once: python scripts/generate_grid_sprite.py
"""
from pathlib import Path
from sim.constants import TILE_H, TILE_W
from sim.world import GRID_H, GRID_W

try:
    from PIL import Image, ImageDraw
except ImportError:
    raise SystemExit("Pillow required: pip install Pillow")

# Match main.py/world constants
WIDTH, HEIGHT = 800, 600
CENTER_X, CENTER_Y = WIDTH / 2, HEIGHT / 2
CX_GRID = (GRID_W - 1) / 2
CY_GRID = (GRID_H - 1) / 2

# Near-black background, thin subtle grid (user: near black, thinner lines)
BG_COLOR = (10, 10, 10)  # near black
GRID_COLOR = (24, 24, 24)  # subtle, thinner appearance
LINE_WIDTH = 1


def grid_to_screen(gx: float, gy: float) -> tuple[float, float]:
    sx = CENTER_X + (gx - gy) * TILE_W
    sy = CENTER_Y + (gx + gy - CX_GRID - CY_GRID) * TILE_H
    return (sx, sy)


def main():
    assets = Path(__file__).resolve().parent.parent / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    out_path = assets / "grid_background.png"

    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    for gx in range(GRID_W + 1):
        for gy in range(GRID_H):
            sx1, sy1 = grid_to_screen(gx, gy)
            sx2, sy2 = grid_to_screen(gx, gy + 1)
            draw.line([(sx1, sy1), (sx2, sy2)], fill=GRID_COLOR, width=LINE_WIDTH)
    for gy in range(GRID_H + 1):
        for gx in range(GRID_W):
            sx1, sy1 = grid_to_screen(gx, gy)
            sx2, sy2 = grid_to_screen(gx + 1, gy)
            draw.line([(sx1, sy1), (sx2, sy2)], fill=GRID_COLOR, width=LINE_WIDTH)

    img.save(out_path)
    print(f"Saved {out_path}")


if __name__ == "__main__":
    main()
