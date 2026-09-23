"""
Headless tests for schema-4 scenario and derived topology.
Run: python -m tests.test_universal_map
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from sim import persistence, places, world
from sim.cars import Car
from sim.cop import (
    COPS_PER_INTERSECTION,
    DISMISS_LINGER,
    FADE_SECONDS,
    INBOUND_TAIL_CELLS,
    _home_at_lane_start,
    in_node_jam,
    intersection_dismiss_score,
    intersection_jam_score,
    pick_deploy_lane,
    place_on_lane_for_intersection,
    spawn_police,
)
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
    grade_rgb,
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
    assert "type" not in out["intersections"]["main"]
    assert out["intersections"]["intersection_3"]["protected"] is False
    assert out["lanes"]["0"]["protected"] is True
    assert out["lanes"]["12"]["protected"] is False
    assert out["route_hints"]  # legacy defaults injected
    assert "police" in out
    assert out["police"] == []


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
            intersection_type=places.INTERSECTION_TYPE_CROSS,
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

    assert g.police_list == []

    # Lane 7: main → Shopping → home at place end (not start)
    assert world.lane_traffic_out(7) == "Shopping"
    assert _home_at_lane_start(7) is False
    # Lane 5: main → Park → home at place end
    assert world.lane_traffic_out(5) == "Park"
    assert _home_at_lane_start(5) is False
    # Lane approaching from place: home at start
    assert world.lane_traffic_in(0) == "Housing"
    assert _home_at_lane_start(0) is True


def _make_test_car(
    lane_index: int = 0,
    position: int = 0,
    mode: str = "lane",
    cell: tuple[int, int] | None = None,
    vis: str = "green",
) -> Car:
    car = Car(
        origin="Housing",
        destination="Office",
        color=(220, 60, 60),
        base_speed_multiplier=1.0,
        lane_index=lane_index,
        position_in_lane=position,
    )
    car.motion_mode = mode
    car.intersection_cell = cell
    car.visibility_state = vis
    if cell is not None:
        car.pose_gx = float(cell[0])
        car.pose_gy = float(cell[1])
    return car


def _stop(car: Car) -> Car:
    car.visibility_state = "red"
    car.speed_scale = 0.0
    return car


def _deadlock_at(node: str) -> list[Car]:
    """Two stopped approaches plus a stuck car in the box. Enough to call a cop."""
    from sim.cop import approach_groups

    groups = approach_groups(node)
    directions = sorted(groups)
    assert len(directions) >= 2, node
    cars: list[Car] = []
    for direction in directions[:2]:
        lane = groups[direction][0]
        cells = world.get_lane_cells(lane)
        src = world.lane_traffic_in(lane)
        if len(cells) < INBOUND_TAIL_CELLS and world.is_intersection(src):
            box = world.get_intersection_cells_by_key(src)
            cars.append(_stop(_make_test_car(mode="path", cell=box[0], lane_index=lane)))
        else:
            cars.append(_stop(_make_test_car(lane_index=lane, position=len(cells) - 1)))
    box = world.get_intersection_cells_by_key(node)
    stuck = _stop(_make_test_car(mode="path", cell=box[0], lane_index=groups[directions[0]][0]))
    stuck.impasse_active = True
    cars.append(stuck)
    return cars


def test_police_on_demand() -> None:
    g = GameState()
    assert g.police_list == []
    assert game_to_scenario(g)["police"] == []

    main_cells = world.get_intersection_cells_by_key("main")
    bypass_cells = world.get_intersection_cells_by_key("bypass")
    assert main_cells and bypass_cells

    g.cars = [_make_test_car(mode="path", cell=main_cells[0])]
    assert intersection_jam_score(g.cars, "main") == 1
    assert intersection_jam_score(g.cars, "bypass") == 0

    inbound = next(i for i in world.lane_ids() if world.lane_traffic_out(i) == "main")
    lane_cells = world.get_lane_cells(inbound)
    g.cars = [_make_test_car(lane_index=inbound, position=len(lane_cells) - 1, vis="red")]
    assert intersection_jam_score(g.cars, "main") == 1
    assert len(lane_cells) > INBOUND_TAIL_CELLS
    edge = len(lane_cells) - INBOUND_TAIL_CELLS
    g.cars = [_make_test_car(lane_index=inbound, position=edge, vis="red")]
    assert intersection_jam_score(g.cars, "main") == 1
    g.cars = [_make_test_car(lane_index=inbound, position=edge - 1, vis="red")]
    assert intersection_jam_score(g.cars, "main") == 0

    approach = pick_deploy_lane("main")
    assert approach is not None
    place = place_on_lane_for_intersection(approach, "main")
    assert place and not world.is_intersection(place)

    flowing = [
        _make_test_car(mode="path", cell=main_cells[i % len(main_cells)], vis="green")
        for i in range(6)
    ] + [
        _make_test_car(mode="path", cell=main_cells[0], vis="cyan")
        for _ in range(3)
    ]
    assert intersection_jam_score(flowing, "main") == 9
    assert intersection_dismiss_score(flowing, "main") == 0
    g.police_list = []
    g.cars = flowing
    g._update_police(0.0)
    assert g.police_list == []

    g.cars = _deadlock_at("main")
    g._update_police(0.0)
    assert len(g.police_list) == COPS_PER_INTERSECTION
    assert g.police_list[0].target_intersection == "main"
    g._update_police(0.0)
    assert len(g.police_list) == 1

    g.police_list = []
    g.cars = _deadlock_at("main") + _deadlock_at("bypass")
    g._update_police(0.0)
    assert {p.target_intersection for p in g.police_list} == {"main", "bypass"}

    holder = spawn_police("main", approach)
    holder.state = "holding"
    holder.current_node = "main"
    g.police_list = [holder]
    g.cars = [_make_test_car(mode="path", cell=main_cells[0], vis="green")]
    g._update_police(DISMISS_LINGER + 0.1)
    assert holder.state == "holding"

    g.cars = []
    g.police_list = [holder]
    holder.linger_timer = 0.0
    holder.hold_time = 0.0
    from sim.cop import FADE_SECONDS
    g._update_police(FADE_SECONDS)
    g._update_police(0.1)
    assert holder.state == "returning"


def test_police_disabled_and_clear_cars() -> None:
    g = GameState()
    g.cars = [_make_test_car()]
    g.clear_cars()
    assert g.cars == []

    g.cars = _deadlock_at("main")
    g.set_police_enabled(False)
    g._update_police(0.0)
    assert g.police_list == []

    g.set_police_enabled(True)
    g._update_police(0.0)
    assert len(g.police_list) == 1

    g.set_police_enabled(False)
    assert g.police_list == []


def test_police_holding_helps_jam() -> None:
    from sim.constants import VIS_ZONE_WIDTH_CELLS
    from sim.cop import DRAIN_SPEED, _intersection_center, advance_signal, approach_groups, drain_cap
    from sim.impasse import apply_impasse
    from sim.paths import direction_index_8_from_tangent
    from sim.visibility import build_poses

    g = GameState()
    main_cells = world.get_intersection_cells_by_key("main")
    groups = approach_groups("main")
    north = groups["N"][0]
    south = groups["S"][0]
    north_cells = world.get_lane_cells(north)
    south_cells = world.get_lane_cells(south)
    approach = pick_deploy_lane("main")
    assert approach is not None
    cop_car = spawn_police("main", approach)
    cop_car.state = "holding"
    cop_car.current_node = "main"
    home_at_0 = _home_at_lane_start(approach)
    cop_car.lane_pos = 0.0 if not home_at_0 else float(cop_car._lane_len(approach) - 1)

    gx, gy, di = cop_car.get_pose()
    cx, cy = _intersection_center("main")
    assert di == direction_index_8_from_tangent(cx - gx, cy - gy)

    path_cars = [
        _make_test_car(mode="path", cell=main_cells[i % len(main_cells)], vis="red")
        for i in range(drain_cap("main") + 1)
    ]
    north_tail = _make_test_car(lane_index=north, position=len(north_cells) - 1, vis="red")
    south_tail = _make_test_car(lane_index=south, position=len(south_cells) - 1, vis="red")
    # A second northbound car, one cell back, so the fan can see the one ahead.
    north_follow = _make_test_car(lane_index=north, position=len(north_cells) - 2, vis="green")
    g.cars = path_cars + [north_tail, south_tail, north_follow]
    g.police_list = [cop_car]
    half = VIS_ZONE_WIDTH_CELLS / 2.0
    poses = build_poses(g.cars)
    g._apply_police_influence(poses, lambda *_: [], half)
    g._apply_visibility(poses, lambda *_: [], half)

    creeping = [c for c in path_cars if c.police_clear == "drain"]
    waiting = [c for c in path_cars if c.police_held]
    cap = drain_cap("main")
    assert len(creeping) == cap
    assert len(waiting) == len(path_cars) - cap
    assert all(c.speed_scale == DRAIN_SPEED and c.visibility_state == "cyan" for c in creeping)
    assert all(c.speed_scale == 0.0 for c in waiting)
    # The same cars keep the slot; the rest do not start until those have left.
    g._apply_police_influence(poses, lambda *_: [], half)
    assert {id(c) for c in path_cars if c.police_clear == "drain"} == {id(c) for c in creeping}
    # One creeper leaves the box; his slot passes to a car that was waiting.
    g.cars = [c for c in g.cars if c is not creeping[0]]
    g._apply_police_influence(build_poses(g.cars), lambda *_: [], half)
    still = {id(c) for c in creeping[1:]}
    now = {id(c) for c in path_cars if c is not creeping[0] and c.police_clear == "drain"}
    assert len(now) == cap
    assert still <= now
    assert north_tail.police_held and south_tail.police_held
    assert north_tail.speed_scale == 0.0 and south_tail.speed_scale == 0.0

    # Box empty and the north queue is the longer one: that direction opens.
    g.cars = [north_tail, north_follow, south_tail]
    assert advance_signal(cop_car, 0.1, g.cars) == ""
    assert cop_car.phase == "green"
    assert cop_car.green_dir == "N"
    assert cop_car.initial_clear is False
    poses = build_poses(g.cars)
    g._apply_police_influence(poses, lambda *_: [], half)
    g._apply_visibility(poses, lambda gx, gy: list(range(len(g.cars))), half)
    assert north_tail.police_clear == "wave" and not north_tail.police_held
    assert north_follow.police_clear == "wave"
    assert south_tail.police_held and south_tail.speed_scale == 0.0
    # The waved car still stops for the car ahead of it.
    assert north_follow.speed_scale == 0.0
    assert north_tail.speed_scale == 1.0

    from sim.cop import RELEASE_CARS

    cop_car.phase = "green"
    cop_car.green_dir = "N"
    cop_car.entered_ids = set()
    cop_car.phase_time = 0.0
    sent = [
        _make_test_car(mode="path", cell=main_cells[i % len(main_cells)], lane_index=north)
        for i in range(RELEASE_CARS)
    ]
    assert advance_signal(cop_car, 0.1, sent) == ""
    assert cop_car.phase == "clear"

    # A held car inside the fan does not stop a waved car. Another car does.
    waved = _make_test_car()
    waved.police_clear = "wave"
    waved.pose_gx, waved.pose_gy, waved.pose_dir_index_8 = 10.0, 10.0, 0
    blocker = _make_test_car()
    blocker.police_held = True
    blocker.pose_gx, blocker.pose_gy, blocker.pose_dir_index_8 = 10.0, 11.0, 0
    g.cars = [waved, blocker]
    g._apply_visibility(build_poses(g.cars), lambda *_: [0, 1], half)
    assert waved.speed_scale == 1.0
    ahead = _make_test_car()
    ahead.pose_gx, ahead.pose_gy, ahead.pose_dir_index_8 = 10.0, 11.0, 0
    g.cars = [waved, ahead]
    g._apply_visibility(build_poses(g.cars), lambda *_: [0, 1], half)
    assert waved.speed_scale == 0.0

    south_tail.police_held = True
    south_tail.impasse_active = True
    south_tail.visibility_state = "red"
    south_tail.speed_scale = 0.0
    pose = (float(south_cells[-1][0]), float(south_cells[-1][1]), 0)
    apply_impasse(0.1, [south_tail], [pose], {id(south_tail): 0}, lambda *_: [], half, {}, set())
    assert south_tail.visibility_state == "red"
    assert south_tail.speed_scale == 0.0

    deploying = spawn_police("main", approach)
    deploying.lane_pos = cop_car.lane_pos
    assert deploying.state == "deploying"
    assert deploying.at_mouth()
    g.police_list = [deploying]
    g.cars = path_cars[:1]
    g._apply_police_influence(build_poses(g.cars), lambda *_: [], half)
    assert g.cars[0].police_clear == ""
    assert g.cars[0].police_held is False

    g.police_list = [cop_car]
    g.rebuild_world_from_config()
    assert any(p.target_intersection == "main" for p in g.police_list)

    shared = main_cells[0]
    assert world.cell_in_intersection(shared, "main")
    overlap_car = _make_test_car(mode="path", cell=shared, vis="red")
    assert in_node_jam(overlap_car, "main")


def test_police_exit_proximity() -> None:
    """Cyan goes to the car nearest its exit. A feed lane stops only at the mouth."""
    from sim.cop import approach_groups, cells_to_exit, drain_cap

    g = GameState()
    main_cells = world.get_intersection_cells_by_key("main")
    out_lane = world.outgoing_lanes("main")[0]
    exit_cell = world.get_lane_cells(out_lane)[0]
    ex, ey = float(exit_cell[0]), float(exit_cell[1])

    def _in_box(along: float):
        car = _make_test_car(mode="path", cell=main_cells[0], vis="red")
        car.pending_out_lane_index = out_lane
        car.pose_gx = ex + along
        car.pose_gy = ey
        return car

    cap = drain_cap("main")
    queued = [_in_box(0.2 + i) for i in range(cap + 1)]
    near, far = queued[0], queued[-1]
    assert cells_to_exit(near, "main") < cells_to_exit(far, "main")
    assert cells_to_exit(near, "main") < 1.0

    approach = pick_deploy_lane("main")
    assert approach is not None
    cop_car = spawn_police("main", approach)
    cop_car.state = "holding"
    cop_car.current_node = "main"
    cop_car.target_intersection = "main"
    cop_car.phase = "clear"
    cop_car.initial_clear = True
    g.police_list = [cop_car]
    g.cars = list(reversed(queued))
    g._apply_police_influence(None, lambda *_: [], 0.5)
    cyan = [c for c in g.cars if c.police_clear == "drain"]
    assert near in cyan and far not in cyan
    assert len(cyan) == cap

    g.cars = [c for c in queued if c is not near]
    g._apply_police_influence(None, lambda *_: [], 0.5)
    assert far.police_clear == "drain"
    assert sum(c.police_clear == "drain" for c in g.cars) == cap

    groups = approach_groups("main")
    lane = groups["S"][0]
    cells = world.get_lane_cells(lane)
    mouth = _make_test_car(lane_index=lane, position=len(cells) - 1, vis="red")
    back = _make_test_car(lane_index=lane, position=len(cells) - 4, vis="red")
    assert cells_to_exit(mouth, "main") <= 0.5
    assert cells_to_exit(back, "main") > 0.5
    cop_car.initial_clear = False
    cop_car.phase = "green"
    cop_car.green_dir = "N"
    g.cars = [mouth, back]
    g._apply_police_influence(None, lambda *_: [], 0.5)
    assert mouth.police_held
    assert back.police_held is False and back.police_clear == ""


def test_police_fades_the_sides_up_before_leaving() -> None:
    """One side stays open, the others rise to full speed, and only then does he leave."""
    from sim.constants import VIS_ZONE_WIDTH_CELLS
    from sim.cop import approach_groups
    from sim.visibility import build_poses

    g = GameState()
    groups = approach_groups("main")
    cop_car = spawn_police("main", pick_deploy_lane("main"))
    cop_car.state = "holding"
    cop_car.current_node = "main"
    cop_car.target_intersection = "main"
    cop_car.phase = "fade"
    cop_car.fade_giveup = False
    cop_car.fade_dirs = tuple(sorted(groups))
    cop_car.fade_time = 0.0
    cop_car.fade_ready = False
    assert len(cop_car.fade_dirs) >= 2
    first, last = cop_car.fade_dirs[0], cop_car.fade_dirs[-1]

    def _mouth(direction: str):
        lane = groups[direction][0]
        cells = world.get_lane_cells(lane)
        return _make_test_car(lane_index=lane, position=len(cells) - 1)

    opened = _mouth(first)
    waiting = _mouth(last)
    g.police_list = [cop_car]
    half = VIS_ZONE_WIDTH_CELLS / 2.0

    def _speeds() -> None:
        g.cars = [opened, waiting]
        poses = build_poses(g.cars)
        g._apply_police_influence(poses, lambda *_: [], half)
        g._apply_visibility(poses, lambda *_: [], half)

    _speeds()
    assert opened.police_clear == "wave" and opened.speed_scale == 1.0
    assert waiting.police_held and waiting.speed_scale == 0.0

    cop_car.fade_time = 0.5 * FADE_SECONDS
    featured = min(len(cop_car.fade_dirs) - 1, int(0.5 * len(cop_car.fade_dirs)))
    assert cop_car.fade_dirs.index(first) <= featured
    assert cop_car.fade_dirs.index(last) > featured
    _speeds()
    assert opened.speed_scale == 1.0 and opened.police_clear == "wave"
    assert waiting.police_release == 0.5 and waiting.speed_scale == 0.5
    assert waiting.police_held is False

    cop_car.fade_time = FADE_SECONDS
    _speeds()
    assert opened.speed_scale == 1.0 and waiting.speed_scale == 1.0
    assert opened.police_clear == "wave" and waiting.police_clear == "wave"

    g.cars = []
    cop_car.fade_ready = True
    g._update_police(0.1)
    assert cop_car.state == "returning"


def test_police_linger_and_divert() -> None:
    from sim.cop import FADE_SECONDS, MAX_HOLD_SECONDS, RESPAWN_COOLDOWN

    g = GameState()
    main_cells = world.get_intersection_cells_by_key("main")
    approach = pick_deploy_lane("main")
    assert approach is not None
    home_at_0 = _home_at_lane_start(approach)

    def _hold_at_main():
        cop_car = spawn_police("main", approach)
        cop_car.state = "holding"
        cop_car.current_node = "main"
        cop_car.target_intersection = "main"
        cop_car.lane_pos = 0.0 if not home_at_0 else float(cop_car._lane_len(approach) - 1)
        cop_car.hold_time = 0.0
        cop_car.linger_timer = 0.0
        cop_car.phase = "clear"
        cop_car.initial_clear = True
        return cop_car

    cop_car = _hold_at_main()
    g.cars = []
    g.police_list = [cop_car]
    g._update_police(FADE_SECONDS)
    g._update_police(0.1)
    assert cop_car.state == "returning"

    cop_car = _hold_at_main()
    g.cars = [_make_test_car(mode="path", cell=main_cells[0], vis="green")]
    g.police_list = [cop_car]
    g._update_police(DISMISS_LINGER + 0.1)
    assert cop_car.state == "holding"

    cop_car = _hold_at_main()
    g.cars = _deadlock_at("bypass")
    g.police_list = [cop_car]
    g._update_police(FADE_SECONDS)
    g._update_police(0.1)
    assert cop_car.state == "diverting"
    assert cop_car.target_intersection == "bypass"
    assert cop_car.can_divert is False

    cop_car = _hold_at_main()
    b1_lane = pick_deploy_lane("bypass")
    assert b1_lane is not None
    b1 = spawn_police("bypass", b1_lane)
    b1.state = "holding"
    b1.current_node = "bypass"
    b1.target_intersection = "bypass"
    g.cars = _deadlock_at("bypass")
    g.police_list = [cop_car, b1]
    g._update_police(FADE_SECONDS)
    g._update_police(0.1)
    assert cop_car.state == "returning"
    assert cop_car.target_intersection == "main"

    cop_car = _hold_at_main()
    cop_car.state = "diverting"
    cop_car.target_intersection = "bypass"
    cop_car.dest_node = "bypass"
    cop_car.can_divert = False
    g.cars = []
    g.police_list = [cop_car]
    g._update_police(0.1)
    assert cop_car.state == "returning"

    # A box that never empties sends him home, and the beat stays quiet afterwards.
    cop_car = _hold_at_main()
    g.cars = _deadlock_at("main")
    g.police_list = [cop_car]
    g._police_cooldown.clear()
    g._update_police(MAX_HOLD_SECONDS + 0.1)
    assert cop_car.state == "holding" and cop_car.phase == "fade" and cop_car.fade_ready
    g._update_police(0.0)
    assert cop_car.state == "returning"
    g._update_police(0.0)
    assert not any(p.state in ("deploying", "holding") for p in g.police_list)
    g._update_police(RESPAWN_COOLDOWN)
    assert any(p.state == "deploying" and p.target_intersection == "main" for p in g.police_list)


def test_police_beats() -> None:
    """A short chain is one cop, deployed from a place lane, and he walks the beat."""
    from sim.cop import _lane_place, _lane_touches, beat_of

    g = GameState()
    intersections = {
        "A": places.IntersectionConfig(size_cells=2, center_x=20, center_y=20),
        "B": places.IntersectionConfig(size_cells=2, center_x=20, center_y=26),
        "C": places.IntersectionConfig(size_cells=2, center_x=20, center_y=34),
        "D": places.IntersectionConfig(size_cells=2, center_x=20, center_y=2),
    }
    places_by_id = {
        "Yard": places.Place(center_x=8, center_y=26, width=3, length=3),
        "North": places.Place(center_x=20, center_y=44, width=3, length=3),
        "East": places.Place(center_x=34, center_y=34, width=3, length=3),
    }
    lanes = {
        1: places.LaneConfig(start_tile=(20, 25), end_tile=(20, 21)),  # B → A
        2: places.LaneConfig(start_tile=(20, 33), end_tile=(20, 27)),  # C → B
        3: places.LaneConfig(start_tile=(20, 3), end_tile=(20, 19)),  # D → A, long
        4: places.LaneConfig(start_tile=(10, 26), end_tile=(19, 26)),  # Yard → B
        5: places.LaneConfig(start_tile=(20, 42), end_tile=(20, 35)),  # North → C
        6: places.LaneConfig(start_tile=(32, 34), end_tile=(21, 34)),  # East → C
        7: places.LaneConfig(start_tile=(20, 21), end_tile=(20, 25)),  # A → B
        8: places.LaneConfig(start_tile=(20, 27), end_tile=(20, 33)),  # B → C
    }
    try:
        world.rebuild_world(place_rects_from_places(places_by_id), intersections, lanes)
        assert beat_of("A") == frozenset({"A", "B", "C"})
        assert "D" not in beat_of("A")
        assert len(world.get_lane_cells(1)) < INBOUND_TAIL_CELLS
        assert len(world.get_lane_cells(3)) >= INBOUND_TAIL_CELLS

        g.police_list = []
        g._police_cooldown.clear()
        g.cars = _deadlock_at("A")
        g._update_police(0.0)
        assert len(g.police_list) == 1
        cop_car = g.police_list[0]
        assert cop_car.target_intersection == "A"
        assert cop_car.routing
        assert not _lane_touches(cop_car.deploy_lane, "A")
        assert _lane_place(cop_car.deploy_lane)
        g._update_police(0.0)
        assert len(g.police_list) == 1

        # A car in the junction upstream is not his to stop. The mouth in front of him is.
        holder = g.police_list[0]
        holder.state = "holding"
        holder.current_node = "A"
        holder.target_intersection = "A"
        holder.phase = "clear"
        holder.initial_clear = True
        b_cell = world.get_intersection_cells_by_key("B")[0]
        a_cell = world.get_intersection_cells_by_key("A")[0]
        upstream = _make_test_car(mode="path", cell=b_cell, vis="red")
        in_box = _make_test_car(mode="path", cell=a_cell, vis="red")
        mouth = _stop(_make_test_car(lane_index=1, position=len(world.get_lane_cells(1)) - 1))
        g.cars = [upstream, in_box, mouth]
        g._apply_police_influence(None, lambda *_: [], 0.5)
        assert upstream.police_held is False and upstream.police_clear == ""
        assert mouth.police_held
        assert in_box.police_clear == "drain"

        # His own box is clear and the far end of the beat is stuck: he walks, tour unspent.
        walker = spawn_police("A", 4)
        walker.state = "holding"
        walker.current_node = "A"
        walker.target_intersection = "A"
        walker.travel_lane = 1
        walker.hold_time = 0.0
        walker.linger_timer = 0.0
        walker.phase = "clear"
        walker.can_divert = True
        g.police_list = [walker]
        # Long approaches only, so the queue does not sit in B and keep A busy.
        north_cells = world.get_lane_cells(5)
        east_cells = world.get_lane_cells(6)
        c_cell = world.get_intersection_cells_by_key("C")[0]
        stuck = _stop(_make_test_car(mode="path", cell=c_cell, lane_index=5))
        stuck.impasse_active = True
        g.cars = [
            _stop(_make_test_car(lane_index=5, position=len(north_cells) - 1)),
            _stop(_make_test_car(lane_index=6, position=len(east_cells) - 1)),
            stuck,
        ]
        g._update_police(FADE_SECONDS)
        g._update_police(0.1)
        assert walker.state == "diverting"
        assert walker.target_intersection == "C"
        assert walker.can_divert is True
    finally:
        GameState()


def test_spawn_skips_full_lane() -> None:
    from sim.cars import spawn_car
    from sim.places import choose_spawn_lane, lane_is_full, spawn_lanes_for_place
    from sim.spawner import update_spawns

    g = GameState()
    origin = g.spawn_places[0]
    lanes = spawn_lanes_for_place(origin)
    assert lanes
    lane = lanes[0]
    cells = world.get_lane_cells(lane)
    assert cells

    at_zero = [_make_test_car(lane_index=lane, position=0)]
    assert lane_is_full(lane, at_zero)
    if len(lanes) >= 2:
        chosen = choose_spawn_lane(origin, occupancy=at_zero)
        assert chosen != lane

    packed = [
        _make_test_car(lane_index=lane, position=min(i, len(cells) - 1))
        for i in range(len(cells))
    ]
    assert lane_is_full(lane, packed)

    all_full = [_make_test_car(lane_index=li, position=0) for li in lanes]
    assert choose_spawn_lane(origin, occupancy=all_full) is None
    assert spawn_car(origin, occupancy=all_full) is None

    timers = {origin: 10.0}
    n_before = len(all_full)
    update_spawns(
        0.0,
        (origin,),
        {origin: True},
        timers,
        g.places,
        all_full,
        origin_spawn_balance_coeff=0.0,
        out_lane_balance_coeff=0.0,
    )
    assert timers[origin] == 10.0
    assert len(all_full) == n_before


def test_jam_chains_short_inbound() -> None:
    """Short inbound (< 8) includes the attached box, not that box's lanes or a further hop."""
    intersections = {
        "A": places.IntersectionConfig(size_cells=2, center_x=20, center_y=20),
        "B": places.IntersectionConfig(size_cells=2, center_x=20, center_y=26),
        "C": places.IntersectionConfig(size_cells=2, center_x=20, center_y=32),
        "D": places.IntersectionConfig(size_cells=2, center_x=20, center_y=2),
    }
    places_by_id = {"Yard": places.Place(8, 26, 3, 3)}
    lanes = {
        1: places.LaneConfig(start_tile=(20, 25), end_tile=(20, 20)),  # B → A
        2: places.LaneConfig(start_tile=(20, 31), end_tile=(20, 26)),  # C → B
        3: places.LaneConfig(start_tile=(20, 2), end_tile=(20, 19)),  # D → A (long)
        4: places.LaneConfig(start_tile=(9, 26), end_tile=(19, 26)),  # Yard → B
    }
    world.rebuild_world(place_rects_from_places(places_by_id), intersections, lanes)
    assert world.lane_traffic_in(1) == "B" and world.lane_traffic_out(1) == "A"
    assert world.lane_traffic_in(2) == "C" and world.lane_traffic_out(2) == "B"
    assert world.lane_traffic_in(3) == "D" and world.lane_traffic_out(3) == "A"
    assert len(world.get_lane_cells(1)) < INBOUND_TAIL_CELLS
    assert len(world.get_lane_cells(3)) >= INBOUND_TAIL_CELLS

    a_cells = world.get_intersection_cells_by_key("A")
    b_cells = world.get_intersection_cells_by_key("B")
    c_cells = world.get_intersection_cells_by_key("C")
    d_cells = world.get_intersection_cells_by_key("D")
    in_b = [_make_test_car(mode="path", cell=b_cells[0], vis="red")]
    assert intersection_jam_score(in_b, "A") == 1
    assert intersection_dismiss_score(in_b, "A") == 1
    assert in_node_jam(in_b[0], "A")
    assert intersection_jam_score(in_b, "A") == intersection_jam_score(in_b, "B")

    in_c = [_make_test_car(mode="path", cell=c_cells[0], vis="red")]
    assert intersection_jam_score(in_c, "A") == 0
    assert intersection_jam_score(in_c, "B") == 1

    in_d = [_make_test_car(mode="path", cell=d_cells[0], vis="red")]
    assert intersection_jam_score(in_d, "A") == 0

    b_in_cells = world.get_lane_cells(4)
    b_tail = [_make_test_car(lane_index=4, position=len(b_in_cells) - 1, vis="red")]
    assert intersection_jam_score(b_tail, "B") == 1
    assert intersection_jam_score(b_tail, "A") == 0

    in_a = [_make_test_car(mode="path", cell=a_cells[0], vis="red")]
    assert intersection_jam_score(in_a, "A") == 1
    flowing_b = [_make_test_car(mode="path", cell=b_cells[0], vis="green")]
    assert intersection_jam_score(flowing_b, "A") == 1
    assert intersection_dismiss_score(flowing_b, "A") == 0


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
    assert g.can_remove_lane(0) is True
    assert g.can_remove_intersection("main") is True
    assert g.can_remove_place("Housing") is True


