"""
Headless tests for schema-4 scenario and derived topology.
Run: python -m tests.test_universal_map
"""
from __future__ import annotations

from sim import places, world
from sim.cop import _home_at_lane_start
from sim.game import GameState
from sim.map_data import (
    aabb_from_corners,
    aabb_from_edge_and_hover,
    bounds_from_center,
    intersection_size_for_hover,
    place_center_from_aabb,
    place_rects_from_places,
    snap_cardinal_end,
)
from sim.constants import TILE_H, TILE_W
from render.selection import (
    edge_faces_sw,
    ensure_ccw,
    iso_aabb_silhouette,
    occupancy_aabb,
    offset_polygon,
    rim_quads,
)
from sim.paths import is_straight_path
from sim.scenario import (
    SCHEMA_VERSION,
    clamp_color_hue,
    clamp_color_sat,
    game_to_scenario,
    load_default_scenario,
    migrate_to_schema_4,
    apply_scenario_to_game,
    scenario_to_game_dicts,
)
from render.buildings import (
    BuildingDef,
    instances_overlap_ok,
    load_catalog,
    pack_place,
    shuffle_building_seed,
)


def test_migrate_schema_3_snippet() -> None:
    raw = {
        "schema_version": 3,
        "place_configs": {
            "Housing": {"spawn_interval": 2.0, "attract_weight": 1.0},
            "Extra": {"spawn_interval": 1.5, "attract_weight": 0.5},
        },
        "place_geometry": {
            "Housing": {"center_x": 36, "center_y": 2, "width": 5, "length": 5},
            "Extra": {"center_x": 10, "center_y": 10, "width": 3, "length": 3},
        },
        "intersection_configs": {
            "main": {"intersection_type": "x", "size_cells": 4, "center_x": 36, "center_y": 48},
            "intersection_3": {"intersection_type": "x", "size_cells": 4, "center_x": 36, "center_y": 48},
        },
        "lane_configs": {
            "0": {
                "speed_limit": 1.0,
                "lane_type": "normal",
                "start_tile": [36, 5],
                "end_tile": [36, 45],
            },
            "12": {
                "speed_limit": 1.0,
                "lane_type": "normal",
                "start_tile": [1, 1],
                "end_tile": [1, 5],
            },
        },
    }
    out = migrate_to_schema_4(raw)
    assert out["schema_version"] == SCHEMA_VERSION
    assert out["places"]["Housing"]["protected"] is True
    assert out["places"]["Extra"]["protected"] is False
    assert out["intersections"]["main"]["protected"] is True
    assert out["intersections"]["intersection_3"]["protected"] is False
    assert out["lanes"]["0"]["protected"] is True
    assert out["lanes"]["12"]["protected"] is False
    assert out["route_hints"]  # legacy defaults injected
    assert out["police"]


def test_tangent_straight_turn_uturn() -> None:
    """Synthetic 4-way: lanes keyed arbitrarily, not 0..11."""
    # Places sized so their edges sit flush with lane endpoints.
    places_by_id = {
        "A": places.Place(11, 1, 4, 4),   # y [ -1, 3)
        "B": places.Place(11, 29, 4, 4),  # y [27, 31)
        "C": places.Place(29, 15, 4, 4),  # x [27, 31)
    }
    intersections = {
        "hub": places.IntersectionConfig(
            intersection_type=places.INTERSECTION_TYPE_X,
            size_cells=4,
            center_x=11,
            center_y=15,
        )
    }
    # hub bounds: x[9,13) y[13,17). Lanes touch place edges and hub faces.
    lanes = {
        100: places.LaneConfig(start_tile=(11, 3), end_tile=(11, 12)),   # A → hub
        101: places.LaneConfig(start_tile=(11, 17), end_tile=(11, 27)),  # hub → B
        102: places.LaneConfig(start_tile=(12, 12), end_tile=(12, 3)),   # hub → A (U-turn)
        103: places.LaneConfig(start_tile=(13, 15), end_tile=(27, 15)),  # hub → C
    }
    world.rebuild_world(place_rects_from_places(places_by_id), intersections, lanes)

    assert world.lane_traffic_in(100) == "A", world.lane_traffic_in(100)
    assert world.lane_traffic_out(100) == "hub", world.lane_traffic_out(100)
    assert is_straight_path(100, 101) is True
    assert is_straight_path(100, 103) is False
    assert places.is_uturn_transition(100, 102) is True, (
        world.lane_traffic_in(100),
        world.lane_traffic_out(102),
    )
    assert places.is_turn_at_intersection(100, 103) is True


