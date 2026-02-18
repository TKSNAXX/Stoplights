"""
Generate 4 cardinal lane tile sprites (N, S, E, W).
Each is an h-biased isometric rhombus with stripe pair (1 yellow, 5 grey, 2 white) pre-oriented.
No runtime rotation—one sprite per lane cell.
Run once: python scripts/generate_lane_sprites.py
"""
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    raise SystemExit("Pillow required: pip install Pillow")

# Match main.py isometric tile geometry
TILE_W = 12  # half-width
TILE_H = 6   # half-height
CENTER_X = 16
CENTER_Y = 10
W, H = 32, 20  # canvas size
YELLOW = (220, 220, 80)
GREY = (95, 95, 95)
WHITE = (220, 220, 220)
STRIPE_HALF = 4  # 8 px band: 4 above and below center


def diamond_vertices():
    """Diamond corners: top, right, bottom, left."""
    return [
        (CENTER_X, CENTER_Y - TILE_H),
        (CENTER_X + TILE_W, CENTER_Y),
        (CENTER_X, CENTER_Y + TILE_H),
        (CENTER_X - TILE_W, CENTER_Y),
    ]


def in_diamond(px: int, py: int) -> bool:
    """Point-in-diamond test: |dx|/TILE_W + |dy|/TILE_H <= 1."""
    dx = abs(px - CENTER_X)
    dy = abs(py - CENTER_Y)
    return dx / TILE_W + dy / TILE_H <= 1.0


def stripe_color_for_y(py: int) -> tuple[int, int, int]:
    """Stripe pattern: row 0 = yellow, 1-5 = grey, 6-7 = white. py relative to band top."""
    row = py
    if row < 0 or row >= 8:
        return GREY  # outside band
    if row == 0:
        return YELLOW
    if row < 6:
        return GREY
    return WHITE


def make_rhombus_horizontal_stripe() -> Image.Image:
    """Rhombus with horizontal stripe (E–W) for N, S lanes."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.polygon(diamond_vertices(), fill=GREY, outline=GREY)
    band_top = CENTER_Y - STRIPE_HALF
    for py in range(H):
        for px in range(W):
            if in_diamond(px, py):
                local_y = py - band_top
                if 0 <= local_y < 8:
                    color = stripe_color_for_y(local_y)
                    img.putpixel((px, py), (*color, 255))
    return img


def make_rhombus_vertical_stripe() -> Image.Image:
    """Rhombus with vertical stripe (N–S) for E, W lanes."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.polygon(diamond_vertices(), fill=GREY, outline=GREY)
    band_left = CENTER_X - STRIPE_HALF
    for py in range(H):
        for px in range(W):
            if in_diamond(px, py):
                local_x = px - band_left
                if 0 <= local_x < 8:
                    color = stripe_color_for_y(local_x)  # reuse same pattern
                    img.putpixel((px, py), (*color, 255))
    return img


def main():
    assets = Path(__file__).resolve().parent.parent / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    for name in ("N", "S"):
        img = make_rhombus_horizontal_stripe()
        img.save(assets / f"lane_{name}.png")
        print(f"Saved lane_{name}.png")
    for name in ("E", "W"):
        img = make_rhombus_vertical_stripe()
        img.save(assets / f"lane_{name}.png")
        print(f"Saved lane_{name}.png")


if __name__ == "__main__":
    main()
