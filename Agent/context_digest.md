# Stoplights Agent Context Digest

**Purpose:** Handoff document for the next agent. Critical context to avoid regressions and wasted effort.

---

## Digest History

- **Prior digest** (undated): Sim refactor, visibility, impasse, police, lane sprites. Some details since superseded.
- **2025-03-06:** Ortho tile pipeline, bypass corner sprite, intersection dialogs, transparency trim, grass-under-corner.
- **2025-03-14:** Mobile places and intersections. PlaceGeometry (center-based); IntersectionConfig with center_x/y. NumberBox widget. Global traffic/speed sliders removed. Lanes derived from masters (places + intersections).
- **2026-08-25:** Universal map model. Schema 4 (`assets/maps/default.json` + `config.json`). Uniform intersections/lanes with `protected`. Straight/U-turn/police home derived; no `STRAIGHT_TRANSITIONS` / main-bypass-extra split. See `STATE-OF-THE-PROJECT.md`.
- **2026-08-25 (item 3):** Authored JSON cells are live world cells. No pad-shift. `world.get_bounds()` is the content AABB; camera/draw use those bounds.
- **2026-08-25 (unified Place):** Runtime `GameState.places` is one `Place` per id (geometry + spawn/attract + `protected`), matching schema 4. `PlaceGeometry` / `PlaceConfig` removed. `spawn_places` stays derived.
- **2026-08-25 (store names):** `GameState.intersections` and `GameState.lanes` match schema 4 (was `*_configs`). Overlapping intersections allowed. Unused one-junction blob APIs and `ALL_LANES`/`GRID_*` mirrors removed.
- **2026-08-25 (tee overlay):** Intersection type `tee` is draw-only. Through-road keeps dual-lane markings; stem side is grey; opposite side transparent. Occupancy remains a square AABB.
- **2026-08-25 (place names):** Place ids are the names. Editable in PlaceVarsDialog via `GameState.rename_place` (retargets keys, hints, cars). Collision with a place or intersection id is a no-op. `protected` is still delete-only.
- **2026-08-26 (lane draw):** Toolbar lane button is an iso road tile. Two-click cardinal draw (ghost preview; Add Lane dialog is readout). One lane per activation. Cancel: Esc key/chip, lane button, click off `get_bounds()`.
- **2026-08-26 (place draw):** Place button is the green iso `place_zone` tile. Two-or-three-corner AABB (1×1 same-cell C2; 1×N if C3 is on the locked edge). Backspace/`<-` pops the last click for place, lane, and intersection.
- **2026-08-26 (intersection draw):** Toolbar iso `road_cross`. Two-click centre-size: 2×2 ghost while aiming, second click is smallest even size whose `bounds_from_center` AABB contains hover (clamp 12). New Intersection dialog is a readout. Backspace/`<-` pops size back to centre.
- **2026-08-27 (infra rim):** Places, lanes, and intersections are **infrastructure**. Open vars dialogs get an iso-bevel selection rim (SW highlight, NE shadow).
- **2026-08-27 (grass close):** Clicking a grass cell dismisses open dialogs. Settings **Grass close** (default on). Draw tools still use map clicks for placement.
- **2026-08-27 (world colour grade):** Settings Colors (hue/sat) grade the world; UI ungraded; identity skips the pass.
- **2026-08-31 (filleted overlays):** Overlay `cross`/`tee` use corner fillets; `none` is the full-grey square; `x` loads as `cross`.

---

## Project Overview

Stoplights is an isometric traffic simulation (Python + Arcade). Cars spawn at places, route through intersections via a graph (`traffic_in`/`traffic_out`), and use visibility-based behavior. Police deploy on gridlock. Maps are schema-4 JSON; the engine does not hardcode Housing/main/lane-7.

### What’s There Now (High Level)

- **Schema 4 scenario.** Places / intersections / lanes / police / route_hints. `protected` replaces base_lane_count / core id sets.
- **Places and intersections are movable.** Center-based geometry. Commit rebuilds the world via `rebuild_world(place_rects, intersections, lanes)`. Overlapping intersections are allowed. Place names are the ids and can be renamed in the place dialog.
- **NumberBox, dialogs, toolbar editor, ortho→iso tiles, zoom/pan.** Lane tool is two-click cardinal draw; place tool is 2/3-corner AABB; intersection tool is two-click centre-size (min 2×2). Dialogs are live readouts. Backspace/`<-` undoes the last placement click. Open infrastructure vars dialogs show an iso-bevel selection rim. Settings Colors (hue/sat) grade the world; UI stays ungraded.
- **Default map** in `assets/maps/default.json` (not reconstructed in Python).

---

## Architecture (Post Universal Map)

### Sim Layer (`sim/`)
- **`scenario.py`** — Schema 4 load, migrate 3→4, apply, serialize.
- **`game.py`** — Orchestrator; `reset_to_defaults()` loads default.json.
- **`world.py`** — Dict of intersections + dict of stable lane ids; `lane_ids()`, `rebuild_world(...)`.
- **`map_data.py`** — Geometry helpers only (`build_lane_cells`, `snap_cardinal_end`, `aabb_from_corners`, `aabb_from_edge_and_hover`, `bounds_from_center`, `intersection_size_for_hover`, `derive_traffic`, `object_at_cell`).
- **`places.py`** — `Place` record; BFS routing; `route_hints`; semantic U-turn.
- **`paths.py`** — Straight when inbound/outbound tangent dot ≥ 0.9.
- **`cop.py`** — Home end derived from place occupancy on the lane.
- **`persistence.py`** — Schema 4 `config.json`.

### Display (`render/`)
- **`selection.py`** — Arcade-free iso AABB silhouette and iso-bevel rim bands (multiply shadow, screen highlight).
- **`color_grade.py`** — Window FBO + HSV shader. Settings hue/sat grade the world pass; identity (0° / 100%) skips it. UI draws after the blit.
- **`corner_gen.py`** — Ortho overlays: `none` is per-cell grey; `cross`/`tee` use `make_corner_fillet` (grass bite + curb) plus `make_straight_through` (continuing yellows).

### Key Conventions (updated)

1. Isometric grid: `ORTHO_TILE_SIZE=32`, `TILE_W=32`, `TILE_H=16`. Grid y increases north. Authored JSON cells = live world cells; `get_bounds()` is the AABB (hi exclusive).
2. Eight directions: 0=N … 7=NW.
3. Iterate with `world.lane_ids()` — ids need not be dense.
4. Delete only when `not entity.protected`.
5. Place names are the ids (shared routing-node namespace with intersections). Rename retargets identity; it is not a display alias.
6. Police home: place end of deploy/return lane.
7. Cop dismiss: red count ≤ 1.
8. **Infrastructure** = places, lanes, intersections (not cars). Selection rim follows open vars dialogs.

### Gotchas (still true / updated)

- PowerShell: `;` not `&&`.
- No `STRAIGHT_TRANSITIONS` / `U_TURN_TRANSITIONS` tables — do not reintroduce.
- Car dataclass: `slots=True`; field order matters.
- Draw crashes: textures / `pixelated=True`.
- Tests: `python -m tests.test_universal_map`.


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

- User-editable maps (lane/place data already decoupled; `GameState.places` persisted as schema-4 `places`).
- Lane positions derived algorithmically from intersection and place positions as masters.
- Camera zoom/scroll (partially implemented).
- More corner/intersection sprites using the arc-band pipeline.