def test_unnamed_intersections_occupancy() -> None:
    places_by_id = {
        "P": places.Place(5, 5, 3, 3),
    }
    intersections = {
        "alpha": places.IntersectionConfig(size_cells=4, center_x=20, center_y=20),
        "beta": places.IntersectionConfig(size_cells=2, center_x=40, center_y=40),
        "gamma": places.IntersectionConfig(size_cells=4, center_x=60, center_y=20),
    }
    lanes = {
        1: places.LaneConfig(start_tile=(6, 7), end_tile=(18, 20)),
    }
    world.rebuild_world(place_rects_from_places(places_by_id), intersections, lanes)
    keys = world.get_intersection_keys()
    assert keys == ["alpha", "beta", "gamma"]
    # Authored centres are live world cells (no pad-shift).
    cell = world.get_intersection_cells_by_key("alpha")[0]
    assert world.get_intersection_at_cell(cell) == "alpha"
    assert "main" not in keys
    x_lo, y_lo, x_hi, y_hi = world.get_bounds()
    assert x_lo <= 20 < x_hi
    assert y_lo <= 20 < y_hi
    assert x_lo <= 60 < x_hi


def test_default_map_hints_and_police_homes() -> None:
    scenario = load_default_scenario()
    g = GameState()
    apply_scenario_to_game(g, scenario)
    places.set_route_hints(g.route_hints)
    g.rebuild_world_from_config()

    hinted = places.spawn_lanes_for_place("Housing", "Park")
    assert hinted
    assert all(world.lane_traffic_out(i) == "bypass" for i in hinted)

    # Lane 7: main → Shopping → home at place end (not start)
    assert world.lane_traffic_out(7) == "Shopping"
    assert _home_at_lane_start(7) is False
    # Lane 5: main → Park → home at place end
    assert world.lane_traffic_out(5) == "Park"
    assert _home_at_lane_start(5) is False
    # Lane approaching from place: home at start
    assert world.lane_traffic_in(0) == "Housing"
    assert _home_at_lane_start(0) is True


def test_rename_place() -> None:
    from sim.cars import Car

    g = GameState()
    car = Car(
        origin="Housing",
        destination="Park",
        color=(220, 60, 60),
        base_speed_multiplier=1.0,
        lane_index=0,
        position_in_lane=0,
    )
    g.cars.append(car)

    assert g.rename_place("Housing", "Homes") == "Homes"
    assert "Homes" in g.places
    assert "Housing" not in g.places
    assert ("Homes", "Park", "bypass") in g.route_hints
    assert ("Park", "Homes", "bypass") in g.route_hints
    assert car.origin == "Homes"
    assert world.lane_traffic_in(0) == "Homes"

    assert g.rename_place("Homes", "main") == "Homes"
    assert g.rename_place("Homes", "Park") == "Homes"
    assert g.rename_place("Homes", "") == "Homes"
    assert g.rename_place("Homes", "   ") == "Homes"
    assert "Homes" in g.places
    assert "Housing" not in g.places


