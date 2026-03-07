# Stoplights Agent Context Digest

**Purpose:** Handoff document for the next agent. Critical context to avoid regressions and wasted effort.

---

## Project Overview

Stoplights is an isometric traffic simulation (Python + Arcade). Cars spawn at four places (Housing, Office, Park, Shopping), route through a central intersection, and exhibit visibility-based behavior (red/yellow/green). Police cars deploy on gridlock (red count threshold) and influence nearby cars to clear jams. Target scale: 10–20× current vehicle count; user-editable maps planned.

---

## Architecture (Post-Refactor)

### Sim Layer (`sim/`)
- **No Arcade imports.** Pure simulation logic.
- **`game.py`** — Orchestrator. `GameState.tick()` calls spawner, visibility, impasse, movement, police.
- **`movement.py`** — Car and police lane movement; `_advance_car`, segment interpolation, pose computation.
- **`visibility.py`** — `forward_right_vectors`, `visibility_zone_band`, spatial bucketing, visibility state loop.
- **`impasse.py`** — Mutual-red detection, impasse timers, white override.
- **`spawner.py`** — Spawn timing, car creation, place selection.
- **`cop.py`** — Police state machine (idle → deploying → holding → returning → despawned).
- **`cars.py`** — `Car` dataclass (slots=True), `spawn_car()`.
- **`places.py`** — Place names, `LANES_BY_PLACE`, `OUT_LANE_BY_PLACE`, `STRAIGHT_TRANSITIONS`, `U_TURN_TRANSITIONS`, `place_bounds()`.
- **`world.py`** — `ALL_LANES`, `GRID_W`, `GRID_H`, `get_intersection_cells()`, `intersection_center()`, `intersection_cell_for_transition()`.
- **`paths.py`** — `path_position`, `path_tangent`, `path_length`, `lane_segment_position`, `lane_segment_tangent`, `direction_index_8_from_tangent`.
- **`map_data.py`** — Loads lanes/intersection/places from JSON; `assets/map.json` overrides defaults.
- **`constants.py`** — Single source for `TILE_W`, `TILE_H`, `CAR_SIZE`, visibility zone, colors, timing.

### Render Layer (`render/`)
- **`camera.py`** — `grid_to_screen(gx, gy, center_x, center_y)`; isometric projection.
- **`sprites.py`** — `CarSpritePool`, lane/intersection texture loading; sprite pooling for scale.
- **`debug.py`** — `visibility_fan_vertices`, perf text.

### UI
- **`ui.py`** — `Slider`, `Switch`; uses `draw_compat.rect_filled` for Arcade 2.x/3.x compat.
- **`draw_compat.py`** — Shared rectangle draw shim.

### Entry
- **`main.py`** — Thin orchestrator: window, game loop, input, draw dispatch. Uses `render/*` and `sim/*`.

---

## Key Conventions

1. **Isometric grid:** `TILE_W=12`, `TILE_H=6`. Grid y increases north. `grid_to_screen` maps grid → screen.
2. **Eight directions:** 0=N, 1=NE, 2=E, 3=SE, 4=S, 5=SW, 6=W, 7=NW. Used for car sprites and lane cardinal mapping.
3. **Lane indices:** 0,1 N; 2,3 S; 4,5 Park (E); 6,7 Shopping (W). Inbound = 0,2,4,6; outbound = 1,3,5,7.
4. **Sprite scale:** Lane tiles 1.5; car sprites 1.5. Use `pixelated=True` on `SpriteList.draw()` for crisp pixels.
5. **Police:** Two cops — Shopping (lane 7, trigger 10), Park (lane 5 southerly, trigger 20). `deploy_home_at_0`/`return_home_at_0` for Park.
6. **Car tinting:** Arcade multiplicative; body takes `car.color`, tires (#292929) stay dark. No special masking.

---

## Lane Sprite Mapping

| Lanes | Cardinal | Texture |
|-------|----------|---------|
| 0, 1  | N        | lane_N.png |
| 2, 3  | S        | lane_S.png |
| 4, 5  | E        | lane_E.png |
| 6, 7  | W        | lane_W.png |

Each road arm uses two opposing direction sprites (e.g. N and S for Housing–Office). Yellow edge on inside when bookmatched.

---

## Gotchas & Past Fixes

- **PowerShell:** Use `;` not `&&` for command chaining.
- **Cop2 Park lane:** Must use southerly Park lane (5), not 4. `deploy_home_at_0=True`, `return_home_at_0=True` for Park.
- **Cop dismiss:** Red count ≤ 1 (not 0) to dismiss.
- **U-turn bug:** `STRAIGHT_TRANSITIONS` must not overlap `U_TURN_TRANSITIONS`; (4,5) and (6,7) are U-turns.
- **Car dataclass:** `slots=True`; non-default fields must come before defaulted ones.
- **Instacrash:** Often draw-related (e.g. missing texture, bad `SpriteList`). Check `pixelated=True` and texture paths.
- **Spatial hash:** Rebuilt in-place each tick; persistence added for scaling.

---

## Assets

- `assets/grid_background.png` — Static 800×600 grid; no procedural draw.
- `assets/intersection.png` — Central intersection sprite.
- `assets/lane_N.png`, `lane_S.png`, `lane_E.png`, `lane_W.png` — Four cardinal lane tiles (rhombus, edge stripes).
- `assets/car_N.png` … `car_NW.png` — Eight direction car sprites.
- `assets/map.json` — Optional override for lanes, intersection, places.

---

## Scripts (Pillow)

- `scripts/generate_grid_sprite.py`
- `scripts/generate_intersection_sprite.py`
- `scripts/generate_lane_sprites.py`
- `scripts/generate_car_sprites.py`

All import from `sim.constants` for `TILE_W`, `TILE_H`, etc.

---

## Performance Notes

- Ticks: 60/s, max 8 substeps/frame.
- Car sprite pooling in `render/sprites.py`; no per-frame `Sprite` allocation.
- Impasse checks narrowed to intersection/approach candidates.
- Perf stats: FPS, substeps, draw ms, tick ms, visibility ms, pair checks. Toggle with `G` (if wired).

---

## Planned / In Progress

- User-editable maps (lane/place data already decoupled via `map_data.py`).
- UI dialogs (sliders/switches in containers).
- Camera zoom/scroll.
- Tiled environment for texture mating.
