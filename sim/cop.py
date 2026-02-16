"""
Police car for gridlock response.
Spawns when red car count >= 10; returns when count stays 0 for 2s.
Uses lane 7 (Shopping outbound): deploy against flow, return with flow.
"""
from __future__ import annotations

from dataclasses import dataclass

from sim.paths import (
    direction_index_8_from_tangent,
    lane_segment_position,
    lane_segment_tangent,
)
from sim.world import ALL_LANES, get_intersection_cells

POLICE_LANE = 7
RED_TRIGGER = 10
RED_ZERO_DURATION = 2.0
POLICE_SPEED = 5.0  # cells per second (similar to normal car pace)
POLICE_PRIORITY_SCALE = 0.3

# Light cycle: white(0) -> blue(1) -> white(2) -> red(3)
LIGHT_CYCLE = [(255, 255, 255), (60, 140, 220), (255, 255, 255), (220, 80, 80)]
LIGHT_PHASE_DURATION = 0.25


@dataclass
class PoliceCar:
    """Police car state machine for gridlock response."""

    state: str = "idle"  # idle | deploying | holding | returning
    lane_pos: float = 0.0  # continuous position on lane 7 (0=intersection, len-1=Shopping)
    direction: int = 1  # +1 toward Shopping, -1 toward intersection
    light_phase: int = 0
    light_timer: float = 0.0
    red_zero_timer: float = 0.0  # seconds with red_count == 0 while holding

    def _lane_len(self) -> int:
        lane = ALL_LANES[POLICE_LANE] if POLICE_LANE < len(ALL_LANES) else []
        return len(lane) if lane else 0

    def _intersection_center(self) -> tuple[float, float]:
        cells = get_intersection_cells()
        if not cells:
            return (0.0, 0.0)
        n = len(cells)
        return (sum(c[0] for c in cells) / n, sum(c[1] for c in cells) / n)

    def get_pose(self) -> tuple[float, float, int]:
        """Return (gx, gy, dir_index_8) for rendering and detection."""
        lane = ALL_LANES[POLICE_LANE] if POLICE_LANE < len(ALL_LANES) else []
        if not lane:
            return (0.0, 0.0, 0)
        n = len(lane)
        pos = max(0.0, min(float(n - 1), self.lane_pos))
        lo = int(pos)
        hi = min(lo + 1, n - 1)
        t = pos - lo
        gx, gy = lane_segment_position(POLICE_LANE, lo, hi, t)
        dx, dy = lane_segment_tangent(POLICE_LANE, lo, hi)
        if self.direction < 0:
            dx, dy = -dx, -dy
        di = direction_index_8_from_tangent(dx, dy)
        return (gx, gy, di)

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

        if self.state == "idle":
            if red_count >= RED_TRIGGER:
                self.state = "deploying"
                self.lane_pos = float(lane_len - 1)
                self.direction = -1
            return

        if self.state == "deploying":
            if self.lane_pos <= 0.5:
                self.state = "holding"
                self.lane_pos = 0.0
                self.red_zero_timer = 0.0
                return
            advance = POLICE_SPEED * dt * self.direction
            self.lane_pos += advance
            self.lane_pos = max(0.0, min(float(lane_len - 1), self.lane_pos))
            return

        if self.state == "holding":
            if red_count == 0:
                self.red_zero_timer += dt
                if self.red_zero_timer >= RED_ZERO_DURATION:
                    self.state = "returning"
                    self.lane_pos = 0.0
                    self.direction = 1
            else:
                self.red_zero_timer = 0.0
            return

        if self.state == "returning":
            advance = POLICE_SPEED * dt * self.direction
            self.lane_pos += advance
            if self.lane_pos >= lane_len - 0.5:
                self.state = "idle"
                self.lane_pos = float(lane_len - 1)
            else:
                self.lane_pos = min(float(lane_len - 1), self.lane_pos)
            return
