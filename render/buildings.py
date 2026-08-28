"""
Place building catalog, lot packing, and overlay draw helpers.

Sim stays Arcade-free; packing/measure use only Pillow + stdlib.
Texture/sprite objects are created by the window when Arcade is up.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path

from sim.constants import ORTHO_TILE_SIZE, TILE_H, TILE_W
from sim.places import (
    BUILDING_KIND_COMMERCIAL,
    BUILDING_KIND_NONE,
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


def _layout_hash(place_id: str, seed: int, *parts: object) -> int:
    key = f"{place_id}:{int(seed)}:" + ":".join(str(p) for p in parts)
    return int(hashlib.md5(key.encode("utf-8")).hexdigest(), 16)


def _is_house_art(asset_id: str) -> bool:
    return str(asset_id).startswith("house")


def _fill_t(place_id: str, slot: int, seed: int) -> float:
    return 0.6 + 0.4 * ((_layout_hash(place_id, seed, "fill", slot) % 1000) / 999.0)


def _offset_in_plate(
    occ_e: int, occ_n: int, pw: int, ph: int, place_id: str, slot: int, seed: int
) -> tuple[int, int]:
    ex = max(0, pw - occ_e)
    ey = max(0, ph - occ_n)
    h = _layout_hash(place_id, seed, "off", slot) % 9
    fx = (0.5, 0.0, 1.0, 0.5, 0.5, 0.0, 1.0, 0.0, 1.0)[h]
    fy = (0.5, 0.5, 0.5, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0)[h]
    ox = ex // 2 if fx == 0.5 else int(round(ex * fx))
    oy = ey // 2 if fy == 0.5 else int(round(ey * fy))
    return max(0, min(ex, ox)), max(0, min(ey, oy))


def _sit_shuffled(
    ce: int,
    cn: int,
    pw: int,
    ph: int,
    asset_id: str,
    place_id: str,
    slot: int,
    seed: int,
) -> tuple[int, int, float, int, int]:
    """Fill 60–100% of allowed occupancy; houses never exceed natural scale. Offset by hash."""
    ce, cn = max(1, int(ce)), max(1, int(cn))
    pw, ph = max(1, int(pw)), max(1, int(ph))
    t = _fill_t(place_id, slot, seed)
    if _is_house_art(asset_id):
        if ce <= pw and cn <= ph:
            hi_e, hi_n = ce, cn
        else:
            fit_hi = min(1.0, (pw + ph) / (ce + cn))
            hi_e = min(pw, max(1, int(round(ce * fit_hi))))
            hi_n = min(ph, max(1, int(round(cn * fit_hi))))
        cap = 1.0
    else:
        fit_hi = min(pw / ce, ph / cn)
        hi_e = min(pw, max(1, int(round(ce * fit_hi))))
        hi_n = min(ph, max(1, int(round(cn * fit_hi))))
        cap = None
    lo_e = max(1, int(round(min(ce, pw, hi_e) * 0.6)))
    lo_n = max(1, int(round(min(cn, ph, hi_n) * 0.6)))
    lo_e, lo_n = min(lo_e, hi_e), min(lo_n, hi_n)
    occ_e = max(1, int(round(lo_e + (hi_e - lo_e) * t)))
    occ_n = max(1, int(round(lo_n + (hi_n - lo_n) * t)))
    occ_e, occ_n = min(occ_e, hi_e, pw), min(occ_n, hi_n, ph)
    fit = min(occ_e / ce, occ_n / cn)
    if cap is not None:
        fit = min(fit, cap)
    occ_e = min(pw, max(1, int(round(ce * fit))))
    occ_n = min(ph, max(1, int(round(cn * fit))))
    ox, oy = _offset_in_plate(occ_e, occ_n, pw, ph, place_id, slot, seed)
    return occ_e, occ_n, fit, ox, oy


def _merge_slot_plates(
    xs: list[int],
    ys: list[int],
    foot: int,
    place_id: str,
    seed: int,
) -> list[tuple[int, int, int, int, int]]:
    """Union 1, 2-adj, or 2×2 slot rects (alleys included). Returns (px, py, pw, ph, slot)."""
    nx, ny = len(xs), len(ys)
    cells = [(ix, iy) for iy in range(ny) for ix in range(nx)]
    cells.sort(key=lambda c: _layout_hash(place_id, seed, "ord", c[0], c[1]))
    claimed: set[tuple[int, int]] = set()
    plates: list[tuple[int, int, int, int, int]] = []
    slot = 0
    for ix, iy in cells:
        if (ix, iy) in claimed:
            continue
        roll = _layout_hash(place_id, seed, "mrg", ix, iy) % 4
        members = [(ix, iy)]
        if roll == 3 and ix + 1 < nx and iy + 1 < ny:
            quad = ((ix, iy), (ix + 1, iy), (ix, iy + 1), (ix + 1, iy + 1))
            if all(p not in claimed for p in quad):
                members = list(quad)
        elif roll == 1 and ix + 1 < nx and (ix + 1, iy) not in claimed:
            members = [(ix, iy), (ix + 1, iy)]
        elif roll == 2 and iy + 1 < ny and (ix, iy + 1) not in claimed:
            members = [(ix, iy), (ix, iy + 1)]
        for p in members:
            claimed.add(p)
        ixs = [p[0] for p in members]
        iys = [p[1] for p in members]
        px, py = xs[min(ixs)], ys[min(iys)]
        pw = xs[max(ixs)] + foot - px
        ph = ys[max(iys)] + foot - py
        plates.append((px, py, pw, ph, slot))
        slot += 1
    return plates


def _slot_hash(place_id: str, kind: str, slot: int, seed: int = 0) -> int:
    key = f"{place_id}:{kind}:{slot}" if not seed else f"{place_id}:{kind}:{slot}:{int(seed)}"
    return int(hashlib.md5(key.encode("utf-8")).hexdigest(), 16)


def _pick_def(
    defs: list[BuildingDef],
    kind: str,
    place_id: str,
    slot: int,
    prefer_e: int,
    prefer_n: int,
    max_e: int | None = None,
    max_n: int | None = None,
    seed: int = 0,
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
    return pool[_slot_hash(place_id, kind, slot, seed) % len(pool)]


def _append_instance(
    packed: list[PackedBuilding],
    d: BuildingDef,
    x0: int,
    y0: int,
    px: int,
    py: int,
    occ_e: int,
    occ_n: int,
    fit: float,
    lx: int,
    ly: int,
) -> None:
    packed.append(
        PackedBuilding(
            asset_id=d.asset_id,
            origin_x=x0 + px + lx,
            origin_y=y0 + py + ly,
            cells_e=occ_e,
            cells_n=occ_n,
            fit_scale=fit,
        )
    )


def pack_place(
    x0: int,
    y0: int,
    width: int,
    length: int,
    kind: str,
    defs: list[BuildingDef],
    place_id: str,
    seed: int = 0,
) -> list[PackedBuilding]:
    """Lay out buildings on a place AABB with yards and gaps. Does not overstuff."""
    w, l = int(width), int(length)
    if min(w, l) < 2:
        return []
    if kind == BUILDING_KIND_NONE:
        return []
    if kind not in (BUILDING_KIND_RESIDENTIAL, BUILDING_KIND_COMMERCIAL):
        kind = default_building_kind(place_id)
    seed = int(seed or 0)
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
    single = nx == 1 and ny == 1
    if seed == 0:
        slot = 0
        for sx in xs:
            for sy in ys:
                d = _pick_def(
                    defs, kind, place_id, slot,
                    w if single else foot, l if single else foot,
                    seed=seed,
                )
                if d is None:
                    continue
                ce, cn = max(1, d.world_cells_e), max(1, d.world_cells_n)
                if single:
                    occ_e, occ_n, fit, lx, ly = _sit_on_lot(ce, cn, w, l)
                    _append_instance(packed, d, x0, y0, 0, 0, occ_e, occ_n, fit, lx, ly)
                else:
                    occ_e, occ_n, fit, lx, ly = _sit_on_lot(ce, cn, foot, foot)
                    _append_instance(packed, d, x0, y0, sx, sy, occ_e, occ_n, fit, lx, ly)
                slot += 1
        return packed

    if single:
        plates = [(0, 0, w, l, 0)]
    else:
        plates = _merge_slot_plates(xs, ys, foot, place_id, seed)
    for px, py, pw, ph, slot in plates:
        d = _pick_def(defs, kind, place_id, slot, pw, ph, seed=seed)
        if d is None:
            continue
        ce, cn = max(1, d.world_cells_e), max(1, d.world_cells_n)
        occ_e, occ_n, fit, lx, ly = _sit_shuffled(ce, cn, pw, ph, d.asset_id, place_id, slot, seed)
        _append_instance(packed, d, x0, y0, px, py, occ_e, occ_n, fit, lx, ly)
    return packed


def _next_distinct_seed(current: int) -> int:
    cur = max(0, int(current or 0))
    for _ in range(16):
        n = secrets.randbelow(2**31 - 1) + 1
        if n != cur:
            return n
    return 1 if cur >= 2**31 - 1 else cur + 1


def _layout_key(items: list[PackedBuilding]) -> tuple:
    return tuple((p.asset_id, p.origin_x, p.origin_y, p.cells_e, p.cells_n, round(p.fit_scale, 4)) for p in items)


def shuffle_building_seed(
    defs: list[BuildingDef],
    kind: str,
    place_id: str,
    width: int,
    length: int,
    current_seed: int = 0,
) -> int:
    """Pick a new nonzero seed; retry a few times if the layout does not change."""
    seed = max(0, int(current_seed or 0))
    before = _layout_key(pack_place(0, 0, width, length, kind, defs, place_id, seed=seed))
    for _ in range(12):
        seed = _next_distinct_seed(seed)
        after = _layout_key(pack_place(0, 0, width, length, kind, defs, place_id, seed=seed))
        if after != before:
            return seed
    return seed


def pack_all_places(
    place_rects: dict[str, dict],
    places_by_id: dict,
    defs: list[BuildingDef],
) -> list[PackedBuilding]:
    """Pack every place. `places_by_id` values need `.building_kind` (or default)."""
    out: list[PackedBuilding] = []
    for name, rect in place_rects.items():
        rec = places_by_id.get(name)
        kind = getattr(rec, "building_kind", None) if rec is not None else None
        if kind not in (BUILDING_KIND_NONE, BUILDING_KIND_RESIDENTIAL, BUILDING_KIND_COMMERCIAL):
            kind = default_building_kind(name)
        seed = int(getattr(rec, "building_seed", 0) or 0) if rec is not None else 0
        x0 = int(rect.get("x", 0))
        y0 = int(rect.get("y", 0))
        w = int(rect.get("w", 0))
        h = int(rect.get("h", 0))
        out.extend(pack_place(x0, y0, w, h, kind, defs, name, seed=seed))
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