def test_reset_loads_default() -> None:
    g = GameState()
    g.places["Zed"] = places.Place(1, 1, 2, 2)
    g.lanes[99] = places.LaneConfig(start_tile=(0, 0), end_tile=(0, 3))
    g.reset_to_defaults()
    assert "Zed" not in g.places
    assert 99 not in g.lanes
    assert set(g.places) == {"Housing", "Office", "Park", "Shopping"}
    assert g.can_remove_lane(0) is False
    assert g.can_remove_intersection("main") is False


def test_stable_lane_ids_survive_gap() -> None:
    places_by_id = {"P": places.Place(0, 0, 2, 2)}
    intersections = {"j": places.IntersectionConfig(size_cells=2, center_x=10, center_y=0)}
    lanes = {
        2: places.LaneConfig(start_tile=(1, 0), end_tile=(8, 0)),
        5: places.LaneConfig(start_tile=(8, 1), end_tile=(1, 1)),
    }
    world.rebuild_world(place_rects_from_places(places_by_id), intersections, lanes)
    assert world.lane_ids() == [2, 5]
    assert world.get_lane_cells(2)
    assert world.get_lane_cells(3) == ()
    assert world.lane_count() == 2


def test_authored_coords_match_world() -> None:
    """Lane endpoints in the world equal authored JSON tiles; bounds cover content."""
    from sim.scenario import load_default_scenario, apply_scenario_to_game

    scenario = load_default_scenario()
    g = GameState()
    apply_scenario_to_game(g, scenario)
    g.rebuild_world_from_config()

    for key, raw in scenario["lanes"].items():
        idx = int(key)
        cells = world.get_lane_cells(idx)
        assert cells, idx
        start = tuple(raw["start_tile"])
        end = tuple(raw["end_tile"])
        assert cells[0] == start, (idx, cells[0], start)
        assert cells[-1] == end, (idx, cells[-1], end)

    x_lo, y_lo, x_hi, y_hi = world.get_bounds()
    for idx in world.lane_ids():
        for gx, gy in world.get_lane_cells(idx):
            assert x_lo <= gx < x_hi
            assert y_lo <= gy < y_hi
    main_cells = world.get_intersection_cells_by_key("main")
    assert (36, 48) in main_cells


def test_place_spawn_survives_rebuild() -> None:
    """A Place holds geometry and spawn_interval in one record; rebuild does not drop spawn."""
    g = GameState()
    record = places.Place(
        center_x=1,
        center_y=1,
        width=2,
        length=2,
        spawn_interval=1.5,
        attract_weight=0.5,
    )
    g.places["Solo"] = record
    g.rebuild_world_from_config()
    assert g.places["Solo"] is record
    assert g.places["Solo"].spawn_interval == 1.5
    assert g.places["Solo"].attract_weight == 0.5
    assert g.places["Solo"].width == 2


def test_camera_roundtrip() -> None:
    from render.camera import grid_to_screen, screen_to_grid

    gx, gy = 36.0, 48.0
    bounds = (0, 0, 80, 90)
    sx, sy = grid_to_screen(gx, gy, 400.0, 300.0, *bounds, zoom_scale=1.0)
    back_x, back_y = screen_to_grid(sx, sy, 400.0, 300.0, *bounds, zoom_scale=1.0)
    assert abs(back_x - gx) < 1e-6
    assert abs(back_y - gy) < 1e-6


def test_tee_layout_for_sides() -> None:
    from render.intersection_topology import tee_layout_for_sides

    assert tee_layout_for_sides(frozenset({"N", "S", "E"})) == ("ns", "E")
    assert tee_layout_for_sides(frozenset({"N", "S", "W"})) == ("ns", "W")
    assert tee_layout_for_sides(frozenset({"E", "W", "S"})) == ("ew", "S")
    assert tee_layout_for_sides(frozenset({"E", "W", "N"})) == ("ew", "N")
    assert tee_layout_for_sides(frozenset({"N", "S"})) == ("ns", "S")
    assert tee_layout_for_sides(frozenset({"N", "E"}), through_fallback="ns") == ("ns", "E")


