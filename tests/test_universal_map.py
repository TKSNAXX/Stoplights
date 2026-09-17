"""
Headless tests for schema-4 scenario and derived topology.
Run: python -m tests.test_universal_map
"""
from __future__ import annotations

from sim import places, world
from sim.cars import Car
from sim.cop import (
    COPS_PER_INTERSECTION,
    DISMISS_LINGER,
    INBOUND_TAIL_CELLS,
    JAM_TRIGGER,
    JAM_TRIGGER_SECOND,
    RED_ZERO_DURATION,
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

    g.police_list = []
    g.cars = [
        _make_test_car(
            lane_index=inbound,
            position=len(lane_cells) - 1 - (i % INBOUND_TAIL_CELLS),
            vis="red",
        )
        for i in range(JAM_TRIGGER)
    ]
    g._update_police(0.0)
    assert len(g.police_list) == 1
    g.police_list = []

    approach = pick_deploy_lane("main")
    assert approach is not None
    place = place_on_lane_for_intersection(approach, "main")
    assert place and not world.is_intersection(place)

    g.cars = [
        _make_test_car(mode="path", cell=main_cells[i % len(main_cells)])
        for i in range(JAM_TRIGGER)
    ]
    g._update_police(0.0)
    assert len(g.police_list) == 1
    assert g.police_list[0].target_intersection == "main"
    first_lane = g.police_list[0].deploy_lane

    g.cars = [
        _make_test_car(mode="path", cell=main_cells[i % len(main_cells)])
        for i in range(JAM_TRIGGER_SECOND)
    ]
    g._update_police(0.0)
    assert len(g.police_list) == 2
    assert len({p.deploy_lane for p in g.police_list}) == 2
    g._update_police(0.0)
    assert len(g.police_list) == COPS_PER_INTERSECTION

    g.police_list = []
    g.cars = [
        _make_test_car(mode="path", cell=main_cells[i % len(main_cells)])
        for i in range(JAM_TRIGGER)
    ] + [
        _make_test_car(mode="path", cell=bypass_cells[i % len(bypass_cells)])
        for i in range(JAM_TRIGGER)
    ]
    g._update_police(0.0)
    targets = {p.target_intersection for p in g.police_list}
    assert "main" in targets and "bypass" in targets
    assert len(g.police_list) == 2

    holding = spawn_police("main", first_lane)
    holding.state = "holding"
    holding.tick(RED_ZERO_DURATION + 0.1, 0)
    assert holding.state == "holding"
    assert holding.depart_pending is False
    holding.tick(DISMISS_LINGER + 0.1, 0)
    assert holding.state == "holding"
    assert holding.depart_pending is True
    still = spawn_police("main", first_lane)
    still.state = "holding"
    still.tick(RED_ZERO_DURATION + 0.1, 50)
    assert still.state == "holding"
    jam_during = spawn_police("main", first_lane)
    jam_during.state = "holding"
    jam_during.tick(RED_ZERO_DURATION + 1.0, 0)
    assert jam_during.depart_pending is False
    linger_mid = jam_during.linger_timer
    assert linger_mid > 0.0
    jam_during.tick(0.1, 50)
    assert jam_during.state == "holding"
    assert jam_during.depart_pending is False
    assert jam_during.linger_timer == linger_mid + 0.1
    jam_end = spawn_police("main", first_lane)
    jam_end.state = "holding"
    jam_end.tick(RED_ZERO_DURATION + 0.1, 0)
    jam_end.tick(DISMISS_LINGER + 0.1, 50)
    assert jam_end.state == "holding"
    assert jam_end.depart_pending is False
    assert jam_end.linger_timer == 0.0

    flowing = [
        _make_test_car(mode="path", cell=main_cells[i % len(main_cells)], vis="green")
        for i in range(6)
    ] + [
        _make_test_car(mode="path", cell=main_cells[0], vis="cyan")
        for _ in range(3)
    ]
    assert intersection_jam_score(flowing, "main") == 9
    assert intersection_dismiss_score(flowing, "main") == 0
    g.police_list = [spawn_police("main", first_lane)]
    g.police_list[0].state = "holding"
    g.cars = flowing
    g._update_police(RED_ZERO_DURATION + 0.1)
    assert g.police_list[0].state == "holding"
    g._update_police(DISMISS_LINGER + 0.1)
    assert g.police_list[0].state == "returning"

    inbound = next(i for i in world.lane_ids() if world.lane_traffic_out(i) == "main")
    lane_cells = world.get_lane_cells(inbound)
    jammed = flowing + [
        _make_test_car(lane_index=inbound, position=len(lane_cells) - 1, vis="red"),
        _make_test_car(lane_index=inbound, position=max(0, len(lane_cells) - 2), vis="red"),
    ]
    assert intersection_dismiss_score(jammed, "main") >= 1
    g.police_list = [spawn_police("main", first_lane)]
    g.police_list[0].state = "holding"
    g.cars = jammed
    g._update_police(RED_ZERO_DURATION + 0.1)
    assert g.police_list[0].state == "holding"


def test_police_disabled_and_clear_cars() -> None:
    g = GameState()
    g.cars = [_make_test_car()]
    g.clear_cars()
    assert g.cars == []

    inbound = next(i for i in world.lane_ids() if world.lane_traffic_out(i) == "main")
    lane_cells = world.get_lane_cells(inbound)
    jam = [
        _make_test_car(
            lane_index=inbound,
            position=len(lane_cells) - 1 - (i % INBOUND_TAIL_CELLS),
            vis="red",
        )
        for i in range(JAM_TRIGGER)
    ]
    g.cars = jam
    g.set_police_enabled(False)
    g._update_police(0.0)
    assert g.police_list == []

    g.set_police_enabled(True)
    g._update_police(0.0)
    assert len(g.police_list) == 1

    g.set_police_enabled(False)
    assert g.police_list == []


def test_police_holding_helps_jam() -> None:
    from sim.constants import POLICE_PRIORITY_SCALE, VIS_ZONE_WIDTH_CELLS
    from sim.cop import _home_at_lane_start, _intersection_center
    from sim.impasse import apply_impasse
    from sim.paths import direction_index_8_from_tangent
    from sim.visibility import build_poses

    g = GameState()
    main_cells = world.get_intersection_cells_by_key("main")
    inbound = next(i for i in world.lane_ids() if world.lane_traffic_out(i) == "main")
    lane_cells = world.get_lane_cells(inbound)
    approach = pick_deploy_lane("main")
    assert approach is not None
    cop_car = spawn_police("main", approach)
    cop_car.state = "holding"
    home_at_0 = _home_at_lane_start(approach)
    cop_car.lane_pos = 0.0 if not home_at_0 else float(cop_car._lane_len(approach) - 1)

    gx, gy, di = cop_car.get_pose()
    cx, cy = _intersection_center("main")
    assert di == direction_index_8_from_tangent(cx - gx, cy - gy)

    path_cars = [
        _make_test_car(mode="path", cell=main_cells[i % len(main_cells)], vis="red")
        for i in range(5)
    ]
    tail = _make_test_car(lane_index=inbound, position=len(lane_cells) - 1, vis="red")
    g.cars = path_cars + [tail]
    g.police_list = [cop_car]
    poses = build_poses(g.cars)
    g._apply_police_influence(poses, lambda *_: [], VIS_ZONE_WIDTH_CELLS / 2.0)
    assert all(c.police_hold_until_exit for c in path_cars)
    assert tail.police_priority_active
    assert not tail.police_hold_until_exit

    tail.impasse_active = True
    tail.visibility_state = "cyan"
    tail.speed_scale = POLICE_PRIORITY_SCALE
    pose = (float(lane_cells[-1][0]), float(lane_cells[-1][1]), 0)
    apply_impasse(
        0.1,
        [tail],
        [pose],
        {id(tail): 0},
        lambda *_: [],
        VIS_ZONE_WIDTH_CELLS / 2.0,
        {},
        set(),
    )
    assert tail.visibility_state == "cyan"
    assert tail.speed_scale == POLICE_PRIORITY_SCALE

    deploying = spawn_police("main", approach)
    deploying.lane_pos = cop_car.lane_pos
    assert deploying.state == "deploying"
    assert deploying.at_mouth()
    g.police_list = [deploying]
    g.cars = path_cars[:1]
    poses = build_poses(g.cars)
    g._apply_police_influence(poses, lambda *_: [], VIS_ZONE_WIDTH_CELLS / 2.0)
    assert g.cars[0].police_hold_until_exit

    g.police_list = [cop_car]
    g.rebuild_world_from_config()
    assert any(p.target_intersection == "main" for p in g.police_list)

    shared = main_cells[0]
    assert world.cell_in_intersection(shared, "main")
    overlap_car = _make_test_car(mode="path", cell=shared, vis="red")
    assert in_node_jam(overlap_car, "main")


def test_police_linger_and_divert() -> None:
    g = GameState()
    main_cells = world.get_intersection_cells_by_key("main")
    bypass_cells = world.get_intersection_cells_by_key("bypass")
    approach = pick_deploy_lane("main")
    assert approach is not None
    home_at_0 = _home_at_lane_start(approach)
    linger_dt = RED_ZERO_DURATION + DISMISS_LINGER + 0.1

    def _hold_at_main() -> object:
        cop_car = spawn_police("main", approach)
        cop_car.state = "holding"
        cop_car.current_node = "main"
        cop_car.lane_pos = 0.0 if not home_at_0 else float(cop_car._lane_len(approach) - 1)
        return cop_car

    cop_car = _hold_at_main()
    g.cars = [_make_test_car(mode="path", cell=main_cells[0], vis="green")]
    g.police_list = [cop_car]
    g._update_police(linger_dt)
    assert cop_car.state == "returning"

    cop_car = _hold_at_main()
    bypass_jam = [
        _make_test_car(mode="path", cell=bypass_cells[i % len(bypass_cells)], vis="red")
        for i in range(3)
    ]
    g.cars = bypass_jam
    g.police_list = [cop_car]
    g._update_police(linger_dt)
    assert cop_car.state == "diverting"
    assert cop_car.target_intersection == "bypass"
    assert cop_car.can_divert is False

    cop_car = _hold_at_main()
    b1_lane = pick_deploy_lane("bypass")
    assert b1_lane is not None
    b1 = spawn_police("bypass", b1_lane)
    b1.state = "holding"
    b1.current_node = "bypass"
    b2_lane = pick_deploy_lane("bypass", {b1.deploy_lane})
    assert b2_lane is not None
    b2 = spawn_police("bypass", b2_lane)
    b2.state = "holding"
    b2.current_node = "bypass"
    g.cars = bypass_jam
    g.police_list = [cop_car, b1, b2]
    g._update_police(linger_dt)
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
    assert g.can_remove_lane(0) is False
    assert g.can_remove_intersection("main") is False
    assert g.can_remove_place("Housing") is True


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
    assert tee.getpixel((tw // 2, 60))[:3] == YELLOW
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


def test_twin_intersection_paths_and_big_stamp() -> None:
    """Keep-side straight, inside turns; far-lane rights are not cached; stamp is Big."""
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
    assert overlay_type_for_intersection("hub", active) == places.INTERSECTION_TYPE_BIG
    assert world.intersection_has_twins("hub")

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


def main() -> None:
    tests = [
        test_migrate_schema_3_snippet,
        test_tangent_straight_turn_uturn,
        test_unnamed_intersections_occupancy,
        test_default_map_hints_and_police_homes,
        test_police_on_demand,
        test_police_disabled_and_clear_cars,
        test_police_holding_helps_jam,
        test_police_linger_and_divert,
        test_spawn_skips_full_lane,
        test_jam_chains_short_inbound,
        test_reset_loads_default,
        test_stable_lane_ids_survive_gap,
        test_authored_coords_match_world,
        test_place_spawn_survives_rebuild,
        test_camera_roundtrip,
        test_camera_yaw_roundtrip,
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
        test_twin_intersection_paths_and_big_stamp,
        test_twin_keep_side_drive,
        test_twin_right_takes_the_inside_lane,
        test_fraternal_drop_lane_exits_onto_the_longer_twin,
        test_sister_overlay_rects,
        test_lane_paint_roles_and_raster,
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
