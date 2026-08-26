"""
Headless tests for schema-4 scenario and derived topology.
Run: python -m tests.test_universal_map
"""
from __future__ import annotations

from sim import places, world
from sim.cop import _home_at_lane_start
from sim.game import GameState
from sim.map_data import place_rects_from_places
from sim.paths import is_straight_path
from sim.scenario import (
    SCHEMA_VERSION,
    load_default_scenario,
    migrate_to_schema_4,
    apply_scenario_to_game,
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