def test_snap_cardinal_end() -> None:
    origin = (10, 10)
    assert snap_cardinal_end(origin, origin) == origin
    assert snap_cardinal_end(origin, (14, 10)) == (14, 10)
    assert snap_cardinal_end(origin, (6, 10)) == (6, 10)
    assert snap_cardinal_end(origin, (10, 15)) == (10, 15)
    assert snap_cardinal_end(origin, (10, 4)) == (10, 4)
    assert snap_cardinal_end(origin, (14, 11)) == (14, 10)
    assert snap_cardinal_end(origin, (11, 15)) == (10, 15)
    assert snap_cardinal_end(origin, (6, 9)) == (6, 10)
    assert snap_cardinal_end(origin, (9, 4)) == (10, 4)
    # |dx| == |dy| prefers E/W
    assert snap_cardinal_end(origin, (13, 13)) == (13, 10)
    assert snap_cardinal_end(origin, (7, 13)) == (7, 10)


def test_place_aabb_from_corners() -> None:
    assert aabb_from_corners((10, 10), (10, 10)) == (10, 10, 1, 1)
    assert aabb_from_corners((10, 10), (14, 13)) == (10, 10, 5, 4)
    assert place_center_from_aabb(10, 10, 5, 4) == (12, 12)
    # reverse order, no clamp: still the min-corner AABB
    assert aabb_from_corners((14, 13), (10, 10)) == (10, 10, 5, 4)
    # clamp to 16, anchored on corner 1
    assert aabb_from_corners((0, 0), (20, 0)) == (0, 0, 16, 1)
    assert aabb_from_corners((20, 0), (0, 0)) == (5, 0, 16, 1)


def test_intersection_size_for_hover() -> None:
    c = (10, 10)
    assert bounds_from_center(10, 10, 2) == (9, 11, 9, 11)
    assert intersection_size_for_hover(c, c) == 2
    assert intersection_size_for_hover(c, (9, 10)) == 2
    assert intersection_size_for_hover(c, (10, 9)) == 2
    # one step outside the 2×2 (cx-1, cx) × (cy-1, cy)
    assert intersection_size_for_hover(c, (11, 10)) == 4
    assert intersection_size_for_hover(c, (10, 11)) == 4
    assert intersection_size_for_hover(c, (8, 10)) == 4
    assert intersection_size_for_hover(c, (100, 10)) == 12
    assert intersection_size_for_hover(c, (10, -100)) == 12


def test_place_aabb_from_edge_and_hover() -> None:
    c1, c2 = (10, 10), (10, 14)
    # C3 on C2 → 1×N strip
    assert aabb_from_edge_and_hover(c1, c2, c2) == (10, 10, 1, 5)
    # off the line → 2D rect
    assert aabb_from_edge_and_hover(c1, c2, (15, 12)) == (10, 10, 6, 5)
    # horizontal edge
    c1, c2 = (8, 3), (12, 3)
    assert aabb_from_edge_and_hover(c1, c2, (12, 3)) == (8, 3, 5, 1)
    assert aabb_from_edge_and_hover(c1, c2, (10, 7)) == (8, 3, 5, 5)


def _iso_center(gx: int, gy: int) -> tuple[float, float]:
    return ((gx - gy) * TILE_W, (gx + gy) * TILE_H)


def test_iso_aabb_silhouette() -> None:
    d1 = iso_aabb_silhouette(0, 0, 1, 1, _iso_center)
    assert len(d1) == 4
    strip = iso_aabb_silhouette(0, 0, 2, 1, _iso_center)
    assert len(strip) == 4
    square = iso_aabb_silhouette(0, 0, 2, 2, _iso_center)
    assert len(square) == 4
    assert occupancy_aabb([(3, 5), (4, 5), (5, 5)]) == (3, 5, 3, 1)


