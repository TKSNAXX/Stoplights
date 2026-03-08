"""
Generate placeholder 32x32 ortho tiles for the tiled environment.
One-way lane tiles: road_n, road_s, road_e, road_w (N reflects S, E reflects W).
Right-hand traffic: one yellow (center) and one white (edge) stripe per tile.
Run: python scripts/generate_ortho_tiles.py
"""
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    raise SystemExit("Pillow required: pip install Pillow")

from sim.constants import ORTHO_TILE_SIZE

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "ortho"
GRASS = (60, 120, 40)
ROAD_GREY = (90, 90, 90)
YELLOW = (220, 220, 80)
WHITE = (220, 220, 220)

# Stripe positions: 2px bands. Yellow left (cols 2-3 / rows 2-3), white right (cols 28-29 / rows 28-29)
YELLOW_LO, YELLOW_HI = 2, 4
WHITE_LO, WHITE_HI = 28, 30

# Dashed yellow: half-tile (16px) dash, half-tile gap
DASH_LEN = ORTHO_TILE_SIZE // 2


def make_grass() -> Image.Image:
    return Image.new("RGBA", (ORTHO_TILE_SIZE, ORTHO_TILE_SIZE), (*GRASS, 255))


def _vert_stripe(img: Image.Image, yellow_col: int, white_col: int) -> None:
    """Draw vertical stripes at given column ranges."""
    for col in range(yellow_col, yellow_col + 2):
        for row in range(ORTHO_TILE_SIZE):
            img.putpixel((col, row), (*YELLOW, 255))
    for col in range(white_col, white_col + 2):
        for row in range(ORTHO_TILE_SIZE):
            img.putpixel((col, row), (*WHITE, 255))


def _horiz_stripe(img: Image.Image, yellow_row: int, white_row: int) -> None:
    """Draw horizontal stripes at given row ranges."""
    for row in range(yellow_row, yellow_row + 2):
        for col in range(ORTHO_TILE_SIZE):
            img.putpixel((col, row), (*YELLOW, 255))
    for row in range(white_row, white_row + 2):
        for col in range(ORTHO_TILE_SIZE):
            img.putpixel((col, row), (*WHITE, 255))


def _vert_stripe_dashed(img: Image.Image, yellow_col: int, white_col: int) -> None:
    """Vertical stripes with dashed yellow (half-tile dash). White solid."""
    for col in range(yellow_col, yellow_col + 2):
        for row in range(0, DASH_LEN):
            img.putpixel((col, row), (*YELLOW, 255))
    for col in range(white_col, white_col + 2):
        for row in range(ORTHO_TILE_SIZE):
            img.putpixel((col, row), (*WHITE, 255))


def _horiz_stripe_dashed(img: Image.Image, yellow_row: int, white_row: int) -> None:
    """Horizontal stripes with dashed yellow (half-tile dash). White solid."""
    for row in range(yellow_row, yellow_row + 2):
        for col in range(0, DASH_LEN):
            img.putpixel((col, row), (*YELLOW, 255))
    for row in range(white_row, white_row + 2):
        for col in range(ORTHO_TILE_SIZE):
            img.putpixel((col, row), (*WHITE, 255))


def make_road_n() -> Image.Image:
    """N lanes: yellow on ortho bottom (inside after iso)."""
    img = Image.new("RGBA", (ORTHO_TILE_SIZE, ORTHO_TILE_SIZE), (*ROAD_GREY, 255))
    _horiz_stripe(img, WHITE_LO, YELLOW_LO)  # yellow bottom, white top
    return img


def make_road_s() -> Image.Image:
    """S lanes: yellow on ortho top (inside after iso)."""
    img = Image.new("RGBA", (ORTHO_TILE_SIZE, ORTHO_TILE_SIZE), (*ROAD_GREY, 255))
    _horiz_stripe(img, YELLOW_LO, WHITE_LO)  # yellow top, white bottom
    return img


def make_road_e() -> Image.Image:
    """E lanes: yellow on ortho left (inside after iso)."""
    img = Image.new("RGBA", (ORTHO_TILE_SIZE, ORTHO_TILE_SIZE), (*ROAD_GREY, 255))
    _vert_stripe(img, YELLOW_LO, WHITE_LO)  # yellow left, white right
    return img


def make_road_w() -> Image.Image:
    """W lanes: yellow on ortho right (inside after iso)."""
    img = Image.new("RGBA", (ORTHO_TILE_SIZE, ORTHO_TILE_SIZE), (*ROAD_GREY, 255))
    _vert_stripe(img, WHITE_LO, YELLOW_LO)  # yellow right, white left
    return img


def make_road_n_pass() -> Image.Image:
    """N passing lane: dashed yellow on ortho bottom."""
    img = Image.new("RGBA", (ORTHO_TILE_SIZE, ORTHO_TILE_SIZE), (*ROAD_GREY, 255))
    _horiz_stripe_dashed(img, WHITE_LO, YELLOW_LO)
    return img


def make_road_s_pass() -> Image.Image:
    """S passing lane: dashed yellow on ortho top."""
    img = Image.new("RGBA", (ORTHO_TILE_SIZE, ORTHO_TILE_SIZE), (*ROAD_GREY, 255))
    _horiz_stripe_dashed(img, YELLOW_LO, WHITE_LO)
    return img


def make_road_e_pass() -> Image.Image:
    """E passing lane: dashed yellow on ortho left."""
    img = Image.new("RGBA", (ORTHO_TILE_SIZE, ORTHO_TILE_SIZE), (*ROAD_GREY, 255))
    _vert_stripe_dashed(img, YELLOW_LO, WHITE_LO)
    return img


def make_road_w_pass() -> Image.Image:
    """W passing lane: dashed yellow on ortho right."""
    img = Image.new("RGBA", (ORTHO_TILE_SIZE, ORTHO_TILE_SIZE), (*ROAD_GREY, 255))
    _vert_stripe_dashed(img, WHITE_LO, YELLOW_LO)
    return img


def make_road_cross() -> Image.Image:
    return Image.new("RGBA", (ORTHO_TILE_SIZE, ORTHO_TILE_SIZE), (*ROAD_GREY, 255))


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    make_grass().save(ASSETS / "grass.png")
    print("Saved grass.png")
    make_road_n().save(ASSETS / "road_n.png")
    make_road_s().save(ASSETS / "road_s.png")
    make_road_e().save(ASSETS / "road_e.png")
    make_road_w().save(ASSETS / "road_w.png")
    make_road_n_pass().save(ASSETS / "road_n_pass.png")
    make_road_s_pass().save(ASSETS / "road_s_pass.png")
    make_road_e_pass().save(ASSETS / "road_e_pass.png")
    make_road_w_pass().save(ASSETS / "road_w_pass.png")
    print("Saved road_n/s/e/w.png, road_n/s/e/w_pass.png")
    make_road_cross().save(ASSETS / "road_cross.png")
    print("Saved road_cross.png")
    print("Done. Place ortho tiles in assets/ortho/ and restart.")


if __name__ == "__main__":
    main()
