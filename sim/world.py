"""
World grid and lane geometry.
Two locations (Housing south, Office north), two-way road with a 2×2 intersection midway.
Lanes are segments: Housing→inter, inter→Office, Office→inter, inter→Housing. Prep for more directions later.
"""
from __future__ import annotations

# Per-direction road lengths (cells from place to intersection, or intersection to place).
HOUSING_ROAD_LENGTH = 12  # Lane 0 and 3
OFFICE_ROAD_LENGTH = 9    # Lane 1 and 2
PARK_ROAD_LENGTH = 6      # Lane 4 and 5
SHOPPING_ROAD_LENGTH = 15 # Lane 6 and 7

# All places are 5×5.
PLACE_SIZE = 5
INTERSECTION_SIZE = 2

# Grid: width accommodates west arm (Shopping road + place) and east (intersection + Park road + place).
_WEST_ARM_WIDTH = 16  # columns for west arm; intersection and N–S/Park shift by this much
GRID_W = 15 + _WEST_ARM_WIDTH  # 31 (room for Park 5×5 at east end)
# Height: south place (5) + Housing road (12) + intersection (2) + Office road (9) + north place (5) = 33
GRID_H = PLACE_SIZE + HOUSING_ROAD_LENGTH + INTERSECTION_SIZE + OFFICE_ROAD_LENGTH + PLACE_SIZE  # 33

# Intersection: lane geometry uses 2×2-era bounds below; drawing and cell set use 3×3 box (so lanes do not move).
_INTER_Y_LO = PLACE_SIZE + HOUSING_ROAD_LENGTH  # 17
_INTER_Y_HI = _INTER_Y_LO + INTERSECTION_SIZE   # 19
_INTER_X_LO = 2 + _WEST_ARM_WIDTH   # 18
_INTER_X_HI = 4 + _WEST_ARM_WIDTH   # 20
# 3×3 intersection box for display and occupancy only (x 17..19, y 16..18; includes south/west lane endpoints).
_INTER_BOX_SIZE = 3
_INTER_BOX_X_LO = 17
_INTER_BOX_Y_LO = 16
INTERSECTION_CELLS = [(x, y) for x in range(_INTER_BOX_X_LO, _INTER_BOX_X_LO + _INTER_BOX_SIZE) for y in range(_INTER_BOX_Y_LO, _INTER_BOX_Y_LO + _INTER_BOX_SIZE)]

# Right-hand traffic: lanes are placed so traffic keeps to the right (in direction of travel).
# N–S arm: northbound = east side (higher x), southbound = west side (lower x).
_NORTHBOUND_X = 3 + _WEST_ARM_WIDTH  # 19
_SOUTHBOUND_X = 2 + _WEST_ARM_WIDTH  # 18
# East arm (Park) and west arm (Shopping): inbound/outbound rows aligned with intersection.
_PARK_INBOUND_Y = _INTER_Y_HI - 1   # 18
_PARK_OUTBOUND_Y = _INTER_Y_LO      # 17
_SHOPPING_INBOUND_Y = _INTER_Y_LO   # 17
_SHOPPING_OUTBOUND_Y = _INTER_Y_HI - 1  # 18

