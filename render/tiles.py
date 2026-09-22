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

from render.corner_gen import (
    make_corner,
    make_cross,
    make_double,
    make_double_corner,
    make_double_tee,
    make_mixed,
    make_straight_through,
    make_tee,
)
from render.lane_paint import STYLE_REV, raster_lane_ortho


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


_corner_texture_cache: dict[tuple, arcade.Texture] = {}
_straight_texture_cache: dict[tuple, arcade.Texture] = {}
_tee_texture_cache: dict[tuple, arcade.Texture] = {}
_cross_texture_cache: dict[tuple[int, int], arcade.Texture] = {}
_double_texture_cache: dict[tuple, arcade.Texture] = {}
_double_tee_texture_cache: dict[tuple, arcade.Texture] = {}
_double_corner_texture_cache: dict[tuple, arcade.Texture] = {}
_mixed_texture_cache: dict[tuple, arcade.Texture] = {}
_lane_paint_cache: dict[tuple, arcade.Texture] = {}
_STRAIGHT_TEX_REV = 13
_TEE_TEX_REV = 9
_CROSS_TEX_REV = 5
_DOUBLE_TEX_REV = 5
_DOUBLE_TEE_TEX_REV = 3
_DOUBLE_CORNER_TEX_REV = 3
_MIXED_TEX_REV = 24
_CORNER_TEX_REV = 3


def generate_corner_texture(
    cells: int,
    quadrant: int = 0,
    paint_thru_lines: bool = True,
) -> arcade.Texture | None:
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
    paint = bool(paint_thru_lines)
    key = (cells, q, paint, _CORNER_TEX_REV)
    if key in _corner_texture_cache:
        return _corner_texture_cache[key]
    try:
        ortho_img = make_corner(cells, quadrant=q, paint_thru_lines=paint)
        iso_img = ortho_to_iso_large(ortho_img, cells=cells)
        tex = arcade.Texture(iso_img, name=f"corner_{cells}_q{q}_p{int(paint)}_r{_CORNER_TEX_REV}")
        _corner_texture_cache[key] = tex
        return tex
    except Exception:
        return None


