"""
Police car for gridlock response.

Cops spawn on demand from the nearest place into a jammed intersection.
Home end of a lane is derived from traffic_in/traffic_out (place end), not map names.
"""
from __future__ import annotations

from dataclasses import dataclass

from sim.constants import POLICE_SPEED
from sim.movement import pose_for_lane_position
from sim.paths import direction_index_8_from_tangent, path_length, path_position, path_tangent
from sim.places import choose_next_lane_from_node
from sim import world

RED_ZERO_DURATION = 2.0
DISMISS_LINGER = 5.0
JAM_TRIGGER = 10
JAM_TRIGGER_SECOND = 20
COPS_PER_INTERSECTION = 2
# Last N inbound cells count toward jam / dismiss / holding cyan.
# Two cells cannot reach 10/20 on a min-size (2×2) two- or three-leg node.
# Inbound lanes shorter than this also pull in the attached intersection box (one hop).
INBOUND_TAIL_CELLS = 8

LIGHT_CYCLE = [(255, 255, 255), (60, 140, 220), (255, 255, 255), (220, 80, 80)]
LIGHT_PHASE_DURATION = 0.25 / 3


def _home_at_lane_start(lane_idx: int) -> bool:
    """
    Home is the place end of the lane.
    If traffic_in is a place, home is pos 0; if traffic_out is a place, home is len-1.
    """
    tin = world.lane_traffic_in(lane_idx)
    tout = world.lane_traffic_out(lane_idx)
    if tin and not world.is_intersection(tin):
        return True
    if tout and not world.is_intersection(tout):
        return False
    # Fallback: treat end toward intersection as home-at-len-1 (legacy Shopping-style).
    return False


def _intersection_center(key: str) -> tuple[float, float]:
    cells = world.get_intersection_cells_by_key(key)
    if not cells:
        return (0.0, 0.0)
    return (
        sum(c[0] for c in cells) / len(cells),
        sum(c[1] for c in cells) / len(cells),
    )


def _place_center(place_id: str) -> tuple[float, float] | None:
    rect = world.get_place_rects().get(place_id)
    if not rect:
        return None
    x = float(rect.get("x", 0))
    y = float(rect.get("y", 0))
    w = float(rect.get("w", 0))
    h = float(rect.get("h", 0))
    return (x + w / 2.0, y + h / 2.0)


def place_on_lane_for_intersection(lane_idx: int, intersection_id: str) -> str | None:
    """Place id at the other end of a lane that touches this intersection, else None."""
    tin = world.lane_traffic_in(lane_idx)
    tout = world.lane_traffic_out(lane_idx)
    if tin == intersection_id and tout and not world.is_intersection(tout):
        return tout
    if tout == intersection_id and tin and not world.is_intersection(tin):
        return tin
    return None


def _path_car_in_box(car, intersection_id: str) -> bool:
    if getattr(car, "motion_mode", "lane") != "path":
        return False
    cell = car.current_cell()
    return cell is not None and world.cell_in_intersection(cell, intersection_id)


def _inbound_tail(car, intersection_id: str) -> bool:
    """True if the car is in the last INBOUND_TAIL_CELLS of a lane approaching this node."""
    if getattr(car, "motion_mode", "lane") == "path":
        return False
    if world.lane_traffic_out(car.lane_index) != intersection_id:
        return False
    lane = car.get_lane()
    if not lane:
        return False
    return car.position_in_lane >= max(0, len(lane) - INBOUND_TAIL_CELLS)


def _short_inbound_attached_intersections(intersection_id: str) -> frozenset[str]:
    """
    Other intersections at the far end of inbound lanes shorter than INBOUND_TAIL_CELLS.
    One hop only: their boxes count, not their inbound lanes.
    """
    attached: set[str] = set()
    for i in world.lane_ids():
        if world.lane_traffic_out(i) != intersection_id:
            continue
        lane = world.get_lane_cells(i)
        if not lane or len(lane) >= INBOUND_TAIL_CELLS:
            continue
        src = world.lane_traffic_in(i)
        if src and src != intersection_id and world.is_intersection(src):
            attached.add(src)
    return frozenset(attached)


def _inbound_red_tail(car, intersection_id: str) -> bool:
    return _inbound_tail(car, intersection_id) and getattr(car, "visibility_state", "green") == "red"


