"""
Lane-change decisions on sister lanes: keep right, pass left, exit before the end.

Reads world merge sides and occupancy; the motion itself is a merge segment in
sim.movement. Police keep their own motion and are not considered here.
"""
from __future__ import annotations

from sim import map_data, routes, world
from sim.occupancy import Occupancy, occupancy_from

# One lateral cell per this many forward cells; shortened when the runway is short.
MERGE_FORWARD_CELLS = 3
# Cells left on a dangling lane before its end forces a merge back.
MERGE_EXIT_LOOKAHEAD = 6
# Landing cell plus this many target cells ahead must always be clear.
MERGE_GAP_AHEAD = 2
# Blind-spot tail: target cells behind the merging car's own level that count.
MERGE_GAP_BEHIND = 2
# Cells the right lane must still run past the landing cell before keeping right.
MIN_RIGHT_RUNWAY = 6
# Base-speed advantage needed before pulling out to pass.
MERGE_SPEED_MARGIN = 0.05
# Cells ahead on the driven lane that count as catching up.
BLOCKER_LOOKAHEAD = 3
# Speed floor while astride the seam, so a change never stalls between lanes.
MERGE_MIN_SCALE = 0.5
# Share of normal travel speed held along the lane-change curve. 1.0 keeps every
# bit of it; lower it to let a change cost the driver some pace.
MERGE_SPEED_KEEP = 1.0

REASON_KEEP = "keep"
REASON_PASS = "pass"
REASON_EXIT = "exit"
REASON_STEP = "step"
# Not a lane change at all: a mother running straight on into her daughter.
REASON_FLOW = "flow"


def merge_choice(car, occupancy: Occupancy | None = None):
    """
    Lane change for this car as (target_lane, target_pos, side, reason), or None.

    Called when a lane segment completes, so changes always begin on a cell
    boundary. Priority: the itinerary's own step, then forced exit, then
    passing, then keeping right.
    """
    if getattr(car, "motion_mode", "lane") != "lane":
        return None
    if getattr(car, "impasse_active", False):
        return None
    if getattr(car, "police_priority_active", False) or getattr(car, "police_hold_until_exit", False):
        return None

    lane = car.lane_index
    pos = int(car.position_in_lane)
    cells = world.get_lane_cells(lane)
    if not cells or pos < 0 or pos >= len(cells):
        return None
    sides = world.cell_merge(*cells[pos])
    if sides == world.MERGE_NEITHER:
        return None

    occ = occupancy_from(occupancy)
    planned = planned_step_lane(car)
    if planned is not None:
        return _step_choice(car, lane, pos, sides, occ, planned)
    if _must_exit(lane, pos, cells):
        return _exit_choice(car, lane, pos, sides, occ)
    left_ok = sides in (world.MERGE_LEFT, world.MERGE_BOTH)
    right_ok = sides in (world.MERGE_RIGHT, world.MERGE_BOTH)
    if left_ok and _blocked_by_slower(car, lane, pos, occ):
        found = _first_clear_target(
            car, lane, pos, world.MERGE_LEFT, occ, strict=True,
            min_runway=MERGE_EXIT_LOOKAHEAD + 1,
        )
        if found is not None:
            return (found[0], found[1], world.MERGE_LEFT, REASON_PASS)
        return None
    if right_ok:
        found = _first_clear_target(
            car, lane, pos, world.MERGE_RIGHT, occ, strict=True, min_runway=MIN_RIGHT_RUNWAY
        )
        # Twins are equal lanes; keep-right is only onto a little sister.
        if found is not None and world.sister_relation(lane, found[0]) == world.SISTER_LITTLE:
            return (found[0], found[1], world.MERGE_RIGHT, REASON_KEEP)
    return None


def hold_merge_speed(cars_list) -> None:
    """
    Floor the speed of cars astride a seam so a lane change always completes.

    A flow onto a daughter crosses nothing, so it brakes like any other cell.
    """
    for car in cars_list:
        if getattr(car, "motion_mode", "lane") != "merge":
            continue
        if getattr(car, "merge_reason", "") == REASON_FLOW:
            continue
        if car.speed_scale < MERGE_MIN_SCALE:
            car.speed_scale = MERGE_MIN_SCALE


def planned_step_lane(car) -> int | None:
    """
    The stepsister the itinerary says to cross onto next, or None.

    Only when the route's current step is the lane being driven, so a
    discretionary change onto a sister never mistakes the step for its own.
    A daughter is the same road carried on, not a step, so it is not one.
    """
    route = getattr(car, "route", ()) or ()
    idx = int(getattr(car, "route_index", 0))
    if not route or idx >= len(route):
        return None
    step = route[idx]
    if step.kind != routes.KIND_LANE or int(step.ref) != car.lane_index:
        return None
    nxt = routes.step_lane_after(route, idx)
    if nxt is None or nxt[0] == car.lane_index:
        return None
    if nxt[0] == world.lane_daughter(car.lane_index):
        return None
    return nxt[0]