def test_selection_rim_offset_and_facing() -> None:
    poly = iso_aabb_silhouette(0, 0, 1, 1, _iso_center)
    cx = sum(p[0] for p in poly) / 4
    cy = sum(p[1] for p in poly) / 4
    inset = offset_polygon(poly, -1.0)
    assert len(inset) == 4
    for p, q in zip(poly, inset):
        d_out = (p[0] - cx) ** 2 + (p[1] - cy) ** 2
        d_in = (q[0] - cx) ** 2 + (q[1] - cy) ** 2
        assert d_in < d_out
    ccw = ensure_ccw(poly)
    sw_hits = [edge_faces_sw(ccw[i], ccw[(i + 1) % len(ccw)]) for i in range(len(ccw))]
    assert any(sw_hits)
    assert any(not h for h in sw_hits)
    assert rim_quads(ccw)[0]
    assert rim_quads(ccw)[1]


def test_color_settings_clamp_roundtrip() -> None:
    """Hue/sat snap and wrap; persist via game_to_scenario and migrate."""
    assert clamp_color_hue(0) == 0
    assert clamp_color_hue(360) == 0
    assert clamp_color_hue(125) == 130
    assert clamp_color_hue(-10) == 350
    assert clamp_color_sat(1.0) == 1.0
    assert clamp_color_sat(0) == 0.0
    assert clamp_color_sat(2.4) == 2.0
    assert clamp_color_sat(0.14) == 0.1

    class Win:
        _edge_pan_enabled = True
        _grass_close_enabled = False
        _color_hue = 360
        _color_sat = 1.94

    g = GameState()
    data = game_to_scenario(g, window=Win())
    assert data["user_settings"]["color_hue"] == 0
    assert data["user_settings"]["color_sat"] == 1.9
    assert data["user_settings"]["grass_close_enabled"] is False

    migrated = migrate_to_schema_4(
        {
            "schema_version": 4,
            "places": {},
            "intersections": {},
            "lanes": {},
            "user_settings": {"color_hue": 370, "color_sat": -1, "edge_pan_enabled": True},
        }
    )
    assert migrated["user_settings"]["color_hue"] == 10
    assert migrated["user_settings"]["color_sat"] == 0.0


def _pack_test_defs() -> list[BuildingDef]:
    return [
        BuildingDef(
            "house", "house.png", "residential",
            8, 8, 3, 3, 256.0, 500.0, 514, 514,
        ),
        BuildingDef(
            "cube", "cube.png", "commercial",
            8, 8, 3, 3, 256.0, 500.0, 514, 514,
        ),
    ]


def _assert_inside_place(items, x0: int, y0: int, w: int, l: int) -> None:
    x1, y1 = x0 + w, y0 + l
    for inst in items:
        assert inst.origin_x >= x0 and inst.origin_y >= y0
        assert inst.origin_x + inst.cells_e <= x1
        assert inst.origin_y + inst.cells_n <= y1


def test_building_pack_counts() -> None:
    defs = _pack_test_defs()
    assert pack_place(0, 0, 1, 1, "residential", defs, "A") == []
    assert pack_place(0, 0, 1, 2, "residential", defs, "A") == []
    assert pack_place(0, 0, 5, 5, "none", defs, "Park") == []
    p22 = pack_place(0, 0, 2, 2, "residential", defs, "A")
    assert len(p22) == 1
    _assert_inside_place(p22, 0, 0, 2, 2)
    p55 = pack_place(10, 20, 5, 5, "residential", defs, "Housing")
    assert len(p55) == 1
    _assert_inside_place(p55, 10, 20, 5, 5)
    p99 = pack_place(0, 0, 9, 9, "residential", defs, "Housing")
    assert len(p99) == 4
    _assert_inside_place(p99, 0, 0, 9, 9)
    assert instances_overlap_ok(p99)
    res = pack_place(0, 0, 5, 5, "residential", defs, "Housing")
    com = pack_place(0, 0, 5, 5, "commercial", defs, "Office")
    assert res[0].asset_id == "house"
    assert com[0].asset_id == "cube"