def in_node_jam(car, intersection_id: str) -> bool:
    """Path cars in the box, inbound tails, or path cars in short-hop attached boxes."""
    if _path_car_in_box(car, intersection_id) or _inbound_tail(car, intersection_id):
        return True
    return any(
        _path_car_in_box(car, other)
        for other in _short_inbound_attached_intersections(intersection_id)
    )


def intersection_jam_score(cars_list, intersection_id: str) -> int:
    """Occupancy for spawn: this box + red inbound tails + path cars in short-hop attached boxes."""
    attached = _short_inbound_attached_intersections(intersection_id)
    score = 0
    for car in cars_list:
        if _path_car_in_box(car, intersection_id):
            score += 1
        elif _inbound_red_tail(car, intersection_id):
            score += 1
        elif any(_path_car_in_box(car, other) for other in attached):
            score += 1
    return score


def intersection_dismiss_score(cars_list, intersection_id: str) -> int:
    """Remaining jam: red-in-box + red inbound tails + red path cars in short-hop attached boxes."""
    attached = _short_inbound_attached_intersections(intersection_id)
    score = 0
    for car in cars_list:
        if _path_car_in_box(car, intersection_id):
            if getattr(car, "visibility_state", "green") == "red":
                score += 1
        elif _inbound_red_tail(car, intersection_id):
            score += 1
        elif any(_path_car_in_box(car, other) for other in attached):
            if getattr(car, "visibility_state", "green") == "red":
                score += 1
    return score


def pick_deploy_lane(intersection_id: str, used_lanes: set[int] | None = None) -> int | None:
    """Nearest place-connected lane into the node; else any unused inbound."""
    used = set(used_lanes or ())
    ix, iy = _intersection_center(intersection_id)
    placed: list[tuple[float, int]] = []
    inbound_fallback: list[int] = []
    for i in world.lane_ids():
        if i in used:
            continue
        place_id = place_on_lane_for_intersection(i, intersection_id)
        if place_id:
            pc = _place_center(place_id)
            if pc is None:
                continue
            dist = (pc[0] - ix) ** 2 + (pc[1] - iy) ** 2
            placed.append((dist, i))
        elif world.lane_traffic_out(i) == intersection_id:
            inbound_fallback.append(i)
    if placed:
        placed.sort(key=lambda t: (t[0], t[1]))
        return placed[0][1]
    if inbound_fallback:
        inbound_fallback.sort()
        return inbound_fallback[0]
    return None


def spawn_police(intersection_id: str, deploy_lane: int) -> PoliceCar:
    """New cop already deploying from the home end of deploy_lane."""
    home_place = place_on_lane_for_intersection(deploy_lane, intersection_id) or ""
    car = PoliceCar(
        deploy_lane=deploy_lane,
        return_lane=deploy_lane,
        travel_lane=deploy_lane,
        target_intersection=intersection_id,
        current_node=intersection_id,
        dest_node=intersection_id,
        home_place=home_place,
        inbound_lane=deploy_lane,
        state="deploying",
        can_divert=True,
    )
    lane_len = car._lane_len(deploy_lane)
    home_at_0 = _home_at_lane_start(deploy_lane)
    if home_at_0:
        car.lane_pos = 0.0
        car.direction = 1
    else:
        car.lane_pos = float(max(0, lane_len - 1))
        car.direction = -1
    return car