# Lane 0: Housing → intersection (in from south), northbound = right-hand. 12 cells, y 5..16.
_LANE_0 = [(_NORTHBOUND_X, PLACE_SIZE + i) for i in range(HOUSING_ROAD_LENGTH)]
# Lane 1: intersection → Office (out to north), northbound. 9 cells, y 19..27.
_LANE_1 = [(_NORTHBOUND_X, _INTER_Y_HI + i) for i in range(OFFICE_ROAD_LENGTH)]
# Lane 2: Office → intersection (in from north), southbound. 9 cells, y 27..19.
_LANE_2 = [(_SOUTHBOUND_X, PLACE_SIZE + HOUSING_ROAD_LENGTH + INTERSECTION_SIZE + OFFICE_ROAD_LENGTH - 1 - i) for i in range(OFFICE_ROAD_LENGTH)]
# Lane 3: intersection → Housing (out to south), southbound. 12 cells, y 16..5.
_LANE_3 = [(_SOUTHBOUND_X, _INTER_Y_LO - 1 - i) for i in range(HOUSING_ROAD_LENGTH)]
# Lane 4: Park → intersection (in from east), right-hand. 6 cells.
_LANE_4 = [(4 + _WEST_ARM_WIDTH + (PARK_ROAD_LENGTH - 1 - i), _PARK_INBOUND_Y) for i in range(PARK_ROAD_LENGTH)]
# Lane 5: intersection → Park (out to east), right-hand. 6 cells.
_LANE_5 = [(4 + _WEST_ARM_WIDTH + i, _PARK_OUTBOUND_Y) for i in range(PARK_ROAD_LENGTH)]
# Lane 6: Shopping → intersection (in from west), right-hand. 15 cells.
_LANE_6 = [(3 + i, _SHOPPING_INBOUND_Y) for i in range(SHOPPING_ROAD_LENGTH)]
# Lane 7: intersection → Shopping (out to west), right-hand. 15 cells.
_LANE_7 = [(3 + (SHOPPING_ROAD_LENGTH - 1 - i), _SHOPPING_OUTBOUND_Y) for i in range(SHOPPING_ROAD_LENGTH)]

ALL_LANES: list[list[tuple[int, int]]] = [_LANE_0, _LANE_1, _LANE_2, _LANE_3, _LANE_4, _LANE_5, _LANE_6, _LANE_7]

# Place bounds for 5×5 blocks at the end of each road (for place_bounds in places.py).
# N–S: 5-wide band centered on the road. Road x is _NORTHBOUND_X (19) and _SOUTHBOUND_X (18); center 18.5, so x 17..21 (5 cols).
_N_S_PLACE_X_LO = _SOUTHBOUND_X - 1  # 17
HOUSING_PLACE_X_LO = _N_S_PLACE_X_LO
OFFICE_PLACE_X_LO = _N_S_PLACE_X_LO
# Housing: y 0..4. Office: y (GRID_H - 5) .. (GRID_H - 1).
# Park place: east of Park road; road ends at x = 4 + _WEST_ARM_WIDTH + PARK_ROAD_LENGTH - 1 = 4+16+6-1 = 25, so place starts at 26.
PARK_PLACE_X_LO = 4 + _WEST_ARM_WIDTH + PARK_ROAD_LENGTH  # 26
# Park 5×5: x 26..30, y centered on intersection: 5 rows e.g. 15..19 (so intersection 17,18 is inside).
PARK_PLACE_Y_LO = _INTER_Y_LO - 2  # 15 (rows 15,16,17,18,19)
# Shopping: west end, 5×5 at x 0..4, y aligned with arm (e.g. 15..19 to match Park).
SHOPPING_PLACE_Y_LO = _INTER_Y_LO - 2  # 15

def get_intersection_cells() -> list[tuple[int, int]]:
    """Return list of (gx, gy) that are part of the 3×3 intersection."""
    return list(INTERSECTION_CELLS)


# One slot per inbound lane (4) within the 3×3; used for occupancy only.
_INTER_SLOT_CELLS = [(18, 16), (18, 18), (19, 17), (17, 17)]


def intersection_cell_for_transition(in_lane_index: int, out_lane_index: int) -> tuple[int, int]:
    """Return one of the four intersection cells for this (in, out) lane pair. Different inbound lanes use different cells so up to 4 cars can be in the intersection."""
    idx = in_lane_index // 2
    if idx < 0 or idx >= len(_INTER_SLOT_CELLS):
        idx = 0
    return _INTER_SLOT_CELLS[idx]


if __name__ == "__main__":
    print("Lane count:", len(ALL_LANES))
    for i, lane in enumerate(ALL_LANES):
        print(f"  Lane {i}: len={len(lane)}, first={lane[0]}, last={lane[-1]}")
    print("Intersection:", INTERSECTION_CELLS)