def test_building_pack_long_variants() -> None:
    """Natural size first; leftover is yard. Long art is not crushed to the long AABB."""
    wing = BuildingDef(
        "house_wing_e", "house_wing_e.png", "residential",
        5, 15, 2, 6, 161.5, 530.0, 643, 531,
    )
    p = pack_place(0, 0, 5, 5, "residential", [wing], "Housing")
    assert len(p) == 1
    _assert_inside_place(p, 0, 0, 5, 5)
    assert p[0].asset_id == "house_wing_e"
    assert p[0].fit_scale == 1.0
    assert p[0].cells_e == 5
    assert p[0].cells_n == 2

    house = BuildingDef(
        "house", "house.png", "residential",
        8, 8, 3, 3, 256.0, 500.0, 514, 514,
    )
    grown = pack_place(0, 0, 6, 6, "residential", [house], "Lot")
    assert len(grown) == 1
    _assert_inside_place(grown, 0, 0, 6, 6)
    assert grown[0].fit_scale == 1.0
    assert grown[0].cells_e == 3 and grown[0].cells_n == 3

    stepped = BuildingDef(
        "block_stepped_e", "block_stepped_e.png", "commercial",
        8, 29, 3, 11, 257.5, 964.0, 1186, 965,
    )
    mall = pack_place(0, 0, 5, 5, "commercial", [stepped], "Office")
    assert len(mall) == 1
    _assert_inside_place(mall, 0, 0, 5, 5)
    assert mall[0].fit_scale == 10 / 14
    assert mall[0].fit_scale > 5 / 11

    defs = load_catalog(persist=True)
    res_ids = {
        pack_place(0, 0, 5, 5, "residential", defs, f"Lot{i}")[0].asset_id
        for i in range(24)
    }
    com_ids = {
        pack_place(0, 0, 5, 5, "commercial", defs, f"Shop{i}")[0].asset_id
        for i in range(24)
    }
    assert res_ids - {"house"}
    assert com_ids - {"cube"}


def test_building_kind_roundtrip() -> None:
    g = GameState()
    assert g.places["Housing"].building_kind == "residential"
    assert g.places["Office"].building_kind == "commercial"
    g.places["Housing"].building_kind = "commercial"
    data = game_to_scenario(g)
    assert data["places"]["Housing"]["building_kind"] == "commercial"
    places_by_id, *_ = scenario_to_game_dicts(migrate_to_schema_4(data))
    assert places_by_id["Housing"].building_kind == "commercial"
    migrated = migrate_to_schema_4(
        {
            "schema_version": 3,
            "place_configs": {
                "Housing": {"spawn_interval": 2.0, "attract_weight": 1.0},
                "Office": {"spawn_interval": 2.0, "attract_weight": 1.0},
            },
            "place_geometry": {
                "Housing": {"center_x": 36, "center_y": 2, "width": 5, "length": 5},
                "Office": {"center_x": 36, "center_y": 70, "width": 5, "length": 5},
            },
            "intersection_configs": {},
            "lane_configs": {},
        }
    )
    assert migrated["places"]["Housing"]["building_kind"] == "residential"
    assert migrated["places"]["Office"]["building_kind"] == "commercial"
    g2 = GameState()
    g2.places["Park"].building_kind = "none"
    data2 = game_to_scenario(g2)
    assert data2["places"]["Park"]["building_kind"] == "none"
    places2, *_ = scenario_to_game_dicts(migrate_to_schema_4(data2))
    assert places2["Park"].building_kind == "none"


