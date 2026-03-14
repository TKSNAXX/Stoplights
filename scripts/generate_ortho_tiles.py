"""
Generate placeholder 32x32 ortho tiles for the tiled environment.
One-way lane tiles: road_n, road_s, road_e, road_w (N reflects S, E reflects W).
Right-hand traffic: one yellow (center) and one white (edge) stripe per tile.
Run: python scripts/generate_ortho_tiles.py
"""
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    raise SystemExit("Pillow required: pip install Pillow")

from sim.constants import ORTHO_TILE_SIZE

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "ortho"
GRASS = (60, 120, 40)
PLACE_ZONE = (90, 140, 50)
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


def make_place_zone() -> Image.Image:
    return Image.new("RGBA", (ORTHO_TILE_SIZE, ORTHO_TILE_SIZE), (*PLACE_ZONE, 255))


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


# Corner tile: 128x128 for 4x4 bypass intersection
CORNER_SIZE = ORTHO_TILE_SIZE * 4

# Lane alignment: arc bands sit ~2px outside where they meet straight lanes.
# Apply this offset to all corner band radii (use for future corners too).
CORNER_LANE_ALIGN_OFFSET = -2

# Arc center = NW corner = lower-left in ortho (0, 127)
# Arc starts on bottom, proceeds upward and leftward 90° to left edge
# Six 2px bands (outer to inner): grey, wh, yel, yel, wh, grey. Offset applied.
# Grey stripes adjacent outside each white for road edge; trim = transparent outside wedge.
CORNER_ARC_CX = 0
CORNER_ARC_CY = CORNER_SIZE - 1
CORNER_BANDS_SPEC = [
    (ROAD_GREY, 95, 97),  # outer grey, 2px outside outer white
    (WHITE, 93, 95),      # outer white
    (YELLOW, 67, 69),     # yellow
    (YELLOW, 61, 63),     # yellow
    (WHITE, 35, 37),      # inner white
    (ROAD_GREY, 33, 35),  # inner grey, 2px outside inner white (toward center)
]


def _arc_bands_with_offset(
    bands: list[tuple[tuple[int, int, int], int, int]],
    offset: int = CORNER_LANE_ALIGN_OFFSET,
) -> list[tuple[tuple[int, int, int], int, int]]:
    """Apply lane alignment offset to band (r_inner, r_outer). Use for all corner arcs."""
    return [(color, r_in + offset, r_out + offset) for color, r_in, r_out in bands]


def _draw_arc_bands(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    start_angle: float,
    end_angle: float,
    bands: list[tuple[tuple[int, int, int], int, int]],
    fill_color: tuple[int, int, int],
) -> None:
    """Draw concentric arc bands outside-in. Each band is (color, r_inner, r_outer). Rest is fill_color."""
    for color, r_inner, r_outer in bands:
        bbox = (cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer)
        draw.pieslice(bbox, start_angle, end_angle, fill=(*color, 255))
        if r_inner > 0:
            inner_bbox = (cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner)
            draw.pieslice(inner_bbox, start_angle, end_angle, fill=(*fill_color, 255))


def make_corner() -> Image.Image:
    """
    Bypass corner: wh/2yel/wh stripes in 90° arc, grey borders, transparent outside wedge.
    Center at NW (lower-left). Arc from bottom upward and leftward.
    Parametric bands for reuse.
    """
    img = Image.new("RGBA", (CORNER_SIZE, CORNER_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    start_angle, end_angle = 270, 360
    bands = _arc_bands_with_offset(CORNER_BANDS_SPEC)
    outer_r = max(r_out for _, _, r_out in bands)
    inner_r = min(r_in for _, r_in, _ in bands)
    # Road grey base wedge (inner and outer trimmed for transparency)
    bbox_base = (CORNER_ARC_CX - outer_r, CORNER_ARC_CY - outer_r, CORNER_ARC_CX + outer_r, CORNER_ARC_CY + outer_r)
    draw.pieslice(bbox_base, start_angle, end_angle, fill=(*ROAD_GREY, 255))
    _draw_arc_bands(
        img, draw,
        CORNER_ARC_CX, CORNER_ARC_CY,
        start_angle, end_angle,
        bands,
        ROAD_GREY,
    )
    # Clear inner segment to transparent (center inside innermost band)
    bbox_inner = (CORNER_ARC_CX - inner_r, CORNER_ARC_CY - inner_r, CORNER_ARC_CX + inner_r, CORNER_ARC_CY + inner_r)
    draw.pieslice(bbox_inner, start_angle, end_angle, fill=(0, 0, 0, 0))
    return img


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    make_grass().save(ASSETS / "grass.png")
    make_place_zone().save(ASSETS / "place_zone.png")
    print("Saved grass.png, place_zone.png")
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
    make_corner().save(ASSETS / "corner.png")
    print("Saved road_cross.png, corner.png")
    print("Done. Place ortho tiles in assets/ortho/ and restart.")


if __name__ == "__main__":
    main()
