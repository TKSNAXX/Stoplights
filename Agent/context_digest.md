# Stoplights Agent Context Digest

**Purpose:** Handoff document for the next agent. Critical context to avoid regressions and wasted effort.

---

## Digest History

- **Prior digest** (undated): Sim refactor, visibility, impasse, police, lane sprites. Some details since superseded.
- **2025-03-06:** Ortho tile pipeline, bypass corner sprite, intersection dialogs, transparency trim, grass-under-corner.
- **2025-03-14:** Mobile places and intersections. PlaceGeometry (center-based); IntersectionConfig with center_x/y. NumberBox widget. Global traffic/speed sliders removed. Lanes derived from masters (places + intersections).

---

## Project Overview

Stoplights is an isometric traffic simulation (Python + Arcade). Cars spawn at four places (Housing, Office, Park, Shopping), route through a central intersection and a bypass junction (Housing–Park direct), and exhibit visibility-based behavior (red/yellow/green). Police cars deploy on gridlock and influence nearby cars to clear jams. Target scale: 10–20× current vehicle count; user-editable maps planned.

### What’s There Now (High Level)

- **Places and intersections are movable.** Center-based geometry. Places: `PlaceGeometry` (center_x, center_y, width, length); intersections: `IntersectionConfig` (center_x, center_y, size_cells, type). Commit required for geometry changes.
- **Two intersections:** Main (4×4 cross, default center 18,24) and bypass (4×4 Housing–Park corner, default center 33,2). Both have explicit centers.
- **NumberBox:** Text box + arrows for numeric input. Replaces size slider. Global traffic/speed sliders removed.
- **Ortho tile pipeline:** 32×32 ortho PNGs; `render/tiles.py` transforms to iso.
- **Road tiles:** `grass`, `place_zone`, `road_n/s/e/w` (+ `_pass` variants), `road_cross`, `corner`.
- **Dialogs:** Place (spawn, attract, geometry + Commit), Lane, Intersection (type, center, size + Commit), Car details.
- **Lanes 8–11:** Housing–Park direct route; own junction (bypass). **Future:** Lanes derived from intersection/place positions as masters.

---

## Architecture (Post-Refactor)

### Sim Layer (`sim/`)
- **No Arcade imports.** Pure simulation logic.
- **`game.py`** — Orchestrator. `GameState.tick()` calls spawner, visibility, impasse, movement, police. Holds `intersection_configs` (main, bypass; each has center_x, center_y), `place_configs`, `place_geometry`, `lane_configs`.
- **`movement.py`** — Car and police lane movement; `_advance_car`, segment interpolation, pose computation.
- **`visibility.py`** — `forward_right_vectors`, `visibility_zone_band`, spatial bucketing, visibility state loop.
- **`impasse.py`** — Mutual-red detection, impasse timers, white override.
- **`spawner.py`** — Spawn timing, car creation, place selection.
- **`cop.py`** — Police state machine (idle → deploying → holding → returning → despawned).
- **`cars.py`** — `Car` dataclass (slots=True), `spawn_car()`.
- **`places.py`** — `PlaceGeometry`, `PlaceConfig`, `IntersectionConfig` (center_x, center_y), `place_bounds()` (from `world.get_place_rects()`).
- **`world.py`** — `ALL_LANES`, `GRID_W`, `GRID_H`, `get_place_rects()`, `rebuild_world(place_rects, main_center, main_size, bypass_center, bypass_size)`.
- **`paths.py`** — `path_position`, `path_tangent`, `path_length`, `lane_segment_position`, `lane_segment_tangent`, `direction_index_8_from_tangent`.
- **`map_data.py`** — `place_rects_from_geometry()`, `geometry_from_place_rects()`, `build_housing_park_route(place_rects, bypass_center, size)`.
- **`constants.py`** — Single source for `TILE_W`, `TILE_H`, `CAR_SIZE`, visibility zone, colors, timing.

### Render Layer (`render/`)
- **`camera.py`** — `grid_to_screen(gx, gy, center_x, center_y)`; isometric projection.
- **`tiles.py`** — `TileSet` loads ortho PNGs, `ortho_to_iso` (32×32→64×32), `ortho_to_iso_large` (128×128→256×128).
- **`sprites.py`** — `CarSpritePool`, car texture loading; sprite pooling for scale.
- **`debug.py`** — `visibility_fan_vertices`, perf text.

