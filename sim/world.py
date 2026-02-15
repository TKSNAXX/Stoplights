"""
World grid and lane geometry.
Two locations (Housing south, Office north), two-way road with a 2×2 intersection midway.
Lanes are segments: Housing→inter, inter→Office, Office→inter, inter→Housing. Prep for more directions later.
"""
from __future__ import annotations

# Grid: 14 wide, 22 tall. Housing 6×6 at bottom (y 0..5), road, Office 6×6 at top (y 16..21), east arm + Park.
ROAD_LENGTH = 10  # total road cells per side (excluding intersection)
INTERSECTION_SIZE = 2
SEGMENT_LENGTH = (ROAD_LENGTH - INTERSECTION_SIZE) // 2  # 4 each side of intersection
GRID_W = 14
GRID_H = 6 + ROAD_LENGTH + 6  # 22

# Intersection: 2×2 midway. Road runs y 6..15; midway y=10,11. x=2,3.
_INTER_Y_LO, _INTER_Y_HI = 10, 12  # y in [10, 11]
INTERSECTION_CELLS = [(x, y) for x in (2, 3) for y in range(_INTER_Y_LO, _INTER_Y_HI)]

# Right-hand traffic: lanes are placed so traffic keeps to the right (in direction of travel).
# N–S arm: northbound = east side (higher x), southbound = west side (lower x).
# East arm (Park): inbound to intersection and outbound to Park use the two rows below.
_NORTHBOUND_X = 3
_SOUTHBOUND_X = 2
_PARK_INBOUND_Y = 11
_PARK_OUTBOUND_Y = 10

# Lane 0: Housing → intersection (in from south), northbound = right-hand
_LANE_0 = [(_NORTHBOUND_X, 6 + i) for i in range(SEGMENT_LENGTH)]
# Lane 1: intersection → Office (out to north), northbound
_LANE_1 = [(_NORTHBOUND_X, _INTER_Y_HI + i) for i in range(SEGMENT_LENGTH)]
# Lane 2: Office → intersection (in from north), southbound = right-hand
_LANE_2 = [(_SOUTHBOUND_X, 15 - i) for i in range(SEGMENT_LENGTH)]
# Lane 3: intersection → Housing (out to south), southbound
_LANE_3 = [(_SOUTHBOUND_X, _INTER_Y_LO - 1 - i) for i in range(SEGMENT_LENGTH)]
# Lane 4: Park → intersection (in from east), right-hand
_LANE_4 = [(7 - i, _PARK_INBOUND_Y) for i in range(SEGMENT_LENGTH)]
# Lane 5: intersection → Park (out to east), right-hand
_LANE_5 = [(4 + i, _PARK_OUTBOUND_Y) for i in range(SEGMENT_LENGTH)]

ALL_LANES: list[list[tuple[int, int]]] = [_LANE_0, _LANE_1, _LANE_2, _LANE_3, _LANE_4, _LANE_5]


def get_intersection_cells() -> list[tuple[int, int]]:
    """Return list of (gx, gy) that are part of the 2×2 intersection."""
    return list(INTERSECTION_CELLS)


if __name__ == "__main__":
    print("Lane count:", len(ALL_LANES))
    for i, lane in enumerate(ALL_LANES):
        print(f"  Lane {i}: len={len(lane)}, first={lane[0]}, last={lane[-1]}")
    print("Intersection:", INTERSECTION_CELLS)
