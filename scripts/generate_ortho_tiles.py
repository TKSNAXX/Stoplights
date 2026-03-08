"""
Generate placeholder 32x32 ortho tiles for the tiled environment.
Simple: grass, road_ns, road_ew, road_cross. Drop into assets/ortho/.
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
ROAD_GREY = (90, 90, 90)
YELLOW = (220, 220, 80)
WHITE = (220, 220, 220)


def make_grass() -> Image.Image:
    img = Image.new("RGBA", (ORTHO_TILE_SIZE, ORTHO_TILE_SIZE), (*GRASS, 255))
    return img


def make_road_ns() -> Image.Image:
    """Vertical road: N-S. Yellow center cols 15-16, white edges cols 2-3 and 28-29."""
    img = Image.new("RGBA", (ORTHO_TILE_SIZE, ORTHO_TILE_SIZE), (*ROAD_GREY, 255))
    for col in range(15, 17):
        for row in range(ORTHO_TILE_SIZE):
            img.putpixel((col, row), (*YELLOW, 255))
    for col in range(2, 4):
        for row in range(ORTHO_TILE_SIZE):
            img.putpixel((col, row), (*WHITE, 255))
    for col in range(28, 30):
        for row in range(ORTHO_TILE_SIZE):
            img.putpixel((col, row), (*WHITE, 255))
    return img


def make_road_ew() -> Image.Image:
    """Horizontal road: E-W. Yellow center rows 15-16, white edges rows 2-3 and 28-29."""
    img = Image.new("RGBA", (ORTHO_TILE_SIZE, ORTHO_TILE_SIZE), (*ROAD_GREY, 255))
    for row in range(15, 17):
        for col in range(ORTHO_TILE_SIZE):
            img.putpixel((col, row), (*YELLOW, 255))
    for row in range(2, 4):
        for col in range(ORTHO_TILE_SIZE):
            img.putpixel((col, row), (*WHITE, 255))
    for row in range(28, 30):
        for col in range(ORTHO_TILE_SIZE):
            img.putpixel((col, row), (*WHITE, 255))
    return img


def make_road_cross() -> Image.Image:
    img = Image.new("RGBA", (ORTHO_TILE_SIZE, ORTHO_TILE_SIZE), (*ROAD_GREY, 255))
    return img


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    make_grass().save(ASSETS / "grass.png")
    print("Saved grass.png")
    make_road_ns().save(ASSETS / "road_ns.png")
    print("Saved road_ns.png")
    make_road_ew().save(ASSETS / "road_ew.png")
    print("Saved road_ew.png")
    make_road_cross().save(ASSETS / "road_cross.png")
    print("Saved road_cross.png")
    print("Done. Place ortho tiles in assets/ortho/ and restart.")


if __name__ == "__main__":
    main()
