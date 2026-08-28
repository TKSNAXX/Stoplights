"""
Place building catalog, lot packing, and overlay draw helpers.

Sim stays Arcade-free; packing/measure use only Pillow + stdlib.
Texture/sprite objects are created by the window when Arcade is up.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from sim.constants import ORTHO_TILE_SIZE, TILE_H, TILE_W
from sim.places import (
    BUILDING_KIND_COMMERCIAL,
    BUILDING_KIND_RESIDENTIAL,
    default_building_kind,
)

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore

GAP_CELLS = 1
NATURAL_SQUARE_CELLS = 3
CATALOG_NAME = "catalog.json"
SKIP_PREFIX = "_"

RESIDENTIAL_PREFIXES = ("house",)
COMMERCIAL_PREFIXES = ("cube", "block_")


@dataclass(frozen=True)
class BuildingDef:
    """One art file and its measured footprints."""

    asset_id: str
    file: str
    kind: str
    art_cells_n: int
    art_cells_e: int
    world_cells_n: int
    world_cells_e: int
    anchor_x: float
    anchor_y: float
    src_w: int
    src_h: int


@dataclass(frozen=True)
class PackedBuilding:
    """One instance on a place lot, in authored grid cells."""

    asset_id: str
    origin_x: int
    origin_y: int
    cells_e: int
    cells_n: int
    fit_scale: float

    @property
    def depth(self) -> float:
        return float(self.origin_x + self.origin_y)


def buildings_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "assets" / "Buildings"


def catalog_path() -> Path:
    return buildings_dir() / CATALOG_NAME


def _kind_for_id(asset_id: str) -> str:
    if asset_id.startswith(RESIDENTIAL_PREFIXES):
        return BUILDING_KIND_RESIDENTIAL
    return BUILDING_KIND_COMMERCIAL


def measure_png(path: Path) -> dict:
    """South-anchor and iso L/R extents in pixels / art cells."""
    if Image is None:
        raise RuntimeError("Pillow required to measure building art")
    im = Image.open(path).convert("RGBA")
    w, h = im.size
    alpha = im.split()[-1]
    opaque: list[tuple[int, int]] = []
    for y in range(h):
        for x in range(w):
            if alpha.getpixel((x, y)) > 0:
                opaque.append((x, y))
    if not opaque:
        return {
            "anchor_x": w / 2,
            "anchor_y": h - 1,
            "src_w": w,
            "src_h": h,
            "art_cells_n": 1,
            "art_cells_e": 1,
        }
    y_s = max(y for _, y in opaque)
    xs = [x for x, y in opaque if y == y_s]
    x_s = (min(xs) + max(xs)) / 2.0
    x_l = min(x for x, _ in opaque)
    x_r = max(x for x, _ in opaque)
    left = max(0.0, x_s - x_l)
    right = max(0.0, x_r - x_s)
    art_n = max(1, int(round(left / ORTHO_TILE_SIZE)))
    art_e = max(1, int(round(right / ORTHO_TILE_SIZE)))
    return {
        "anchor_x": x_s,
        "anchor_y": float(y_s),
        "src_w": w,
        "src_h": h,
        "art_cells_n": art_n,
        "art_cells_e": art_e,
    }


def _world_from_art(art_n: int, art_e: int, cal_n: int, cal_e: int) -> tuple[int, int]:
    cal_n = max(1, cal_n)
    cal_e = max(1, cal_e)
    wn = max(1, int(round(art_n * NATURAL_SQUARE_CELLS / cal_n)))
    we = max(1, int(round(art_e * NATURAL_SQUARE_CELLS / cal_e)))
    return wn, we


def scan_catalog(dir_path: Path | None = None) -> list[BuildingDef]:
    """Measure every non-sketch PNG and scale so cube/house is 3x3 world cells."""
    root = dir_path or buildings_dir()
    files = sorted(p for p in root.glob("*.png") if not p.name.startswith(SKIP_PREFIX))
    raw: dict[str, dict] = {}
    for path in files:
        asset_id = path.stem
        raw[asset_id] = {"file": path.name, **measure_png(path)}
    cal = raw.get("cube") or raw.get("house") or next(iter(raw.values()), None)
    if cal is None:
        return []
    cal_n = int(cal["art_cells_n"])
    cal_e = int(cal["art_cells_e"])
    defs: list[BuildingDef] = []
    for asset_id, m in raw.items():
        wn, we = _world_from_art(int(m["art_cells_n"]), int(m["art_cells_e"]), cal_n, cal_e)
        defs.append(
            BuildingDef(
                asset_id=asset_id,
                file=m["file"],
                kind=_kind_for_id(asset_id),
                art_cells_n=int(m["art_cells_n"]),
                art_cells_e=int(m["art_cells_e"]),
                world_cells_n=wn,
                world_cells_e=we,
                anchor_x=float(m["anchor_x"]),
                anchor_y=float(m["anchor_y"]),
                src_w=int(m["src_w"]),
                src_h=int(m["src_h"]),
            )
        )
    return defs


def write_catalog(defs: list[BuildingDef], path: Path | None = None) -> None:
    dest = path or catalog_path()
    dest.write_text(
        json.dumps({"buildings": [asdict(d) for d in defs]}, indent=2) + "\n",
        encoding="utf-8",
    )


def defs_from_json(data: dict) -> list[BuildingDef]:
    out: list[BuildingDef] = []
    for raw in data.get("buildings") or []:
        if not isinstance(raw, dict):
            continue
        out.append(
            BuildingDef(
                asset_id=str(raw["asset_id"]),
                file=str(raw["file"]),
                kind=str(raw.get("kind", BUILDING_KIND_RESIDENTIAL)),
                art_cells_n=int(raw["art_cells_n"]),
                art_cells_e=int(raw["art_cells_e"]),
                world_cells_n=int(raw["world_cells_n"]),
                world_cells_e=int(raw["world_cells_e"]),
                anchor_x=float(raw["anchor_x"]),
                anchor_y=float(raw["anchor_y"]),
                src_w=int(raw["src_w"]),
                src_h=int(raw["src_h"]),
            )
        )
    return out


def load_catalog(dir_path: Path | None = None, persist: bool = True) -> list[BuildingDef]:
    """Load catalog.json if present; otherwise measure and optionally write it."""
    root = dir_path or buildings_dir()
    cached = root / CATALOG_NAME
    if cached.is_file():
        try:
            data = json.loads(cached.read_text(encoding="utf-8"))
            defs = defs_from_json(data)
            if defs:
                return defs
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass
    defs = scan_catalog(root)
    if persist and defs:
        write_catalog(defs, cached)
    return defs


def count_along(size: int, foot: int, gap: int = GAP_CELLS) -> tuple[int, bool]:
    """How many footprints fit on one axis. Leftover becomes yard, not a reserved inner hole."""
    if size < 2:
        return 0, False
    if size < foot:
        return 1, True
    n = (size + gap) // (foot + gap)
    return max(1, n), False


def _spread(count: int, foot: int, size: int, gap: int = GAP_CELLS) -> list[int]:
    """Place `count` feet with at least `gap` between; leftover is outer yard plus extra alleys."""
    if count <= 1:
        return [max(0, (size - foot) // 2)]
    used = count * foot + (count - 1) * gap
    extra = max(0, size - used)
    outer = extra // 2
    alley_extra = extra - 2 * outer
    gaps = count - 1
    base_gap = gap + (alley_extra // gaps if gaps else 0)
    rem = alley_extra % gaps if gaps else 0
    pos = outer
    out: list[int] = []
    for i in range(count):
        out.append(pos)
        pos += foot + base_gap + (1 if i < rem else 0)
    return out


def _slot_hash(place_id: str, kind: str, slot: int) -> int:
    return int(hashlib.md5(f"{place_id}:{kind}:{slot}".encode("utf-8")).hexdigest(), 16)


def _sit_on_lot(ce: int, cn: int, w: int, l: int) -> tuple[int, int, float, int, int]:
    """Building first: natural plate if it fits; leftover cells are yard.

    If it will not sit on the lot, scale by iso span (e+n) so a long mall stays chunky
    instead of being crushed by min(lot/long_axis). Occupancy is that plate clamped
    to the lot; the sprite uses `fit` and may overhang by a cell or two.
    """
    ce, cn = max(1, int(ce)), max(1, int(cn))
    w, l = max(1, int(w)), max(1, int(l))
    if ce <= w and cn <= l:
        occ_e, occ_n = ce, cn
        fit = 1.0
    else:
        fit = min(1.0, (w + l) / (ce + cn))
        occ_e = min(w, max(1, int(round(ce * fit))))
        occ_n = min(l, max(1, int(round(cn * fit))))
    ox = max(0, (w - occ_e) // 2)
    oy = max(0, (l - occ_n) // 2)
    return occ_e, occ_n, fit, ox, oy


def _slot_hash(place_id: str, kind: str, slot: int) -> int:
    return int(hashlib.md5(f"{place_id}:{kind}:{slot}".encode("utf-8")).hexdigest(), 16)


def _pick_def(
    defs: list[BuildingDef],
    kind: str,
    place_id: str,
    slot: int,
    prefer_e: int,
    prefer_n: int,
    max_e: int | None = None,
    max_n: int | None = None,
) -> BuildingDef | None:
    pool = [d for d in defs if d.kind == kind]
    if not pool:
        pool = list(defs)
    if max_e is not None and max_n is not None:
        fitting = [d for d in pool if d.world_cells_e <= max_e and d.world_cells_n <= max_n]
        if fitting:
            pool = fitting
    if not pool:
        return None
    if prefer_e > prefer_n:
        oriented = [d for d in pool if d.world_cells_e >= d.world_cells_n]
    elif prefer_n > prefer_e:
        oriented = [d for d in pool if d.world_cells_n >= d.world_cells_e]
    else:
        oriented = []
    if oriented:
        pool = oriented
    return pool[_slot_hash(place_id, kind, slot) % len(pool)]


def pack_place(
    x0: int,
    y0: int,
    width: int,
    length: int,
    kind: str,
    defs: list[BuildingDef],
    place_id: str,
) -> list[PackedBuilding]:
    """Lay out buildings on a place AABB with yards and gaps. Does not overstuff."""
    w, l = int(width), int(length)
    if min(w, l) < 2:
        return []
    kind = kind if kind in (BUILDING_KIND_RESIDENTIAL, BUILDING_KIND_COMMERCIAL) else default_building_kind(place_id)
    foot = NATURAL_SQUARE_CELLS
    small_lot = w <= 5 and l <= 5
    nx, _ = count_along(w, foot)
    ny, _ = count_along(l, foot)
    if small_lot:
        nx, ny = 1, 1
    if nx < 1 or ny < 1:
        return []
    xs = _spread(nx, foot, w)
    ys = _spread(ny, foot, l)
    packed: list[PackedBuilding] = []
    slot = 0
    single = nx == 1 and ny == 1
    for sx in xs:
        for sy in ys:
            d = _pick_def(defs, kind, place_id, slot, w if single else foot, l if single else foot)
            if d is None:
                continue
            ce, cn = max(1, d.world_cells_e), max(1, d.world_cells_n)
            if single:
                occ_e, occ_n, fit, ox, oy = _sit_on_lot(ce, cn, w, l)
            else:
                occ_e, occ_n, fit, lx, ly = _sit_on_lot(ce, cn, foot, foot)
                ox, oy = sx + lx, sy + ly
            packed.append(
                PackedBuilding(
                    asset_id=d.asset_id,
                    origin_x=x0 + ox,
                    origin_y=y0 + oy,
                    cells_e=occ_e,
                    cells_n=occ_n,
                    fit_scale=fit,
                )
            )
            slot += 1
    return packed


def pack_all_places(
    place_rects: dict[str, dict],
    places_by_id: dict,
    defs: list[BuildingDef],
) -> list[PackedBuilding]:
    """Pack every place. `places_by_id` values need `.building_kind` (or default)."""
    out: list[PackedBuilding] = []
    for name, rect in place_rects.items():
        rec = places_by_id.get(name)
        kind = getattr(rec, "building_kind", None) or default_building_kind(name)
        x0 = int(rect.get("x", 0))
        y0 = int(rect.get("y", 0))
        w = int(rect.get("w", 0))
        h = int(rect.get("h", 0))
        out.extend(pack_place(x0, y0, w, h, kind, defs, name))
    return out


def natural_sprite_scale(defn: BuildingDef) -> float:
    """Arcade sprite.scale so art maps to world_cells at zoom 1 (pixel = screen px)."""
    art_span = (defn.art_cells_e + defn.art_cells_n) * ORTHO_TILE_SIZE
    world_span = (defn.world_cells_e + defn.world_cells_n) * TILE_W
    if art_span <= 0:
        return 1.0
    return world_span / art_span


def south_vertex_screen(sx_cell: float, sy_cell: float, zoom_scale: float) -> tuple[float, float]:
    """Cell centre to south diamond vertex."""
    return (sx_cell, sy_cell - TILE_H * zoom_scale)


def sprite_center_from_anchor(
    south_sx: float,
    south_sy: float,
    defn: BuildingDef,
    sprite_scale: float,
) -> tuple[float, float]:
    """Place texture so the measured south anchor sits on south_sx/sy (Arcade y-up)."""
    dx = (defn.src_w / 2.0 - defn.anchor_x) * sprite_scale
    dy = (defn.anchor_y - defn.src_h / 2.0) * sprite_scale
    return (south_sx + dx, south_sy + dy)


def instances_overlap_ok(items: list[PackedBuilding], gap: int = GAP_CELLS) -> bool:
    """True when AABBs do not overlap and (if more than one) honor gap on both axes or either alley."""
    for i, a in enumerate(items):
        ax1, ay1 = a.origin_x, a.origin_y
        ax2, ay2 = ax1 + a.cells_e, ay1 + a.cells_n
        for b in items[i + 1 :]:
            bx1, by1 = b.origin_x, b.origin_y
            bx2, by2 = bx1 + b.cells_e, by1 + b.cells_n
            sep_x = max(bx1 - ax2, ax1 - bx2)
            sep_y = max(by1 - ay2, ay1 - by2)
            if sep_x < 0 and sep_y < 0:
                return False
            if sep_x < 0 and sep_y < gap:
                return False
            if sep_y < 0 and sep_x < gap:
                return False
            if sep_x >= 0 and sep_y >= 0 and sep_x < gap and sep_y < gap:
                return False
    return True