def generate_straight_texture(
    cells: int,
    axis: str = "ns",
    paint_thru_lines: bool = True,
) -> arcade.Texture | None:
    """Straight-through overlay: dual centre lanes on grey. Cached by (cells, axis)."""
    if Image is None:
        return None
    cells = max(2, min(12, cells))
    if cells % 2 != 0:
        cells = (cells // 2) * 2
    ax = axis if axis in ("ns", "ew") else "ns"
    paint = bool(paint_thru_lines)
    key = (cells, ax, paint, _STRAIGHT_TEX_REV)
    if key in _straight_texture_cache:
        return _straight_texture_cache[key]
    try:
        ortho_img = make_straight_through(cells, axis=ax, paint_thru_lines=paint)
        iso_img = ortho_to_iso_large(ortho_img, cells=cells)
        tex = arcade.Texture(iso_img, name=f"straight_{cells}_{ax}_p{int(paint)}_r{_STRAIGHT_TEX_REV}")
        _straight_texture_cache[key] = tex
        return tex
    except Exception:
        return None


def generate_tee_texture(
    cells: int,
    axis: str = "ns",
    stem: str = "E",
    paint_thru_lines: bool = True,
) -> arcade.Texture | None:
    """Tee overlay: through dual-lane band plus stem-side fillets. Cached by (cells, axis, stem)."""
    if Image is None:
        return None
    cells = max(2, min(12, cells))
    if cells % 2 != 0:
        cells = (cells // 2) * 2
    ax = axis if axis in ("ns", "ew") else "ns"
    st = stem if stem in ("N", "S", "E", "W") else "E"
    paint = bool(paint_thru_lines)
    key = (cells, ax, st, paint, _TEE_TEX_REV)
    if key in _tee_texture_cache:
        return _tee_texture_cache[key]
    try:
        ortho_img = make_tee(cells, axis=ax, stem=st, paint_thru_lines=paint)
        iso_img = ortho_to_iso_large(ortho_img, cells=cells)
        tex = arcade.Texture(iso_img, name=f"tee_{cells}_{ax}_{st}_p{int(paint)}_r{_TEE_TEX_REV}")
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


def generate_double_texture(
    cells: int,
    travel_cells: int = 4,
    travel_x: int | None = None,
    travel_y: int | None = None,
) -> arcade.Texture | None:
    """Larger Cross with shoulder-sized fillets. Cached by cell count and travel."""
    if Image is None:
        return None
    cells = max(2, min(12, cells))
    if cells % 2 != 0:
        cells = (cells // 2) * 2
    tx = travel_x if travel_x is not None else travel_cells
    ty = travel_y if travel_y is not None else travel_cells
    key = (cells, travel_cells, tx, ty, _DOUBLE_TEX_REV)
    if key in _double_texture_cache:
        return _double_texture_cache[key]
    try:
        ortho_img = make_double(cells, travel_cells=travel_cells, travel_x=tx, travel_y=ty)
        iso_img = ortho_to_iso_large(ortho_img, cells=cells)
        tex = arcade.Texture(iso_img, name=f"double_{cells}_{tx}_{ty}_r{_DOUBLE_TEX_REV}")
        _double_texture_cache[key] = tex
        return tex
    except Exception:
        return None


def generate_double_tee_texture(
    cells: int,
    axis: str = "ns",
    stem: str = "E",
    through_travel: int = 4,
    stem_travel: int = 4,
) -> arcade.Texture | None:
    """Centred even tee: through + stem bands, stem-corner fillets, open face punched."""
    if Image is None:
        return None
    cells = max(2, min(12, cells))
    if cells % 2 != 0:
        cells = (cells // 2) * 2
    ax = axis if axis in ("ns", "ew") else "ns"
    st = stem if stem in ("N", "S", "E", "W") else "E"
    key = (cells, ax, st, through_travel, stem_travel, _DOUBLE_TEE_TEX_REV)
    if key in _double_tee_texture_cache:
        return _double_tee_texture_cache[key]
    try:
        ortho_img = make_double_tee(
            cells,
            axis=ax,
            stem=st,
            through_travel=through_travel,
            stem_travel=stem_travel,
        )
        iso_img = ortho_to_iso_large(ortho_img, cells=cells)
        tex = arcade.Texture(
            iso_img,
            name=f"double_tee_{cells}_{ax}_{st}_{through_travel}_{stem_travel}_r{_DOUBLE_TEE_TEX_REV}",
        )
        _double_tee_texture_cache[key] = tex
        return tex
    except Exception:
        return None


def generate_double_corner_texture(
    cells: int,
    quadrant: int = 0,
    travel_x: int = 4,
    travel_y: int = 4,
) -> arcade.Texture | None:
    """Centred even corner L plus one inner fillet."""
    if Image is None:
        return None
    cells = max(2, min(12, cells))
    if cells % 2 != 0:
        cells = (cells // 2) * 2
    q = quadrant % 4
    key = (cells, q, travel_x, travel_y, _DOUBLE_CORNER_TEX_REV)
    if key in _double_corner_texture_cache:
        return _double_corner_texture_cache[key]
    try:
        ortho_img = make_double_corner(cells, quadrant=q, travel_x=travel_x, travel_y=travel_y)
        iso_img = ortho_to_iso_large(ortho_img, cells=cells)
        tex = arcade.Texture(
            iso_img,
            name=f"double_corner_{cells}_q{q}_{travel_x}_{travel_y}_r{_DOUBLE_CORNER_TEX_REV}",
        )
        _double_corner_texture_cache[key] = tex
        return tex
    except Exception:
        return None


def generate_mixed_texture(
    cells: int,
    leftovers: tuple[tuple[int, int, int], ...],
    family: str,
    axis: str = "ns",
    stem: str = "E",
    yaw: int = 0,
    spans: dict[str, tuple[int, int]] | None = None,
    paint_thru_lines: bool = True,
    intersection_key: str | None = None,
) -> arcade.Texture | None:
    """Mouth-based twin stamp. Cached by leftovers, spans, family, yaw, thru paint."""
    if Image is None:
        return None
    from render.corner_gen import frozen_curb_key
    from render.thru_lines import frozen_thru_profile

    cells = max(2, min(12, cells))
    if cells % 2 != 0:
        cells = (cells // 2) * 2
    ax = axis if axis in ("ns", "ew") else "ns"
    st = stem if stem in ("N", "S", "E", "W") else "E"
    fam = family if family in ("cross", "tee", "corner", "straight") else "cross"
    yq = int(yaw) % 4
    paint = bool(paint_thru_lines)
    frozen_spans = tuple(sorted((e, lo, hi) for e, (lo, hi) in (spans or {}).items()))
    thru_key = frozen_thru_profile(
        cells,
        fam,
        axis=ax,
        stem=st,
        spans=spans,
        intersection_key=intersection_key,
        paint=paint,
    )
    curb_key = frozen_curb_key(intersection_key, fam, ax, st, spans)
    key = (
        cells,
        leftovers,
        fam,
        ax,
        st,
        yq,
        frozen_spans,
        paint,
        thru_key,
        curb_key,
        _MIXED_TEX_REV,
    )
    if key in _mixed_texture_cache:
        return _mixed_texture_cache[key]
    try:
        ortho_img = make_mixed(
            cells,
            leftovers,
            family=fam,
            axis=ax,
            stem=st,
            spans=spans or {},
            paint_thru_lines=paint,
            intersection_key=intersection_key,
        )
        if yq:
            ortho_img = ortho_img.rotate(-90 * yq, expand=False)
        iso_img = ortho_to_iso_large(ortho_img, cells=cells)
        tex = arcade.Texture(iso_img, name=f"mixed_{cells}_{fam}_{yq}_p{int(paint)}_r{_MIXED_TEX_REV}")
        _mixed_texture_cache[key] = tex
        return tex
    except Exception:
        return None


def generate_lane_paint_texture(
    display_dir: str,
    role_a: str,
    role_b: str,
    phase: int = 0,
) -> arcade.Texture | None:
    """Iso lane tile for two lateral roles. Cached by display dir, roles, phase, style rev."""
    if Image is None:
        return None
    d = display_dir if display_dir in ("N", "S", "E", "W") else "N"
    key = (d, role_a, role_b, int(phase), STYLE_REV)
    cached = _lane_paint_cache.get(key)
    if cached is not None:
        return cached
    try:
        ortho_img = raster_lane_ortho(d, role_a, role_b, int(phase))
        if ortho_img is None:
            return None
        iso_img = ortho_to_iso(ortho_img)
        tex = arcade.Texture(iso_img, name=f"lane_{d}_{role_a}_{role_b}_{phase}_r{STYLE_REV}")
        _lane_paint_cache[key] = tex
        return tex
    except Exception:
        return None
