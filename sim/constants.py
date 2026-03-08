"""
Shared simulation/display constants.

Centralizing these reduces drift between runtime code and sprite-generation scripts.
"""
from __future__ import annotations

# Ortho source tile size (square); iso diamond = 2*TILE_W x 2*TILE_H
ORTHO_TILE_SIZE = 32

# Isometric tile half-size in pixels (diamond: width 2*TILE_W, height 2*TILE_H)
TILE_W = 32
TILE_H = 16

# Car procedural fallback geometry and placeholder sprite shape
CAR_SIZE = 22
CAR_TRIANGLE_BASE_HALF = 4

# Visibility zone geometry (grid-space)
VIS_ZONE_LENGTH_CELLS = 2.0
VIS_ZONE_WIDTH_CELLS = 1.0

# Common palette values
LANE_UPWARD_GREY = (95, 95, 95)
LANE_DOWNWARD_GREY = (80, 80, 80)
PLACE_LABEL_COLOR = (220, 220, 220)
CAR_DEFAULT = (220, 60, 60)

# Behavior tuning
IMPASSE_DURATION = 2.0
IMPASSE_SPEED_SCALE = 0.3
POLICE_SPEED = 5.0
POLICE_PRIORITY_SCALE = 0.3
