"""
Police car for gridlock response.
Spawns when red car count >= red_trigger; returns when count stays 0 for 2s.
Configurable deploy_lane (home→intersection) and return_lane (intersection→home).
"""
from __future__ import annotations

from dataclasses import dataclass

from sim.constants import POLICE_PRIORITY_SCALE, POLICE_SPEED
from sim.movement import pose_for_lane_position
from sim import world

RED_ZERO_DURATION = 2.0

# Light cycle: white(0) -> blue(1) -> white(2) -> red(3)
LIGHT_CYCLE = [(255, 255, 255), (60, 140, 220), (255, 255, 255), (220, 80, 80)]
LIGHT_PHASE_DURATION = 0.25 / 3


@dataclass
class PoliceCar:
    """Police car state machine for gridlock response."""

    deploy_lane: int = 7  # lane from home toward intersection (e.g. 7=Shopping, 4=Park inbound)
    return_lane: int = 7  # lane from intersection toward home (same as deploy for 2-way arms)
    red_trigger: int = 10  # spawn when red_count >= this
    deploy_home_at_0: bool = False  # if True, home is at lane pos 0 (e.g. lane 4 Park); else at len-1 (e.g. lane 7 Shopping)
    return_home_at_0: bool = False  # if True, home is at lane pos 0 on return_lane (use when same lane both ways)
    state: str = "idle"  # idle | deploying | holding | returning | despawned
    lane_pos: float = 0.0  # continuous position on current lane (0=intersection end, len-1=home end)
    direction: int = 1  # +1 toward home, -1 toward intersection
    light_phase: int = 0
    light_timer: float = 0.0
    red_zero_timer: float = 0.0  # seconds with red_count <= 1 while holding

    def _current_lane(self) -> int:
        """Lane index for current state: deploy_lane when deploying/holding, return_lane when returning."""
        return self.deploy_lane if self.state != "returning" else self.return_lane

    def _lane_len(self, lane_idx: int | None = None) -> int:
        idx = lane_idx if lane_idx is not None else self._current_lane()
        lane = world.get_lane_cells(idx)
        return len(lane) if lane else 0

    def get_pose(self) -> tuple[float, float, int]:
        """Return (gx, gy, dir_index_8) for rendering and detection."""
        lane_idx = self._current_lane()
        lane = world.get_lane_cells(lane_idx)
        if not lane:
            return (0.0, 0.0, 0)
        return pose_for_lane_position(lane_idx, self.lane_pos, self.direction)

    def get_light_color(self) -> tuple[int, int, int]:
        """Current light color; white when returning (lights off)."""
        if self.state == "returning":
            return (255, 255, 255)
        return LIGHT_CYCLE[self.light_phase % len(LIGHT_CYCLE)]

    def tick(
        self,
        dt: float,
        red_count: int,
    ) -> None:
        """Advance state and movement."""
        lane_len = self._lane_len()
        if lane_len < 2:
            return

        # Light flash
        if self.state != "returning":
            self.light_timer += dt
            while self.light_timer >= LIGHT_PHASE_DURATION:
                self.light_timer -= LIGHT_PHASE_DURATION
                self.light_phase = (self.light_phase + 1) % len(LIGHT_CYCLE)

        if self.state in ("idle", "despawned"):
            if red_count >= self.red_trigger:
                self.state = "deploying"
                lane_len = self._lane_len(self.deploy_lane)
                if self.deploy_home_at_0:
                    self.lane_pos = 0.0
                    self.direction = 1  # toward intersection (len-1)
                else:
                    self.lane_pos = float(lane_len - 1)
                    self.direction = -1  # toward intersection (0)
            return

        if self.state == "deploying":
            lane_len = self._lane_len(self.deploy_lane)
            # Arrive: near intersection end (0 for home-at-len-1, len-1 for home-at-0)
            if self.deploy_home_at_0:
                arrived = self.lane_pos >= lane_len - 0.5
            else:
                arrived = self.lane_pos <= 0.5
            if arrived:
                self.state = "holding"
                self.lane_pos = 0.0 if not self.deploy_home_at_0 else float(lane_len - 1)  # intersection end
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
                    if self.return_home_at_0:
                        self.lane_pos = float(lane_len - 1)  # start at intersection end
                        self.direction = -1  # toward home (pos 0)
                    else:
                        self.lane_pos = 0.0  # start at intersection end
                        self.direction = 1   # toward home (len-1)
            else:
                self.red_zero_timer = 0.0
            return

        if self.state == "returning":
            lane_len = self._lane_len(self.return_lane)
            advance = POLICE_SPEED * dt * self.direction
            self.lane_pos += advance
            if self.return_home_at_0:
                arrived = self.lane_pos <= 0.5
                self.lane_pos = max(0.0, self.lane_pos)
            else:
                arrived = self.lane_pos >= lane_len - 1
                self.lane_pos = min(float(lane_len - 1), self.lane_pos)
            if arrived:
                self.state = "despawned"
                self.lane_pos = 0.0 if self.return_home_at_0 else float(lane_len - 1)
            return
