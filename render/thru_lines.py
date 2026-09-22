"""Through-paint stripes and nested corner arcs on intersection overlays."""
from __future__ import annotations

import math

from render.lane_paint import ROLE_ONCOMING, ROLE_SISTER, STYLES, dash_on_at
from sim.constants import ORTHO_TILE_SIZE

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore

Seam = tuple[int, str]
Profile = tuple[Seam, ...]

_QUADRANT_EDGES: dict[int, tuple[str, str]] = {
    0: ("W", "N"),
    1: ("S", "W"),
    2: ("E", "S"),
    3: ("N", "E"),
}
_OPP = {"N": "S", "S": "N", "E": "W", "W": "E"}


def _road_grey() -> tuple[int, int, int]:
    from render.corner_gen import ROAD_GREY

    return ROAD_GREY


def _yellow() -> tuple[int, int, int]:
    from render.corner_gen import YELLOW

    return YELLOW


def _white() -> tuple[int, int, int]:
    from render.corner_gen import WHITE

    return WHITE


def _synthetic_normal(n: int) -> Profile:
    mid = max(1, n // 2)
    return ((mid, ROLE_ONCOMING),)


def _seams_from_span(span: tuple[int, int]) -> Profile:
    lo, hi = int(span[0]), int(span[1])
    width = hi - lo + 1
    if width == 2:
        return ((lo + 1, ROLE_ONCOMING),)
    if width == 4:
        return (
            (lo + 1, ROLE_SISTER),
            (lo + 2, ROLE_ONCOMING),
            (lo + 3, ROLE_SISTER),
        )
    return ()


def _live_profiles(intersection_key: str) -> dict[str, Profile] | None:
    from render.intersection_topology import _bounds_from_cells, _raw_mouth_crossings
    from sim import world

    cells = world.get_intersection_cells_by_key(intersection_key)
    if not cells:
        return None
    x_lo, _x_hi, y_lo, _y_hi = _bounds_from_cells(cells)
    crossings = _raw_mouth_crossings(intersection_key, cells)
    faces: dict[str, dict[int, str]] = {}
    for _i, edge, kind, gx, gy in crossings:
        perp = gy if edge in ("W", "E") else gx
        local = perp - (y_lo if edge in ("W", "E") else x_lo)
        slot = faces.setdefault(edge, {})
        prev = slot.get(local)
        if prev is not None and prev != kind:
            slot[local] = ""
        else:
            slot[local] = kind
    return {edge: _seams_from_occupied(occupied) for edge, occupied in faces.items()}


def _seams_from_occupied(occupied: dict[int, str]) -> Profile:
    """Interior seams along a contiguous occupied run of 2+ cells.

    Twin beside opposite (3-cell) is sister then oncoming, not an extra single.
    Gaps or a lone One mouth emit nothing.
    """
    if not occupied or any(k == "" for k in occupied.values()):
        return ()
    items = sorted(occupied.items())
    if len(items) < 2:
        return ()
    idxs = [i for i, _ in items]
    if idxs[-1] - idxs[0] + 1 != len(idxs):
        return ()
    seams: list[Seam] = []
    for (a, ka), (b, kb) in zip(items, items[1:]):
        if b != a + 1:
            return ()
        role = ROLE_SISTER if ka == kb else ROLE_ONCOMING
        seams.append((b, role))
    return tuple(seams)


def resolve_face_profiles(
    n: int,
    *,
    spans: dict[str, tuple[int, int]] | None = None,
    intersection_key: str | None = None,
) -> dict[str, Profile]:
    """Per-edge seam profiles from live mouths, span widths, or Normal defaults."""
    if intersection_key:
        live = _live_profiles(intersection_key)
        if live is not None:
            return live
    if spans:
        return {e: _seams_from_span(sp) for e, sp in spans.items()}
    syn = _synthetic_normal(n)
    return {e: syn for e in ("N", "S", "E", "W")}


def frozen_thru_profile(
    n: int,
    family: str,
    *,
    axis: str = "ns",
    stem: str = "E",
    quadrant: int = 0,
    spans: dict[str, tuple[int, int]] | None = None,
    intersection_key: str | None = None,
    paint: bool = True,
) -> tuple:
    """Cache key fragment: required-face seam tuples, or empty when paint is off."""
    if not paint or family == "cross":
        return ()
    profiles = resolve_face_profiles(n, spans=spans, intersection_key=intersection_key)
    edges = _required_edges(family, axis, stem, quadrant, spans)
    return tuple(sorted((e, profiles.get(e, ())) for e in edges))


def _required_edges(
    family: str,
    axis: str,
    stem: str,
    quadrant: int,
    spans: dict[str, tuple[int, int]] | None,
) -> tuple[str, ...]:
    if family == "corner":
        if spans:
            active = tuple(e for e in ("N", "E", "S", "W") if e in spans)
            if len(active) == 2:
                return active
        return _QUADRANT_EDGES[quadrant % 4]
    if family in ("tee", "straight"):
        if axis == "ew":
            return ("E", "W")
        return ("N", "S")
    return ()


def _oncoming_indices(profile: Profile) -> tuple[int, ...]:
    return tuple(k for k, role in profile if role == ROLE_ONCOMING)


def pair_has_off_centre_oncoming(
    profiles: dict[str, Profile],
    edges: tuple[str, ...],
    n: int,
) -> bool:
    """True when a painted face has an oppose seam that is not the centre index."""
    centre = n // 2
    for edge in edges:
        for k in _oncoming_indices(profiles.get(edge, ())):
            if k != centre:
                return True
    return False


def pair_oncoming_is_centred(
    profiles: dict[str, Profile],
    edges: tuple[str, ...],
    n: int,
) -> bool:
    """Every painted face has its oncoming seam on the centre index, and nowhere else."""
    if not edges or pair_has_off_centre_oncoming(profiles, edges, n):
        return False
    centre = n // 2
    return all(centre in _oncoming_indices(profiles.get(edge, ())) for edge in edges)


def painted_pair_off_centre(intersection_key: str) -> bool:
    """The card locks thru lines when the painted pair's yellow is off centre."""
    from render.intersection_topology import (
        _bounds_from_cells,
        classify_intersection_sides,
        mouth_spans_by_edge,
        mouth_spans_local,
        overlay_type_for_sides,
        straight_axis_for_intersection,
        tee_layout_for_sides,
    )
    from sim import world

    cells = world.get_intersection_cells_by_key(intersection_key)
    if not cells:
        return False
    active, _, _ = classify_intersection_sides(
        intersection_key, cells, require_centre_two=False
    )
    family = overlay_type_for_sides(active)
    if family not in ("tee", "corner", "straight"):
        return False
    x_lo, x_hi, _, _ = _bounds_from_cells(cells)
    n = x_hi - x_lo
    n = max(2, min(12, int(n)))
    if n % 2:
        n = (n // 2) * 2
    spans = mouth_spans_local(cells, mouth_spans_by_edge(intersection_key, cells))
    axis, stem = tee_layout_for_sides(
        active,
        through_fallback=straight_axis_for_intersection(intersection_key, cells, active),
    )
    profiles = resolve_face_profiles(n, spans=spans, intersection_key=intersection_key)
    edges = _required_edges(family, axis, stem, 0, spans)
    return pair_has_off_centre_oncoming(profiles, edges, n)


def _seqs_compatible(a: Profile, b: Profile, n: int) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    rev = tuple((n - k, role) for k, role in reversed(b))
    return a == rev


def _geom_center(quadrant: int, size: int) -> tuple[int, int]:
    q = quadrant % 4
    cx = size if q in (1, 2) else 0
    cy = size if q in (0, 1) else 0
    return cx, cy


def _seam_image_px(k: int, n: int) -> int:
    return (n - k) * ORTHO_TILE_SIZE


def _seam_radius_px(quadrant: int, edge: str, k: int, n: int) -> int:
    size = n * ORTHO_TILE_SIZE
    p = _seam_image_px(k, n)
    cx, cy = _geom_center(quadrant, size)
    if edge in ("W", "E"):
        return abs(p - cx)
    return abs(p - cy)


def _inner_origin(edge: str, pair: frozenset[str], n: int, lx: int, ly: int) -> tuple[int, int]:
    if pair == frozenset({"W", "N"}):
        if edge == "W":
            return n - ly, -1
        return lx, 1
    if pair == frozenset({"S", "W"}):
        if edge == "S":
            return lx, 1
        return ly, 1
    if pair == frozenset({"E", "S"}):
        if edge == "S":
            return n - lx, -1
        return ly, 1
    if pair == frozenset({"N", "E"}):
        if edge == "N":
            return n - lx, -1
        return n - ly, -1
    return 0, 1


def _from_inner(
    edge: str,
    pair: frozenset[str],
    n: int,
    lx: int,
    ly: int,
    seams: Profile,
) -> list[tuple[int, str, int]]:
    k_inner, sign = _inner_origin(edge, pair, n, lx, ly)
    keyed: list[tuple[int, str, int]] = []
    for k, role in seams:
        offset = (k - k_inner) * sign
        if offset <= 0:
            continue
        keyed.append((offset, role, k))
    keyed.sort()
    return keyed


def _is_pavement(px, x: int, y: int, w: int, h: int, grey: tuple[int, int, int]) -> bool:
    if x < 0 or y < 0 or x >= w or y >= h:
        return False
    d = px[x, y]
    return bool(d[3]) and d[:3] == grey


def _stamp(px, x: int, y: int, w: int, h: int, color: tuple[int, int, int], grey) -> None:
    if _is_pavement(px, x, y, w, h, grey):
        px[x, y] = (*color, 255)


def _paint_oncoming_stripe(img, split: int, horizontal: bool) -> None:
    """Two 2px yellows, same inclusive packing as `_stroke_through_yellows`."""
    grey = _road_grey()
    yellow = _yellow()
    px = img.load()
    w, h = img.size
    # PIL rectangle (split-4, split-3) is inclusive — two pixels, not one.
    offsets = (split - 4, split - 3, split + 3, split + 4)
    if horizontal:
        for y in offsets:
            for x in range(w):
                _stamp(px, x, y, w, h, yellow, grey)
    else:
        for x in offsets:
            for y in range(h):
                _stamp(px, x, y, w, h, yellow, grey)


def _paint_sister_stripe(img, split: int, horizontal: bool) -> None:
    """2px dash, same weight as the corner sister arc and the yellow pair."""
    grey = _road_grey()
    white = _white()
    style = STYLES[ROLE_SISTER]
    px = img.load()
    w, h = img.size
    if horizontal:
        for y in (split, split + 1):
            for x in range(w):
                if dash_on_at(style, x):
                    _stamp(px, x, y, w, h, white, grey)
    else:
        for x in (split, split + 1):
            for y in range(h):
                if dash_on_at(style, y):
                    _stamp(px, x, y, w, h, white, grey)


def _blend_overlay(img, overlay) -> None:
    grey = _road_grey()
    src = overlay.load()
    dst = img.load()
    w, h = img.size
    for y in range(h):
        for x in range(w):
            p = src[x, y]
            if p[3] == 0:
                continue
            if _is_pavement(dst, x, y, w, h, grey):
                dst[x, y] = p


def _paint_oncoming_arc(overlay, cx: int, cy: int, r: int, start: int, end: int) -> None:
    """2px pieslice rings, same weight as `_CORNER_BANDS_BASE` yellows.

    Outer ring first, then inner, so the inner punch does not wipe the pair.
    """
    if ImageDraw is None:
        return
    draw = ImageDraw.Draw(overlay)
    yellow = _yellow()
    # 2px rings (r_out - r_in == 2), same as `_CORNER_BANDS_BASE` yellows.
    for r_out, r_in in ((r + 5, r + 3), (r - 2, r - 4)):
        if r_out <= 0:
            continue
        draw.pieslice(
            (cx - r_out, cy - r_out, cx + r_out, cy + r_out),
            start,
            end,
            fill=(*yellow, 255),
        )
        if r_in > 0:
            draw.pieslice(
                (cx - r_in, cy - r_in, cx + r_in, cy + r_in),
                start,
                end,
                fill=(0, 0, 0, 0),
            )


def _paint_sister_arc(overlay, cx: int, cy: int, r: int, start: int, end: int) -> None:
    if ImageDraw is None or r <= 0:
        return
    draw = ImageDraw.Draw(overlay)
    white = _white()
    style = STYLES[ROLE_SISTER]
    span = end - start
    if span < 0:
        span += 360
    on_deg = max(0.5, (style.dash_on / r) * 180.0 / math.pi)
    off_deg = max(0.5, (style.dash_off / r) * 180.0 / math.pi)
    theta = float(start)
    limit = start + span
    while theta < limit:
        t1 = min(theta + on_deg, limit)
        draw.arc(
            (cx - r, cy - r, cx + r, cy + r),
            theta,
            t1,
            fill=(*white, 255),
            width=2,
        )
        theta = t1 + off_deg


def _stroke_axis(
    img,
    n: int,
    profiles: dict[str, Profile],
    edges: tuple[str, str],
    horizontal: bool,
) -> None:
    a, b = edges
    pa, pb = profiles.get(a, ()), profiles.get(b, ())
    if not _seqs_compatible(pa, pb, n):
        return
    for k, role in pa:
        split = _seam_image_px(k, n)
        if role == ROLE_ONCOMING:
            _paint_oncoming_stripe(img, split, horizontal)
        elif role == ROLE_SISTER:
            _paint_sister_stripe(img, split, horizontal)


def _stroke_corner(
    img,
    n: int,
    profiles: dict[str, Profile],
    quadrant: int,
    spans: dict[str, tuple[int, int]] | None,
) -> None:
    from render.corner_gen import _arc_center
    from render.intersection_topology import leftover_xy_for_pair

    e1, e2 = _QUADRANT_EDGES[quadrant % 4]
    p1, p2 = profiles.get(e1, ()), profiles.get(e2, ())
    if not p1 or not p2:
        return
    local = spans or {}
    leftover = leftover_xy_for_pair(n, local, e1, e2) if local else None
    paired: list[tuple[str, int, int]] = []
    if leftover is not None:
        lx, ly = leftover
        pair = frozenset({e1, e2})
        s1 = _from_inner(e1, pair, n, lx, ly, p1)
        s2 = _from_inner(e2, pair, n, lx, ly, p2)
        if not s1 or not s2 or len(s1) != len(s2):
            return
        if any(a[0] != b[0] or a[1] != b[1] for a, b in zip(s1, s2)):
            return
        for (_off, role, k1), (_o2, _r2, k2) in zip(s1, s2):
            r1 = _seam_radius_px(quadrant, e1, k1, n)
            r2 = _seam_radius_px(quadrant, e2, k2, n)
            if abs(r1 - r2) > 1:
                return
            paired.append((role, (r1 + r2) // 2, k1))
    else:
        if not _seqs_compatible(p1, p2, n):
            return
        for k, role in p1:
            r1 = _seam_radius_px(quadrant, e1, k, n)
            r2 = _seam_radius_px(quadrant, e2, k, n)
            if abs(r1 - r2) > 1:
                return
            paired.append((role, (r1 + r2) // 2, k))
    if not paired:
        return
    size = n * ORTHO_TILE_SIZE
    cx, cy, start_a, end_a = _arc_center(quadrant, size)
    if Image is None:
        return
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    # Oncoming pieslice punches clear the interior; sisters must be stroked after.
    for role, r, _k in paired:
        if role == ROLE_ONCOMING:
            _paint_oncoming_arc(overlay, cx, cy, r, start_a, end_a)
    for role, r, _k in paired:
        if role == ROLE_SISTER:
            _paint_sister_arc(overlay, cx, cy, r, start_a, end_a)
    _blend_overlay(img, overlay)


def stroke_thru_lines(
    img,
    cells: int,
    family: str,
    *,
    axis: str = "ns",
    stem: str = "E",
    quadrant: int = 0,
    spans: dict[str, tuple[int, int]] | None = None,
    intersection_key: str | None = None,
    paint: bool = True,
) -> None:
    """Stroke sister/oncoming seams on remaining pavement.

    No-ops for a cross, when paint is off, or when the pair's oncoming seam
    is not the centre index.
    """
    if not paint or Image is None or img is None:
        return
    fam = family if family in ("tee", "corner", "straight") else family
    if fam == "cross":
        return
    n = max(2, min(12, int(cells)))
    if n % 2:
        n = (n // 2) * 2
    if fam == "corner" and not spans:
        lo, hi = n // 2 - 1, n // 2
        e1, e2 = _QUADRANT_EDGES[quadrant % 4]
        spans = {e1: (lo, hi), e2: (lo, hi)}
    profiles = resolve_face_profiles(n, spans=spans, intersection_key=intersection_key)
    if fam == "corner":
        from render.intersection_topology import corner_quadrant_for_sides

        q = quadrant
        if spans:
            q = corner_quadrant_for_sides(frozenset(spans))
        edges = _required_edges(fam, axis, stem, q, spans)
        if not pair_oncoming_is_centred(profiles, edges, n):
            return
        _stroke_corner(img, n, profiles, q, spans)
        return
    if fam in ("tee", "straight"):
        ax = axis if axis in ("ns", "ew") else "ns"
        edges = ("E", "W") if ax == "ew" else ("N", "S")
        if not pair_oncoming_is_centred(profiles, edges, n):
            return
        horizontal = ax == "ns"
        _stroke_axis(img, n, profiles, edges, horizontal)