def test_sanitize_save_name() -> None:
    assert persistence.sanitize_save_name("../escape") is None
    assert persistence.sanitize_save_name("..\\escape") is None
    assert persistence.sanitize_save_name("bad/name") is None
    assert persistence.sanitize_save_name("") is None
    assert persistence.sanitize_save_name("   ") is None
    assert persistence.sanitize_save_name("city map") == "city_map"
    assert persistence.sanitize_save_name("Paint-Test_1") == "Paint-Test_1"


def test_named_map_save_load_roundtrip() -> None:
    g = GameState()
    g.places["Zed"] = places.Place(3, 4, 2, 2)
    g.intersections["plaza"] = places.IntersectionConfig(size_cells=2, center_x=8, center_y=9)
    g.lanes[77] = places.LaneConfig(start_tile=(1, 2), end_tile=(1, 6))
    places_snap = {k: (p.center_x, p.center_y, p.width, p.length) for k, p in g.places.items()}
    ints_snap = {k: (i.center_x, i.center_y, i.size_cells) for k, i in g.intersections.items()}
    lanes_snap = {k: (tuple(l.start_tile), tuple(l.end_tile)) for k, l in g.lanes.items()}
    with tempfile.TemporaryDirectory() as td:
        folder = Path(td)
        working = folder / "config.json"
        assert persistence.save_named_map(g, "city", directory=folder) == "city"
        assert persistence.list_saved_maps(folder) == ["city"]
        g2 = GameState()
        assert persistence.load_named_map(g2, "city", directory=folder, working_path=working)
        assert {k: (p.center_x, p.center_y, p.width, p.length) for k, p in g2.places.items()} == places_snap
        assert {k: (i.center_x, i.center_y, i.size_cells) for k, i in g2.intersections.items()} == ints_snap
        assert getattr(g2.intersections["plaza"], "paint_thru_lines", None) is True
        assert {k: (tuple(l.start_tile), tuple(l.end_tile)) for k, l in g2.lanes.items()} == lanes_snap
        assert working.is_file()


def test_new_game_restores_default_places() -> None:
    g = GameState()
    g.places["Zed"] = places.Place(1, 1, 2, 2)
    with tempfile.TemporaryDirectory() as td:
        persistence.new_game(g, working_path=Path(td) / "config.json")
    assert "Zed" not in g.places
    assert set(g.places) == {"Housing", "Office", "Park", "Shopping"}


def test_delete_default_lane_and_intersection() -> None:
    """Protected default lanes and intersections may still be deleted."""
    g = GameState()
    assert 0 in g.lanes and getattr(g.lanes[0], "protected", False)
    assert "main" in g.intersections and getattr(g.intersections["main"], "protected", False)
    g.delete_lane(0)
    assert 0 not in g.lanes
    g.delete_intersection("main")
    assert "main" not in g.intersections


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


def test_camera_yaw_roundtrip() -> None:
    from render.camera import grid_to_screen, screen_to_grid

    gx, gy = 36.0, 48.0
    bounds = (0, 0, 80, 90)
    for q in range(4):
        sx, sy = grid_to_screen(gx, gy, 400.0, 300.0, *bounds, zoom_scale=1.0, view_yaw_q=q)
        back_x, back_y = screen_to_grid(sx, sy, 400.0, 300.0, *bounds, zoom_scale=1.0, view_yaw_q=q)
        assert abs(back_x - gx) < 1e-6
        assert abs(back_y - gy) < 1e-6


def test_map_camera_matches_grid_to_screen() -> None:
    """World pixels through the map camera land on the same screen points as grid_to_screen."""
    from render.camera import grid_to_screen, grid_to_world_px, map_camera_screen

    bounds = (0, 0, 80, 90)
    width, height = 800.0, 600.0
    cells = ((10.0, 12.0), (36.0, 48.0), (79.0, 0.0))
    pans = ((0.0, 0.0), (40.0, -15.0), (-100.0, 80.0))
    zooms = (0.25, 1.0, 2.5)
    for yaw in range(4):
        for gx, gy in cells:
            wx, wy = grid_to_world_px(gx, gy, *bounds, yaw)
            for cam_x, cam_y in pans:
                for zoom in zooms:
                    got = map_camera_screen(wx, wy, cam_x, cam_y, zoom, width, height)
                    expected = grid_to_screen(
                        gx, gy, width / 2.0 - cam_x, height / 2.0 - cam_y, *bounds, zoom, yaw,
                    )
                    assert abs(got[0] - expected[0]) < 1e-6
                    assert abs(got[1] - expected[1]) < 1e-6


def test_camera_yaw_north_looks_like_east() -> None:
    from render.camera import grid_to_screen

    bounds = (0, 0, 80, 90)
    cx = (0 + 80 - 1) / 2.0
    cy = (0 + 90 - 1) / 2.0
    sx_e, sy_e = grid_to_screen(cx + 1, cy, 400.0, 300.0, *bounds, zoom_scale=1.0, view_yaw_q=0)
    sx_n, sy_n = grid_to_screen(cx, cy + 1, 400.0, 300.0, *bounds, zoom_scale=1.0, view_yaw_q=1)
    assert abs(sx_e - sx_n) < 1e-6
    assert abs(sy_e - sy_n) < 1e-6


def test_iso_depth_reverses_at_180() -> None:
    from render.camera import iso_depth

    bounds = (0, 0, 80, 90)
    d0a = iso_depth(10.0, 10.0, *bounds, 0)
    d0b = iso_depth(12.0, 14.0, *bounds, 0)
    d2a = iso_depth(10.0, 10.0, *bounds, 2)
    d2b = iso_depth(12.0, 14.0, *bounds, 2)
    assert d0a != d0b
    assert (d0a < d0b) == (d2a > d2b)


def test_yaw_cardinal_and_dir_remap() -> None:
    from render.camera import (
        cardinal_label_anchors,
        display_dir_index,
        road_tile_key,
        rotate_cardinal,
        rotate_sides,
        rotate_straight_axis,
    )

    assert rotate_cardinal("N", 1) == "E"
    assert rotate_cardinal("N", 2) == "S"
    assert rotate_cardinal("N", 3) == "W"
    assert rotate_cardinal("N", 4) == "N"
    assert rotate_sides(frozenset({"N", "E"}), 1) == frozenset({"E", "S"})
    assert rotate_straight_axis("ns", 1) == "ew"
    assert rotate_straight_axis("ew", 1) == "ns"
    assert rotate_straight_axis("ns", 2) == "ns"
    assert road_tile_key("N", 1) == "road_e"
    assert display_dir_index(0, 1) == 2
    assert display_dir_index(0, 2) == 4
    assert display_dir_index(7, 1) == 1
    assert cardinal_label_anchors("N", 0) == ("center", "bottom")
    assert cardinal_label_anchors("N", 1) == ("right", "center")


def test_view_south_cell_corners() -> None:
    from render.camera import view_south_cell

    bounds = (0, 0, 80, 90)
    assert view_south_cell(5, 5, 3, 4, *bounds, 0) == (5, 5)
    assert view_south_cell(5, 5, 3, 4, *bounds, 1) == (7, 5)
    assert view_south_cell(5, 5, 3, 4, *bounds, 2) == (7, 8)
    assert view_south_cell(5, 5, 3, 4, *bounds, 3) == (5, 8)


def test_overlay_type_for_sides() -> None:
    from render.intersection_topology import overlay_type_for_sides

    assert overlay_type_for_sides(frozenset()) == "none"
    assert overlay_type_for_sides(frozenset({"N"})) == "straight"
    assert overlay_type_for_sides(frozenset({"E"})) == "straight"
    assert overlay_type_for_sides(frozenset({"N", "S"})) == "straight"
    assert overlay_type_for_sides(frozenset({"E", "W"})) == "straight"
    assert overlay_type_for_sides(frozenset({"N", "E"})) == "corner"
    assert overlay_type_for_sides(frozenset({"N", "S", "E"})) == "tee"
    assert overlay_type_for_sides(frozenset({"N", "S", "E", "W"})) == "cross"

    from sim.scenario import scenario_to_game_dicts

    _places, ixs, _lanes, _police, _hints, _in_bal, _out_bal = scenario_to_game_dicts(
        {
            "places": {},
            "intersections": {"hub": {"center_x": 10, "center_y": 10, "size_cells": 4, "protected": False}},
            "lanes": {},
        }
    )
    assert ixs["hub"].size_cells == 4


def test_tee_layout_for_sides() -> None:
    from render.intersection_topology import tee_layout_for_sides

    assert tee_layout_for_sides(frozenset({"N", "S", "E"})) == ("ns", "E")
    assert tee_layout_for_sides(frozenset({"N", "S", "W"})) == ("ns", "W")
    assert tee_layout_for_sides(frozenset({"E", "W", "S"})) == ("ew", "S")
    assert tee_layout_for_sides(frozenset({"E", "W", "N"})) == ("ew", "N")
    assert tee_layout_for_sides(frozenset({"N", "S"})) == ("ns", "S")
    assert tee_layout_for_sides(frozenset({"N", "E"}), through_fallback="ns") == ("ns", "E")


def test_tee_corner_quadrants() -> None:
    from render.intersection_topology import tee_corner_quadrants

    assert tee_corner_quadrants("E") == (2, 3)
    assert tee_corner_quadrants("W") == (0, 1)
    assert tee_corner_quadrants("N") == (0, 3)
    assert tee_corner_quadrants("S") == (1, 2)


