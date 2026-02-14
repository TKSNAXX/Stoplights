"""
World grid and lane geometry.
Two locations (Housing south, Office north), one lane between them. No intersection.
"""
from __future__ import annotations

# Grid: 6 wide, 22 tall. Housing 6×6 at bottom (y 0..5), road (y 6..15), Office 6×6 at top (y 16..21).
ROAD_LENGTH = 10
GRID_W = 6
GRID_H = 6 + ROAD_LENGTH + 6  # 22

# Single lane: Housing (south) -> Office (north). Center column, road cells only.
_CX = 2
_LANE = [(_CX, 6 + i) for i in range(ROAD_LENGTH)]

ALL_LANES: list[list[tuple[int, int]]] = [_LANE]


if __name__ == "__main__":
    print("Lane count:", len(ALL_LANES))
    for i, lane in enumerate(ALL_LANES):
        print(f"  Lane {i}: len={len(lane)}, first={lane[0]}, last={lane[-1]}")