def _step_choice(car, lane: int, pos: int, sides: str, occ: Occupancy, target_lane: int):
    """
    Cross onto the lane the itinerary names, anywhere along the shared run.

    Insists on a clear window while there is runway left, then yields only to
    cars ahead once the lane is about to end, as a forced exit does.
    """
    cells = world.get_lane_cells(lane)
    strict = (len(cells) - 1 - pos) > MERGE_EXIT_LOOKAHEAD
    for side in (world.MERGE_LEFT, world.MERGE_RIGHT):
        if sides not in (side, world.MERGE_BOTH):
            continue
        found = _first_clear_target(
            car, lane, pos, side, occ, strict=strict, only_lane=target_lane
        )
        if found is not None:
            return (found[0], found[1], side, REASON_STEP)
    return None


def _must_exit(lane: int, pos: int, cells: tuple[tuple[int, int], ...]) -> bool:
    """True on a lane that leads nowhere and is about to run out."""
    if world.lane_traffic_out(lane) or world.lane_daughter(lane) is not None:
        return False
    return (len(cells) - 1 - pos) <= MERGE_EXIT_LOOKAHEAD


def _exit_choice(car, lane: int, pos: int, sides: str, occ: Occupancy):
    """Merge back toward the through lane; whoever is ahead takes the gap."""
    candidates = []
    if sides in (world.MERGE_LEFT, world.MERGE_BOTH):
        candidates.append(world.MERGE_LEFT)
    if sides in (world.MERGE_RIGHT, world.MERGE_BOTH):
        candidates.append(world.MERGE_RIGHT)
    # Prefer a through lane over another dangling one.
    candidates.sort(key=lambda s: 0 if _side_leads_somewhere(lane, pos, s) else 1)
    for side in candidates:
        found = _first_clear_target(car, lane, pos, side, occ, strict=False)
        if found is not None:
            return (found[0], found[1], side, REASON_EXIT)
    return None


def _side_leads_somewhere(lane: int, pos: int, side: str) -> bool:
    found = world.merge_target(lane, pos, side, MERGE_FORWARD_CELLS)
    return bool(found and world.lane_exit_node(found[0]))


def _first_clear_target(
    car,
    lane: int,
    pos: int,
    side: str,
    occ: Occupancy,
    strict: bool,
    min_runway: int = 0,
    only_lane: int | None = None,
):
    """Longest runway whose landing cell is usable, shortening toward one cell."""
    for forward in range(MERGE_FORWARD_CELLS, 0, -1):
        found = world.merge_target(lane, pos, side, forward)
        if found is None:
            continue
        target_lane, target_pos = found
        if only_lane is not None and target_lane != only_lane:
            continue
        if min_runway:
            remaining = len(world.get_lane_cells(target_lane)) - 1 - target_pos
            if remaining < min_runway:
                continue
        if _gap_usable(car, lane, pos, target_lane, target_pos, forward, occ, strict):
            return (target_lane, target_pos)
    return None


def _gap_usable(
    car,
    lane: int,
    pos: int,
    target_lane: int,
    target_pos: int,
    forward_cells: int,
    occ: Occupancy,
    strict: bool,
) -> bool:
    """
    Check the target lane from the driver's blind spot through the gap ahead of
    the landing cell.

    A discretionary change needs the whole window clear. A forced exit only
    yields to cars ahead of the merging car; those behind it give way.
    """
    cells = world.get_lane_cells(lane)
    target_cells = world.get_lane_cells(target_lane)
    if not cells or not target_cells:
        return False
    heading = map_data.offset_for_direction(world.lane_direction(lane))
    mine = cells[pos]
    lo = target_pos - forward_cells - MERGE_GAP_BEHIND
    hi = target_pos + MERGE_GAP_AHEAD
    for other in occ.cars_on_lane(target_lane):
        if other is car:
            continue
        other_pos = int(getattr(other, "position_in_lane", -1))
        if other_pos < lo or other_pos > hi:
            continue
        if strict or other_pos == target_pos:
            return False
        other_cell = target_cells[other_pos]
        forward = (other_cell[0] - mine[0]) * heading[0] + (other_cell[1] - mine[1]) * heading[1]
        if forward > 0:
            return False
    return True


def _blocked_by_slower(car, lane: int, pos: int, occ: Occupancy) -> bool:
    """A car close ahead on this lane that is slow enough to be worth passing."""
    mine = float(getattr(car, "base_speed_multiplier", 1.0))
    for other in occ.cars_on_lane(lane):
        if other is car:
            continue
        other_pos = int(getattr(other, "position_in_lane", -1))
        if other_pos <= pos or other_pos > pos + BLOCKER_LOOKAHEAD:
            continue
        if mine > float(getattr(other, "base_speed_multiplier", 1.0)) + MERGE_SPEED_MARGIN:
            return True
    return False
