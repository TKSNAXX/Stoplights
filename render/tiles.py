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

from render.corner_gen import make_corner, make_cross, make_straight_through, make_tee


# Affine coeffs for inverse: iso dest (x,y) -> ortho source (a*x+b*y+c, d*x+e*y+f)
# Maps 64x32 iso diamond pixels back to 32x32 ortho square
ORTHO_TO_ISO_AFFINE = (0.5, 1.0, -16, -0.5, 1.0, 16)


def ortho_to_iso_large(src: Image.Image, cells: int = 4) -> Image.Image:
    """
    Transform ortho square (cells*32) into iso diamond (cells*64 x cells*32).
    For 128x128 ortho -> 256x128 iso. Keeps scale relative to 32x32 tiles.
    """
    if Image is None:
        raise RuntimeError("Pillow required for ortho_to_iso_large: pip install Pillow")
    half = (ORTHO_TILE_SIZE * cells) // 2
    src = src.convert("RGBA")
    expected = (ORTHO_TILE_SIZE * cells, ORTHO_TILE_SIZE * cells)
    if src.size != expected:
        src = src.resize(expected, resample=NEAREST)
    out_w = ORTHO_TILE_SIZE * 2 * cells
    out_h = ORTHO_TILE_SIZE * cells
    affine = (0.5, 1.0, -half, -0.5, 1.0, half)
    return src.transform(
        (out_w, out_h),
        AFFINE,
        affine,
        resample=NEAREST,
        fillcolor=(0, 0, 0, 0),
    )


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
                size = img.size
                if size == (128, 128):
                    iso_img = ortho_to_iso_large(img, cells=4)
                else:
                    iso_img = ortho_to_iso(img)
                tex = arcade.Texture(iso_img, name=name)
                self._textures[name] = tex
            except Exception as e:
                print(f"[TileSet] Failed to load '{name}': {e}")

    def get(self, name: str) -> arcade.Texture | None:
        return self._textures.get(name)

    def __len__(self) -> int:
        return len(self._textures)


_corner_texture_cache: dict[tuple[int, int], arcade.Texture] = {}
_straight_texture_cache: dict[tuple[int, str, int], arcade.Texture] = {}
_tee_texture_cache: dict[tuple[int, str, str, int], arcade.Texture] = {}
_cross_texture_cache: dict[tuple[int, int], arcade.Texture] = {}
_STRAIGHT_TEX_REV = 11
_TEE_TEX_REV = 6
_CROSS_TEX_REV = 4


def generate_corner_texture(cells: int, quadrant: int = 0) -> arcade.Texture | None:
    """
    Generate corner texture for given cell count and quadrant 0..3. Cached by (cells, quadrant).
    Returns None if Pillow unavailable.
    """
    if Image is None:
        return None
    cells = max(2, min(12, cells))
    if cells % 2 != 0:
        cells = (cells // 2) * 2
    q = quadrant % 4
    key = (cells, q)
    if key in _corner_texture_cache:
        return _corner_texture_cache[key]
    try:
        ortho_img = make_corner(cells, quadrant=q)
        iso_img = ortho_to_iso_large(ortho_img, cells=cells)
        tex = arcade.Texture(iso_img, name=f"corner_{cells}_q{q}")
        _corner_texture_cache[key] = tex
        return tex
    except Exception:
        return None


def generate_straight_texture(cells: int, axis: str = "ns") -> arcade.Texture | None:
    """Straight-through overlay: dual centre lanes on grey. Cached by (cells, axis)."""
    if Image is None:
        return None
    cells = max(2, min(12, cells))
    if cells % 2 != 0:
        cells = (cells // 2) * 2
    ax = axis if axis in ("ns", "ew") else "ns"
    key = (cells, ax, _STRAIGHT_TEX_REV)
    if key in _straight_texture_cache:
        return _straight_texture_cache[key]
    try:
        ortho_img = make_straight_through(cells, axis=ax)
        iso_img = ortho_to_iso_large(ortho_img, cells=cells)
        tex = arcade.Texture(iso_img, name=f"straight_{cells}_{ax}_r{_STRAIGHT_TEX_REV}")
        _straight_texture_cache[key] = tex
        return tex
    except Exception:
        return None


def generate_tee_texture(cells: int, axis: str = "ns", stem: str = "E") -> arcade.Texture | None:
    """Tee overlay: through dual-lane band plus stem-side fillets. Cached by (cells, axis, stem)."""
    if Image is None:
        return None
    cells = max(2, min(12, cells))
    if cells % 2 != 0:
        cells = (cells // 2) * 2
    ax = axis if axis in ("ns", "ew") else "ns"
    st = stem if stem in ("N", "S", "E", "W") else "E"
    key = (cells, ax, st, _TEE_TEX_REV)
    if key in _tee_texture_cache:
        return _tee_texture_cache[key]
    try:
        ortho_img = make_tee(cells, axis=ax, stem=st)
        iso_img = ortho_to_iso_large(ortho_img, cells=cells)
        tex = arcade.Texture(iso_img, name=f"tee_{cells}_{ax}_{st}_r{_TEE_TEX_REV}")
        _tee_texture_cache[key] = tex
        return tex
    except Exception:
        return None


def generate_cross_texture(cells: int) -> arcade.Texture | None:
    """Four-way filleted overlay. Cached by cell count."""
    if Image is None:
        return None
    cells = max(2, min(12, cells))
    if cells % 2 != 0:
        cells = (cells // 2) * 2
    key = (cells, _CROSS_TEX_REV)
    if key in _cross_texture_cache:
        return _cross_texture_cache[key]
    try:
        ortho_img = make_cross(cells)
        iso_img = ortho_to_iso_large(ortho_img, cells=cells)
        tex = arcade.Texture(iso_img, name=f"cross_{cells}_r{_CROSS_TEX_REV}")
        _cross_texture_cache[key] = tex
        return tex
    except Exception:
        return None