def test_building_seed_shuffle() -> None:
    defs = load_catalog(persist=True)
    a = pack_place(0, 0, 5, 5, "residential", defs, "Housing", seed=0)
    b = pack_place(0, 0, 5, 5, "residential", defs, "Housing")
    assert a and a[0].asset_id == b[0].asset_id
    ids = {
        pack_place(0, 0, 5, 5, "residential", defs, "Housing", seed=s)[0].asset_id
        for s in range(1, 48)
    }
    assert len(ids) > 1
    g = GameState()
    assert getattr(g.places["Housing"], "building_seed", 0) == 0
    g.places["Housing"].building_seed = 7
    data = game_to_scenario(g)
    assert data["places"]["Housing"]["building_seed"] == 7
    places_by_id, *_ = scenario_to_game_dicts(migrate_to_schema_4(data))
    assert places_by_id["Housing"].building_seed == 7
    migrated = migrate_to_schema_4(
        {
            "schema_version": 4,
            "places": {
                "Housing": {
                    "center_x": 36, "center_y": 2, "width": 5, "length": 5,
                    "building_kind": "residential",
                },
            },
            "intersections": {},
            "lanes": {},
        }
    )
    assert migrated["places"]["Housing"]["building_seed"] == 0
    new_seed = shuffle_building_seed(defs, "residential", "Housing", 5, 5, 0)
    assert new_seed != 0
    shuffled = pack_place(0, 0, 5, 5, "residential", defs, "Housing", seed=new_seed)
    assert shuffled


def test_building_layout_shuffle() -> None:
    defs = load_catalog(persist=True)
    house0 = pack_place(0, 0, 5, 5, "residential", defs, "Housing", seed=0)
    assert len(house0) == 1
    assert house0[0].asset_id == "house"
    assert house0[0].cells_e == 3 and house0[0].cells_n == 3
    layouts = {
        (inst.origin_x, inst.origin_y, inst.cells_e, inst.cells_n)
        for s in range(1, 48)
        for inst in pack_place(0, 0, 5, 5, "residential", defs, "Housing", seed=s)
    }
    assert len(layouts) > 1
    p99 = pack_place(0, 0, 9, 9, "residential", defs, "Housing", seed=0)
    assert len(p99) == 4
    merged = None
    for s in range(1, 120):
        packed = pack_place(0, 0, 9, 9, "residential", defs, "Estate", seed=s)
        if len(packed) < 4:
            merged = packed
            break
    assert merged is not None
    _assert_inside_place(merged, 0, 0, 9, 9)
    for inst in merged:
        if inst.asset_id.startswith("house"):
            assert inst.fit_scale <= 1.0 + 1e-9


def test_building_catalog_natural_scale() -> None:
    defs = load_catalog(persist=True)
    by_id = {d.asset_id: d for d in defs}
    assert "cube" in by_id and "house" in by_id
    assert by_id["cube"].world_cells_n == 3
    assert by_id["cube"].world_cells_e == 3
    assert by_id["house"].world_cells_n == 3
    assert by_id["house"].world_cells_e == 3


def main() -> None:
    tests = [
        test_migrate_schema_3_snippet,
        test_tangent_straight_turn_uturn,
        test_unnamed_intersections_occupancy,
        test_default_map_hints_and_police_homes,
        test_reset_loads_default,
        test_stable_lane_ids_survive_gap,
        test_authored_coords_match_world,
        test_place_spawn_survives_rebuild,
        test_camera_roundtrip,
        test_tee_layout_for_sides,
        test_rename_place,
        test_snap_cardinal_end,
        test_place_aabb_from_corners,
        test_place_aabb_from_edge_and_hover,
        test_intersection_size_for_hover,
        test_iso_aabb_silhouette,
        test_selection_rim_offset_and_facing,
        test_color_settings_clamp_roundtrip,
        test_building_pack_counts,
        test_building_pack_long_variants,
        test_building_kind_roundtrip,
        test_building_seed_shuffle,
        test_building_layout_shuffle,
        test_building_catalog_natural_scale,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    if failed:
        raise SystemExit(f"{failed} test(s) failed")
    print(f"All {len(tests)} tests passed.")


if __name__ == "__main__":
    main()
