"""
Isometric wireframe cube on the same cell geometry as the car placeholders.

Footprint matches the 64x32 tile diamond (TILE_W / TILE_H). Height is one ortho
tile so the verticals read as a cube. Hidden edges (far bottom-north corner)
are drawn dimmer.

Run: python scripts/generate_iso_cube.py
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sim.constants import ORTHO_TILE_SIZE, TILE_H, TILE_W

try:
    from PIL import Image, ImageDraw
except ImportError:
    raise SystemExit("Pillow required: pip install Pillow")

# Same diamond as generate_car_sprites.py, parked in the lower half of a 64x64 canvas
# so the cube has room to stand up.
CANVAS_W = TILE_W * 2
CANVAS_H = TILE_H * 2 + ORTHO_TILE_SIZE
CX = TILE_W
CY = TILE_H + ORTHO_TILE_SIZE
CUBE_H = ORTHO_TILE_SIZE

VISIBLE = (210, 210, 210, 255)
HIDDEN = (110, 110, 110, 255)


def diamond_at(cx: int, cy: int) -> list[tuple[int, int]]:
    """Diamond corners: N, E, S, W (grid north is screen-up-left in this project)."""
    return [
        (cx, cy - TILE_H),
        (cx + TILE_W, cy),
        (cx, cy + TILE_H),
        (cx - TILE_W, cy),
    ]


def main() -> None:
    assets = Path(__file__).resolve().parent.parent / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    bot = diamond_at(CX, CY)
    top = [(x, y - CUBE_H) for x, y in bot]
    n_b, e_b, s_b, w_b = bot
    n_t, e_t, s_t, w_t = top

    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    hidden = [
        (n_b, e_b),
        (n_b, w_b),
        (n_b, n_t),
    ]
    visible = [
        (n_t, e_t),
        (e_t, s_t),
        (s_t, w_t),
        (w_t, n_t),
        (e_b, s_b),
        (s_b, w_b),
        (e_b, e_t),
        (s_b, s_t),
        (w_b, w_t),
    ]
    for a, b in hidden:
        draw.line([a, b], fill=HIDDEN, width=1)
    for a, b in visible:
        draw.line([a, b], fill=VISIBLE, width=1)

    out = assets / "cube_wire.png"
    img.save(out)
    print(f"Saved {out.name} ({CANVAS_W}x{CANVAS_H})")


if __name__ == "__main__":
    main()
