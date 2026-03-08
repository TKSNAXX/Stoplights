"""Ortho-to-iso tile loading and TileSet management."""
from __future__ import annotations

from pathlib import Path

import arcade

try:
    from PIL import Image
    from PIL.Image import AFFINE, NEAREST
except ImportError:
    Image = None  # type: ignore
    AFFINE = NEAREST = None  # type: ignore

from sim.constants import ORTHO_TILE_SIZE


# Affine coeffs for inverse: iso dest (x,y) -> ortho source (a*x+b*y+c, d*x+e*y+f)
# Maps 64x32 iso diamond pixels back to 32x32 ortho square
ORTHO_TO_ISO_AFFINE = (0.5, 1.0, -16, -0.5, 1.0, 16)


def ortho_to_iso(src: Image.Image) -> Image.Image:
    """
    Transform a 32x32 ortho square into a 64x32 iso diamond.
    Uses PIL affine with inverse mapping: iso dest -> ortho source.
    Transparent outside the diamond.
    """
    if Image is None:
        raise RuntimeError("Pillow required for ortho_to_iso: pip install Pillow")

    src = src.convert("RGBA")
    if src.size != (ORTHO_TILE_SIZE, ORTHO_TILE_SIZE):
        src = src.resize((ORTHO_TILE_SIZE, ORTHO_TILE_SIZE), resample=NEAREST)

    out_w, out_h = 64, 32

    return src.transform(
        (out_w, out_h),
        AFFINE,
        ORTHO_TO_ISO_AFFINE,
        resample=NEAREST,
        fillcolor=(0, 0, 0, 0),
    )


class TileSet:
    """
    Loads ortho PNGs from a directory, transforms to iso at startup,
    and exposes arcade.Texture by name (stem of filename).
    """

    def __init__(self, ortho_dir: Path) -> None:
        self._textures: dict[str, arcade.Texture] = {}
        self._load_all(ortho_dir)

    def _load_all(self, ortho_dir: Path) -> None:
        if Image is None or not ortho_dir.is_dir():
            return
        for path in sorted(ortho_dir.glob("*.png")):
            name = path.stem
            try:
                img = Image.open(path)
                iso_img = ortho_to_iso(img)
                tex = arcade.Texture(iso_img, name=name)
                self._textures[name] = tex
            except Exception as e:
                print(f"[TileSet] Failed to load '{name}': {e}")

    def get(self, name: str) -> arcade.Texture | None:
        return self._textures.get(name)

    def __len__(self) -> int:
        return len(self._textures)