@dataclass
class PoliceCar:
    """Police car state machine for gridlock response."""

    deploy_lane: int = 0
    return_lane: int = 0
    travel_lane: int = 0
    target_intersection: str = ""
    current_node: str = ""
    dest_node: str = ""
    home_place: str = ""
    inbound_lane: int | None = None
    state: str = "deploying"  # deploying | holding | diverting | returning | despawned
    motion: str = "lane"  # lane | path
    path_in: int = 0
    path_out: int = 0
    path_t: float = 0.0
    lane_pos: float = 0.0
    direction: int = 1
    light_phase: int = 0
    light_timer: float = 0.0
    red_zero_timer: float = 0.0
    linger_timer: float = 0.0
    depart_pending: bool = False
    can_divert: bool = True
    use_reverse: bool = False

    def _current_lane(self) -> int:
        return self.travel_lane

    def _lane_len(self, lane_idx: int | None = None) -> int:
        idx = lane_idx if lane_idx is not None else self._current_lane()
        lane = world.get_lane_cells(idx)
        return len(lane) if lane else 0

    def at_mouth(self) -> bool:
        """True when at the intersection end of the travel lane (holding, or just arriving)."""
        if self.state == "holding":
            return True
        if self.state != "deploying" or self.motion != "lane":
            return False
        lane_len = self._lane_len(self.travel_lane)
        if lane_len < 2:
            return False
        home_at_0 = _home_at_lane_start(self.travel_lane)
        if home_at_0:
            return self.lane_pos >= lane_len - 1.0
        return self.lane_pos <= 0.5

    def get_pose(self) -> tuple[float, float, int]:
        if self.motion == "path":
            gx, gy = path_position(self.path_in, self.path_out, self.path_t)
            dx, dy = path_tangent(self.path_in, self.path_out, self.path_t)
            di = direction_index_8_from_tangent(dx, dy)
            return (gx, gy, di)
        lane_idx = self._current_lane()
        lane = world.get_lane_cells(lane_idx)
        if not lane:
            return (0.0, 0.0, 0)
        gx, gy, di = pose_for_lane_position(lane_idx, self.lane_pos, self.direction)
        if self.at_mouth() and self.target_intersection:
            cx, cy = _intersection_center(self.target_intersection)
            dx, dy = cx - gx, cy - gy
            if dx * dx + dy * dy > 1e-9:
                di = direction_index_8_from_tangent(dx, dy)
        return (gx, gy, di)

    def get_light_color(self) -> tuple[int, int, int]:
        if self.state == "returning":
            return (255, 255, 255)
        return LIGHT_CYCLE[self.light_phase % len(LIGHT_CYCLE)]

    def begin_divert(self, dest_intersection: str) -> None:
        """Leave the current box toward dest; lights stay on. One tour only."""
        self.can_divert = False
        self.depart_pending = False
        self.use_reverse = False
        from_node = self.current_node or self.target_intersection
        self.state = "diverting"
        self.target_intersection = dest_intersection
        self.dest_node = dest_intersection
        self.begin_hop(from_node, dest_intersection, inbound=self.travel_lane)

    def begin_return_home(self) -> None:
        """Lights off; graph-route to the original deploy place, or reverse if none."""
        was = self.state
        self.depart_pending = False
        self.state = "returning"
        if not self.home_place:
            self._begin_reverse_home()
            return
        self.dest_node = self.home_place
        self.use_reverse = False
        if self.motion == "path":
            return
        if was in ("holding", "deploying"):
            from_node = self.current_node or self.target_intersection
            self.begin_hop(from_node, self.home_place, inbound=self.travel_lane)

    def begin_hop(self, from_node: str, dest: str, inbound: int | None) -> None:
        """Pick the next out-lane toward dest; cross the box when leaving an intersection."""
        if not dest:
            self._begin_reverse_home()
            return
        out = choose_next_lane_from_node(from_node, dest, inbound)
        if out is None:
            self._begin_reverse_home()
            return
        self.dest_node = dest
        sitting_on_outbound = (
            inbound is not None
            and world.is_intersection(from_node)
            and world.lane_traffic_in(inbound) == from_node
        )
        if sitting_on_outbound:
            self.motion = "lane"
            self.travel_lane = out
            self.return_lane = out
            self.lane_pos = 0.0
            self.direction = 1
            self.inbound_lane = out
            return
        if inbound is not None and world.is_intersection(from_node):
            self.motion = "path"
            self.path_in = inbound
            self.path_out = out
            self.path_t = 0.0
            return
        self.motion = "lane"
        self.travel_lane = out
        self.return_lane = out
        self.lane_pos = 0.0
        self.direction = 1
        self.inbound_lane = out

    def _begin_reverse_home(self) -> None:
        """Fallback: reverse along the current/original deploy lane to its place end."""
        self.state = "returning"
        self.use_reverse = True
        self.motion = "lane"
        self.travel_lane = self.deploy_lane
        self.return_lane = self.deploy_lane
        lane_len = self._lane_len(self.deploy_lane)
        home_at_0 = _home_at_lane_start(self.deploy_lane)
        if home_at_0:
            self.lane_pos = float(max(0, lane_len - 1))
            self.direction = -1
        else:
            self.lane_pos = 0.0
            self.direction = 1

    def _advance_path(self, dt: float) -> None:
        length = max(0.1, path_length(self.path_in, self.path_out))
        self.path_t += POLICE_SPEED * dt / length
        if self.path_t < 1.0:
            return
        self.motion = "lane"
        self.travel_lane = self.path_out
        self.return_lane = self.path_out
        self.lane_pos = 0.0
        self.direction = 1
        self.inbound_lane = self.path_out
        self.path_t = 1.0

    def _arrive_at_node(self, node: str | None) -> None:
        if not node:
            self.state = "despawned"
            return
        if self.use_reverse:
            if not world.is_intersection(node):
                self.state = "despawned"
            return
        if not world.is_intersection(node):
            if self.state == "returning" and node == (self.dest_node or self.home_place):
                self.state = "despawned"
                return
            self.current_node = node
            self.begin_hop(node, self.dest_node, inbound=None)
            return
        self.current_node = node
        if self.state == "diverting" and node == self.dest_node:
            self.state = "holding"
            self.target_intersection = node
            self.red_zero_timer = 0.0
            self.linger_timer = 0.0
            self.depart_pending = False
            lane_len = self._lane_len(self.travel_lane)
            self.lane_pos = float(max(0, lane_len - 1))
            self.direction = 1
            return
        self.begin_hop(node, self.dest_node, inbound=self.travel_lane)

    def _advance_lane(self, dt: float) -> None:
        lane_len = self._lane_len()
        if lane_len < 2:
            self.state = "despawned"
            return
        self.lane_pos += POLICE_SPEED * dt * self.direction
        if self.direction >= 0:
            if self.lane_pos >= lane_len - 1.0:
                self.lane_pos = float(lane_len - 1)
                self._arrive_at_node(world.lane_traffic_out(self.travel_lane))
            else:
                self.lane_pos = min(float(lane_len - 1), self.lane_pos)
        else:
            if self.lane_pos <= 0.5:
                self.lane_pos = 0.0
                self._arrive_at_node(world.lane_traffic_in(self.travel_lane))
            else:
                self.lane_pos = max(0.0, self.lane_pos)

    def _advance_motion(self, dt: float) -> None:
        if self.motion == "path":
            self._advance_path(dt)
        else:
            self._advance_lane(dt)

    def tick(self, dt: float, node_score: int) -> None:
        if self.motion == "lane":
            lane_len = self._lane_len()
            if lane_len < 2:
                self.state = "despawned"
                return

        if self.state != "returning":
            self.light_timer += dt
            while self.light_timer >= LIGHT_PHASE_DURATION:
                self.light_timer -= LIGHT_PHASE_DURATION
                self.light_phase = (self.light_phase + 1) % len(LIGHT_CYCLE)

        if self.state == "despawned":
            return

        if self.state == "deploying":
            lane_len = self._lane_len(self.travel_lane)
            home_at_0 = _home_at_lane_start(self.travel_lane)
            if home_at_0:
                arrived = self.lane_pos >= lane_len - 1.0
            else:
                arrived = self.lane_pos <= 0.5
            if arrived:
                self.state = "holding"
                self.current_node = self.target_intersection
                self.lane_pos = 0.0 if not home_at_0 else float(lane_len - 1)
                self.red_zero_timer = 0.0
                self.linger_timer = 0.0
                self.depart_pending = False
                return
            advance = POLICE_SPEED * dt * self.direction
            self.lane_pos += advance
            self.lane_pos = max(0.0, min(float(lane_len - 1), self.lane_pos))
            return

        if self.state == "holding":
            if self.red_zero_timer < RED_ZERO_DURATION:
                if node_score <= 1:
                    remaining_confirm = RED_ZERO_DURATION - self.red_zero_timer
                    applied = min(dt, remaining_confirm)
                    self.red_zero_timer += applied
                    dt_linger = dt - applied
                else:
                    self.red_zero_timer = 0.0
                    self.linger_timer = 0.0
                    self.depart_pending = False
                    return
                if self.red_zero_timer < RED_ZERO_DURATION:
                    return
                self.linger_timer += dt_linger
            else:
                self.linger_timer += dt
            if self.linger_timer >= DISMISS_LINGER:
                if node_score <= 1:
                    self.depart_pending = True
                else:
                    self.red_zero_timer = 0.0
                    self.linger_timer = 0.0
                    self.depart_pending = False
            return

        if self.state in ("diverting", "returning"):
            self._advance_motion(dt)