def test_corner_quadrant_for_sides() -> None:
    from render.corner_gen import make_corner
    from render.intersection_topology import corner_quadrant_for_sides

    assert corner_quadrant_for_sides(frozenset({"W", "N"})) == 0
    assert corner_quadrant_for_sides(frozenset({"S", "W"})) == 1
    assert corner_quadrant_for_sides(frozenset({"E", "S"})) == 2
    assert corner_quadrant_for_sides(frozenset({"N", "E"})) == 3

    # Connected-edge midpoints stay pavement; the other two faces stay clear.
    # Image left/bottom/right/top ↔ world W/N/E/S after the iso shear.
    expected = {
        0: ("left", "bottom"),
        1: ("right", "bottom"),
        2: ("right", "top"),
        3: ("left", "top"),
    }
    for q, sides in expected.items():
        img = make_corner(4, quadrant=q)
        w, h = img.size
        mid = {
            "left": img.getpixel((0, h // 2)),
            "right": img.getpixel((w - 1, h // 2)),
            "top": img.getpixel((w // 2, 0)),
            "bottom": img.getpixel((w // 2, h - 1)),
        }
        for name, px in mid.items():
            if name in sides:
                assert px[3] == 255, f"q{q} {name} should be opaque"
            else:
                assert px[3] == 0, f"q{q} {name} should be clear"


def test_filleted_cross_tee_transparency() -> None:
    from render.corner_gen import ROAD_GREY, WHITE, YELLOW, make_cross, make_tee

    cross = make_cross(4)
    w, h = cross.size
    assert cross.getpixel((0, 0))[3] == 0
    assert cross.getpixel((w - 1, 0))[3] == 0
    assert cross.getpixel((0, h - 1))[3] == 0
    assert cross.getpixel((w - 1, h - 1))[3] == 0
    cx, cy = w // 2, h // 2
    centre = cross.getpixel((cx, cy))
    assert centre[3] == 255
    assert centre[:3] == ROAD_GREY
    assert cross.getpixel((cx, 60))[:3] != YELLOW
    for dx in range(-8, 9):
        for dy in range(-8, 9):
            assert cross.getpixel((cx + dx, cy + dy))[:3] != WHITE

    tee = make_tee(4, axis="ns", stem="E")
    tw, th = tee.size
    assert tee.getpixel((0, 0))[3] == 0
    assert tee.getpixel((0, th - 1))[3] == 0
    assert tee.getpixel((tw - 1, 0))[3] == 0
    assert tee.getpixel((tw - 1, th - 1))[3] == 0
    tee_c = tee.getpixel((tw // 2, th // 2))
    assert tee_c[3] == 255
    assert tee_c[:3] != WHITE
    # Through yellows continue; branch yellows do not enter the box.
    # Two 2px strokes (PIL-inclusive), same as the old `_stroke_through_yellows`.
    assert tee.getpixel((tw // 2, 60))[:3] == YELLOW
    assert tee.getpixel((tw // 2, 61))[:3] == YELLOW
    assert tee.getpixel((60, 16))[:3] != YELLOW
    # Open shoulder (opposite the stem) stays transparent on 4-cell+ stamps.
    assert tee.getpixel((tw // 2, 104))[3] == 0
    # Both stem-side corners have a fillet lip (not only one).
    def _has_white_near(x0: int, y0: int, r: int = 24) -> bool:
        for y in range(max(0, y0 - r), min(th, y0 + r + 1)):
            for x in range(max(0, x0 - r), min(tw, x0 + r + 1)):
                p = tee.getpixel((x, y))
                if p[:3] == WHITE and p[3]:
                    return True
        return False

    assert _has_white_near(16, 16)
    assert _has_white_near(tw - 16, 16)

    def _cross_white_near(x0: int, y0: int, r: int = 28) -> bool:
        for y in range(max(0, y0 - r), min(h, y0 + r + 1)):
            for x in range(max(0, x0 - r), min(w, x0 + r + 1)):
                p = cross.getpixel((x, y))
                if p[:3] == WHITE and p[3]:
                    return True
        return False

    assert _cross_white_near(24, 24)
    assert _cross_white_near(w - 24, 24)
    assert _cross_white_near(24, h - 24)
    assert _cross_white_near(w - 24, h - 24)

    for n in (6, 8, 12):
        big = make_cross(n)
        bw, bh = big.size
        assert big.getpixel((bw // 2, bh // 2))[:3] == ROAD_GREY
        assert big.getpixel((0, 0))[3] == 0
        tee_n = make_tee(n, axis="ns", stem="E")
        tw_n, th_n = tee_n.size
        assert tee_n.getpixel((tw_n // 2, th_n // 2))[3] == 255
        assert tee_n.getpixel((tw_n // 2, 8))[:3] == ROAD_GREY
        band_hi = (n // 2 + 1) * 32
        assert tee_n.getpixel((tw_n // 2, band_hi + 4))[3] == 0


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
        _police_enabled = False
        _color_hue = 360
        _color_sat = 1.94

    g = GameState()
    data = game_to_scenario(g, window=Win())
    assert data["user_settings"]["color_hue"] == 0
    assert data["user_settings"]["color_sat"] == 1.9
    assert data["user_settings"]["grass_close_enabled"] is False
    assert data["user_settings"]["police_enabled"] is False

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


def test_grade_rgb_identity_and_hue_shift() -> None:
    green = (40, 190, 70)
    assert grade_rgb(green, 0, 1.0) == green
    assert grade_rgb((255, 255, 255), 90, 1.5) == (255, 255, 255)
    assert grade_rgb((40, 190, 70, 140), 0, 1.0)[3] == 140
    shifted = grade_rgb(green, 120, 1.0)
    assert shifted != green
    assert shifted[2] > shifted[1]


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


def test_rebuild_topology_tables() -> None:
    """Incoming/outgoing, oncoming pairs, and attached short-inbounds are rebuild caches."""
    g = GameState()
    assert world.outgoing_lanes("Housing")
    assert all(world.lane_traffic_in(i) == "Housing" for i in world.outgoing_lanes("Housing"))
    assert all(world.lane_traffic_out(i) == "main" for i in world.incoming_lanes("main") if world.lane_traffic_out(i))
    assert world.in_lane_ids() == places.in_lane_indices()
    assert 0 in world.in_lane_ids()
    assert world.oncoming_lane(0) == 3
    assert world.oncoming_lane(3) == 0
    assert world.oncoming_lane(1) == 2
    assert world.oncoming_lane(2) == 1
    assert world.oncoming_lane(4) == 5
    assert world.oncoming_lane(5) == 4
    assert world.oncoming_lane(6) == 7
    assert world.oncoming_lane(7) == 6
    hops = world.best_next_hops("Housing", "Park")
    assert "bypass" in hops

    intersections = {
        "A": places.IntersectionConfig(size_cells=2, center_x=20, center_y=20),
        "B": places.IntersectionConfig(size_cells=2, center_x=20, center_y=26),
        "C": places.IntersectionConfig(size_cells=2, center_x=20, center_y=32),
        "D": places.IntersectionConfig(size_cells=2, center_x=20, center_y=2),
    }
    places_by_id = {"Yard": places.Place(8, 26, 3, 3)}
    lanes = {
        1: places.LaneConfig(start_tile=(20, 25), end_tile=(20, 20)),
        2: places.LaneConfig(start_tile=(20, 31), end_tile=(20, 26)),
        3: places.LaneConfig(start_tile=(20, 2), end_tile=(20, 19)),
        4: places.LaneConfig(start_tile=(9, 26), end_tile=(19, 26)),
    }
    world.rebuild_world(place_rects_from_places(places_by_id), intersections, lanes)
    assert world.attached_intersections("A") == frozenset({"B"})
    assert "C" not in world.attached_intersections("A")
    assert world.attached_intersections("B") == frozenset({"C"})
    g.rebuild_world_from_config()


def test_sister_geometry_staggered_and_corner() -> None:
    """Sisters share heading, oncoming the reverse; adjacency and overlap, not endpoints."""
    places.set_route_hints([])
    lanes = {
        9: places.LaneConfig(start_tile=(64, 23), end_tile=(64, 70)),
        10: places.LaneConfig(start_tile=(63, 70), end_tile=(63, 23)),
        82: places.LaneConfig(start_tile=(65, 25), end_tile=(65, 67)),
        83: places.LaneConfig(start_tile=(62, 67), end_tile=(62, 25)),
    }
    world.rebuild_world({}, {}, lanes)
    assert world.sister_lane(9) == 82
    assert world.sister_lane(82) == 9
    assert world.sister_lane(10) == 83
    assert world.sister_lane(83) == 10
    assert world.oncoming_lane(9) == 10
    assert world.oncoming_lane(10) == 9
    assert world.oncoming_lane(82) is None
    assert world.oncoming_lane(83) is None

    # The short inner lanes start and stop inside their sister's interior. Each
    # lane names the role its partner plays, so the pair reads both ways.
    assert world.sister_relation(9, 82) == world.SISTER_LITTLE
    assert world.sister_relation(82, 9) == world.SISTER_BIG
    assert world.sister_relation(10, 83) == world.SISTER_LITTLE
    assert world.sister_relation(83, 10) == world.SISTER_BIG
    assert world.sister_links(9) == ((82, world.SISTER_LITTLE),)
    # Northbound 9 merges right into 82; 82 merges left into 9.
    assert world.cell_merge(64, 40) == world.MERGE_RIGHT
    assert world.cell_merge(65, 40) == world.MERGE_LEFT
    # Southbound sisters sit at lower x, so the sides flip with the heading.
    assert world.cell_merge(63, 40) == world.MERGE_RIGHT
    assert world.cell_merge(62, 40) == world.MERGE_LEFT
    # A little sister's own mouths still pass; the big sister's do not.
    assert world.cell_merge(65, 25) == world.MERGE_LEFT
    assert world.cell_merge(65, 67) == world.MERGE_LEFT
    assert world.cell_merge(64, 23) == world.MERGE_NEITHER
    assert world.cell_merge(64, 70) == world.MERGE_NEITHER
    assert world.cell_merge(0, 0) == world.MERGE_NEITHER
    assert world.cell_is_passing(64, 40)
    assert not world.cell_is_passing(64, 23)
    assert len(world.lane_merge_cells(9)) == 43
    assert len(world.lane_merge_cells(82)) == len(world.get_lane_cells(82))

    corner = {
        1: places.LaneConfig(start_tile=(0, 10), end_tile=(5, 10)),
        2: places.LaneConfig(start_tile=(6, 11), end_tile=(10, 11)),
    }
    world.rebuild_world({}, {}, corner)
    assert world.sister_lane(1) is None
    assert world.sister_lane(2) is None
    assert world.oncoming_lane(1) is None
    assert world.oncoming_lane(2) is None

    opposite_corner = {
        1: places.LaneConfig(start_tile=(0, 10), end_tile=(5, 10)),
        2: places.LaneConfig(start_tile=(10, 11), end_tile=(6, 11)),
    }
    world.rebuild_world({}, {}, opposite_corner)
    assert world.sister_lane(1) is None
    assert world.oncoming_lane(1) is None
    assert world.oncoming_lane(2) is None

    shared = {
        1: places.LaneConfig(start_tile=(4, 10), end_tile=(12, 10)),
        2: places.LaneConfig(start_tile=(4, 11), end_tile=(12, 11)),
    }
    world.rebuild_world({}, {}, shared)
    assert world.sister_lane(1) == 2
    assert world.sister_lane(2) == 1
    assert world.oncoming_lane(1) is None
    assert world.oncoming_lane(2) is None
    # Equal length and aligned: identical twins, merge along the whole run.
    assert world.sister_relation(1, 2) == world.SISTER_TWIN
    assert world.sister_relation(2, 1) == world.SISTER_TWIN
    assert world.cell_merge(8, 10) == world.MERGE_LEFT
    assert world.cell_merge(8, 11) == world.MERGE_RIGHT

    eastbound = {
        1: places.LaneConfig(start_tile=(0, 10), end_tile=(40, 10)),
        2: places.LaneConfig(start_tile=(5, 11), end_tile=(35, 11)),
    }
    world.rebuild_world({}, {}, eastbound)
    assert world.sister_relation(1, 2) == world.SISTER_LITTLE
    assert world.sister_relation(2, 1) == world.SISTER_BIG
    # Eastbound driver's left is +y, the mirror of the northbound case.
    assert world.cell_merge(20, 10) == world.MERGE_LEFT
    assert world.cell_merge(20, 11) == world.MERGE_RIGHT
    assert world.cell_merge(0, 10) == world.MERGE_NEITHER

    three_abreast = {
        1: places.LaneConfig(start_tile=(10, 0), end_tile=(10, 40)),
        2: places.LaneConfig(start_tile=(11, 5), end_tile=(11, 35)),
        3: places.LaneConfig(start_tile=(12, 0), end_tile=(12, 40)),
    }
    world.rebuild_world({}, {}, three_abreast)
    # Merge sides come from neighbour occupancy, and a lane keeps every sister,
    # so the middle lane is flanked and passes both ways.
    assert world.cell_merge(11, 20) == world.MERGE_BOTH
    assert world.cell_merge(10, 20) == world.MERGE_RIGHT
    assert world.cell_merge(12, 20) == world.MERGE_LEFT
    assert world.sister_lanes(2) == (1, 3)
    assert world.sister_relation(3, 2) == world.SISTER_LITTLE

    facing = {
        1: places.LaneConfig(start_tile=(0, 10), end_tile=(0, 20)),
        2: places.LaneConfig(start_tile=(1, 20), end_tile=(1, 10)),
    }
    world.rebuild_world({}, {}, facing)
    assert world.oncoming_lane(1) == 2
    # Crossing the yellow is not a merge.
    assert world.cell_merge(0, 15) == world.MERGE_NEITHER
    assert world.cell_merge(1, 15) == world.MERGE_NEITHER
    GameState()


def _stepsister_chain() -> None:
    """
    Southbound corridor of three staggered lanes between two places.

    Each lane runs out inside the next, so a driver must step right, then left,
    to get from North to South. x10 for the outer legs, x9 for the middle.
    """
    places_by_id = {
        "North": places.Place(center_x=10, center_y=52, width=3, length=3),
        "South": places.Place(center_x=10, center_y=8, width=3, length=3),
    }
    lanes = {
        1: places.LaneConfig(start_tile=(10, 50), end_tile=(10, 36)),
        2: places.LaneConfig(start_tile=(9, 42), end_tile=(9, 15)),
        3: places.LaneConfig(start_tile=(10, 23), end_tile=(10, 10)),
    }
    places.set_route_hints([])
    world.rebuild_world(place_rects_from_places(places_by_id), {}, lanes)


def test_stepsister_chain_and_corridor() -> None:
    """Lanes that begin and end inside each other force a step across the seam."""
    _stepsister_chain()
    assert world.lane_traffic_in(1) == "North" and world.lane_traffic_out(1) == ""
    assert world.lane_traffic_in(2) == "" and world.lane_traffic_out(2) == ""
    assert world.lane_traffic_in(3) == "" and world.lane_traffic_out(3) == "South"

    assert world.sister_relation(1, 2) == world.SISTER_STEP
    assert world.sister_relation(2, 1) == world.SISTER_ELDER
    assert world.sister_relation(2, 3) == world.SISTER_STEP
    assert world.sister_relation(3, 2) == world.SISTER_ELDER
    # The middle lane holds both roles, in the order a driver meets them.
    assert world.sister_links(2) == (
        (1, world.SISTER_ELDER),
        (3, world.SISTER_STEP),
    )
    # The outer legs share a column, so they are not sisters at all.
    assert world.sister_relation(1, 3) is None

    # Southbound driver's left is +x: right onto the middle lane, then left off it.
    assert world.cell_merge(10, 40) == world.MERGE_RIGHT
    assert world.cell_merge(9, 40) == world.MERGE_LEFT
    assert world.cell_merge(9, 20) == world.MERGE_LEFT
    assert world.cell_merge(10, 20) == world.MERGE_RIGHT
    # Between the two shared runs the middle lane has no one alongside.
    assert world.cell_merge(9, 30) == world.MERGE_NEITHER

    assert world.stepsister_step(1) == (2, world.MERGE_RIGHT)
    assert world.stepsister_step(2) == (3, world.MERGE_LEFT)
    assert world.stepsister_step(3) is None  # it reaches South on its own
    assert world.corridor_after(1) == (1, 2, 3)
    assert world.corridor_after(2) == (2, 3)
    assert world.corridor_before(3) == (1, 2, 3)

    # Routing reads the whole corridor as one hop from North to South.
    for lane in (1, 2, 3):
        assert world.lane_exit_node(lane) == "South"
        assert world.lane_entry_node(lane) == "North"
    assert world.destination_reachable("North", "South")
    GameState()


def test_stepsister_route_steps_and_drive() -> None:
    """A planned corridor lists every lane, and a car steps its way through."""
    from sim import passing, routes
    from sim.movement import advance_car
    from sim.occupancy import Occupancy
    from sim.situation import refresh_situations

    _stepsister_chain()
    route = routes.plan_route("North", "South")
    assert route is not None
    assert [(s.kind, s.ref) for s in route] == [
        ("place", "North"),
        ("lane", 1),
        ("lane", 2),
        ("lane", 3),
        ("place", "South"),
    ]
    assert routes.format_route_nodes(route) == "North > South"
    first = routes.first_lane_step_index(route)
    assert routes.step_lane_after(route, first) == (2, first + 1)
    assert routes.out_lane_after(route, first) is None

    car = Car(
        origin="North",
        destination="South",
        color=(220, 60, 60),
        base_speed_multiplier=1.0,
        lane_index=1,
        position_in_lane=0,
        route=route,
        route_index=first,
    )
    assert passing.planned_step_lane(car) == 2

    to_remove: list = []
    t = 0.0
    seen: list[tuple[int, int]] = []
    sides: list[str] = []
    for _ in range(4000):
        t += 1.0 / 60.0
        occ = Occupancy.from_cars([car])
        advance_car(car, t, 8.0, to_remove, occ)
        refresh_situations([car], occ)
        if car.motion_mode == "merge":
            assert car.merge_reason == passing.REASON_STEP
            if not sides or sides[-1] != car.merge_side:
                sides.append(car.merge_side)
        key = (car.lane_index, car.route_index)
        if not seen or seen[-1] != key:
            seen.append(key)
        if to_remove:
            break

    # Each crossing carries the itinerary onto the lane the car now occupies.
    assert seen == [(1, first), (2, first + 1), (3, first + 2)]
    assert sides == [world.MERGE_RIGHT, world.MERGE_LEFT]
    # It ran to the end of the corridor and arrived, rather than despawning mid-road.
    assert car.lane_index == 3
    assert car.position_in_lane == len(world.get_lane_cells(3)) - 1
    GameState()


def test_stepsister_step_survives_a_blocked_seam() -> None:
    """With the seam packed the whole way, the car still lands on the step lane."""
    from sim import routes
    from sim.movement import advance_car
    from sim.occupancy import Occupancy

    _stepsister_chain()
    route = routes.plan_route("North", "South")
    assert route is not None
    first = routes.first_lane_step_index(route)
    cells_1 = world.get_lane_cells(1)
    car = Car(
        origin="North",
        destination="South",
        color=(220, 60, 60),
        base_speed_multiplier=1.0,
        lane_index=1,
        position_in_lane=len(cells_1) - 1,
        route=route,
        route_index=first,
    )
    # Fill the middle lane alongside so no gap is ever usable.
    blockers = [
        _make_test_car(lane_index=2, position=pos)
        for pos in range(0, len(world.get_lane_cells(2)))
    ]
    to_remove: list = []
    advance_car(car, 0.0, 8.0, to_remove, Occupancy.from_cars([car, *blockers]))
    assert not to_remove
    assert car.lane_index == 2
    assert car.route_index == first + 1
    GameState()


def _mother_daughter_chain() -> None:
    """
    Southbound road of three lanes in one column between two places.

    Each lane's last cell abuts the next lane's first, so the three make one
    continuous road with no node anywhere between North and South.
    """
    places_by_id = {
        "North": places.Place(center_x=10, center_y=52, width=3, length=3),
        "South": places.Place(center_x=10, center_y=8, width=3, length=3),
    }
    lanes = {
        1: places.LaneConfig(start_tile=(10, 50), end_tile=(10, 36)),
        2: places.LaneConfig(start_tile=(10, 35), end_tile=(10, 24)),
        3: places.LaneConfig(start_tile=(10, 23), end_tile=(10, 10)),
    }
    places.set_route_hints([])
    world.rebuild_world(place_rects_from_places(places_by_id), {}, lanes)


def test_mother_daughter_chain_is_one_road() -> None:
    """Lanes joined end into start make a corridor without a seam to cross."""
    _mother_daughter_chain()
    assert world.lane_traffic_in(1) == "North" and world.lane_traffic_out(1) == ""
    assert world.lane_traffic_in(2) == "" and world.lane_traffic_out(2) == ""
    assert world.lane_traffic_in(3) == "" and world.lane_traffic_out(3) == "South"

    assert world.lane_daughter(1) == 2 and world.lane_mother(2) == 1
    assert world.lane_daughter(2) == 3 and world.lane_mother(3) == 2
    assert world.lane_mother(1) is None and world.lane_daughter(3) is None
    assert world.kin_relation(1, 2) == world.KIN_DAUGHTER
    assert world.kin_relation(2, 1) == world.KIN_MOTHER
    assert world.kin_relation(1, 3) is None

    # End to end is not side by side: no sisters, no seam, nothing to merge across.
    assert world.sister_links(1) == () and world.sister_links(2) == ()
    assert not world.lane_merge_cells(1)
    assert world.cell_merge(10, 40) == world.MERGE_NEITHER
    assert world.stepsister_step(1) is None

    assert world.corridor_link(1) == (2, world.KIN_DAUGHTER)
    assert world.corridor_link(3) is None
    assert world.corridor_after(1) == (1, 2, 3)
    assert world.corridor_after(2) == (2, 3)
    assert world.corridor_before(3) == (1, 2, 3)
    for lane in (1, 2, 3):
        assert world.lane_exit_node(lane) == "South"
        assert world.lane_entry_node(lane) == "North"
    assert world.destination_reachable("North", "South")

    # Meeting the middle of a lane, or its nose head on, is no kin at all.
    head_on = {
        1: places.LaneConfig(start_tile=(10, 50), end_tile=(10, 36)),
        2: places.LaneConfig(start_tile=(10, 20), end_tile=(10, 34)),
    }
    world.rebuild_world({}, {}, head_on)
    assert world.lane_daughter(1) is None
    assert world.lane_mother(2) is None
    GameState()


def test_mother_daughter_route_and_seamless_drive() -> None:
    """The itinerary lists every lane, and the car rolls across each joint."""
    from sim import passing, routes
    from sim.movement import advance_car
    from sim.occupancy import Occupancy
    from sim.situation import UNKNOWN, refresh_situations

    _mother_daughter_chain()
    route = routes.plan_route("North", "South")
    assert route is not None
    assert [(s.kind, s.ref) for s in route] == [
        ("place", "North"),
        ("lane", 1),
        ("lane", 2),
        ("lane", 3),
        ("place", "South"),
    ]
    first = routes.first_lane_step_index(route)
    car = Car(
        origin="North",
        destination="South",
        color=(220, 60, 60),
        base_speed_multiplier=1.0,
        lane_index=1,
        position_in_lane=0,
        route=route,
        route_index=first,
    )
    # The road carried on is not a step, so no lane change is ever planned.
    assert passing.planned_step_lane(car) is None

    to_remove: list = []
    t = 0.0
    seen: list[tuple[int, int]] = []
    poses: list[float] = []
    features: set[str] = set()
    for _ in range(4000):
        t += 1.0 / 60.0
        occ = Occupancy.from_cars([car])
        advance_car(car, t, 8.0, to_remove, occ)
        refresh_situations([car], occ)
        if car.motion_mode == "merge":
            assert car.merge_reason == passing.REASON_FLOW
            assert car.merge_side == ""
            # Nothing is crossed, so the car dialog reports no lane change.
            assert car.merge_state == UNKNOWN
        if car.lane_index == 1:
            features.add(car.next_feature)
        key = (car.lane_index, car.route_index)
        if not seen or seen[-1] != key:
            seen.append(key)
        poses.append(car.pose_gy)
        if to_remove:
            break

    # Each joint carries the itinerary onto the lane the car now occupies.
    assert seen == [(1, first), (2, first + 1), (3, first + 2)]
    assert features == {"continue lane 2"}
    assert car.lane_index == 3
    assert car.position_in_lane == len(world.get_lane_cells(3)) - 1

    # Southbound down one column: never back up, never skip a cell of road.
    assert poses[0] == 50.0 and poses[-1] == 10.0
    assert all(b <= a for a, b in zip(poses, poses[1:]))
    assert max(a - b for a, b in zip(poses, poses[1:])) < 1.0
    # The joint itself is driven, not jumped: poses land inside the gap.
    assert any(35.0 < gy < 36.0 for gy in poses)
    assert any(23.0 < gy < 24.0 for gy in poses)
    GameState()


def test_mother_lane_is_never_forced_off_its_own_road() -> None:
    """A mother with a little sister alongside carries on instead of exiting."""
    from sim import passing
    from sim.occupancy import Occupancy

    places_by_id = {
        "North": places.Place(center_x=10, center_y=52, width=3, length=3),
        "South": places.Place(center_x=10, center_y=8, width=3, length=3),
    }
    lanes = {
        1: places.LaneConfig(start_tile=(10, 50), end_tile=(10, 36)),
        2: places.LaneConfig(start_tile=(10, 35), end_tile=(10, 10)),
        3: places.LaneConfig(start_tile=(9, 48), end_tile=(9, 37)),
    }
    places.set_route_hints([])
    world.rebuild_world(place_rects_from_places(places_by_id), {}, lanes)
    assert world.lane_daughter(1) == 2
    assert world.sister_relation(1, 3) == world.SISTER_LITTLE
    assert world.cell_merge(10, 37) == world.MERGE_RIGHT

    cells_1 = world.get_lane_cells(1)
    tail = len(cells_1) - 2  # the cell at y=37, one shy of the end
    assert cells_1[tail] == (10, 37)
    # The little sister must still bail out; the mother has a road to follow.
    assert passing._must_exit(3, len(world.get_lane_cells(3)) - 1, world.get_lane_cells(3))
    assert not passing._must_exit(1, tail, cells_1)

    car = _make_test_car(lane_index=1, position=tail)
    assert passing.merge_choice(car, Occupancy.from_cars([car])) is None
    GameState()


def _twin_cross() -> None:
    """
    8-wide hub with eastbound twin inbounds and twin outbounds on three headings.

    Hub bounds x[16,24) y[16,24). Eastbound left is +y; northbound left is -x;
    southbound left is +x.
    """
    places_by_id = {
        "West": places.Place(center_x=10, center_y=19, width=5, length=5),
        "East": places.Place(center_x=30, center_y=19, width=5, length=5),
        "North": places.Place(center_x=20, center_y=32, width=5, length=5),
        "South": places.Place(center_x=20, center_y=8, width=5, length=5),
    }
    intersections = {
        "hub": places.IntersectionConfig(size_cells=8, center_x=20, center_y=20),
    }
    lanes = {
        1: places.LaneConfig(start_tile=(13, 19), end_tile=(15, 19)),
        2: places.LaneConfig(start_tile=(13, 18), end_tile=(15, 18)),
        3: places.LaneConfig(start_tile=(24, 19), end_tile=(27, 19)),
        4: places.LaneConfig(start_tile=(24, 18), end_tile=(27, 18)),
        5: places.LaneConfig(start_tile=(18, 24), end_tile=(18, 29)),
        6: places.LaneConfig(start_tile=(19, 24), end_tile=(19, 29)),
        7: places.LaneConfig(start_tile=(19, 15), end_tile=(19, 12)),
        8: places.LaneConfig(start_tile=(18, 15), end_tile=(18, 12)),
    }
    places.set_route_hints([])
    world.rebuild_world(place_rects_from_places(places_by_id), intersections, lanes)


def _twin_double_double() -> None:
    """
    8-wide hub with centred 2+2 duals on all four headings.

    Eastbound y=18/19, westbound y=20/21; northbound x=20/21, southbound x=18/19.
    """
    places_by_id = {
        "West": places.Place(center_x=10, center_y=19, width=5, length=5),
        "East": places.Place(center_x=30, center_y=19, width=5, length=5),
        "North": places.Place(center_x=20, center_y=32, width=5, length=5),
        "South": places.Place(center_x=20, center_y=8, width=5, length=5),
    }
    intersections = {
        "hub": places.IntersectionConfig(size_cells=8, center_x=20, center_y=20),
    }
    lanes = {
        1: places.LaneConfig(start_tile=(13, 19), end_tile=(15, 19)),
        2: places.LaneConfig(start_tile=(13, 18), end_tile=(15, 18)),
        3: places.LaneConfig(start_tile=(24, 19), end_tile=(27, 19)),
        4: places.LaneConfig(start_tile=(24, 18), end_tile=(27, 18)),
        5: places.LaneConfig(start_tile=(20, 24), end_tile=(20, 29)),
        6: places.LaneConfig(start_tile=(21, 24), end_tile=(21, 29)),
        7: places.LaneConfig(start_tile=(19, 15), end_tile=(19, 12)),
        8: places.LaneConfig(start_tile=(18, 15), end_tile=(18, 12)),
        9: places.LaneConfig(start_tile=(15, 20), end_tile=(12, 20)),
        10: places.LaneConfig(start_tile=(15, 21), end_tile=(12, 21)),
        11: places.LaneConfig(start_tile=(27, 20), end_tile=(24, 20)),
        12: places.LaneConfig(start_tile=(27, 21), end_tile=(24, 21)),
        13: places.LaneConfig(start_tile=(18, 29), end_tile=(18, 24)),
        14: places.LaneConfig(start_tile=(19, 29), end_tile=(19, 24)),
        15: places.LaneConfig(start_tile=(20, 12), end_tile=(20, 15)),
        16: places.LaneConfig(start_tile=(21, 12), end_tile=(21, 15)),
    }
    places.set_route_hints([])
    world.rebuild_world(place_rects_from_places(places_by_id), intersections, lanes)


def test_identical_and_fraternal_twins() -> None:
    """Twins are named after shared mouths; merge sides follow the shared run."""
    identical = {
        1: places.LaneConfig(start_tile=(4, 10), end_tile=(12, 10)),
        2: places.LaneConfig(start_tile=(4, 11), end_tile=(12, 11)),
    }
    world.rebuild_world({}, {}, identical)
    assert world.sister_relation(1, 2) == world.SISTER_TWIN
    assert world.cell_merge(8, 10) == world.MERGE_LEFT
    assert world.cell_merge(8, 11) == world.MERGE_RIGHT

    frat_start = {
        1: places.LaneConfig(start_tile=(0, 10), end_tile=(20, 10)),
        2: places.LaneConfig(start_tile=(0, 11), end_tile=(12, 11)),
    }
    world.rebuild_world({}, {}, frat_start)
    assert world.sister_relation(1, 2) == world.SISTER_TWIN_START
    assert world.sister_relation(2, 1) == world.SISTER_TWIN_START
    assert world.cell_merge(6, 10) == world.MERGE_LEFT
    assert world.cell_merge(16, 10) == world.MERGE_NEITHER

    frat_end = {
        1: places.LaneConfig(start_tile=(0, 10), end_tile=(20, 10)),
        2: places.LaneConfig(start_tile=(8, 11), end_tile=(20, 11)),
    }
    world.rebuild_world({}, {}, frat_end)
    assert world.sister_relation(1, 2) == world.SISTER_TWIN_END
    assert world.cell_merge(14, 10) == world.MERGE_LEFT
    assert world.cell_merge(2, 10) == world.MERGE_NEITHER

    nested = {
        1: places.LaneConfig(start_tile=(0, 10), end_tile=(40, 10)),
        2: places.LaneConfig(start_tile=(5, 11), end_tile=(35, 11)),
    }
    world.rebuild_world({}, {}, nested)
    assert world.sister_relation(1, 2) == world.SISTER_LITTLE
    GameState()


def test_twin_intersection_paths_and_double_stamp() -> None:
    """Keep-side straight, inside turns; far-lane rights are not cached; stamp is One."""
    from render.intersection_topology import (
        classify_intersection_sides,
        overlay_type_for_intersection,
        overlay_type_for_sides,
    )
    from sim import paths

    _twin_cross()
    assert world.sister_relation(1, 2) == world.SISTER_TWIN
    assert world.lane_traffic_out(1) == "hub" and world.lane_traffic_in(3) == "hub"
    assert world.left_lane_of((1, 2)) == 1
    assert world.left_lane_of((5, 6)) == 5
    assert world.left_lane_of((7, 8)) == 7

    legal = {
        (1, 5),
        (1, 3),
        (1, 8),
        (2, 5),
        (2, 4),
        (2, 8),
    }
    weaves = {
        (1, 6),
        (1, 4),
        (1, 7),
        (2, 6),
        (2, 3),
        (2, 7),
    }
    for pair in legal:
        assert places.is_valid_intersection_path(*pair), pair
        assert pair in paths._PATH_CACHE, pair
    for pair in weaves:
        assert not places.is_valid_intersection_path(*pair), pair
        assert pair not in paths._PATH_CACHE, pair

    cells = world.get_intersection_cells_by_key("hub")
    active, _, _ = classify_intersection_sides("hub", cells)
    assert overlay_type_for_sides(active) == places.INTERSECTION_TYPE_CROSS
    assert overlay_type_for_intersection("hub", active) == places.INTERSECTION_TYPE_CROSS
    assert world.intersection_has_twins("hub")
    assert places.clamp_intersection_type("big") == places.INTERSECTION_TYPE_CROSS
    assert places.clamp_intersection_type("double") == places.INTERSECTION_TYPE_CROSS
    assert places.clamp_intersection_type("mixed") == places.INTERSECTION_TYPE_CROSS
    assert places.clamp_intersection_type("one") == places.INTERSECTION_TYPE_CROSS
    assert places.clamp_intersection_type("normal") == places.INTERSECTION_TYPE_CROSS

    places_by_id = {
        "West": places.Place(center_x=10, center_y=19, width=5, length=5),
        "East": places.Place(center_x=30, center_y=19, width=5, length=5),
        "North": places.Place(center_x=20, center_y=32, width=5, length=5),
        "South": places.Place(center_x=20, center_y=8, width=5, length=5),
    }
    intersections = {
        "hub": places.IntersectionConfig(size_cells=8, center_x=20, center_y=20),
    }
    single_in = {
        1: places.LaneConfig(start_tile=(13, 19), end_tile=(15, 19)),
        3: places.LaneConfig(start_tile=(24, 19), end_tile=(27, 19)),
        4: places.LaneConfig(start_tile=(24, 18), end_tile=(27, 18)),
        5: places.LaneConfig(start_tile=(18, 24), end_tile=(18, 29)),
        6: places.LaneConfig(start_tile=(19, 24), end_tile=(19, 29)),
        7: places.LaneConfig(start_tile=(19, 15), end_tile=(19, 12)),
        8: places.LaneConfig(start_tile=(18, 15), end_tile=(18, 12)),
    }
    world.rebuild_world(place_rects_from_places(places_by_id), intersections, single_in)
    assert places.is_valid_intersection_path(1, 5)
    assert not places.is_valid_intersection_path(1, 6)
    assert places.is_valid_intersection_path(1, 8)
    assert not places.is_valid_intersection_path(1, 7)
    assert places.is_valid_intersection_path(1, 3)
    assert not places.is_valid_intersection_path(1, 4)

    double_to_single = {
        1: places.LaneConfig(start_tile=(13, 19), end_tile=(15, 19)),
        2: places.LaneConfig(start_tile=(13, 18), end_tile=(15, 18)),
        3: places.LaneConfig(start_tile=(24, 19), end_tile=(27, 19)),
        5: places.LaneConfig(start_tile=(18, 24), end_tile=(18, 29)),
        6: places.LaneConfig(start_tile=(19, 24), end_tile=(19, 29)),
    }
    world.rebuild_world(place_rects_from_places(places_by_id), intersections, double_to_single)
    assert places.is_valid_intersection_path(1, 3)
    assert places.is_valid_intersection_path(2, 3)
    GameState()


def test_twin_keep_side_drive() -> None:
    """A car on the left twin goes through on the left outbound, not the weave."""
    from sim import routes
    from sim.movement import advance_car
    from sim.occupancy import Occupancy

    _twin_cross()
    route = routes.plan_route("West", "East")
    assert route is not None
    lanes = [int(s.ref) for s in route if s.kind == "lane"]
    assert lanes[0] in (1, 2)
    if lanes[0] == 1:
        assert 3 in lanes
        assert 4 not in lanes
    else:
        assert 4 in lanes
        assert 3 not in lanes

    first = routes.first_lane_step_index(route)
    car = Car(
        origin="West",
        destination="East",
        color=(220, 60, 60),
        base_speed_multiplier=1.0,
        lane_index=int(route[first].ref),
        position_in_lane=0,
        route=route,
        route_index=first,
    )
    to_remove: list = []
    t = 0.0
    seen: list[int] = []
    for _ in range(4000):
        t += 1.0 / 60.0
        occ = Occupancy.from_cars([car])
        advance_car(car, t, 8.0, to_remove, occ)
        if not seen or seen[-1] != car.lane_index:
            seen.append(car.lane_index)
        if to_remove:
            break
    assert seen[0] in (1, 2)
    if seen[0] == 1:
        assert 3 in seen and 4 not in seen
    else:
        assert 4 in seen and 3 not in seen
    assert car.destination == "East"
    GameState()


def test_twin_right_takes_the_inside_lane() -> None:
    """A right from either eastbound twin lands on the right outbound, not the far left."""
    _twin_cross()
    assert world.nearer_to_entry_edge(1, (7, 8)) == 8
    assert not places.is_valid_intersection_path(1, 7)
    assert places.is_valid_intersection_path(1, 8)
    assert places.is_valid_intersection_path(2, 8)
    GameState()


def test_fraternal_drop_lane_exits_onto_the_longer_twin() -> None:
    """A short twin-start with no node at its end steps onto the longer twin."""
    from sim import passing
    from sim.occupancy import Occupancy

    places_by_id = {
        "North": places.Place(center_x=10, center_y=40, width=3, length=3),
        "South": places.Place(center_x=10, center_y=8, width=3, length=3),
    }
    lanes = {
        1: places.LaneConfig(start_tile=(10, 38), end_tile=(10, 10)),
        2: places.LaneConfig(start_tile=(11, 38), end_tile=(11, 20)),
    }
    places.set_route_hints([])
    world.rebuild_world(place_rects_from_places(places_by_id), {}, lanes)
    assert world.sister_relation(1, 2) == world.SISTER_TWIN_START
    assert world.lane_traffic_out(1) == "South"
    assert world.lane_traffic_out(2) == ""
    cells_2 = world.get_lane_cells(2)
    tail = len(cells_2) - 1
    assert passing._must_exit(2, tail, cells_2)
    car = _make_test_car(lane_index=2, position=tail)
    choice = passing.merge_choice(car, Occupancy.from_cars([car]))
    assert choice is not None
    assert choice[0] == 1
    assert choice[3] == passing.REASON_EXIT
    GameState()


def test_twins_do_not_keep_right() -> None:
    """Identical twins stay in lane while going straight; keep-right is little sisters only."""
    from sim import passing
    from sim.occupancy import Occupancy

    lanes = {
        1: places.LaneConfig(start_tile=(0, 10), end_tile=(20, 10)),
        2: places.LaneConfig(start_tile=(0, 11), end_tile=(20, 11)),
    }
    world.rebuild_world({}, {}, lanes)
    assert world.sister_relation(1, 2) == world.SISTER_TWIN
    left = world.left_lane_of((1, 2))
    assert left == 2
    car = _make_test_car(lane_index=2, position=0)
    assert passing.merge_choice(car, Occupancy.from_cars([car])) is None
    GameState()


def test_twin_double_double_has_no_weaves() -> None:
    """Every twin-to-twin combination: no straight-cross, far-turn, or 180."""
    from render.intersection_topology import overlay_type_for_intersection
    from sim.junction import LEFT_OF, OPPOSITE_CARDINAL, RIGHT_OF

    _twin_double_double()
    assert overlay_type_for_intersection("hub", frozenset({"N", "S", "E", "W"})) == (
        places.INTERSECTION_TYPE_CROSS
    )
    node = "hub"
    saw_straight = saw_turn = saw_uturn = 0
    for in_lane in world.incoming_lanes(node):
        in_group = world.mouth_group(in_lane, node, inbound=True)
        if len(in_group) < 2:
            continue
        in_left = world.left_lane_of(in_group)
        din = world.lane_direction(in_lane)
        for out_lane in world.outgoing_lanes(node):
            out_group = world.mouth_group(out_lane, node, inbound=False)
            if len(out_group) < 2:
                continue
            out_left = world.left_lane_of(out_group)
            dout = world.lane_direction(out_lane)
            keep = (in_lane == in_left) == (out_lane == out_left)
            inside = out_lane == world.nearer_to_entry_edge(in_lane, out_group)
            legal = places.is_valid_intersection_path(in_lane, out_lane)
            if dout == din:
                saw_straight += 1
                assert legal == keep, (in_lane, out_lane)
            elif dout == LEFT_OF.get(din) or dout == RIGHT_OF.get(din):
                saw_turn += 1
                assert legal == inside, (in_lane, out_lane)
            elif dout == OPPOSITE_CARDINAL.get(din):
                saw_uturn += 1
                assert not legal, (in_lane, out_lane)
            if dout == din and not keep:
                assert not legal, (in_lane, out_lane, "straight weave")
            if dout in (LEFT_OF.get(din), RIGHT_OF.get(din)) and not inside:
                assert not legal, (in_lane, out_lane, "far-turn weave")
    assert saw_straight and saw_turn and saw_uturn
    GameState()


def test_double_cross_requires_closed_dual() -> None:
    """Deleting a dual lane drops Double to Mixed; shifting it off centre drops to Jogged."""
    from render.intersection_topology import overlay_type_for_intersection

    _twin_double_double()
    assert overlay_type_for_intersection("hub", frozenset({"N", "S", "E", "W"})) == (
        places.INTERSECTION_TYPE_CROSS
    )

    places_by_id = {
        "West": places.Place(center_x=10, center_y=19, width=5, length=5),
        "East": places.Place(center_x=30, center_y=19, width=5, length=5),
        "North": places.Place(center_x=20, center_y=32, width=5, length=5),
        "South": places.Place(center_x=20, center_y=8, width=5, length=5),
    }
    intersections = {
        "hub": places.IntersectionConfig(size_cells=8, center_x=20, center_y=20),
    }
    closed = {
        1: places.LaneConfig(start_tile=(13, 19), end_tile=(15, 19)),
        2: places.LaneConfig(start_tile=(13, 18), end_tile=(15, 18)),
        3: places.LaneConfig(start_tile=(24, 19), end_tile=(27, 19)),
        4: places.LaneConfig(start_tile=(24, 18), end_tile=(27, 18)),
        5: places.LaneConfig(start_tile=(20, 24), end_tile=(20, 29)),
        6: places.LaneConfig(start_tile=(21, 24), end_tile=(21, 29)),
        7: places.LaneConfig(start_tile=(19, 15), end_tile=(19, 12)),
        8: places.LaneConfig(start_tile=(18, 15), end_tile=(18, 12)),
        9: places.LaneConfig(start_tile=(15, 20), end_tile=(12, 20)),
        10: places.LaneConfig(start_tile=(15, 21), end_tile=(12, 21)),
        11: places.LaneConfig(start_tile=(27, 20), end_tile=(24, 20)),
        12: places.LaneConfig(start_tile=(27, 21), end_tile=(24, 21)),
        13: places.LaneConfig(start_tile=(18, 29), end_tile=(18, 24)),
        14: places.LaneConfig(start_tile=(19, 29), end_tile=(19, 24)),
        15: places.LaneConfig(start_tile=(20, 12), end_tile=(20, 15)),
        16: places.LaneConfig(start_tile=(21, 12), end_tile=(21, 15)),
    }
    missing = dict(closed)
    del missing[2]
    places.set_route_hints([])
    world.rebuild_world(place_rects_from_places(places_by_id), intersections, missing)
    assert overlay_type_for_intersection("hub", frozenset({"N", "S", "E", "W"})) == (
        places.INTERSECTION_TYPE_CROSS
    )

    shifted = dict(closed)
    shifted[1] = places.LaneConfig(start_tile=(13, 17), end_tile=(15, 17))
    world.rebuild_world(place_rects_from_places(places_by_id), intersections, shifted)
    assert overlay_type_for_intersection("hub", frozenset({"N", "S", "E", "W"})) == (
        places.INTERSECTION_TYPE_CROSS
    )
    GameState()


def test_twin_elsewhere_does_not_make_mixed_cross() -> None:
    """A 4-way of singles stays Normal Cross even if a leg is a twin-start further up the road."""
    from render.intersection_topology import (
        classify_intersection_sides,
        overlay_type_for_intersection,
        overlay_type_for_sides,
    )

    places_by_id = {
        "West": places.Place(center_x=4, center_y=20, width=5, length=5),
        "East": places.Place(center_x=36, center_y=20, width=5, length=5),
        "North": places.Place(center_x=20, center_y=40, width=5, length=5),
        "South": places.Place(center_x=20, center_y=4, width=5, length=5),
    }
    intersections = {
        "hub": places.IntersectionConfig(size_cells=4, center_x=20, center_y=20),
    }
    lanes = {
        1: places.LaneConfig(start_tile=(7, 19), end_tile=(17, 19)),
        2: places.LaneConfig(start_tile=(17, 20), end_tile=(7, 20)),
        3: places.LaneConfig(start_tile=(33, 20), end_tile=(22, 20)),
        4: places.LaneConfig(start_tile=(22, 19), end_tile=(33, 19)),
        5: places.LaneConfig(start_tile=(20, 22), end_tile=(20, 37)),
        6: places.LaneConfig(start_tile=(19, 37), end_tile=(19, 22)),
        7: places.LaneConfig(start_tile=(20, 17), end_tile=(20, 7)),
        8: places.LaneConfig(start_tile=(19, 7), end_tile=(19, 17)),
        9: places.LaneConfig(start_tile=(18, 37), end_tile=(18, 30)),
    }
    places.set_route_hints([])
    world.rebuild_world(place_rects_from_places(places_by_id), intersections, lanes)
    assert world.sister_relation(6, 9) == world.SISTER_TWIN_START
    cells = world.get_intersection_cells_by_key("hub")
    active, _, _ = classify_intersection_sides("hub", cells, require_centre_two=False)
    assert overlay_type_for_sides(active) == places.INTERSECTION_TYPE_CROSS
    assert not world.intersection_has_twins("hub")
    assert overlay_type_for_intersection("hub", active) == places.INTERSECTION_TYPE_CROSS
    GameState()


def _has_color_near(img, x0: int, y0: int, rgb: tuple[int, int, int], r: int = 6) -> bool:
    w, h = img.size
    for y in range(max(0, y0 - r), min(h, y0 + r + 1)):
        for x in range(max(0, x0 - r), min(w, x0 + r + 1)):
            p = img.getpixel((x, y))
            if p[:3] == rgb and p[3]:
                return True
    return False


def test_double_stamp_shoulder_not_travel_bundle() -> None:
    """8-cell Double fillets the 2-cell shoulder; curb is grey outline then white inset."""
    from render.corner_gen import ROAD_GREY, WHITE, double_fillet_inner_r, make_double
    from render.lane_paint import CURB_INSET, CURB_WIDTH
    from sim.constants import ORTHO_TILE_SIZE

    img = make_double(8)
    w, h = img.size
    assert (w, h) == (8 * ORTHO_TILE_SIZE, 8 * ORTHO_TILE_SIZE)
    for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        assert img.getpixel((x, y))[3] == 0
    centre = img.getpixel((w // 2, h // 2))
    assert centre[3] == 255 and centre[:3] == ROAD_GREY

    inner_r = double_fillet_inner_r(8)
    assert inner_r == 2 * ORTHO_TILE_SIZE
    # q3 TL: pieslice punch includes r, so grey/white sit just outside it.
    g0 = img.getpixel((inner_r + 1, 1))
    g1 = img.getpixel((inner_r + CURB_INSET, 1))
    w0 = img.getpixel((inner_r + CURB_INSET + 1, 1))
    w1 = img.getpixel((inner_r + CURB_INSET + CURB_WIDTH, 1))
    assert g0[:3] == ROAD_GREY and g0[3] == 255
    assert g1[:3] == ROAD_GREY and g1[3] == 255
    assert w0[:3] == WHITE and w0[3]
    assert w1[:3] == WHITE and w1[3]

    travel0 = inner_r + CURB_INSET + CURB_WIDTH + 1
    travel1 = 6 * ORTHO_TILE_SIZE
    for y in range(travel0 + 4, travel1 - 4):
        for x in range(travel0 + 4, travel1 - 4):
            p = img.getpixel((x, y))
            assert p[:3] != WHITE, (x, y)
            assert p[:3] == ROAD_GREY and p[3] == 255


def _mixed_ew_twins() -> None:
    """8-wide hub: twin mouths on E/W, single mouths on N/S."""
    places_by_id = {
        "West": places.Place(center_x=10, center_y=19, width=5, length=5),
        "East": places.Place(center_x=30, center_y=19, width=5, length=5),
        "North": places.Place(center_x=20, center_y=32, width=5, length=5),
        "South": places.Place(center_x=20, center_y=8, width=5, length=5),
    }
    intersections = {
        "hub": places.IntersectionConfig(size_cells=8, center_x=20, center_y=20),
    }
    lanes = {
        1: places.LaneConfig(start_tile=(13, 19), end_tile=(15, 19)),
        2: places.LaneConfig(start_tile=(13, 18), end_tile=(15, 18)),
        3: places.LaneConfig(start_tile=(24, 19), end_tile=(27, 19)),
        4: places.LaneConfig(start_tile=(24, 18), end_tile=(27, 18)),
        5: places.LaneConfig(start_tile=(19, 24), end_tile=(19, 29)),
        7: places.LaneConfig(start_tile=(19, 15), end_tile=(19, 12)),
    }
    places.set_route_hints([])
    world.rebuild_world(place_rects_from_places(places_by_id), intersections, lanes)


def _mixed_paint(family: str | None = None):
    from render.corner_gen import make_mixed
    from render.intersection_topology import (
        classify_intersection_sides,
        mixed_corner_leftovers,
        mouth_spans_by_edge,
        mouth_spans_local,
        overlay_type_for_sides,
    )

    cells = world.get_intersection_cells_by_key("hub")
    active, _, _ = classify_intersection_sides("hub", cells, require_centre_two=False)
    spans = mouth_spans_by_edge("hub", cells)
    leftovers = mixed_corner_leftovers(cells, spans, active)
    local = mouth_spans_local(cells, spans)
    fam = family if family is not None else overlay_type_for_sides(active)
    img = make_mixed(8, leftovers, family=fam, spans=local, intersection_key="hub")
    return img, leftovers, local, active, fam


def test_mixed_stamp_min_leftover_and_virtual_curb() -> None:
    """One-way 8-cell E/W twins: NW leftover box is (lx, ly) at BL; left curb is yellow."""
    from render.corner_gen import ROAD_GREY, WHITE, YELLOW
    from render.intersection_topology import overlay_type_for_intersection
    from render.lane_paint import CURB_INSET, CURB_WIDTH
    from sim.constants import ORTHO_TILE_SIZE

    _mixed_ew_twins()
    cells = world.get_intersection_cells_by_key("hub")
    img, leftovers, _local, active, family = _mixed_paint()
    assert overlay_type_for_intersection("hub", active) == places.INTERSECTION_TYPE_CROSS
    assert family == "cross"
    by_q = {q: (lx, ly) for q, lx, ly in leftovers}
    assert 0 in by_q
    lx, ly = by_q[0]
    assert lx != ly
    t = ORTHO_TILE_SIZE
    size = 8 * t
    dx, dy = ly * t, lx * t
    # AABB remainder is grass; the r×r bite sits at the mouths, not the AABB.
    assert img.getpixel((1, size - 2))[3] == 0
    r_px = min(dx, dy)
    if dy > dx:
        extra_y = size - dy + r_px + max(1, (dy - r_px) // 2)
        assert img.getpixel((max(1, dx - r_px // 2), extra_y))[3] == 0
    else:
        extra_x = max(1, (dx - r_px) // 2)
        assert img.getpixel((min(size - 2, extra_x), size - 2))[3] == 0
    east_of = img.getpixel((min(size - 1, dx + 8), size - 2))
    assert east_of[3] == 255, "leftover wider than image dx (ns shoulder)"
    south_of = img.getpixel((size // 2, max(0, size - dy - 8)))
    assert south_of[3] == 255, "leftover taller than image dy (ew shoulder)"
    # Inner leftover is plaza, not a punched rectangle (that pinched the roads into an X).
    inner = img.getpixel((min(size - 1, dx + 4), max(0, size - dy - 4)))
    assert inner[3] == 255 and inner[:3] == ROAD_GREY

    y_s = size - dy
    r_px = min(dx, dy)
    if dy >= dx:
        # Straight curb is the longer (vertical) leftover; yellow inset, driver's left.
        sample_y = min(size - 2, size - dy + r_px + max(4, (dy - r_px) // 2))
        white_x = dx + CURB_INSET + CURB_WIDTH // 2
        assert _has_color_near(img, white_x, sample_y, YELLOW, r=3)
        sharp = img.getpixel((dx, sample_y))
    else:
        sample_x = max(2, (dx - r_px) // 2)
        white_y = y_s - CURB_INSET - CURB_WIDTH // 2
        assert _has_color_near(img, sample_x, white_y, YELLOW, r=3)
        sharp = img.getpixel((sample_x, min(size - 1, y_s)))
    assert sharp[:3] != WHITE
    GameState()


def _mixed_tee_no_south() -> None:
    """Same hub as E/W twins, but no south mouth."""
    places_by_id = {
        "West": places.Place(center_x=10, center_y=19, width=5, length=5),
        "East": places.Place(center_x=30, center_y=19, width=5, length=5),
        "North": places.Place(center_x=20, center_y=32, width=5, length=5),
    }
    intersections = {
        "hub": places.IntersectionConfig(size_cells=8, center_x=20, center_y=20),
    }
    lanes = {
        1: places.LaneConfig(start_tile=(13, 19), end_tile=(15, 19)),
        2: places.LaneConfig(start_tile=(13, 18), end_tile=(15, 18)),
        3: places.LaneConfig(start_tile=(24, 19), end_tile=(27, 19)),
        4: places.LaneConfig(start_tile=(24, 18), end_tile=(27, 18)),
        5: places.LaneConfig(start_tile=(19, 24), end_tile=(19, 29)),
    }
    places.set_route_hints([])
    world.rebuild_world(place_rects_from_places(places_by_id), intersections, lanes)


def test_mixed_tee_open_face_from_mouth_span() -> None:
    """One-way tee punches the open cardinal. That right curb stays white; the left is yellow."""
    from render.corner_gen import ROAD_GREY, WHITE, YELLOW, _image_span_px, _union_span
    from render.intersection_topology import overlay_type_for_intersection, overlay_type_for_sides
    from render.lane_paint import CURB_INSET
    from sim.constants import ORTHO_TILE_SIZE

    _mixed_tee_no_south()
    img, _leftovers, local, active, family = _mixed_paint()
    assert overlay_type_for_sides(active) == "tee"
    assert overlay_type_for_intersection("hub", active) == places.INTERSECTION_TYPE_TEE
    assert family == "tee"
    assert "S" not in local
    t = ORTHO_TILE_SIZE
    size = 8 * t
    # Open south is image right (make_tee / iso); through is E/W.
    ylo, _yhi = local["W"]
    assert img.getpixel((size - 4, size // 2))[3] == 0
    through_mid_y = ylo * t + t // 2
    plaza = img.getpixel((size // 2, through_mid_y))
    assert plaza[3] == 255 and plaza[:3] == ROAD_GREY
    _x0, x1 = _image_span_px(_union_span(local["E"], local["W"]), 8)
    assert img.getpixel((x1 - CURB_INSET - 1, size // 2))[:3] == WHITE
    w, h = img.size
    assert any(img.getpixel((x, y))[:3] == YELLOW for y in range(0, h, 4) for x in range(0, w, 4))
    GameState()


def _mixed_corner_wn() -> None:
    """W+N mouths only."""
    places_by_id = {
        "West": places.Place(center_x=10, center_y=19, width=5, length=5),
        "North": places.Place(center_x=20, center_y=32, width=5, length=5),
    }
    intersections = {
        "hub": places.IntersectionConfig(size_cells=8, center_x=20, center_y=20),
    }
    lanes = {
        1: places.LaneConfig(start_tile=(13, 19), end_tile=(15, 19)),
        2: places.LaneConfig(start_tile=(13, 18), end_tile=(15, 18)),
        5: places.LaneConfig(start_tile=(19, 24), end_tile=(19, 29)),
    }
    places.set_route_hints([])
    world.rebuild_world(place_rects_from_places(places_by_id), intersections, lanes)


def test_mixed_corner_is_mouth_L_not_scaled_pie() -> None:
    """One-way corner pavement is an L of the two mouth bands, with one inner fillet."""
    from render.corner_gen import ROAD_GREY, YELLOW, _image_span_px
    from render.intersection_topology import overlay_type_for_intersection, overlay_type_for_sides
    from sim.constants import ORTHO_TILE_SIZE

    _mixed_corner_wn()
    img, leftovers, local, active, family = _mixed_paint()
    assert overlay_type_for_sides(active) == "corner"
    assert overlay_type_for_intersection("hub", active) == places.INTERSECTION_TYPE_CORNER
    assert family == "corner"
    assert frozenset(local) == frozenset({"W", "N"})
    t = ORTHO_TILE_SIZE
    size = 8 * t
    n = 8
    # Open SE of the image stays clear — not a plaza or scaled pie.
    assert img.getpixel((size - 4, 4))[3] == 0
    assert img.getpixel((size - 4, size // 2))[3] == 0
    wx0, wx1 = _image_span_px(local["W"], n)
    ny0, ny1 = _image_span_px(local["N"], n)
    meet = img.getpixel(((wx0 + wx1) // 2, (ny0 + ny1) // 2))
    assert meet[3] == 255 and meet[:3] == ROAD_GREY
    # South of the W-mouth and east of the N-mouth is grass.
    assert img.getpixel((min(size - 1, wx1 + 8), max(0, ny0 - 8)))[3] == 0
    assert leftovers and leftovers[0][0] == 0
    dx, dy = leftovers[0][2] * t, leftovers[0][1] * t
    r_px = min(dx, dy)
    join = img.getpixel((dx - 4, size - dy + 4))
    assert join[3] == 255 and join[:3] == ROAD_GREY
    assert _has_color_near(img, dx - 4, size - 4, YELLOW, r=8)
    GameState()


def test_mixed_corner_ns_double_ew_single_on_stamp_axes() -> None:
    """Size-6 W+N mixed corner: 4-cell N/S, 2-cell E/W — leftover extra is beside the single."""
    from render.corner_gen import ROAD_GREY, WHITE, _image_span_px, make_mixed
    from render.intersection_topology import corner_leftovers_from_local
    from render.lane_paint import CURB_INSET, CURB_WIDTH
    from sim.constants import ORTHO_TILE_SIZE

    n = 6
    spans = {"N": (1, 4), "W": (2, 3)}
    leftovers = corner_leftovers_from_local(n, spans)
    img = make_mixed(n, leftovers, family="corner", spans=spans)
    assert leftovers and leftovers[0] == (0, 1, 2)
    t = ORTHO_TILE_SIZE
    size = n * t
    lx, ly = leftovers[0][1], leftovers[0][2]
    dx, dy = ly * t, lx * t
    r_px = min(dx, dy)
    wx0, wx1 = _image_span_px(spans["W"], n)
    ny0, ny1 = _image_span_px(spans["N"], n)

    extra_x = max(1, (dx - r_px) // 2)
    assert img.getpixel((extra_x, size - 2))[3] == 0
    ns_mid = img.getpixel(((wx0 + wx1) // 2, (ny0 + ny1) // 2))
    assert ns_mid[3] == 255 and ns_mid[:3] == ROAD_GREY
    # Extra strip must not bite the 4-cell N/S corridor (horizontal Y-band).
    assert img.getpixel((dx + 8, (ny0 + ny1) // 2))[3] == 255
    join = img.getpixel((dx - 4, size - dy + 4))
    assert join[3] == 255 and join[:3] == ROAD_GREY
    assert _has_color_near(img, dx - 4, size - 4, WHITE, r=8)
    y_s = size - dy
    white_y = y_s - CURB_INSET - CURB_WIDTH // 2
    assert _has_color_near(img, max(2, (dx - r_px) // 2), white_y, WHITE, r=3)
    west = img.getpixel(((wx0 + wx1) // 2, size - 2))
    assert west[3] == 255
    r_out = min(wx1 - wx0, ny1 - ny0)
    assert r_out > 0
    assert img.getpixel((wx1 - 2, ny0 + 2))[3] == 0
    pie = img.getpixel((wx1 - r_out + r_out // 2, ny0 + r_out - r_out // 2))
    assert pie[3] == 255 and pie[:3] == ROAD_GREY
    assert _has_color_near(
        img, wx1 - r_out + r_out - CURB_INSET - 1, ny0 + r_out, WHITE, r=8
    )
    assert _has_color_near(
        img, wx1 - CURB_INSET - CURB_WIDTH // 2, size - 2, WHITE, r=4
    )
    GameState()


def _double_tee_no_south() -> None:
    """Closed dual on W, E, and N: two pairs in and out, centred; no south face."""
    places_by_id = {
        "West": places.Place(center_x=10, center_y=19, width=5, length=5),
        "East": places.Place(center_x=30, center_y=19, width=5, length=5),
        "North": places.Place(center_x=20, center_y=32, width=5, length=5),
    }
    intersections = {
        "hub": places.IntersectionConfig(size_cells=8, center_x=20, center_y=20),
    }
    lanes = {
        1: places.LaneConfig(start_tile=(13, 19), end_tile=(15, 19)),
        2: places.LaneConfig(start_tile=(13, 18), end_tile=(15, 18)),
        3: places.LaneConfig(start_tile=(24, 19), end_tile=(27, 19)),
        4: places.LaneConfig(start_tile=(24, 18), end_tile=(27, 18)),
        5: places.LaneConfig(start_tile=(20, 24), end_tile=(20, 29)),
        6: places.LaneConfig(start_tile=(21, 24), end_tile=(21, 29)),
        9: places.LaneConfig(start_tile=(15, 20), end_tile=(12, 20)),
        10: places.LaneConfig(start_tile=(15, 21), end_tile=(12, 21)),
        11: places.LaneConfig(start_tile=(27, 20), end_tile=(24, 20)),
        12: places.LaneConfig(start_tile=(27, 21), end_tile=(24, 21)),
        13: places.LaneConfig(start_tile=(18, 29), end_tile=(18, 24)),
        14: places.LaneConfig(start_tile=(19, 29), end_tile=(19, 24)),
    }
    places.set_route_hints([])
    world.rebuild_world(place_rects_from_places(places_by_id), intersections, lanes)


def _double_corner_wn() -> None:
    """Closed dual on W and N only."""
    places_by_id = {
        "West": places.Place(center_x=10, center_y=19, width=5, length=5),
        "North": places.Place(center_x=20, center_y=32, width=5, length=5),
    }
    intersections = {
        "hub": places.IntersectionConfig(size_cells=8, center_x=20, center_y=20),
    }
    lanes = {
        1: places.LaneConfig(start_tile=(13, 19), end_tile=(15, 19)),
        2: places.LaneConfig(start_tile=(13, 18), end_tile=(15, 18)),
        5: places.LaneConfig(start_tile=(20, 24), end_tile=(20, 29)),
        6: places.LaneConfig(start_tile=(21, 24), end_tile=(21, 29)),
        9: places.LaneConfig(start_tile=(15, 20), end_tile=(12, 20)),
        10: places.LaneConfig(start_tile=(15, 21), end_tile=(12, 21)),
        13: places.LaneConfig(start_tile=(18, 29), end_tile=(18, 24)),
        14: places.LaneConfig(start_tile=(19, 29), end_tile=(19, 24)),
    }
    places.set_route_hints([])
    world.rebuild_world(place_rects_from_places(places_by_id), intersections, lanes)


def test_double_tee_classified_open_and_fillet() -> None:
    """3-way closed dual is Double Tee: open face clear, through grey, stem-corner curb white."""
    from render.corner_gen import ROAD_GREY, WHITE, double_fillet_inner_r, make_double_tee
    from render.intersection_topology import (
        classify_intersection_sides,
        overlay_type_for_intersection,
        overlay_type_for_sides,
        tee_layout_for_sides,
    )
    from render.lane_paint import CURB_INSET, CURB_WIDTH
    from sim.constants import ORTHO_TILE_SIZE

    _double_tee_no_south()
    cells = world.get_intersection_cells_by_key("hub")
    active, _, _ = classify_intersection_sides("hub", cells, require_centre_two=False)
    assert overlay_type_for_sides(active) == "tee"
    assert overlay_type_for_intersection("hub", active) == places.INTERSECTION_TYPE_TEE

    axis, stem = tee_layout_for_sides(active)
    img = make_double_tee(8, axis=axis, stem=stem, through_travel=4, stem_travel=4)
    t = ORTHO_TILE_SIZE
    size = 8 * t
    # Missing south, stem north, axis ew: open is image right.
    assert stem == "N" and axis == "ew"
    assert img.getpixel((size - 4, size // 2))[3] == 0
    through = img.getpixel((size // 2 + 8, size // 2))
    assert through[3] == 255 and through[:3] == ROAD_GREY
    inner_r = double_fillet_inner_r(8, 4)
    g0 = img.getpixel((inner_r + 1, 1))
    w0 = img.getpixel((inner_r + CURB_INSET + 1, 1))
    w1 = img.getpixel((inner_r + CURB_INSET + CURB_WIDTH, 1))
    assert g0[:3] == ROAD_GREY and g0[3] == 255
    assert w0[:3] == WHITE and w0[3]
    assert w1[:3] == WHITE and w1[3]
    # Through curb continues along the open face (image right), not only at the centre.
    x1 = 6 * t
    white_x = x1 - CURB_INSET - CURB_WIDTH // 2
    for y in (8, size // 2, size - 9):
        assert _has_color_near(img, white_x, y, WHITE, r=2), y
        assert img.getpixel((x1 - 1, y))[:3] == ROAD_GREY
    GameState()


def test_tee_open_face_curb_runs_across() -> None:
    """Through ROLE_CURB continues the full open face, not only the mouth middle."""
    from render.corner_gen import WHITE, make_double_tee
    from render.lane_paint import CURB_INSET, CURB_WIDTH
    from sim.constants import ORTHO_TILE_SIZE

    t = ORTHO_TILE_SIZE
    for cells in (4, 6, 8):
        img = make_double_tee(
            cells, axis="ew", stem="N", through_travel=4, stem_travel=4
        )
        size = cells * t
        travel = min(4, cells)
        lo = (cells - travel) // 2
        x1 = (lo + travel) * t
        white_x = x1 - CURB_INSET - CURB_WIDTH // 2
        for y in (8, size // 2, size - 9):
            assert _has_color_near(img, white_x, y, WHITE, r=2), (cells, y)


def test_double_corner_classified_is_L() -> None:
    """2-perp closed dual is Double Corner: equal-width annulus, not a full plaza."""
    from render.corner_gen import ROAD_GREY, WHITE, make_double_corner
    from render.intersection_topology import (
        classify_intersection_sides,
        corner_quadrant_for_sides,
        overlay_type_for_intersection,
        overlay_type_for_sides,
    )
    from sim.constants import ORTHO_TILE_SIZE

    _double_corner_wn()
    cells = world.get_intersection_cells_by_key("hub")
    active, _, _ = classify_intersection_sides("hub", cells, require_centre_two=False)
    assert overlay_type_for_sides(active) == "corner"
    assert overlay_type_for_intersection("hub", active) == places.INTERSECTION_TYPE_CORNER
    q = corner_quadrant_for_sides(active)
    assert q == 0
    img = make_double_corner(8, quadrant=q, travel_x=4, travel_y=4)
    t = ORTHO_TILE_SIZE
    size = 8 * t
    assert img.getpixel((size - 4, 4))[3] == 0
    meet = img.getpixel((size // 2, size // 2))
    assert meet[3] == 255 and meet[:3] == ROAD_GREY
    inner_r = 2 * t
    assert _has_color_near(img, inner_r + 3, size - 2, WHITE, r=8)
    outer_r = inner_r + 4 * t
    assert _has_color_near(img, 2, size - outer_r - 3, WHITE, r=8)
    GameState()


def test_leftover_zero_flush_double_is_opaque() -> None:
    """Flush travel (leftover 0) does not punch AABB-corner armpit fillets."""
    from render.corner_gen import ROAD_GREY, WHITE, double_fillet_inner_r, make_double
    from render.lane_paint import CURB_INSET, CURB_WIDTH

    assert double_fillet_inner_r(4, 4) == 0
    img = make_double(4, travel_cells=4)
    w, h = img.size
    for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        p = img.getpixel((x, y))
        assert p[3] == 255 and p[:3] == ROAD_GREY, (x, y, p)
    throat = CURB_INSET + CURB_WIDTH
    assert _has_color_near(img, throat // 2, h - throat // 2, WHITE, r=4)
    assert _has_color_near(img, throat // 2, throat // 2, WHITE, r=4)
    assert _has_color_near(img, w - throat // 2, h - throat // 2, WHITE, r=4)
    assert _has_color_near(img, w - throat // 2, throat // 2, WHITE, r=4)


def test_leftover_zero_mixed_flush_mouth_paints_throat_L() -> None:
    """Size-4 double+single: leftover (0, 1) still gets inner L along the flush face."""
    from render.corner_gen import WHITE, make_mixed
    from render.intersection_topology import corner_leftovers_from_local
    from render.lane_paint import CURB_INSET, CURB_WIDTH
    from sim.constants import ORTHO_TILE_SIZE

    n = 4
    spans = {"N": (0, 3), "W": (1, 2)}
    leftovers = corner_leftovers_from_local(n, spans)
    assert leftovers == ((0, 0, 1),)
    img = make_mixed(n, leftovers, family="corner", spans=spans)
    t = ORTHO_TILE_SIZE
    size = n * t
    dx = 1 * t
    white_y = size - CURB_INSET - CURB_WIDTH // 2
    assert _has_color_near(img, max(2, dx // 2), white_y, WHITE, r=3)
    assert _has_color_near(img, dx + CURB_INSET + 1, size - CURB_INSET - 1, WHITE, r=4)
    assert img.getpixel((0, size - 1))[3] == 255


def test_leftover_zero_three_lane_flush_paints_segment() -> None:
    """Size-6 3-lane flush vs 2-cell mouth: leftover (0, 2) curb along the extra."""
    from render.corner_gen import WHITE, make_mixed
    from render.intersection_topology import corner_leftovers_from_local
    from render.lane_paint import CURB_INSET, CURB_WIDTH
    from sim.constants import ORTHO_TILE_SIZE

    n = 6
    spans = {"N": (0, 5), "W": (2, 3)}
    leftovers = corner_leftovers_from_local(n, spans)
    assert leftovers == ((0, 0, 2),)
    img = make_mixed(n, leftovers, family="corner", spans=spans)
    t = ORTHO_TILE_SIZE
    size = n * t
    dx = 2 * t
    white_y = size - CURB_INSET - CURB_WIDTH // 2
    assert _has_color_near(img, max(2, dx // 2), white_y, WHITE, r=3)
    assert _has_color_near(img, dx + CURB_INSET + 1, size - CURB_INSET - 1, WHITE, r=4)
    assert img.getpixel((0, size - 1))[3] == 255


def test_leftover_zero_size2_one_lane_paints_throat_L() -> None:
    """2-cell AABB with a 1-cell mouth: leftover 0 on one axis still paints the L."""
    from render.corner_gen import WHITE, make_mixed
    from render.intersection_topology import corner_leftovers_from_local
    from render.lane_paint import CURB_INSET, CURB_WIDTH
    from sim.constants import ORTHO_TILE_SIZE

    n = 2
    spans = {"N": (0, 1), "W": (0, 0)}
    leftovers = corner_leftovers_from_local(n, spans)
    assert leftovers == ((0, 0, 1),)
    img = make_mixed(n, leftovers, family="corner", spans=spans)
    t = ORTHO_TILE_SIZE
    size = n * t
    dx = 1 * t
    white_y = size - CURB_INSET - CURB_WIDTH // 2
    assert _has_color_near(img, max(2, dx // 2), white_y, WHITE, r=3)
    assert _has_color_near(img, dx + CURB_INSET + 1, size - CURB_INSET - 1, WHITE, r=4)


def test_size2_one_asymmetric_uses_zero_throat_L() -> None:
    """Size-2 tee/cross leftover (1, 1) is a 0-throat L, not a one-cell inner fillet."""
    from render.corner_gen import ROAD_GREY, WHITE, make_mixed
    from render.intersection_topology import corner_leftovers_from_local
    from render.lane_paint import CURB_INSET
    from sim.constants import ORTHO_TILE_SIZE

    n = 2
    t = ORTHO_TILE_SIZE
    size = n * t
    join_x, join_y = t, size - t

    cross_spans = {"N": (1, 1), "S": (1, 1), "W": (0, 0), "E": (0, 0)}
    leftovers = corner_leftovers_from_local(n, cross_spans)
    assert (0, 1, 1) in leftovers
    img = make_mixed(n, leftovers, family="cross", spans=cross_spans)
    assert img.getpixel((1, size - 1))[3] == 0
    assert img.getpixel((t // 2, size - t // 2))[3] == 0
    meet = img.getpixel((size - 4, 4))
    assert meet[3] == 255 and meet[:3] == ROAD_GREY, meet
    assert _has_color_near(img, join_x + CURB_INSET + 1, join_y - CURB_INSET - 1, WHITE, r=6)

    tee_spans = {"N": (1, 1), "S": (1, 1), "W": (0, 0)}
    tee_left = corner_leftovers_from_local(n, tee_spans)
    assert (0, 1, 1) in tee_left
    tee = make_mixed(n, tee_left, family="tee", axis="ns", stem="W", spans=tee_spans)
    assert tee.getpixel((1, size - 1))[3] == 0
    assert tee.getpixel((t // 2, size - t // 2))[3] == 0
    assert _has_color_near(tee, t + CURB_INSET, size - t - CURB_INSET, WHITE, r=8)

    corner_spans = {"N": (1, 1), "W": (0, 0)}
    c_left = corner_leftovers_from_local(n, corner_spans)
    assert c_left == ((0, 1, 1),)
    corner = make_mixed(n, c_left, family="corner", spans=corner_spans)
    assert corner.getpixel((1, size - 1))[3] == 0


def test_through_width_chamfer_cross_tee_and_skip() -> None:
    """Chamfer needs leftover room; two-mouth corners keep fillet / 0-throat L."""
    from render.corner_gen import (
        ROAD_GREY,
        WHITE,
        _through_chamfer_specs,
        make_mixed,
    )
    from render.intersection_topology import corner_leftovers_from_local
    from sim.constants import ORTHO_TILE_SIZE

    def _centroid(tri: list[tuple[int, int]]) -> tuple[int, int]:
        xs = [p[0] for p in tri]
        ys = [p[1] for p in tri]
        return sum(xs) // len(xs), sum(ys) // len(ys)

    n = 6
    t = ORTHO_TILE_SIZE
    size = n * t

    def _clamp_xy(x: int, y: int) -> tuple[int, int]:
        return min(size - 1, max(0, x)), min(size - 1, max(0, y))

    # Inner leftover (both axes > 0): fillet, not chamfer.
    inner_spans = {"N": (1, 2), "S": (2, 2), "W": (1, 2), "E": (1, 2)}
    assert _through_chamfer_specs(n, inner_spans) == []
    inner_img = make_mixed(
        n,
        corner_leftovers_from_local(n, inner_spans),
        family="cross",
        spans=inner_spans,
    )
    leftover_plaza = inner_img.getpixel((size - t + 2, size - 2 * t + 2))
    assert leftover_plaza[3] == 255 and leftover_plaza[:3] == ROAD_GREY, leftover_plaza
    assert inner_img.getpixel((size - 2, size - 2))[3] == 0

    # Size-4 flush twins: leftover 0 on a perp axis, no D×D room.
    n4 = 4
    size4 = n4 * t
    flush4 = {"N": (0, 1), "S": (1, 1), "W": (0, 1), "E": (0, 1)}
    assert _through_chamfer_specs(n4, flush4) == []
    img4 = make_mixed(
        n4,
        corner_leftovers_from_local(n4, flush4),
        family="cross",
        spans=flush4,
    )
    meet4 = img4.getpixel((size4 // 2, size4 // 2))
    assert meet4[3] == 255 and meet4[:3] == ROAD_GREY, meet4

    # Four-way with a perp mouth occupies the corner even on size 6.
    occupied = {"N": (0, 1), "S": (1, 1), "W": (0, 1), "E": (0, 1)}
    assert _through_chamfer_specs(n, occupied) == []

    # Tee: chamfer the open through-side, not the stem leftover corner.
    tee_spans = {"N": (0, 1), "S": (1, 1), "E": (0, 1)}
    tee_specs = _through_chamfer_specs(n, tee_spans)
    assert len(tee_specs) == 1
    tee = make_mixed(
        n,
        corner_leftovers_from_local(n, tee_spans),
        family="tee",
        axis="ns",
        stem="E",
        spans=tee_spans,
    )
    tox, toy = _clamp_xy(*_centroid(tee_specs[0]["outer"]))
    assert tee.getpixel((tox, toy))[3] == 0
    tix, tiy = _clamp_xy(*_centroid(tee_specs[0]["inner"]))
    tp = tee.getpixel((tix, tiy))
    assert tp[3] == 255 and tp[:3] == ROAD_GREY, tp

    st_spans = {"N": (1, 2), "S": (2, 2)}
    st_specs = _through_chamfer_specs(n, st_spans)
    assert len(st_specs) == 1
    st = make_mixed(n, (), family="straight", spans=st_spans)
    sox, soy = _clamp_xy(*_centroid(st_specs[0]["outer"]))
    assert st.getpixel((sox, soy))[3] == 0
    six, siy = _clamp_xy(*_centroid(st_specs[0]["inner"]))
    sp = st.getpixel((six, siy))
    assert sp[3] == 255 and sp[:3] == ROAD_GREY, sp
    assert _has_color_near(
        st,
        (st_specs[0]["hyp0"][0] + st_specs[0]["hyp1"][0]) // 2,
        (st_specs[0]["hyp0"][1] + st_specs[0]["hyp1"][1]) // 2,
        WHITE,
        r=8,
    )

    corner_spans = {"N": (1, 2), "W": (0, 0)}
    assert _through_chamfer_specs(n, corner_spans) == []
    corner = make_mixed(
        n,
        corner_leftovers_from_local(n, corner_spans),
        family="corner",
        spans=corner_spans,
    )
    assert corner.getpixel((size - 2, 2))[3] == 0

    eq = {"N": (1, 2), "S": (1, 2), "E": (1, 2), "W": (1, 2)}
    assert _through_chamfer_specs(n, eq) == []


def test_one_stamp_family_and_clamp() -> None:
    assert places.overlay_stamp_family(places.INTERSECTION_TYPE_ONE_CROSS) == "cross"
    assert places.overlay_stamp_family(places.INTERSECTION_TYPE_ONE_TEE) == "tee"
    assert places.overlay_stamp_family(places.INTERSECTION_TYPE_ONE_CORNER) == "corner"
    assert places.overlay_stamp_family(places.INTERSECTION_TYPE_ONE_STRAIGHT) == "straight"
    assert places.overlay_stamp_family(places.INTERSECTION_TYPE_JOGGED_CROSS) == "cross"
    assert places.overlay_stamp_family(places.INTERSECTION_TYPE_JOGGED_TEE) == "tee"
    assert places.overlay_stamp_family(places.INTERSECTION_TYPE_JOGGED_CORNER) == "corner"
    assert places.clamp_intersection_type("jogged") == places.INTERSECTION_TYPE_CROSS
    assert places.overlay_stamp_family(places.INTERSECTION_TYPE_NORMAL_CROSS) == "cross"
    assert places.overlay_stamp_family(places.INTERSECTION_TYPE_NORMAL_CORNER) == "corner"


def test_one_lane_corner_classified_uses_mouth_span() -> None:
    """Single-lane W+N on a 6-cell AABB is One Corner, not the centred dual pie."""
    from render.corner_gen import ROAD_GREY, WHITE, make_mixed
    from render.intersection_topology import (
        classify_intersection_sides,
        mixed_corner_leftovers,
        mouth_spans_by_edge,
        mouth_spans_local,
        overlay_type_for_intersection,
        overlay_type_for_sides,
    )
    from render.lane_paint import CURB_INSET
    from sim.constants import ORTHO_TILE_SIZE

    places_by_id = {
        "West": places.Place(center_x=8, center_y=22, width=5, length=5),
        "North": places.Place(center_x=17, center_y=32, width=5, length=5),
    }
    intersections = {
        "hub": places.IntersectionConfig(size_cells=6, center_x=20, center_y=20),
    }
    lanes = {
        1: places.LaneConfig(start_tile=(10, 22), end_tile=(16, 22)),
        2: places.LaneConfig(start_tile=(17, 23), end_tile=(17, 29)),
    }
    places.set_route_hints([])
    world.rebuild_world(place_rects_from_places(places_by_id), intersections, lanes)
    cells = world.get_intersection_cells_by_key("hub")
    active, _, _ = classify_intersection_sides("hub", cells, require_centre_two=False)
    assert overlay_type_for_sides(active) == "corner"
    assert not world.intersection_has_twins("hub")
    assert overlay_type_for_intersection("hub", active) == places.INTERSECTION_TYPE_CORNER
    spans = mouth_spans_by_edge("hub", cells)
    local = mouth_spans_local(cells, spans)
    leftovers = mixed_corner_leftovers(cells, spans, active)
    img = make_mixed(6, leftovers, family="corner", spans=local)
    t = ORTHO_TILE_SIZE
    size = 6 * t
    assert img.getpixel((size - 4, 4))[3] == 0
    meet = img.getpixel((8, size - 8))
    assert meet[3] == 255 and meet[:3] == ROAD_GREY, meet
    assert _has_color_near(img, CURB_INSET + 1, size - CURB_INSET - 1, WHITE, r=6)
    GameState()


def test_one_lane_offset_fillet_at_mouth_not_aabb() -> None:
    """1-cell N flush west + 1-cell W at south: micro-fillet sits on the mouth join."""
    from render.corner_gen import WHITE, make_mixed
    from render.intersection_topology import corner_leftovers_from_local
    from render.lane_paint import CURB_INSET
    from sim.constants import ORTHO_TILE_SIZE

    n = 6
    spans = {"N": (0, 0), "W": (0, 0)}
    leftovers = corner_leftovers_from_local(n, spans)
    assert leftovers == ((0, 0, 5),)
    img = make_mixed(n, leftovers, family="corner", spans=spans)
    t = ORTHO_TILE_SIZE
    size = n * t
    dx = 5 * t
    assert img.getpixel((size // 2, size // 2))[3] == 0
    assert _has_color_near(img, dx + CURB_INSET + 1, size - CURB_INSET - 1, WHITE, r=6)
    assert img.getpixel((0, size - 1))[3] == 255


def test_one_equal_width_L_gets_exterior_fillet() -> None:
    """One-lane W+N, equal 1-cell mouths, unequal leftover: outer is square-then-turn."""
    from render.corner_gen import ROAD_GREY, WHITE, _image_span_px, make_mixed
    from render.intersection_topology import corner_leftovers_from_local
    from render.lane_paint import CURB_INSET
    from sim.constants import ORTHO_TILE_SIZE

    n = 6
    spans = {"N": (0, 0), "W": (2, 2)}
    leftovers = corner_leftovers_from_local(n, spans)
    assert leftovers == ((0, 0, 3),)
    img = make_mixed(n, leftovers, family="corner", spans=spans)
    t = ORTHO_TILE_SIZE
    wx0, wx1 = _image_span_px(spans["W"], n)
    ny0, ny1 = _image_span_px(spans["N"], n)
    r_out = min(wx1 - wx0, ny1 - ny0)
    assert r_out == t
    assert img.getpixel((wx1 - 2, ny0 + 2))[3] == 0
    pie = img.getpixel((wx1 - r_out + r_out // 2, ny0 + r_out - r_out // 2))
    assert pie[3] == 255 and pie[:3] == ROAD_GREY
    assert _has_color_near(
        img, wx1 - r_out + r_out - CURB_INSET - 1, ny0 + r_out, WHITE, r=8
    )
    strip = img.getpixel((t // 2, (ny0 + ny1) // 2))
    assert strip[3] == 255 and strip[:3] == ROAD_GREY


def test_tee_spandrel_is_pavement() -> None:
    """Leftover fillet fills the square-outside-arc; AABB corner stays grass."""
    from render.corner_gen import ROAD_GREY, make_double_tee
    from sim.constants import ORTHO_TILE_SIZE

    t = ORTHO_TILE_SIZE
    for cells, r in ((6, t), (8, 2 * t)):
        img = make_double_tee(
            cells, axis="ew", stem="N", through_travel=4, stem_travel=4
        )
        sx = sy = r - 4
        sp = img.getpixel((sx, sy))
        assert sp[3] == 255 and sp[:3] == ROAD_GREY, (cells, sx, sy, sp)
        assert img.getpixel((0, 0))[3] == 0
        assert img.getpixel((r + 4, 1))[3] == 255


def test_equal_width_corner_follows_pair_table() -> None:
    """q1 occupies image BR, q3 occupies TL — not the opposite L."""
    from render.corner_gen import make_double_corner

    img1 = make_double_corner(6, quadrant=1, travel_x=4, travel_y=4)
    w, h = img1.size
    assert img1.getpixel((w - 3, h // 2))[3] == 255
    assert img1.getpixel((w // 2, h - 3))[3] == 255
    assert img1.getpixel((2, h // 2))[3] == 0
    assert img1.getpixel((w // 2, 2))[3] == 0

    img3 = make_double_corner(6, quadrant=3, travel_x=4, travel_y=4)
    w, h = img3.size
    assert img3.getpixel((2, h // 2))[3] == 255
    assert img3.getpixel((w // 2, 2))[3] == 255
    assert img3.getpixel((w - 3, h // 2))[3] == 0
    assert img3.getpixel((w // 2, h - 3))[3] == 0


def test_size4_double_corner_has_outer_curb_no_inner_bite() -> None:
    from render.corner_gen import WHITE, make_double_corner
    from render.lane_paint import CURB_INSET, CURB_WIDTH

    img = make_double_corner(4, quadrant=0, travel_x=4, travel_y=4)
    w, h = img.size
    assert img.getpixel((0, h - 1))[3] == 255
    assert _has_color_near(img, 2, 1, WHITE, r=4)
    assert img.getpixel((w - 4, 4))[3] == 0
    throat = CURB_INSET + CURB_WIDTH
    assert _has_color_near(img, throat // 2, h - throat // 2, WHITE, r=4)


def test_mixed_leftover_quadrants_match_pair_table() -> None:
    from render.intersection_topology import corner_leftovers_from_local

    n = 8
    # E+N leftover at image TL (q3), not BR (q1).
    spans_ne = {"E": (2, 5), "N": (2, 5)}
    by_q = {q: (lx, ly) for q, lx, ly in corner_leftovers_from_local(n, spans_ne)}
    assert 3 in by_q and 1 not in by_q
    # W+S leftover at image BR (q1), not TL (q3).
    spans_sw = {"W": (2, 5), "S": (2, 5)}
    by_q = {q: (lx, ly) for q, lx, ly in corner_leftovers_from_local(n, spans_sw)}
    assert 1 in by_q and 3 not in by_q


def test_mixed_ne_leftover_punches_image_tl() -> None:
    from render.corner_gen import make_mixed
    from render.intersection_topology import corner_leftovers_from_local

    n = 8
    spans = {"N": (2, 5), "S": (2, 5), "E": (2, 5), "W": (2, 5)}
    leftovers = corner_leftovers_from_local(n, spans)
    img = make_mixed(n, leftovers, family="cross", spans=spans)
    t = 32
    size = n * t
    assert img.getpixel((1, 1))[3] == 0
    assert img.getpixel((size - 2, 1))[3] == 0
    assert img.getpixel((1, size - 2))[3] == 0
    assert img.getpixel((size - 2, size - 2))[3] == 0


def test_width6_centered_span_uses_one_cell_fillet() -> None:
    """Future triple width: leftover 1 on an 8-cell AABB, no new stamp type."""
    from render.corner_gen import double_fillet_inner_r, make_double
    from sim.constants import ORTHO_TILE_SIZE

    assert double_fillet_inner_r(8, 6) == ORTHO_TILE_SIZE
    img = make_double(8, travel_cells=6)
    assert img.getpixel((0, 0))[3] == 0
    r = ORTHO_TILE_SIZE
    sp = img.getpixel((r - 4, r - 4))
    assert sp[3] == 255


def test_sister_overlay_rects() -> None:
    """Half-cell mouths and the half-cell seam meet without overlapping."""
    from render.camera import grid_to_screen
    from render.selection import (
        grid_rect_screen_quad,
        mouth_half_rect,
        sister_seam_rect,
    )
    from sim.constants import TILE_H, TILE_W

    green = mouth_half_rect((65, 25), "N")
    red = mouth_half_rect((65, 67), "N", at_exit=True)
    assert green == (64.5, 24.5, 65.5, 25.0)
    assert red == (64.5, 67.0, 65.5, 67.5)
    # Southbound mouths take the other half of their cell.
    assert mouth_half_rect((62, 67), "S") == (61.5, 67.0, 62.5, 67.5)
    assert mouth_half_rect((62, 25), "S", at_exit=True) == (61.5, 24.5, 62.5, 25.0)
    assert mouth_half_rect((5, 11), "E") == (4.5, 10.5, 5.0, 11.5)
    assert mouth_half_rect((5, 5), "") is None

    seam = sister_seam_rect((65, 25), (65, 67), "N", 64)
    assert seam == (64.25, 25.0, 64.75, 67.0)
    # Blue starts where green ends and stops where red begins.
    assert seam[1] == green[3] and seam[3] == red[1]
    assert sister_seam_rect((5, 11), (35, 11), "E", 10) == (5.0, 10.25, 35.0, 10.75)

    bounds = (0, 0, 16, 16)

    def to_screen(gx: float, gy: float) -> tuple[float, float]:
        return grid_to_screen(gx, gy, 400.0, 300.0, *bounds, zoom_scale=1.0)

    # A full-cell rect is the same diamond the isolate tint already draws.
    quad = grid_rect_screen_quad((4.5, 4.5, 5.5, 5.5), to_screen)
    cx, cy = to_screen(5.0, 5.0)
    assert sorted(quad) == sorted(
        [(cx, cy + TILE_H), (cx + TILE_W, cy), (cx, cy - TILE_H), (cx - TILE_W, cy)]
    )


def test_lane_paint_roles_and_raster() -> None:
    from render.lane_paint import (
        PAVEMENT,
        ROLE_CURB,
        ROLE_ONCOMING,
        ROLE_SISTER,
        WHITE,
        YELLOW,
        lateral_roles,
        raster_lane_ortho,
        texture_phase,
    )

    places.set_route_hints([])
    lanes = {
        9: places.LaneConfig(start_tile=(64, 23), end_tile=(64, 70)),
        10: places.LaneConfig(start_tile=(63, 70), end_tile=(63, 23)),
        82: places.LaneConfig(start_tile=(65, 25), end_tile=(65, 67)),
        83: places.LaneConfig(start_tile=(62, 67), end_tile=(62, 25)),
    }
    world.rebuild_world({}, {}, lanes)
    assert world.lane_at_cell(64, 23) == 9
    assert lateral_roles("N", 64, 23) == {"W": ROLE_ONCOMING, "E": ROLE_CURB}
    assert lateral_roles("N", 64, 40) == {"W": ROLE_ONCOMING, "E": ROLE_SISTER}
    assert lateral_roles("N", 65, 40) == {"W": ROLE_SISTER, "E": ROLE_CURB}
    for gx, gy in world.get_lane_cells(82):
        roles = lateral_roles("N", gx, gy)
        assert ROLE_ONCOMING not in roles.values()

    img_s = raster_lane_ortho("N", ROLE_SISTER, ROLE_CURB, 0)
    assert img_s is not None
    assert img_s.getpixel((0, 31))[:3] == WHITE
    assert img_s.getpixel((0, 30))[:3] == PAVEMENT
    img_c = raster_lane_ortho("N", ROLE_CURB, ROLE_CURB, 0)
    assert img_c.getpixel((0, 31))[:3] == PAVEMENT
    assert img_c.getpixel((0, 30))[:3] == PAVEMENT
    assert img_c.getpixel((0, 28))[:3] == WHITE
    img_o = raster_lane_ortho("N", ROLE_ONCOMING, ROLE_CURB, 0)
    assert img_o.getpixel((0, 31))[:3] == PAVEMENT
    assert img_o.getpixel((0, 28))[:3] == YELLOW

    phase = texture_phase(ROLE_ONCOMING, ROLE_SISTER, 40)
    img9 = raster_lane_ortho("N", ROLE_ONCOMING, ROLE_SISTER, phase)
    img82 = raster_lane_ortho("N", ROLE_SISTER, ROLE_CURB, phase)
    for x in range(32):
        assert img9.getpixel((x, 0))[:3] == img82.getpixel((x, 31))[:3]
    GameState()


def test_lane_end_chamfer() -> None:
    """A sister mouth on open road tapers; a shared, lone, or hosted mouth stays square."""
    from render.lane_paint import (
        PAVEMENT,
        ROLE_CURB,
        ROLE_LEFT_CURB,
        ROLE_SISTER,
        WHITE,
        YELLOW,
        grass_at,
        paint_spec,
        raster_lane_ortho,
    )
    from render.tiles import _lane_paint_cache, generate_lane_paint_texture

    end = raster_lane_ortho("N", ROLE_SISTER, ROLE_CURB, 0, ("end", "E"))
    assert end is not None
    assert end.getpixel((0, 0)) == grass_at(0, 0)
    assert end.getpixel((28, 28))[:3] == PAVEMENT
    assert end.getpixel((8, 31))[:3] == WHITE
    assert _has_color_near(end, 19, 19, WHITE, r=4)

    start = raster_lane_ortho("N", ROLE_SISTER, ROLE_CURB, 0, ("start", "E"))
    assert start is not None
    assert start.getpixel((31, 0)) == grass_at(31, 0)
    assert start.getpixel((0, 31))[:3] == WHITE
    assert start.getpixel((4, 28))[:3] == PAVEMENT

    west = raster_lane_ortho("N", ROLE_LEFT_CURB, ROLE_SISTER, 0, ("end", "W"))
    assert west is not None
    assert west.getpixel((0, 31)) == grass_at(0, 31)
    assert _has_color_near(west, 18, 14, YELLOW, r=4)

    places.set_route_hints([])
    world.rebuild_world(
        {},
        {},
        {
            1: places.LaneConfig(start_tile=(10, 0), end_tile=(10, 20)),
            2: places.LaneConfig(start_tile=(11, 4), end_tile=(11, 16)),
            3: places.LaneConfig(start_tile=(9, 4), end_tile=(9, 16)),
            4: places.LaneConfig(start_tile=(20, 0), end_tile=(20, 10)),
            5: places.LaneConfig(start_tile=(21, 0), end_tile=(21, 10)),
            6: places.LaneConfig(start_tile=(30, 0), end_tile=(30, 10)),
            7: places.LaneConfig(start_tile=(40, 10), end_tile=(40, 0)),
            8: places.LaneConfig(start_tile=(41, 0), end_tile=(41, 10)),
            9: places.LaneConfig(start_tile=(60, 0), end_tile=(60, 20)),
            10: places.LaneConfig(start_tile=(61, 2), end_tile=(61, 8)),
            11: places.LaneConfig(start_tile=(61, 9), end_tile=(61, 14)),
        },
    )
    assert paint_spec("N", 11, 16)[4] == ("end", "E")
    assert paint_spec("N", 11, 4)[4] == ("start", "E")
    assert paint_spec("N", 11, 10)[4] is None
    assert paint_spec("N", 10, 20)[4] is None
    assert paint_spec("N", 9, 16)[4] == ("end", "W")
    assert paint_spec("N", 21, 10)[4] is None
    assert paint_spec("N", 30, 10)[4] is None
    assert paint_spec("N", 41, 10)[4] is None
    assert world.lane_daughter(10) == 11 and world.lane_mother(11) == 10
    assert paint_spec("N", 61, 8)[4] is None
    assert paint_spec("N", 61, 9)[4] is None
    assert paint_spec("N", 61, 2)[4] == ("start", "E")
    assert paint_spec("N", 61, 14)[4] == ("end", "E")

    world.rebuild_world(
        {},
        {"hub": places.IntersectionConfig(size_cells=4, center_x=11, center_y=16)},
        {
            1: places.LaneConfig(start_tile=(10, 0), end_tile=(10, 20)),
            2: places.LaneConfig(start_tile=(11, 4), end_tile=(11, 16)),
        },
    )
    assert world.get_intersection_at_cell((11, 16)) == "hub"
    assert paint_spec("N", 11, 16)[4] is None

    world.rebuild_world(
        {"Shed": {"x": 50, "y": 11, "w": 1, "h": 1}},
        {},
        {
            1: places.LaneConfig(start_tile=(49, 0), end_tile=(49, 20)),
            2: places.LaneConfig(start_tile=(50, 2), end_tile=(50, 10)),
        },
    )
    assert paint_spec("N", 50, 10)[4] is None

    tex = generate_lane_paint_texture("N", ROLE_SISTER, ROLE_CURB, 0, ("end", "E"))
    assert tex is not None
    assert ("N", ROLE_SISTER, ROLE_CURB, 0, ("end", "E")) in {
        k[:5] for k in _lane_paint_cache
    }
    GameState()


def test_path_cache_matches_live() -> None:
    from sim.paths import compute_path_position, path_length, path_position

    GameState()
    # 0 → 1 is straight through main; 0 → 5 is a turn toward Park.
    for in_lane, out_lane in ((0, 1), (0, 5)):
        for t in (0.0, 1.0):
            cached = path_position(in_lane, out_lane, t)
            live = compute_path_position(in_lane, out_lane, t)
            assert abs(cached[0] - live[0]) < 1e-9
            assert abs(cached[1] - live[1]) < 1e-9
        live_len = 0.0
        prev = compute_path_position(in_lane, out_lane, 0.0)
        for i in range(1, 33):
            p = compute_path_position(in_lane, out_lane, i / 32.0)
            live_len += ((p[0] - prev[0]) ** 2 + (p[1] - prev[1]) ** 2) ** 0.5
            prev = p
        assert abs(path_length(in_lane, out_lane) - live_len) < 1e-9


def test_occupancy_jam_and_lane_full() -> None:
    from sim.occupancy import Occupancy
    from sim.places import lane_is_full, spawn_lanes_for_place

    g = GameState()
    origin = g.spawn_places[0]
    lane = spawn_lanes_for_place(origin)[0]
    at_zero = [_make_test_car(lane_index=lane, position=0)]
    occ = Occupancy.from_cars(at_zero)
    assert lane_is_full(lane, occ)
    assert lane_is_full(lane, at_zero)

    main_cells = world.get_intersection_cells_by_key("main")
    path_cars = [_make_test_car(mode="path", cell=main_cells[0], vis="red")]
    occ_path = Occupancy.from_cars(path_cars)
    assert intersection_jam_score(occ_path, "main") == 1
    assert intersection_jam_score(path_cars, "main") == 1
    assert intersection_jam_score(occ_path, "bypass") == 0

    inbound = next(i for i in world.incoming_lanes("main"))
    lane_cells = world.get_lane_cells(inbound)
    tail = [_make_test_car(lane_index=inbound, position=len(lane_cells) - 1, vis="red")]
    assert intersection_jam_score(Occupancy.from_cars(tail), "main") == intersection_jam_score(tail, "main") == 1


def test_route_hinted_housing_park_via_bypass() -> None:
    from sim import routes

    GameState()
    places.set_route_hints([
        ("Housing", "Park", "bypass"),
        ("Park", "Housing", "bypass"),
    ])
    route = routes.plan_route("Housing", "Park")
    assert route is not None
    nodes = routes.format_route_nodes(route)
    assert nodes == "Housing > bypass > Park"
    assert "main" not in {s.ref for s in route if s.kind == "intersection"}


def test_route_housing_office_via_main() -> None:
    from sim import routes

    GameState()
    places.set_route_hints([
        ("Housing", "Park", "bypass"),
        ("Park", "Housing", "bypass"),
    ])
    assert "main" in world.best_next_hops("Housing", "Office")
    assert "bypass" not in world.best_next_hops("Housing", "Office")
    route = routes.plan_route("Housing", "Office")
    assert route is not None
    kinds = [s.kind for s in route]
    refs = [s.ref for s in route]
    assert "place" in kinds and "intersection" in kinds
    assert refs[0] == "Housing" and refs[-1] == "Office"


def _place_chain_world() -> None:
    places_by_id = {
        "Start": places.Place(center_x=2, center_y=10, width=3, length=3),
        "Hub": places.Place(center_x=14, center_y=10, width=3, length=3),
        "End": places.Place(center_x=26, center_y=10, width=3, length=3),
    }
    lanes = {
        1: places.LaneConfig(start_tile=(4, 10), end_tile=(12, 10)),
        2: places.LaneConfig(start_tile=(16, 10), end_tile=(24, 10)),
    }
    places.set_route_hints([])
    world.rebuild_world(place_rects_from_places(places_by_id), {}, lanes)


def test_route_intermediate_place_hop_or_despawn() -> None:
    from sim import routes
    from sim.movement import advance_car
    from sim.occupancy import Occupancy

    _place_chain_world()
    assert world.lane_traffic_in(1) == "Start" and world.lane_traffic_out(1) == "Hub"
    assert world.lane_traffic_in(2) == "Hub" and world.lane_traffic_out(2) == "End"

    route = routes.plan_route("Start", "End")
    assert route is not None
    assert routes.format_route_nodes(route) == "Start > Hub > End"
    inbound = routes.first_lane(route)
    idx = routes.first_lane_step_index(route)
    hop = routes.next_lane_after_place(route, idx)
    assert hop is not None
    next_lane, next_idx = hop
    cells = world.get_lane_cells(inbound)
    assert cells

    free = Car(
        origin="Start",
        destination="End",
        color=(220, 60, 60),
        base_speed_multiplier=1.0,
        lane_index=inbound,
        position_in_lane=len(cells) - 1,
        route=route,
        route_index=idx,
    )
    to_remove: list[Car] = []
    advance_car(free, 0.0, 10.0, to_remove, Occupancy())
    assert free not in to_remove
    assert free.lane_index == next_lane
    assert free.position_in_lane == 0
    assert free.route_index == next_idx
    assert free.motion_mode == "lane"

    packed_car = Car(
        origin="Start",
        destination="End",
        color=(220, 60, 60),
        base_speed_multiplier=1.0,
        lane_index=inbound,
        position_in_lane=len(cells) - 1,
        route=route,
        route_index=idx,
    )
    blocker = Car(
        origin="Hub",
        destination="End",
        color=(60, 140, 220),
        base_speed_multiplier=1.0,
        lane_index=next_lane,
        position_in_lane=0,
    )
    to_remove = []
    advance_car(packed_car, 0.0, 10.0, to_remove, Occupancy.from_cars([blocker]))
    assert packed_car in to_remove
    assert packed_car.lane_index == inbound
    assert packed_car.motion_mode != "place"
    GameState()


def test_route_destination_despawn() -> None:
    from sim import routes
    from sim.movement import advance_car

    GameState()
    route = routes.plan_route("Housing", "Park")
    assert route is not None
    last_lane = None
    last_idx = 0
    for i, step in enumerate(route):
        if step.kind == "lane":
            last_lane = int(step.ref)
            last_idx = i
    assert last_lane is not None
    cells = world.get_lane_cells(last_lane)
    car = Car(
        origin="Housing",
        destination="Park",
        color=(220, 60, 60),
        base_speed_multiplier=1.0,
        lane_index=last_lane,
        position_in_lane=len(cells) - 1,
        route=route,
        route_index=last_idx,
    )
    to_remove: list[Car] = []
    advance_car(car, 0.0, 10.0, to_remove)
    assert car in to_remove


def test_route_unreachable() -> None:
    from sim import routes

    GameState()
    assert routes.plan_route("Housing", "Atlantis") is None
    assert routes.plan_route("Housing", "Housing") is None


def test_route_spawn_full_first_lane_no_retry() -> None:
    from sim import routes
    from sim.cars import spawn_car

    GameState()
    real = routes.plan_route
    calls = {"n": 0}

    def wrapped(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    routes.plan_route = wrapped  # type: ignore[method-assign]
    try:
        planned = real("Housing", "Park")
        assert planned is not None
        first = routes.first_lane(planned)
        assert first is not None
        packed = [_make_test_car(lane_index=first, position=0)]
        calls["n"] = 0
        assert spawn_car("Housing", destination="Park", occupancy=packed) is None
        assert calls["n"] == 1
    finally:
        routes.plan_route = real  # type: ignore[method-assign]


def test_route_rename_retargets_place_steps() -> None:
    from sim.cars import spawn_car

    g = GameState()
    car = spawn_car("Housing", destination="Park")
    assert car is not None
    g.cars.append(car)
    assert g.rename_place("Housing", "Homes") == "Homes"
    assert car.origin == "Homes"
    assert any(s.kind == "place" and s.ref == "Homes" for s in car.route)
    assert all(s.ref != "Housing" for s in car.route if s.kind == "place")
    assert car in g.cars


def test_hint_via_exact_beats_dest_star() -> None:
    GameState()
    places.set_route_hints([
        ("Housing", "*", "*"),
        ("Housing", "Office", "bypass"),
        ("Housing", "Park", "bypass"),
    ])
    assert places._hint_via("Housing", "Office") == "bypass"
    assert places._hint_via("Housing", "Shopping") == "*"
    places.set_route_hints([
        ("Housing", "Park", "bypass"),
        ("Housing", "*", "*"),
    ])
    assert places._hint_via("Housing", "Park") == "bypass"
    assert places._hint_via("Housing", "Office") == "*"


def test_route_office_forced_via_bypass() -> None:
    from sim import routes

    GameState()
    places.set_route_hints([("Housing", "Office", "bypass")])
    route = routes.plan_route("Housing", "Office")
    assert route is not None
    assert routes.format_route_nodes(route) == "Housing > bypass > Park > main > Office"
    assert {s.ref for s in route if s.kind == "intersection"} == {"bypass", "main"}


def test_route_multi_mouth_slack_then_shortest() -> None:
    from sim import routes

    GameState()
    places.set_route_hints([])
    saw_main = False
    saw_bypass = False
    for _ in range(200):
        route = routes.plan_route("Housing", "Office")
        assert route is not None
        nodes = routes.format_route_nodes(route)
        if nodes == "Housing > main > Office":
            saw_main = True
            assert "bypass" not in {s.ref for s in route if s.kind == "intersection"}
        elif nodes == "Housing > bypass > Park > main > Office":
            saw_bypass = True
        else:
            raise AssertionError(f"unexpected slack walk {nodes}")
        if saw_main and saw_bypass:
            break
    assert saw_main and saw_bypass


def test_choose_next_lane_stays_greedy() -> None:
    GameState()
    places.set_route_hints([])
    for _ in range(20):
        lane = places.choose_next_lane_from_node("Housing", "Office")
        assert lane is not None
        assert world.lane_traffic_out(lane) == "main"


def _pose_lane_car(car: Car, dir_index_8: int = 0) -> None:
    cell = car.current_cell()
    assert cell is not None
    car.pose_gx = float(cell[0])
    car.pose_gy = float(cell[1])
    car.pose_dir_index_8 = dir_index_8
    car.speed_scale = 1.0
    car.visibility_state = "green"


def test_roll_observe_skills() -> None:
    from sim.awareness import OBSERVE_SKILLS, roll_observe_skills

    seen_k: set[int] = set()
    for _ in range(80):
        k, skills = roll_observe_skills()
        assert k in (0, 1, 2, 3)
        assert len(skills) == k
        assert len(set(skills)) == k
        assert set(skills) <= set(OBSERVE_SKILLS)
        seen_k.add(k)
    assert 0 in seen_k and 3 in seen_k


def test_observe_fan_red_still_wins() -> None:
    from sim.awareness import OBSERVE_SKILLS, apply_observe_skills
    from sim.occupancy import Occupancy
    from sim.visibility import build_poses, nearby_indices, rebuild_spatial_buckets_inplace

    GameState()
    follower = _make_test_car(lane_index=0, position=0)
    leader = _make_test_car(lane_index=0, position=1)
    follower.awareness = 3
    follower.observe_skills = OBSERVE_SKILLS
    leader.awareness = 3
    leader.observe_skills = OBSERVE_SKILLS
    _pose_lane_car(follower)
    _pose_lane_car(leader)
    cars_list = [follower, leader]
    poses = build_poses(cars_list)
    buckets: dict = {}
    rebuild_spatial_buckets_inplace(buckets, poses)
    nearby = lambda gx, gy: nearby_indices(gx, gy, buckets, 2)
    g = GameState()
    g.cars = cars_list
    g._apply_visibility(poses, nearby, 0.5)
    apply_observe_skills(cars_list, Occupancy.from_cars(cars_list), poses, nearby, 0.5)
    assert follower.visibility_state == "red"
    assert follower.speed_scale == 0.0


def test_observe_behind_speeds_up() -> None:
    from sim.awareness import apply_observe_skills
    from sim.occupancy import Occupancy
    from sim.visibility import build_poses, nearby_indices, rebuild_spatial_buckets_inplace

    GameState()
    follower = _make_test_car(lane_index=0, position=0)
    leader = _make_test_car(lane_index=0, position=1)
    leader.observe_skills = ("behind",)
    leader.awareness = 1
    _pose_lane_car(follower)
    _pose_lane_car(leader)
    cars_list = [follower, leader]
    poses = build_poses(cars_list)
    buckets: dict = {}
    rebuild_spatial_buckets_inplace(buckets, poses)
    nearby = lambda gx, gy: nearby_indices(gx, gy, buckets, 2)
    apply_observe_skills(cars_list, Occupancy.from_cars(cars_list), poses, nearby, 0.5)
    assert leader.speed_scale > 1.0
    assert leader.speed_scale <= 1.2


def test_observe_ahead_slows() -> None:
    from sim.awareness import apply_observe_skills
    from sim.occupancy import Occupancy
    from sim.visibility import build_poses, nearby_indices, rebuild_spatial_buckets_inplace

    GameState()
    cells = world.get_lane_cells(0)
    assert len(cells) > 6
    subject = _make_test_car(lane_index=0, position=0)
    blocker = _make_test_car(lane_index=0, position=5)
    subject.observe_skills = ("ahead",)
    subject.awareness = 1
    _pose_lane_car(subject)
    _pose_lane_car(blocker)
    cars_list = [subject, blocker]
    poses = build_poses(cars_list)
    buckets: dict = {}
    rebuild_spatial_buckets_inplace(buckets, poses)
    nearby = lambda gx, gy: nearby_indices(gx, gy, buckets, 2)
    apply_observe_skills(cars_list, Occupancy.from_cars(cars_list), poses, nearby, 0.5)
    assert subject.speed_scale == 0.7

    plain = _make_test_car(lane_index=0, position=0)
    _pose_lane_car(plain)
    cars2 = [plain, blocker]
    poses2 = build_poses(cars2)
    apply_observe_skills(cars2, Occupancy.from_cars(cars2), poses2, nearby, 0.5)
    assert plain.speed_scale == 1.0


def test_observe_side_slows_for_passer() -> None:
    from sim.awareness import apply_observe_skills
    from sim.occupancy import Occupancy
    from sim.visibility import build_poses, nearby_indices, rebuild_spatial_buckets_inplace

    places_by_id = {
        "Start": places.Place(center_x=2, center_y=10, width=3, length=3),
        "End": places.Place(center_x=14, center_y=10, width=3, length=3),
    }
    lanes = {
        1: places.LaneConfig(start_tile=(4, 10), end_tile=(12, 10)),
        2: places.LaneConfig(start_tile=(4, 11), end_tile=(12, 11)),
    }
    places.set_route_hints([])
    world.rebuild_world(place_rects_from_places(places_by_id), {}, lanes)
    assert world.sister_lane(1) == 2
    subject = _make_test_car(lane_index=1, position=5)
    passer = _make_test_car(lane_index=2, position=4)
    subject.observe_skills = ("side",)
    subject.awareness = 1
    _pose_lane_car(subject, dir_index_8=2)
    _pose_lane_car(passer, dir_index_8=2)
    cars_list = [subject, passer]
    poses = build_poses(cars_list)
    buckets: dict = {}
    rebuild_spatial_buckets_inplace(buckets, poses)
    nearby = lambda gx, gy: nearby_indices(gx, gy, buckets, 2)
    apply_observe_skills(cars_list, Occupancy.from_cars(cars_list), poses, nearby, 0.5)
    assert abs(subject.speed_scale - 0.85) < 1e-9

    lonely = _make_test_car(lane_index=1, position=5)
    lonely.observe_skills = ("side",)
    lonely.awareness = 1
    _pose_lane_car(lonely, dir_index_8=2)
    cars3 = [lonely]
    poses3 = build_poses(cars3)
    apply_observe_skills(cars3, Occupancy.from_cars(cars3), poses3, nearby, 0.5)
    assert lonely.speed_scale == 1.0
    GameState()


def test_situation_maneuver_labels() -> None:
    from sim.situation import classify_intersection_maneuver, classify_place

    tee_sides = frozenset({"N", "S", "E"})
    assert classify_intersection_maneuver("corner", frozenset({"N", "E"}), "N", "E") == "corner right"
    assert classify_intersection_maneuver("corner", frozenset({"N", "W"}), "N", "W") == "corner left"
    assert classify_intersection_maneuver("cross", frozenset({"N", "S", "E", "W"}), "N", "S") == "cross straight"
    assert classify_intersection_maneuver("cross", frozenset({"N", "S", "E", "W"}), "N", "E") == "cross right"
    assert classify_intersection_maneuver("cross", frozenset({"N", "S", "E", "W"}), "N", "W") == "cross left"
    assert classify_intersection_maneuver("tee", tee_sides, "N", "E") == "tee branch right"
    assert classify_intersection_maneuver("tee", tee_sides, "N", "S") == "tee straight"
    assert classify_intersection_maneuver("tee", tee_sides, "W", "N") == "tee straight right"
    assert classify_intersection_maneuver("tee", tee_sides, "W", "S") == "tee straight left"
    assert classify_intersection_maneuver("straight", frozenset({"N", "S"}), "N", "S") == "straight"
    assert classify_place("Office", "Office") == "place destination"
    assert classify_place("Park", "Office") == "place passthru"


def test_situation_lane_counts_and_next_feature_cars() -> None:
    from sim.occupancy import Occupancy
    from sim.situation import refresh_situations

    GameState()
    inbound = next(i for i in world.lane_ids() if world.lane_traffic_out(i) == "main")
    lane = world.get_lane_cells(inbound)
    assert len(lane) >= 3
    tail = _make_test_car(lane_index=inbound, position=0)
    mid = _make_test_car(lane_index=inbound, position=1)
    lead = _make_test_car(lane_index=inbound, position=2)
    main_cells = world.get_intersection_cells_by_key("main")
    box = _make_test_car(mode="path", cell=main_cells[0])
    cars_list = [tail, mid, lead, box]
    occ = Occupancy.from_cars(cars_list)
    refresh_situations(cars_list, occ)
    tin = world.lane_traffic_in(inbound)
    assert mid.on_feature == f"lane {inbound} {tin}->main"
    assert mid.cars_ahead == 1
    assert mid.cars_behind == 1
    assert mid.next_feature_cars is None
    assert lead.cars_ahead == 0
    assert lead.cars_behind == 2
    assert lead.next_feature_cars == 1
    assert tail.cars_ahead == 2
    assert tail.cars_behind == 0
    assert box.cars_ahead is None
    assert box.cars_behind is None
    assert box.next_feature_cars is None
    assert box.on_feature.startswith("intersection ")
    GameState()


def test_situation_sister_counts() -> None:
    from sim.occupancy import Occupancy
    from sim.situation import refresh_situations

    GameState()
    pair = next(
        ((i, world.sister_lane(i)) for i in world.lane_ids() if world.sister_lane(i) is not None),
        None,
    )
    if pair is None:
        lone = _make_test_car(lane_index=next(iter(world.lane_ids())), position=0)
        occ = Occupancy.from_cars([lone])
        refresh_situations([lone], occ)
        assert lone.sister_ahead is None
        assert lone.sister_behind is None
        GameState()
        return
    a, b = pair
    subject = _make_test_car(lane_index=a, position=2)
    sister_front = _make_test_car(lane_index=b, position=5)
    sister_back = _make_test_car(lane_index=b, position=0)
    cars_list = [subject, sister_front, sister_back]
    occ = Occupancy.from_cars(cars_list)
    refresh_situations(cars_list, occ)
    assert subject.sister_ahead == 1
    assert subject.sister_behind == 1
    GameState()


def test_situation_place_and_on_lane_from_route() -> None:
    from sim.occupancy import Occupancy
    from sim.routes import KIND_LANE, KIND_PLACE, RouteStep
    from sim.situation import refresh_situations

    GameState()
    lane_id = next(
        i
        for i in world.lane_ids()
        if world.lane_traffic_out(i) and not world.is_intersection(world.lane_traffic_out(i))
    )
    dest = world.lane_traffic_out(lane_id)
    car = _make_test_car(lane_index=lane_id, position=0)
    car.destination = dest
    car.route = (RouteStep(KIND_LANE, lane_id), RouteStep(KIND_PLACE, dest))
    car.route_index = 0
    refresh_situations([car], Occupancy.from_cars([car]))
    assert car.next_feature == "place destination"
    car.destination = dest + "_other"
    refresh_situations([car], Occupancy.from_cars([car]))
    assert car.next_feature == "place passthru"
    GameState()


def _sister_highway() -> None:
    """The four-lane pair east of the Park: 9/82 northbound, 10/83 southbound."""
    places.set_route_hints([])
    world.rebuild_world(
        {},
        {},
        {
            9: places.LaneConfig(start_tile=(64, 23), end_tile=(64, 70)),
            10: places.LaneConfig(start_tile=(63, 70), end_tile=(63, 23)),
            82: places.LaneConfig(start_tile=(65, 25), end_tile=(65, 67)),
            83: places.LaneConfig(start_tile=(62, 67), end_tile=(62, 25)),
        },
    )


def test_merge_target_geometry() -> None:
    _sister_highway()
    assert world.lane_pos_at_cell(65, 41) == (82, 16)
    assert world.lane_pos_at_cell(64, 23) == (9, 0)
    assert world.lane_pos_at_cell(1, 1) is None

    # Three cells of runway, one cell across, onto the neighbour lane.
    assert world.merge_target(9, 15, world.MERGE_RIGHT, 3) == (82, 16)
    assert world.merge_target(82, 16, world.MERGE_LEFT, 3) == (9, 21)
    # Southbound sisters sit at lower x, so the sides flip with the heading.
    assert world.merge_target(10, 15, world.MERGE_RIGHT, 3) == (83, 15)
    assert world.merge_target(83, 15, world.MERGE_LEFT, 3) == (10, 21)
    # Nothing on that side, and "neither" is not a side.
    assert world.merge_target(9, 15, world.MERGE_LEFT, 3) is None
    assert world.merge_target(9, 15, world.MERGE_NEITHER, 3) is None
    # The little sister's last cell still reaches its big sister.
    last_82 = len(world.get_lane_cells(82)) - 1
    assert world.merge_target(82, last_82, world.MERGE_LEFT, 3) == (9, 47)
    # Past the little sister's end there is nowhere to land.
    assert world.merge_target(9, 46, world.MERGE_RIGHT, 3) is None
    # Crossing the yellow is not a merge.
    world.rebuild_world(
        {},
        {},
        {
            1: places.LaneConfig(start_tile=(0, 10), end_tile=(0, 20)),
            2: places.LaneConfig(start_tile=(1, 20), end_tile=(1, 10)),
        },
    )
    assert world.merge_target(1, 4, world.MERGE_RIGHT, 3) is None
    assert world.merge_target(1, 4, world.MERGE_LEFT, 3) is None
    GameState()


def test_merge_curve_is_a_smooth_s() -> None:
    from sim.paths import merge_length, merge_position, merge_tangent

    _sister_highway()
    assert world.merge_target(9, 15, world.MERGE_RIGHT, 3) == (82, 16)
    assert merge_position(9, 15, 82, 16, 0.0) == (64.0, 38.0)
    assert merge_position(9, 15, 82, 16, 1.0) == (65.0, 41.0)

    # Dead ahead at both lanes: no lateral velocity where the car sits in a lane.
    for t in (0.0, 1.0):
        dx, dy = merge_tangent(9, 15, 82, 16, t)
        assert abs(dx) < 1e-6
        assert abs(dy - 1.0) < 1e-6

    prev_x, prev_y = -1.0, -1.0
    for i in range(21):
        t = i / 20.0
        gx, gy = merge_position(9, 15, 82, 16, t)
        assert gx >= prev_x - 1e-9
        assert gy >= prev_y - 1e-9
        prev_x, prev_y = gx, gy
        _dx, dy = merge_tangent(9, 15, 82, 16, t)
        assert dy >= 0.7  # never swings past 45 degrees off the lane heading

    length = merge_length(9, 15, 82, 16)
    assert 3.0 <= length <= 3.4  # barely longer than the straight three cells
    short = world.merge_target(9, 15, world.MERGE_RIGHT, 2)
    assert merge_length(9, 15, short[0], short[1]) < length
    GameState()


def test_keep_right_onto_little_sister() -> None:
    from sim import passing
    from sim.occupancy import Occupancy

    _sister_highway()
    car = _make_test_car(lane_index=9, position=15)
    assert passing.merge_choice(car, Occupancy.from_cars([car])) == (
        82,
        16,
        world.MERGE_RIGHT,
        passing.REASON_KEEP,
    )

    # Before the little sister starts there is no merge to make.
    early = _make_test_car(lane_index=9, position=0)
    assert passing.merge_choice(early, Occupancy.from_cars([early])) is None

    # Nor where it would run out from under the car.
    late = _make_test_car(lane_index=9, position=len(world.get_lane_cells(9)) - 8)
    assert passing.merge_choice(late, Occupancy.from_cars([late])) is None

    # A car already on the right keeps it.
    settled = _make_test_car(lane_index=82, position=15)
    assert passing.merge_choice(settled, Occupancy.from_cars([settled])) is None

    # Traffic in the blind spot of the target lane holds the merge back.
    blind = _make_test_car(lane_index=82, position=12)
    keeper = _make_test_car(lane_index=9, position=15)
    assert passing.merge_choice(keeper, Occupancy.from_cars([keeper, blind])) is None
    GameState()


def test_pass_left_only_when_faster() -> None:
    from sim import passing
    from sim.occupancy import Occupancy

    _sister_highway()
    slow = _make_test_car(lane_index=82, position=20)
    slow.base_speed_multiplier = 0.8
    fast = _make_test_car(lane_index=82, position=18)
    fast.base_speed_multiplier = 1.2
    assert passing.merge_choice(fast, Occupancy.from_cars([slow, fast])) == (
        9,
        23,
        world.MERGE_LEFT,
        passing.REASON_PASS,
    )

    # No advantage, no point pulling out.
    same = _make_test_car(lane_index=82, position=18)
    same.base_speed_multiplier = 0.8
    assert passing.merge_choice(same, Occupancy.from_cars([slow, same])) is None

    # Too far ahead to have been caught up with.
    distant = _make_test_car(lane_index=82, position=30)
    distant.base_speed_multiplier = 0.8
    chaser = _make_test_car(lane_index=82, position=18)
    chaser.base_speed_multiplier = 1.2
    assert passing.merge_choice(chaser, Occupancy.from_cars([distant, chaser])) is None

    # The passing lane must be clear to use it.
    occupied = _make_test_car(lane_index=9, position=23)
    assert passing.merge_choice(fast, Occupancy.from_cars([slow, fast, occupied])) is None
    GameState()


def test_queue_slides_to_the_clearer_sister() -> None:
    from sim import passing
    from sim.occupancy import Occupancy

    _sister_highway()
    # Far enough along that keep-right has no runway, but the right sister is still there.
    lane = world.get_lane_cells(9)
    # Runway for keep-right is gone here; the right sister still has cells ahead.
    pos = 38
    assert pos < len(lane)
    car = _make_test_car(lane_index=9, position=pos)
    assert passing.merge_choice(car, Occupancy.from_cars([car])) is None

    stopped = _make_test_car(lane_index=9, position=pos + 2)
    stopped.speed_scale = 0.0
    choice = passing.merge_choice(car, Occupancy.from_cars([car, stopped]))
    assert choice is not None
    target_lane, _target_pos, side, reason = choice
    assert (target_lane, side, reason) == (82, world.MERGE_RIGHT, passing.REASON_QUEUE)

    # Moving traffic keeps its lane, however empty the sister is.
    moving = _make_test_car(lane_index=9, position=pos + 2)
    moving.speed_scale = 1.0
    assert passing.merge_choice(car, Occupancy.from_cars([car, moving])) is None

    # A sister with just as many cars ahead is no improvement.
    heading_y = lane[pos][1] + 6
    sister = world.get_lane_cells(82)
    sister_pos = next(i for i, cell in enumerate(sister) if cell[1] == heading_y)
    full = _make_test_car(lane_index=82, position=sister_pos)
    assert passing.merge_choice(car, Occupancy.from_cars([car, stopped, full])) is None
    GameState()


def test_forced_exit_and_who_takes_the_gap() -> None:
    from sim import passing
    from sim.occupancy import Occupancy

    _sister_highway()
    cells_82 = world.get_lane_cells(82)
    forced_pos = len(cells_82) - 1 - passing.MERGE_EXIT_LOOKAHEAD
    car = _make_test_car(lane_index=82, position=forced_pos)
    choice = passing.merge_choice(car, Occupancy.from_cars([car]))
    assert choice is not None
    target_lane, _target_pos, side, reason = choice
    assert (target_lane, side, reason) == (9, world.MERGE_LEFT, passing.REASON_EXIT)

    # One cell earlier the lane still has room, so nothing is forced.
    unhurried = _make_test_car(lane_index=82, position=forced_pos - 1)
    assert passing.merge_choice(unhurried, Occupancy.from_cars([unhurried])) is None

    # Whoever is ahead takes the gap: a car further along blocks the merge.
    merger = _make_test_car(lane_index=82, position=forced_pos)
    landing = world.merge_target(82, forced_pos, world.MERGE_LEFT, passing.MERGE_FORWARD_CELLS)
    ahead = _make_test_car(lane_index=9, position=landing[1])
    assert passing.merge_choice(merger, Occupancy.from_cars([merger, ahead])) is None

    # A car behind the merging one gives way, so the exit still goes ahead.
    behind = _make_test_car(lane_index=9, position=landing[1] - passing.MERGE_FORWARD_CELLS - 1)
    assert passing.merge_choice(merger, Occupancy.from_cars([merger, behind])) == (
        landing[0],
        landing[1],
        world.MERGE_LEFT,
        passing.REASON_EXIT,
    )

    # The same car behind would hold back a discretionary merge.
    keeper = _make_test_car(lane_index=9, position=15)
    tail = _make_test_car(lane_index=82, position=12)
    assert passing.merge_choice(keeper, Occupancy.from_cars([keeper, tail])) is None
    GameState()


def test_merge_drives_through_and_returns_to_lane_mode() -> None:
    import math

    from sim import movement
    from sim.movement import advance_car
    from sim.occupancy import Occupancy

    _sister_highway()
    car = _make_test_car(lane_index=9, position=14)
    occ = Occupancy.from_cars([car])
    to_remove: list = []
    speed = 10.0
    t = 0.0
    advance_car(car, t, speed, to_remove, occ)

    merged = False
    poses: list[tuple[float, float]] = []
    facings: set[int] = set()
    leans: list[float] = []
    merge_poses: list[tuple[float, float]] = []
    for _ in range(400):
        t += 1.0 / 60.0
        advance_car(car, t, speed, to_remove, occ)
        if car.pose_gx is not None and car.pose_gy is not None:
            poses.append((car.pose_gx, car.pose_gy))
        if car.motion_mode == "merge":
            merged = True
            facings.add(car.pose_dir_index_8)
            leans.append(car.pose_lean_deg)
            if car.pose_gx is not None and car.pose_gy is not None:
                merge_poses.append((car.pose_gx, car.pose_gy))
            assert car.merge_source_lane == 9
            assert car.lane_index == 82  # committed to the landing cell at once
            assert car.merge_side == world.MERGE_RIGHT
        if merged and car.motion_mode == "lane" and car.lane_index == 82:
            break

    assert merged
    assert not to_remove
    assert car.motion_mode == "lane"
    assert car.lane_index == 82
    assert car.merge_source_lane is None
    assert car.merge_side == ""
    # The pose never jumps: one cell per step at most, and it crosses the seam.
    assert len(poses) > 3
    assert max(
        max(abs(b[0] - a[0]), abs(b[1] - a[1])) for a, b in zip(poses, poses[1:])
    ) < 1.0
    assert any(64.0 < gx < 65.0 for gx, _gy in poses)
    # The sprite keeps the lane's own texture and leans instead: the octant next
    # door is drawn bolt upright and would read as a 90 degree turn.
    assert facings == {0}
    # One lean, snapped on and held: no tween, and no wobble across the seam.
    assert set(leans) in ({movement.MERGE_LEAN_DEG}, {-movement.MERGE_LEAN_DEG})
    assert car.pose_lean_deg == 0.0  # and stands back up on the far side
    # Pace holds along the curve: the cubic's own parameter would coast the
    # middle of the change at little better than half speed.
    steps = [
        math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(merge_poses, merge_poses[1:])
    ]
    assert len(steps) > 6
    assert min(steps) > 0.95 * max(steps)
    GameState()


def test_dangling_lane_end_snaps_instead_of_despawning() -> None:
    from sim.movement import advance_car
    from sim.occupancy import Occupancy

    _sister_highway()
    # Sitting on the very last cell, past any chance to merge: the old code path
    # hopped through a place and despawned.
    car = _make_test_car(lane_index=82, position=len(world.get_lane_cells(82)) - 1)
    occ = Occupancy.from_cars([car])
    to_remove: list = []
    advance_car(car, 0.0, 10.0, to_remove, occ)
    assert not to_remove
    assert car.lane_index == 9
    assert car.motion_mode == "lane"
    GameState()


def test_merge_speed_floor_completes_the_change() -> None:
    from sim.passing import MERGE_MIN_SCALE, hold_merge_speed

    _sister_highway()
    merging = _make_test_car(lane_index=82, position=16)
    merging.motion_mode = "merge"
    merging.merge_source_lane = 9
    merging.merge_source_pos = 15
    merging.merge_side = world.MERGE_RIGHT
    merging.speed_scale = 0.0
    stopped = _make_test_car(lane_index=9, position=15)
    stopped.speed_scale = 0.0
    hold_merge_speed([merging, stopped])
    assert merging.speed_scale == MERGE_MIN_SCALE
    assert stopped.speed_scale == 0.0
    GameState()


def test_lane_and_node_mouth_cells() -> None:
    GameState()
    lane_ids = world.lane_ids()
    assert lane_ids
    for i in lane_ids:
        cells = world.get_lane_cells(i)
        start, end = world.lane_start_end_cells(i)
        assert start == cells[0]
        assert end == cells[-1]
    for place in world.get_place_rects():
        entrances, exits = world.node_entrance_exit_cells(place)
        for i in world.incoming_lanes(place):
            cells = world.get_lane_cells(i)
            assert cells[-1] in entrances
        for i in world.outgoing_lanes(place):
            cells = world.get_lane_cells(i)
            assert cells[0] in exits
    for key in world.get_intersection_keys():
        entrances, exits = world.node_entrance_exit_cells(key)
        for i in world.incoming_lanes(key):
            cells = world.get_lane_cells(i)
            if cells:
                assert cells[-1] in entrances
        for i in world.outgoing_lanes(key):
            cells = world.get_lane_cells(i)
            if cells:
                assert cells[0] in exits


def test_nearest_car_in_radius() -> None:
    from sim.cars import nearest_car_in_radius

    a = _make_test_car(0, 0)
    a.pose_gx, a.pose_gy = 10.0, 10.0
    b = _make_test_car(0, 1)
    b.pose_gx, b.pose_gy = 12.0, 10.0
    assert nearest_car_in_radius([a, b], 10.1, 10.0) is a
    assert nearest_car_in_radius([a, b], 11.7, 10.0) is b
    assert nearest_car_in_radius([a, b], 10.0, 12.0) is None
    assert nearest_car_in_radius([a, b], 10.0, 11.0) is a


def test_observed_cars_membership() -> None:
    from sim.awareness import observed_cars
    from sim.occupancy import Occupancy
    from sim.visibility import build_poses, nearby_indices, rebuild_spatial_buckets_inplace

    GameState()
    subject = _make_test_car(lane_index=0, position=0)
    fan_car = _make_test_car(lane_index=0, position=1)
    queue_car = _make_test_car(lane_index=0, position=5)
    stray = _make_test_car(lane_index=0, position=2)
    subject.pose_gx, subject.pose_gy, subject.pose_dir_index_8 = 5.0, 5.0, 0
    fan_car.pose_gx, fan_car.pose_gy, fan_car.pose_dir_index_8 = 5.0, 6.0, 0
    queue_car.pose_gx, queue_car.pose_gy, queue_car.pose_dir_index_8 = 20.0, 20.0, 0
    stray.pose_gx, stray.pose_gy, stray.pose_dir_index_8 = 0.0, 0.0, 0
    cars_list = [subject, fan_car, queue_car, stray]
    poses = build_poses(cars_list)
    buckets: dict = {}
    rebuild_spatial_buckets_inplace(buckets, poses)
    nearby = lambda gx, gy: nearby_indices(gx, gy, buckets, 2)
    occ = Occupancy.from_cars(cars_list)

    seen = observed_cars(subject, cars_list, occ, poses, nearby, 0.5)
    assert any(c is fan_car for c in seen)
    assert not any(c is queue_car for c in seen)
    assert not any(c is stray for c in seen)

    subject.observe_skills = ("ahead",)
    subject.awareness = 1
    seen = observed_cars(subject, cars_list, occ, poses, nearby, 0.5)
    assert any(c is fan_car for c in seen)
    assert any(c is queue_car for c in seen)

    subject.visibility_state = "red"
    subject.speed_scale = 0.0
    seen = observed_cars(subject, cars_list, occ, poses, nearby, 0.5)
    assert any(c is fan_car for c in seen)
    assert not any(c is queue_car for c in seen)

    subject.visibility_state = "green"
    subject.speed_scale = 1.0
    subject.observe_skills = ("behind",)
    tail = _make_test_car(lane_index=0, position=0)
    tail.pose_gx, tail.pose_gy, tail.pose_dir_index_8 = 5.0, 3.5, 0
    cars2 = [subject, tail]
    poses2 = build_poses(cars2)
    rebuild_spatial_buckets_inplace(buckets, poses2)
    occ2 = Occupancy.from_cars(cars2)
    seen = observed_cars(subject, cars2, occ2, poses2, nearby, 0.5)
    assert any(c is tail for c in seen)


def test_paint_thru_lines_normal_on_off() -> None:
    from render.corner_gen import WHITE, YELLOW, make_corner, make_tee

    tee_on = make_tee(4, axis="ns", stem="E", paint_thru_lines=True)
    tw, th = tee_on.size
    assert tee_on.getpixel((tw // 2, 60))[:3] == YELLOW
    assert tee_on.getpixel((tw // 2, 61))[:3] == YELLOW
    tee_off = make_tee(4, axis="ns", stem="E", paint_thru_lines=False)
    assert tee_off.getpixel((tw // 2, 60))[:3] != YELLOW
    assert _has_color_near(tee_off, 16, 16, WHITE, r=24)
    assert _has_color_near(tee_off, tw - 16, 16, WHITE, r=24)

    corner_on = make_corner(4, quadrant=0, paint_thru_lines=True)
    _cw, ch = corner_on.size
    assert _has_color_near(corner_on, 8, 60, YELLOW, r=6)
    yellow_run = 0
    best = 0
    for y in range(ch):
        p = corner_on.getpixel((0, y))
        if p[:3] == YELLOW and p[3]:
            yellow_run += 1
            best = max(best, yellow_run)
        else:
            yellow_run = 0
    assert best >= 2
    corner_off = make_corner(4, quadrant=0, paint_thru_lines=False)
    w, h = corner_off.size
    for y in range(0, h, 4):
        for x in range(0, w, 4):
            assert corner_off.getpixel((x, y))[:3] != YELLOW
    assert _has_color_near(corner_off, 16, ch - 16, WHITE, r=12)


def test_paint_thru_lines_one_skips() -> None:
    from render.corner_gen import YELLOW, make_mixed
    from render.intersection_topology import corner_leftovers_from_local

    n = 6
    spans = {"N": (0, 0), "W": (0, 0)}
    img = make_mixed(
        n,
        corner_leftovers_from_local(n, spans),
        family="corner",
        spans=spans,
        paint_thru_lines=True,
    )
    w, h = img.size
    for y in range(0, h, 3):
        for x in range(0, w, 3):
            assert img.getpixel((x, y))[:3] != YELLOW


def test_paint_thru_lines_double_corner() -> None:
    from render.corner_gen import WHITE, YELLOW, make_double_corner
    from sim.constants import ORTHO_TILE_SIZE

    img = make_double_corner(8, quadrant=0, travel_x=4, travel_y=4)
    t = ORTHO_TILE_SIZE
    size = 8 * t
    assert img.getpixel((4, size - 4))[3] == 0
    assert _has_color_near(img, 124, size - 2, YELLOW, r=6)
    assert _has_color_near(img, 96, size - 2, WHITE, r=8)


def test_paint_thru_lines_asymmetric_mixed_skips() -> None:
    from render.corner_gen import YELLOW, make_mixed
    from render.intersection_topology import corner_leftovers_from_local

    n = 6
    spans = {"N": (1, 2), "W": (0, 0)}
    img = make_mixed(
        n,
        corner_leftovers_from_local(n, spans),
        family="corner",
        spans=spans,
        paint_thru_lines=True,
    )
    w, h = img.size
    for y in range(0, h, 3):
        for x in range(0, w, 3):
            assert img.getpixel((x, y))[:3] != YELLOW


def test_paint_thru_lines_three_cell_mixed_corner() -> None:
    """Twin beside opposite on both faces: one sister dash and one double yellow."""
    from render.corner_gen import WHITE, YELLOW, make_mixed
    from render.intersection_topology import (
        classify_intersection_sides,
        mixed_corner_leftovers,
        mouth_spans_by_edge,
        mouth_spans_local,
        overlay_type_for_intersection,
        overlay_type_for_sides,
    )
    from render.thru_lines import ROLE_ONCOMING, ROLE_SISTER, _seams_from_occupied, resolve_face_profiles

    assert _seams_from_occupied({3: "out", 4: "in", 5: "in"}) == (
        (4, ROLE_ONCOMING),
        (5, ROLE_SISTER),
    )
    assert _seams_from_occupied({1: "in"}) == ()
    assert _seams_from_occupied({1: "in", 3: "out"}) == ()

    places_by_id = {
        "East": places.Place(center_x=30, center_y=20, width=5, length=5),
        "North": places.Place(center_x=20, center_y=32, width=5, length=5),
        "West": places.Place(center_x=8, center_y=20, width=5, length=5),
    }
    intersections = {
        "hub": places.IntersectionConfig(size_cells=4, center_x=20, center_y=20),
    }
    lanes = {
        1: places.LaneConfig(start_tile=(22, 19), end_tile=(26, 19)),
        2: places.LaneConfig(start_tile=(26, 20), end_tile=(22, 20)),
        3: places.LaneConfig(start_tile=(26, 21), end_tile=(22, 21)),
        4: places.LaneConfig(start_tile=(19, 26), end_tile=(19, 22)),
        5: places.LaneConfig(start_tile=(20, 22), end_tile=(20, 26)),
        6: places.LaneConfig(start_tile=(21, 22), end_tile=(21, 26)),
    }
    places.set_route_hints([])
    world.rebuild_world(place_rects_from_places(places_by_id), intersections, lanes)
    cells = world.get_intersection_cells_by_key("hub")
    active, _, _ = classify_intersection_sides("hub", cells, require_centre_two=False)
    assert overlay_type_for_sides(active) == "corner"
    assert overlay_type_for_intersection("hub", active) == places.INTERSECTION_TYPE_CORNER
    spans = mouth_spans_by_edge("hub", cells)
    local = mouth_spans_local(cells, spans)
    leftovers = mixed_corner_leftovers(cells, spans, active)
    prof = resolve_face_profiles(4, spans=local, intersection_key="hub")
    assert set(prof) == {"E", "N"}
    assert all(prof[e] for e in prof)
    img = make_mixed(
        4,
        leftovers,
        family="corner",
        spans=local,
        paint_thru_lines=True,
        intersection_key="hub",
    )
    assert _has_color_near(img, 64, 2, YELLOW, r=24)
    assert _has_color_near(img, 32, 2, WHITE, r=24)
    GameState()


def test_paint_thru_lines_mixed_tee_through() -> None:
    from render.corner_gen import WHITE, YELLOW, make_mixed
    from render.intersection_topology import (
        classify_intersection_sides,
        mixed_corner_leftovers,
        mouth_spans_by_edge,
        mouth_spans_local,
        overlay_type_for_intersection,
        overlay_type_for_sides,
        tee_layout_for_sides,
    )
    from sim.constants import ORTHO_TILE_SIZE

    places_by_id = {
        "West": places.Place(center_x=10, center_y=19, width=5, length=5),
        "East": places.Place(center_x=30, center_y=19, width=5, length=5),
        "North": places.Place(center_x=20, center_y=32, width=5, length=5),
    }
    intersections = {
        "hub": places.IntersectionConfig(size_cells=8, center_x=20, center_y=20),
    }
    lanes = {
        1: places.LaneConfig(start_tile=(13, 19), end_tile=(15, 19)),
        2: places.LaneConfig(start_tile=(13, 18), end_tile=(15, 18)),
        3: places.LaneConfig(start_tile=(24, 19), end_tile=(27, 19)),
        4: places.LaneConfig(start_tile=(24, 18), end_tile=(27, 18)),
        5: places.LaneConfig(start_tile=(19, 24), end_tile=(19, 29)),
        9: places.LaneConfig(start_tile=(15, 20), end_tile=(12, 20)),
        10: places.LaneConfig(start_tile=(15, 21), end_tile=(12, 21)),
        11: places.LaneConfig(start_tile=(27, 20), end_tile=(24, 20)),
        12: places.LaneConfig(start_tile=(27, 21), end_tile=(24, 21)),
    }
    places.set_route_hints([])
    world.rebuild_world(place_rects_from_places(places_by_id), intersections, lanes)
    cells = world.get_intersection_cells_by_key("hub")
    active, _, _ = classify_intersection_sides("hub", cells, require_centre_two=False)
    assert overlay_type_for_sides(active) == "tee"
    assert overlay_type_for_intersection("hub", active) == places.INTERSECTION_TYPE_TEE
    spans = mouth_spans_by_edge("hub", cells)
    local = mouth_spans_local(cells, spans)
    leftovers = mixed_corner_leftovers(cells, spans, active)
    axis, stem = tee_layout_for_sides(active)
    img = make_mixed(
        8,
        leftovers,
        family="tee",
        axis=axis,
        stem=stem,
        spans=local,
        paint_thru_lines=True,
        intersection_key="hub",
    )
    t = ORTHO_TILE_SIZE
    size = 8 * t
    split = (8 - 4) * t
    assert img.getpixel((split - 4, size // 2))[:3] == YELLOW
    assert img.getpixel((size - 4, size // 2))[3] == 0
    assert img.getpixel((8, 8))[:3] != YELLOW
    # Sister dash on the through band is two pixels, not one.
    sister = (8 - 3) * t
    assert img.getpixel((sister, size // 2))[:3] == WHITE
    assert img.getpixel((sister + 1, size // 2))[:3] == WHITE
    from ui.dialogs.intersection import IntersectionVarsDialog

    dlg = IntersectionVarsDialog(0, 0, "hub", intersections["hub"])
    assert dlg._paint_switch.enabled is True
    GameState()


def test_gapped_face_paints_nothing_and_leaves_switch_free() -> None:
    """A gap has no oppose seam, so nothing is drawn and the switch stays free."""
    from render.corner_gen import YELLOW, make_mixed
    from render.intersection_topology import (
        classify_intersection_sides,
        mixed_corner_leftovers,
        mouth_spans_by_edge,
        mouth_spans_local,
        overlay_type_for_intersection,
    )
    from ui.dialogs.intersection import IntersectionVarsDialog

    places_by_id = {
        "West": places.Place(center_x=10, center_y=19, width=5, length=5),
        "East": places.Place(center_x=30, center_y=19, width=5, length=5),
    }
    cfg = places.IntersectionConfig(size_cells=8, center_x=20, center_y=20, paint_thru_lines=True)
    intersections = {"hub": cfg}
    lanes = {
        1: places.LaneConfig(start_tile=(13, 18), end_tile=(15, 18)),
        2: places.LaneConfig(start_tile=(15, 21), end_tile=(12, 21)),
        3: places.LaneConfig(start_tile=(24, 19), end_tile=(27, 19)),
        4: places.LaneConfig(start_tile=(27, 20), end_tile=(24, 20)),
    }
    places.set_route_hints([])
    world.rebuild_world(place_rects_from_places(places_by_id), intersections, lanes)
    cells = world.get_intersection_cells_by_key("hub")
    active, _, _ = classify_intersection_sides("hub", cells, require_centre_two=False)
    assert overlay_type_for_intersection("hub", active) == places.INTERSECTION_TYPE_STRAIGHT
    spans = mouth_spans_by_edge("hub", cells)
    local = mouth_spans_local(cells, spans)
    leftovers = mixed_corner_leftovers(cells, spans, active)
    img = make_mixed(
        8,
        leftovers,
        family="straight",
        axis="ew",
        spans=local,
        paint_thru_lines=True,
        intersection_key="hub",
    )
    w, h = img.size
    for y in range(0, h, 3):
        for x in range(0, w, 3):
            assert img.getpixel((x, y))[:3] != YELLOW
    stored = cfg.paint_thru_lines
    dlg = IntersectionVarsDialog(0, 0, "hub", cfg)
    assert dlg._paint_switch.enabled is True
    dlg._apply_config()
    assert cfg.paint_thru_lines is stored
    GameState()


def test_paint_thru_lines_scenario_roundtrip() -> None:
    from sim.scenario import _normalize_intersection

    missing = _normalize_intersection({"center_x": 4, "center_y": 5, "size_cells": 4})
    assert missing["paint_thru_lines"] is True
    off = _normalize_intersection(
        {"center_x": 4, "center_y": 5, "size_cells": 4, "paint_thru_lines": False}
    )
    assert off["paint_thru_lines"] is False
    _, ixs, _, _, _, _, _ = scenario_to_game_dicts(
        {
            "places": {},
            "intersections": {"hub": {"center_x": 4, "center_y": 5, "size_cells": 4}},
            "lanes": {},
        }
    )
    assert ixs["hub"].paint_thru_lines is True
    g = GameState()
    g.places = {}
    g.intersections = {
        "hub": places.IntersectionConfig(
            size_cells=4, center_x=4, center_y=5, paint_thru_lines=False
        )
    }
    g.lanes = {}
    g.route_hints = []
    sc = game_to_scenario(g)
    assert sc["intersections"]["hub"]["paint_thru_lines"] is False
    _, ixs2, _, _, _, _, _ = scenario_to_game_dicts(sc)
    assert ixs2["hub"].paint_thru_lines is False


def test_jogged_is_off_centre_and_skips_thru_lines() -> None:
    """Off-centre yellow is not drawn, and the switch locks without writing the flag."""
    from render.corner_gen import YELLOW, make_mixed
    from render.intersection_topology import (
        classify_intersection_sides,
        mixed_corner_leftovers,
        mouth_spans_by_edge,
        mouth_spans_local,
        overlay_type_for_intersection,
    )
    from ui.dialogs.intersection import IntersectionVarsDialog
    from sim import persistence

    g = GameState()
    persistence.load_config(g)
    g.rebuild_world_from_config()
    expect = {
        "intersection_213": "tee",
        "intersection_195": "tee",
        "intersection_204": "tee",
        "intersection_219": "corner",
        "intersection_201": "corner",
        "intersection_210": "corner",
        "intersection_214": "cross",
        "intersection_217": "tee",
        "intersection_218": "corner",
    }
    for key, shape in expect.items():
        cells = world.get_intersection_cells_by_key(key)
        active, _, _ = classify_intersection_sides(key, cells, require_centre_two=False)
        itype = overlay_type_for_intersection(key, active)
        assert itype == shape, (key, itype)

    key = "intersection_218"
    cells = world.get_intersection_cells_by_key(key)
    active, _, _ = classify_intersection_sides(key, cells, require_centre_two=False)
    spans = mouth_spans_by_edge(key, cells)
    local = mouth_spans_local(cells, spans)
    leftovers = mixed_corner_leftovers(cells, spans, active)
    n = g.intersections[key].size_cells
    img = make_mixed(
        n,
        leftovers,
        family="corner",
        spans=local,
        paint_thru_lines=True,
        intersection_key=key,
    )
    w, h = img.size
    for y in range(0, h, 3):
        for x in range(0, w, 3):
            assert img.getpixel((x, y))[:3] != YELLOW

    cfg = g.intersections[key]
    stored = cfg.paint_thru_lines
    dlg = IntersectionVarsDialog(0, 0, key, cfg)
    assert dlg._paint_switch.enabled is False
    dlg._paint_switch.value = True
    dlg._apply_config()
    assert cfg.paint_thru_lines is stored
    assert dlg._paint_switch.value is False
    GameState()


def test_paint_thru_dialog_one_can_turn_off() -> None:
    from ui.dialogs.intersection import IntersectionVarsDialog
    from ui.widgets.switch import Switch
    from render.intersection_topology import (
        classify_intersection_sides,
        overlay_type_for_intersection,
    )

    sw = Switch(0, 0, 50, 22, initial_value=True, enabled=False)
    assert sw.on_press(5, 5) is True
    assert sw.value is True
    sw.enabled = True
    assert sw.on_press(5, 5) is True
    assert sw.value is False

    places_by_id = {
        "West": places.Place(center_x=8, center_y=22, width=5, length=5),
        "North": places.Place(center_x=17, center_y=32, width=5, length=5),
    }
    intersections = {
        "hub": places.IntersectionConfig(size_cells=6, center_x=20, center_y=20),
    }
    lanes = {
        1: places.LaneConfig(start_tile=(10, 22), end_tile=(16, 22)),
        2: places.LaneConfig(start_tile=(17, 23), end_tile=(17, 29)),
    }
    places.set_route_hints([])
    world.rebuild_world(place_rects_from_places(places_by_id), intersections, lanes)
    cells = world.get_intersection_cells_by_key("hub")
    active, _, _ = classify_intersection_sides("hub", cells, require_centre_two=False)
    raw = overlay_type_for_intersection("hub", active)
    assert raw == places.INTERSECTION_TYPE_CORNER
    cfg = intersections["hub"]
    dlg = IntersectionVarsDialog(0, 0, "hub", cfg)
    assert dlg._paint_switch.enabled is True
    dlg._paint_switch.value = False
    dlg._apply_config()
    assert cfg.paint_thru_lines is False
    GameState()


def _paint_hub(places_by_id, lanes, *, size: int, family: str, axis: str = "ns", stem: str = "E"):
    from render.corner_gen import make_mixed
    from render.intersection_topology import (
        mixed_corner_leftovers,
        mouth_spans_by_edge,
        mouth_spans_local,
    )

    intersections = {
        "hub": places.IntersectionConfig(size_cells=size, center_x=20, center_y=20),
    }
    places.set_route_hints([])
    world.rebuild_world(place_rects_from_places(places_by_id), intersections, lanes)
    cells = world.get_intersection_cells_by_key("hub")
    spans = mouth_spans_by_edge("hub", cells)
    local = mouth_spans_local(cells, spans)
    leftovers = mixed_corner_leftovers(cells, spans, frozenset(local))
    img = make_mixed(
        size,
        leftovers,
        family=family,
        axis=axis,
        stem=stem,
        spans=local,
        paint_thru_lines=False,
        intersection_key="hub",
    )
    return img, local, leftovers


def test_yellow_left_curb_lane_corner_and_tee() -> None:
    """Driver's left curb is yellow on a one-way face; a two-way face stays white."""
    from render.corner_gen import WHITE, YELLOW, _image_span_px, _union_span, curb_scheme, frozen_curb_key
    from render.lane_paint import (
        ROLE_CURB,
        ROLE_LEFT_CURB,
        ROLE_ONCOMING,
        ROLE_SISTER,
        lateral_roles,
        raster_lane_ortho,
    )
    from render.lane_paint import CURB_INSET
    from sim.constants import ORTHO_TILE_SIZE

    places.set_route_hints([])
    world.rebuild_world(
        {},
        {},
        {
            1: places.LaneConfig(start_tile=(10, 10), end_tile=(10, 20)),
            2: places.LaneConfig(start_tile=(11, 10), end_tile=(11, 20)),
            3: places.LaneConfig(start_tile=(29, 20), end_tile=(29, 10)),
            4: places.LaneConfig(start_tile=(30, 10), end_tile=(30, 20)),
        },
    )
    assert lateral_roles("N", 10, 15) == {"W": ROLE_LEFT_CURB, "E": ROLE_SISTER}
    assert lateral_roles("N", 11, 15) == {"W": ROLE_SISTER, "E": ROLE_CURB}
    assert lateral_roles("N", 30, 15) == {"W": ROLE_ONCOMING, "E": ROLE_CURB}
    img_lane = raster_lane_ortho("N", ROLE_LEFT_CURB, ROLE_CURB, 0)
    assert img_lane.getpixel((0, 28))[:3] == YELLOW
    assert img_lane.getpixel((0, 2))[:3] == WHITE

    t = ORTHO_TILE_SIZE
    # Left turn: eastbound in, northbound out. Inner fillet yellow, exterior white.
    img, local, _ = _paint_hub(
        {
            "West": places.Place(center_x=8, center_y=22, width=5, length=5),
            "North": places.Place(center_x=17, center_y=32, width=5, length=5),
        },
        {
            1: places.LaneConfig(start_tile=(10, 22), end_tile=(16, 22)),
            2: places.LaneConfig(start_tile=(17, 23), end_tile=(17, 29)),
        },
        size=6,
        family="corner",
    )
    size = 6 * t
    left_key = frozen_curb_key("hub", "corner", spans=local)
    assert ("N", "W") in left_key[0] and ("W", "N") in left_key[0]
    assert 0 in left_key[1]
    assert img.getpixel((CURB_INSET + 1, size - CURB_INSET - 1))[:3] == YELLOW
    ny0, _ny1 = _image_span_px(local["N"], 6)
    assert img.getpixel((4, ny0 + CURB_INSET))[:3] == WHITE

    # Same mouths, opposite way: right turn. Fillet white, exterior yellow. Cache key differs.
    img_r, local_r, _ = _paint_hub(
        {
            "West": places.Place(center_x=8, center_y=22, width=5, length=5),
            "North": places.Place(center_x=17, center_y=32, width=5, length=5),
        },
        {
            1: places.LaneConfig(start_tile=(16, 22), end_tile=(10, 22)),
            2: places.LaneConfig(start_tile=(17, 29), end_tile=(17, 23)),
        },
        size=6,
        family="corner",
    )
    right_key = frozen_curb_key("hub", "corner", spans=local_r)
    assert local_r == local
    assert right_key != left_key
    assert 0 not in right_key[1]
    assert img_r.getpixel((CURB_INSET + 1, size - CURB_INSET - 1))[:3] == WHITE
    assert img_r.getpixel((4, ny0 + CURB_INSET))[:3] == YELLOW

    # One-way eastbound through. Open north (driver's left) is yellow; open south stays white.
    places_ew = {
        "West": places.Place(center_x=10, center_y=19, width=5, length=5),
        "East": places.Place(center_x=30, center_y=19, width=5, length=5),
    }
    through = {
        1: places.LaneConfig(start_tile=(13, 19), end_tile=(15, 19)),
        3: places.LaneConfig(start_tile=(24, 19), end_tile=(27, 19)),
    }
    img_s, local_s, _ = _paint_hub(
        {**places_ew, "South": places.Place(center_x=20, center_y=8, width=5, length=5)},
        {**through, 7: places.LaneConfig(start_tile=(20, 15), end_tile=(20, 12))},
        size=8,
        family="tee",
        axis="ew",
        stem="S",
    )
    size8 = 8 * t
    x0, x1 = _image_span_px(_union_span(local_s["E"], local_s["W"]), 8)
    assert img_s.getpixel((x0 + CURB_INSET + 1, size8 // 2))[:3] == YELLOW
    stem_s = curb_scheme("hub", "tee", "ew", "S")
    assert 1 not in stem_s.fillets and 2 in stem_s.fillets

    img_n, local_n, _ = _paint_hub(
        {**places_ew, "North": places.Place(center_x=20, center_y=32, width=5, length=5)},
        {**through, 5: places.LaneConfig(start_tile=(19, 24), end_tile=(19, 29))},
        size=8,
        family="tee",
        axis="ew",
        stem="N",
    )
    x0n, x1n = _image_span_px(_union_span(local_n["E"], local_n["W"]), 8)
    assert img_n.getpixel((x1n - CURB_INSET - 1, size8 // 2))[:3] == WHITE
    stem_n = curb_scheme("hub", "tee", "ew", "N")
    assert 0 in stem_n.fillets and 3 not in stem_n.fillets

    # Two-way through, one-way southbound stem: only the stem's left shoulder is yellow.
    img_stem, _local_stem, _ = _paint_hub(
        {
            **places_ew,
            "South": places.Place(center_x=20, center_y=8, width=5, length=5),
        },
        {
            1: places.LaneConfig(start_tile=(13, 19), end_tile=(15, 19)),
            3: places.LaneConfig(start_tile=(24, 19), end_tile=(27, 19)),
            9: places.LaneConfig(start_tile=(15, 20), end_tile=(12, 20)),
            11: places.LaneConfig(start_tile=(27, 20), end_tile=(24, 20)),
            7: places.LaneConfig(start_tile=(20, 15), end_tile=(20, 12)),
        },
        size=8,
        family="tee",
        axis="ew",
        stem="S",
    )
    xs0, xs1 = _image_span_px(_union_span(_local_stem["E"], _local_stem["W"]), 8)
    assert img_stem.getpixel((xs0 + CURB_INSET + 1, size8 // 2))[:3] == WHITE
    stem_only = curb_scheme("hub", "tee", "ew", "S")
    assert stem_only.fillets == {2}
    assert ("E", "S") in stem_only.halves
    assert ("N", "W") not in stem_only.halves

    # One-way straight: left edge yellow, right edge white.
    img_st, local_st, _ = _paint_hub(
        places_ew,
        through,
        size=8,
        family="straight",
        axis="ew",
    )
    sx0, sx1 = _image_span_px(_union_span(local_st["E"], local_st["W"]), 8)
    assert img_st.getpixel((sx0 + CURB_INSET + 1, size8 // 2))[:3] == YELLOW
    assert img_st.getpixel((sx1 - CURB_INSET - 1, size8 // 2))[:3] == WHITE

    # One-way north arm on a two-way cross: that arm's left curb is yellow.
    img_x, _local_x, _ = _paint_hub(
        {
            **places_ew,
            "North": places.Place(center_x=20, center_y=32, width=5, length=5),
            "South": places.Place(center_x=20, center_y=8, width=5, length=5),
        },
        {
            1: places.LaneConfig(start_tile=(13, 19), end_tile=(15, 19)),
            2: places.LaneConfig(start_tile=(15, 20), end_tile=(12, 20)),
            3: places.LaneConfig(start_tile=(24, 19), end_tile=(27, 19)),
            4: places.LaneConfig(start_tile=(27, 20), end_tile=(24, 20)),
            5: places.LaneConfig(start_tile=(19, 24), end_tile=(19, 29)),
            6: places.LaneConfig(start_tile=(20, 12), end_tile=(20, 15)),
            7: places.LaneConfig(start_tile=(21, 15), end_tile=(21, 12)),
        },
        size=8,
        family="cross",
    )
    cross = curb_scheme("hub", "cross")
    assert cross.halves == {("W", "N")}
    assert cross.fillets == {0}
    w, h = img_x.size
    assert any(img_x.getpixel((x, y))[:3] == YELLOW for y in range(h) for x in range(0, w, 2))

    # Two-way corner keeps every curb white.
    img_two, _, _ = _paint_hub(
        {
            "West": places.Place(center_x=8, center_y=22, width=5, length=5),
            "North": places.Place(center_x=17, center_y=32, width=5, length=5),
        },
        {
            1: places.LaneConfig(start_tile=(10, 22), end_tile=(16, 22)),
            2: places.LaneConfig(start_tile=(16, 21), end_tile=(10, 21)),
            3: places.LaneConfig(start_tile=(17, 23), end_tile=(17, 29)),
            4: places.LaneConfig(start_tile=(18, 29), end_tile=(18, 23)),
        },
        size=6,
        family="corner",
    )
    assert curb_scheme("hub", "corner").halves == set()
    tw, th = img_two.size
    for y in range(th):
        for x in range(tw):
            assert img_two.getpixel((x, y))[:3] != YELLOW
    GameState()


def main() -> None:
    tests = [
        test_migrate_schema_3_snippet,
        test_tangent_straight_turn_uturn,
        test_unnamed_intersections_occupancy,
        test_default_map_hints_and_police_homes,
        test_police_on_demand,
        test_police_disabled_and_clear_cars,
        test_police_holding_helps_jam,
        test_police_exit_proximity,
        test_police_fades_the_sides_up_before_leaving,
        test_police_linger_and_divert,
        test_police_beats,
        test_spawn_skips_full_lane,
        test_jam_chains_short_inbound,
        test_reset_loads_default,
        test_sanitize_save_name,
        test_named_map_save_load_roundtrip,
        test_new_game_restores_default_places,
        test_delete_default_lane_and_intersection,
        test_stable_lane_ids_survive_gap,
        test_authored_coords_match_world,
        test_place_spawn_survives_rebuild,
        test_camera_roundtrip,
        test_camera_yaw_roundtrip,
        test_map_camera_matches_grid_to_screen,
        test_camera_yaw_north_looks_like_east,
        test_iso_depth_reverses_at_180,
        test_yaw_cardinal_and_dir_remap,
        test_view_south_cell_corners,
        test_overlay_type_for_sides,
        test_tee_layout_for_sides,
        test_tee_corner_quadrants,
        test_corner_quadrant_for_sides,
        test_filleted_cross_tee_transparency,
        test_rename_place,
        test_snap_cardinal_end,
        test_place_aabb_from_corners,
        test_place_aabb_from_edge_and_hover,
        test_intersection_size_for_hover,
        test_iso_aabb_silhouette,
        test_selection_rim_offset_and_facing,
        test_color_settings_clamp_roundtrip,
        test_grade_rgb_identity_and_hue_shift,
        test_building_pack_counts,
        test_building_pack_long_variants,
        test_building_kind_roundtrip,
        test_building_seed_shuffle,
        test_building_layout_shuffle,
        test_building_catalog_natural_scale,
        test_rebuild_topology_tables,
        test_sister_geometry_staggered_and_corner,
        test_stepsister_chain_and_corridor,
        test_stepsister_route_steps_and_drive,
        test_stepsister_step_survives_a_blocked_seam,
        test_mother_daughter_chain_is_one_road,
        test_mother_daughter_route_and_seamless_drive,
        test_mother_lane_is_never_forced_off_its_own_road,
        test_identical_and_fraternal_twins,
        test_twin_intersection_paths_and_double_stamp,
        test_twin_keep_side_drive,
        test_twin_right_takes_the_inside_lane,
        test_fraternal_drop_lane_exits_onto_the_longer_twin,
        test_twins_do_not_keep_right,
        test_twin_double_double_has_no_weaves,
        test_double_cross_requires_closed_dual,
        test_twin_elsewhere_does_not_make_mixed_cross,
        test_double_stamp_shoulder_not_travel_bundle,
        test_mixed_stamp_min_leftover_and_virtual_curb,
        test_mixed_tee_open_face_from_mouth_span,
        test_mixed_corner_is_mouth_L_not_scaled_pie,
        test_mixed_corner_ns_double_ew_single_on_stamp_axes,
        test_double_tee_classified_open_and_fillet,
        test_tee_open_face_curb_runs_across,
        test_double_corner_classified_is_L,
        test_leftover_zero_flush_double_is_opaque,
        test_leftover_zero_mixed_flush_mouth_paints_throat_L,
        test_leftover_zero_three_lane_flush_paints_segment,
        test_leftover_zero_size2_one_lane_paints_throat_L,
        test_size2_one_asymmetric_uses_zero_throat_L,
        test_through_width_chamfer_cross_tee_and_skip,
        test_paint_thru_lines_normal_on_off,
        test_paint_thru_lines_one_skips,
        test_paint_thru_lines_double_corner,
        test_paint_thru_lines_asymmetric_mixed_skips,
        test_paint_thru_lines_three_cell_mixed_corner,
        test_paint_thru_lines_mixed_tee_through,
        test_gapped_face_paints_nothing_and_leaves_switch_free,
        test_paint_thru_lines_scenario_roundtrip,
        test_jogged_is_off_centre_and_skips_thru_lines,
        test_paint_thru_dialog_one_can_turn_off,
        test_one_stamp_family_and_clamp,
        test_one_lane_corner_classified_uses_mouth_span,
        test_one_lane_offset_fillet_at_mouth_not_aabb,
        test_one_equal_width_L_gets_exterior_fillet,
        test_tee_spandrel_is_pavement,
        test_equal_width_corner_follows_pair_table,
        test_size4_double_corner_has_outer_curb_no_inner_bite,
        test_mixed_leftover_quadrants_match_pair_table,
        test_mixed_ne_leftover_punches_image_tl,
        test_width6_centered_span_uses_one_cell_fillet,
        test_sister_overlay_rects,
        test_lane_paint_roles_and_raster,
        test_lane_end_chamfer,
        test_yellow_left_curb_lane_corner_and_tee,
        test_path_cache_matches_live,
        test_occupancy_jam_and_lane_full,
        test_route_hinted_housing_park_via_bypass,
        test_route_housing_office_via_main,
        test_route_intermediate_place_hop_or_despawn,
        test_route_destination_despawn,
        test_route_unreachable,
        test_route_spawn_full_first_lane_no_retry,
        test_route_rename_retargets_place_steps,
        test_hint_via_exact_beats_dest_star,
        test_route_office_forced_via_bypass,
        test_route_multi_mouth_slack_then_shortest,
        test_choose_next_lane_stays_greedy,
        test_roll_observe_skills,
        test_observe_fan_red_still_wins,
        test_observe_behind_speeds_up,
        test_observe_ahead_slows,
        test_observe_side_slows_for_passer,
        test_situation_maneuver_labels,
        test_situation_lane_counts_and_next_feature_cars,
        test_situation_sister_counts,
        test_situation_place_and_on_lane_from_route,
        test_merge_target_geometry,
        test_merge_curve_is_a_smooth_s,
        test_keep_right_onto_little_sister,
        test_pass_left_only_when_faster,
        test_queue_slides_to_the_clearer_sister,
        test_forced_exit_and_who_takes_the_gap,
        test_merge_drives_through_and_returns_to_lane_mode,
        test_dangling_lane_end_snaps_instead_of_despawning,
        test_merge_speed_floor_completes_the_change,
        test_lane_and_node_mouth_cells,
        test_nearest_car_in_radius,
        test_observed_cars_membership,
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
