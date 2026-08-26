"""
Police car for gridlock response.

Home end of a lane is derived from traffic_in/traffic_out (place end), not map names.
"""
from __future__ import annotations

from dataclasses import dataclass

from sim.constants import POLICE_SPEED
from sim.movement import pose_for_lane_position
from sim import world

RED_ZERO_DURATION = 2.0

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


@dataclass
class PoliceCar:
    """Police car state machine for gridlock response."""

    deploy_lane: int = 7
    return_lane: int = 7
    red_trigger: int = 10
    state: str = "idle"  # idle | deploying | holding | returning | despawned
    lane_pos: float = 0.0
    direction: int = 1
    light_phase: int = 0
    light_timer: float = 0.0
    red_zero_timer: float = 0.0

    def _current_lane(self) -> int:
        return self.deploy_lane if self.state != "returning" else self.return_lane

    def _lane_len(self, lane_idx: int | None = None) -> int:
        idx = lane_idx if lane_idx is not None else self._current_lane()
        lane = world.get_lane_cells(idx)
        return len(lane) if lane else 0

    def get_pose(self) -> tuple[float, float, int]:
        lane_idx = self._current_lane()
        lane = world.get_lane_cells(lane_idx)
        if not lane:
            return (0.0, 0.0, 0)
        return pose_for_lane_position(lane_idx, self.lane_pos, self.direction)

    def get_light_color(self) -> tuple[int, int, int]:
        if self.state == "returning":
            return (255, 255, 255)
        return LIGHT_CYCLE[self.light_phase % len(LIGHT_CYCLE)]

    def tick(self, dt: float, red_count: int) -> None:
        lane_len = self._lane_len()
        if lane_len < 2:
            return

        if self.state != "returning":
            self.light_timer += dt
            while self.light_timer >= LIGHT_PHASE_DURATION:
                self.light_timer -= LIGHT_PHASE_DURATION
                self.light_phase = (self.light_phase + 1) % len(LIGHT_CYCLE)

        if self.state in ("idle", "despawned"):
            if red_count >= self.red_trigger:
                self.state = "deploying"
                lane_len = self._lane_len(self.deploy_lane)
                home_at_0 = _home_at_lane_start(self.deploy_lane)
                if home_at_0:
                    self.lane_pos = 0.0
                    self.direction = 1
                else:
                    self.lane_pos = float(lane_len - 1)
                    self.direction = -1
            return

        if self.state == "deploying":
            lane_len = self._lane_len(self.deploy_lane)
            home_at_0 = _home_at_lane_start(self.deploy_lane)
            if home_at_0:
                arrived = self.lane_pos >= lane_len - 0.5
            else:
                arrived = self.lane_pos <= 0.5
            if arrived:
                self.state = "holding"
                self.lane_pos = 0.0 if not home_at_0 else float(lane_len - 1)
                self.red_zero_timer = 0.0
                return
            advance = POLICE_SPEED * dt * self.direction
            self.lane_pos += advance
            self.lane_pos = max(0.0, min(float(lane_len - 1), self.lane_pos))
            return

        if self.state == "holding":
            if red_count <= 1:
                self.red_zero_timer += dt
                if self.red_zero_timer >= RED_ZERO_DURATION:
                    self.state = "returning"
                    lane_len = self._lane_len(self.return_lane)
                    home_at_0 = _home_at_lane_start(self.return_lane)
                    if home_at_0:
                        self.lane_pos = float(lane_len - 1)
                        self.direction = -1
                    else:
                        self.lane_pos = 0.0
                        self.direction = 1
            else:
                self.red_zero_timer = 0.0
            return

        if self.state == "returning":
            lane_len = self._lane_len(self.return_lane)
            home_at_0 = _home_at_lane_start(self.return_lane)
            advance = POLICE_SPEED * dt * self.direction
            self.lane_pos += advance
            if home_at_0:
                arrived = self.lane_pos <= 0.5
                self.lane_pos = max(0.0, self.lane_pos)
            else:
                arrived = self.lane_pos >= lane_len - 1
                self.lane_pos = min(float(lane_len - 1), self.lane_pos)
            if arrived:
                self.state = "despawned"
                self.lane_pos = 0.0 if home_at_0 else float(lane_len - 1)
            return