### UI
- **`ui.py`** — `NumberBox` (text box + arrows, min/max/step), `Slider`, `Dialog`, `PlaceVarsDialog`, `LaneVarsDialog`, `IntersectionVarsDialog`, `CarDeetsDialog`. `DialogManager` tracks `_focused_widget` for key routing.
- **`draw_compat.py`** — Shared rectangle draw shim.

### Entry
- **`main.py`** — Thin orchestrator: window, game loop, input, draw dispatch. Uses `render/*` and `sim/*`.

---

## Key Conventions

1. **Isometric grid:** `ORTHO_TILE_SIZE=32`, `TILE_W=32`, `TILE_H=16`. Grid y increases north. `grid_to_screen` maps grid → screen.
2. **Eight directions:** 0=N, 1=NE, 2=E, 3=SE, 4=S, 5=SW, 6=W, 7=NW. Used for car sprites and lane cardinal mapping.
3. **Lane indices:** 0–7 main; 8–11 bypass (Housing–Park). Inbound 0,2,4,6,8,10; outbound 1,3,5,7,9,11.
4. **Sprite scale:** Lane tiles 1.5; car sprites 1.5. Use `pixelated=True` on `SpriteList.draw()` for crisp pixels.
5. **Police:** Two cops — Shopping (lane 7, trigger 10), Park (lane 5 southerly, trigger 20). `deploy_home_at_0`/`return_home_at_0` for Park.
6. **Car tinting:** Arcade multiplicative; body takes `car.color`, tires (#292929) stay dark. No special masking.

---

## Road Tile Mapping

- **Per-cell:** `grass`, `place_zone`, `road_n`, `road_s`, `road_e`, `road_w` (+ `_pass`). Intersection cells: `road_cross` or `corner`.
- **Corner sprite:** Multi-cell (4×4), 128×128 ortho → 256×128 iso. Arc bands: grey, wh, yel, yel, wh, grey. Transparency inner/outer; grass underneath.

---

## Gotchas & Past Fixes

- **PowerShell:** Use `;` not `&&` for command chaining.
- **Corner algo:** Use `_arc_bands_with_offset` for all bands; include grey borders in spec; clear inner segment to transparent; draw grass under bypass when corner mode.
- **Cop2 Park lane:** Must use southerly Park lane (5), not 4. `deploy_home_at_0=True`, `return_home_at_0=True` for Park.
- **Cop dismiss:** Red count ≤ 1 (not 0) to dismiss.
- **U-turn bug:** `STRAIGHT_TRANSITIONS` must not overlap `U_TURN_TRANSITIONS`; (4,5) and (6,7) are U-turns.
- **Car dataclass:** `slots=True`; non-default fields must come before defaulted ones.
- **Instacrash:** Often draw-related (e.g. missing texture, bad `SpriteList`). Check `pixelated=True` and texture paths.
- **Spatial hash:** Rebuilt in-place each tick; persistence added for scaling.

---

## Assets

- `assets/ortho/*.png` — Ortho tile sources (grass, place_zone, road_n/s/e/w, road_*_pass, road_cross, corner). Transformed to iso at load.
- `assets/car_N.png` … `car_NW.png` — Eight direction car sprites.
- `assets/map.json` — Optional override for lanes, intersection, places.

---

## Scripts (Pillow)

- **`scripts/generate_ortho_tiles.py`** — Produces 32×32 ortho tiles + 128×128 corner. Run `python -m scripts.generate_ortho_tiles`. Uses `_arc_bands_with_offset`, `CORNER_LANE_ALIGN_OFFSET`, `CORNER_BANDS_SPEC`.
- `scripts/generate_car_sprites.py` — Car direction sprites.
- `scripts/_archive/` — Legacy lane/intersection generators.

Import from `sim.constants` for `ORTHO_TILE_SIZE`, `TILE_W`, `TILE_H`.

---

## Performance Notes

- Ticks: 60/s, max 8 substeps/frame.
- Car sprite pooling in `render/sprites.py`; no per-frame `Sprite` allocation.
- Impasse checks narrowed to intersection/approach candidates.
- Perf stats: FPS, substeps, draw ms, tick ms, visibility ms, pair checks. Toggle with `G` (if wired).

---

## Planned / In Progress

- User-editable maps (lane/place data already decoupled; `place_geometry` persisted).
- Lane positions derived algorithmically from intersection and place positions as masters.
- Camera zoom/scroll (partially implemented).
- More corner/intersection sprites using the arc-band pipeline.
