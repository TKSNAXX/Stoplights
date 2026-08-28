# Stoplights — State of the Project

**As of:** 2026-08-28 (cop linger, graph divert, full-lane spawn)  
**Status:** Playable prototype / in-game editor-lite. Not a shippable game.  
**Stack:** Python 3 + Arcade (`arcade>=2.6.0`). Entry point: `python main.py` from `Stoplights/`.

This is the current-state snapshot. Read it first. The other Agent files are supporting material, not all of it still true.

| File | Role |
|------|------|
| **This file** | What exists, what works, what is broken or unfinished, where to go next. |
| `PROJECT-BRIEF.md` | Original intent and first-pass spec (Feb 2026). Historical. The red-cubes-on-a-grid version is long behind us. |
| `game_reqs.md` | Living requirements v0.2 (last updated 2025-03-06). Dialogs, tiles, zoom, and editable maps were listed as draft; most of that is now in, if unfinished. Traffic signals remain deferred. |
| `context_digest.md` | Agent handoff: architecture map, conventions, gotchas. Still useful; some details may lag this file. |

---

## 1. What this game is

**Vision:** A Chris Sawyer / RCT-scale isometric sandbox about micromanaging traffic — lane by lane, hour by hour — that eventually captures the mess of real road construction. Cars have origins and destinations. Places generate and attract demand. Roads are discrete directed lanes that start and stop at intersections. Long-term flavour: scheduled demand, backups, crashes, emergency vehicles, construction, Steam if it is fun.

**What it is today:** A self-running isometric traffic sim with a working (if rough) in-game editor. There is still **no stoplight**. Cars use a visibility cone (green / yellow / red), an impasse white-override when two cars deadlock, and police that spawn on demand from the nearest place into a jammed intersection (max two per node at local scores 10/20). After a 2s dismiss confirm they linger 5s, then graph-divert as a second cop to another jammed node or go home. Places do not spawn onto a packed outbound lane. Demand is steady, not time-of-day.

The name is a promise, not a feature.

---

## 2. How far we got

The first pass was: one 2×2 crossroad, four 6×6 places, grey lanes, red cubes, no player input. That plan is complete and then some.

### Universal map model (2026-08-25)

The engine no longer special-cases `main` / `bypass` / “extra” or the original twelve lane indices.

- **Schema 4** is the lingua franca for `assets/maps/default.json` and `config.json`. Runtime `GameState.places` is one `Place` record per id (geometry + spawn/attract + `protected`) — same shape as JSON. `spawn_places` is derived (outbound-lane eligibility), not a second store.
- Place names **are** those ids (map labels, `route_hints`, car origin/destination). They are editable in the place dialog; `GameState.rename_place` retargets the identity. Collision with another place or an intersection id is refused. `protected` still means delete-only.
- Places, intersections, and lanes are **infrastructure**: the authored occupancy cars use. Uniform records with a **`protected`** flag (delete refused when true). Types stay `Place` / `LaneConfig` / `IntersectionConfig`. Cars are not infrastructure.
- **`traffic_in` / `traffic_out`** derived from occupancy at lane endpoints.
- **Straight / turn / U-turn** from tangents and place identity — not hardcoded `(0,1)` tables.
- **Police** spawn on demand from the nearest place into a jammed intersection (max two per node at local 10/20). Home end of the deploy lane is the place. After 2s confirm + 5s linger they may graph-divert once as a second cop, else go home. `police` in schema 4 is empty (not authored units).
- **Route hints** (e.g. Housing↔Park via bypass) live in map data, not Python names.
- Stable **lane ids** as a dict (gaps allowed). `reset_to_defaults()` reloads `default.json`.
- Schema 3 saves migrate on load (living sandbox extras kept).

Headless check: `python -m tests.test_universal_map`.

### Shipped and real

- **Sim / display split.** `sim/` has no Arcade imports. `main.py` + `render/` + `ui.py` read sim state and draw.
- **World rebuild from config.** `world.rebuild_world(place_rects, intersections, lanes)` — one path for every junction. Authored cell coordinates are live world coordinates (`get_bounds()`); no pad-shift. Runtime stores match schema 4: `GameState.places`, `.intersections`, `.lanes`. Overlapping intersections are allowed.
- **Routing graph.** BFS next-hops over place/intersection nodes; optional `route_hints`.
- **Car motion.** Lane segments + turn arcs; visibility fans; spatial buckets; impasse; police.
- **Ortho → iso tiles**, dialogs, toolbar editor, discrete zoom/pan. Intersection overlay types: `x`, `corner`, `straight`, `tee`. Tee is draw-only (through-road markings + stem-side grey; opposite side transparent). Occupancy stays a square AABB.
- **Persistence.** Schema 4 `config.json`. Cars not saved. Debounced save + save-on-close.
- **Editable place names.** Place dialog `TextBox` commits via `rename_place` (keys, hints, live cars). Intersection rename is out of scope.
- **Mouse-drawn lanes.** Toolbar iso-road button enters a two-click cardinal tool (ghost preview; Add Lane dialog is a live readout). One lane per activation. Cancel via Esc (key or upper-left Esc chip), the lane button, or a click off the map island.
- **Mouse-drawn places.** Toolbar green iso `place_zone` button: two opposite corners finish a rect; a colinear second corner waits for a third (1×1 if C2 is the same cell; 1×N strip if C3 sits on the locked edge). New Place dialog is a readout. Backspace / upper-right `<-` undoes the last placement click for place, lane, and intersection tools.
- **Mouse-drawn intersections.** Toolbar iso `road_cross` button: a 2×2 ghost follows the cursor as centre; first click locks it, second click sets even size (2..12) to the smallest stamp whose occupancy contains the hover cell (`bounds_from_center`). New Intersection dialog is a readout (type / centre / size). One junction per activation. Backend stays `center_x/y` + even `size_cells`.
- **Infrastructure selection rim.** Opening a place / lane / intersection vars dialog rims that occupancy with an iso bevel: SW inner highlight, NE outer shadow, fading over a few screen pixels. Shadow multiplies the tiles; highlight screens — the pavement colour stays, only the edge contrast changes.
- **Grass close.** Clicking an empty grass cell dismisses open dialogs (Settings toggle; on by default). Not used while a draw tool is placing.
- **World colour grade.** Settings **Colors** (Hue 0–360°, Sat 0–200%) grade the map — tiles, cars, draw ghosts, selection rims, visibility fans — in one post-process pass. Dialogs, toolbar, Esc/`<-` chips, place/cardinal labels, and the perf overlay stay ungraded. Hue 0° and sat 100% skip the extra pass.
- **Perf overlay.** Always on; `V` toggles visibility fans.

### Present in data / UI but not wired

- **Lane `speed_limit`.** Stored and shown; not yet applied to movement.

### Explicitly not in this iteration

- Traffic signals / right-of-way devices.
- Time-of-day demand, crashes, construction.
- Named multi-map UI (one session save + one default file).
- Soft validation for invalid editor geometry (MAP-4).
- Algorithmic lane derivation from place/intersection masters only (endpoints are still authored).

---

## 3. Architecture

```
main.py          Window, game loop, input, draw
ui.py            Dialogs, toolbar, widgets
render/selection.py  Infra selection silhouette / rim bands
render/color_grade.py  World hue/sat post-process (FBO + HSV shader)
sim/
  scenario.py    Schema 4 load / migrate / apply / serialize
  game.py        GameState.places / intersections / lanes; reset loads default.json
  world.py       Uniform intersections + stable lane id dict; authored coords; get_bounds()
  map_data.py    Geometry helpers only (no named default map)
  places.py      Place record + graph routing + route_hints
  paths.py       Tangents, straight-by-dot, turn arcs
  cop.py         On-demand cops; jam score per intersection; place-end home
  persistence.py config.json schema 4
  …
assets/maps/default.json   Authored default scenario
config.json                Living session save (schema 4)
tests/test_universal_map.py
```

**Scenario contract (schema 4):** `places`, `intersections`, `lanes`, `police` (always `[]`; cops are spawned at runtime), `route_hints`, `spawn_balance`, `user_settings`. Entity ids may be named `main` / `Housing` in data; the engine treats them as opaque strings.

**Conventions:** Grid y increases north. Eight directions 0=N … 7=NW. Iterate lanes with `world.lane_ids()`, not `range(lane_count())`.

---

## 4. The living save (`config.json`)

Migrated from schema 3. May still contain sandbox extras (Place 1/2, overlapping `intersection_3` on main, lanes 0–21). That is intentional until cleaned in-editor. Reset = reload `assets/maps/default.json`.

---

## 5. How to run

```bash
cd Stoplights
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python main.py
python -m tests.test_universal_map
```

**Controls:** Click infrastructure for dialogs (selection rim); toolbar for new intersection/place/lane/settings. Lane: two-click cardinal. Place: two or three corners. Intersection: 2×2 centre, then size. Esc / Esc chip / tool button / off-island cancel. Backspace or `<-` pops the last placement click. Scroll zooms; arrows pan; `V` visibility fans. Settings: edge pan, grass close (click grass to dismiss dialogs).

---

## 6. Known gotchas

- **U-turns:** Semantic (same place on approach in and exit out). No index tables.
- **Police home:** Place end of the lane (`traffic_in` place → pos 0; `traffic_out` place → len−1).
- **Cop dismiss:** Remaining red jam for **that node** (red-in-box + red inbound tails in the last 8 cells; if an inbound is shorter, that attached intersection’s box as well, not its lanes) ≤ 1 for 2s confirm, then 5s linger (no mid-linger cancel; re-assess once at the end). Then graph-divert as 2nd cop to another jammed node with fewer than 2 cops, else home; abort divert if dest clears. Spawn occupancy 10/20 per node. No spawn onto a packed outbound lane (cell 0 taken or car count ≥ length; timer unspent). Path-in-box is occupancy membership (overlaps count). Holding or arriving-at-mouth cyans that node’s jam; in-transit (including divert) uses the cop’s fan. Rebuild prunes invalid cops instead of wiping the list.
- **Car dataclass:** `slots=True`; non-default fields first.
- **Draw crashes:** Missing texture / `pixelated=True`.
- **New junctions:** Only matter if lanes pierce them (occupancy at endpoints).
- **Authored = world:** JSON lane tiles and centres are the sim cells after rebuild. Draw iterates `get_bounds()`.
- **Place id = name:** Renaming retargets `places`, spawn maps, `route_hints`, and live cars. Empty or colliding names are no-ops. Intersection ids share that namespace.
- **Lane draw is one-shot:** finishing a lane exits the tool; it does not chain another draw.
- **Place draw:** 2-corner AABB or 3-corner extrude; Backspace/<- is a universal placement undo (does not cancel).
- **Intersection draw is one-shot:** 2×2 ghost while aiming; second click sizes. Even-size occupancy is slightly asymmetric (size 2 is `cx-1` and `cx`). Ghost uses `bounds_from_center`.
- **Infrastructure:** places, lanes, and intersections. Selection rim follows open vars dialogs, not draw-tool ghosts or cars.

---

## 7. What “bring it to ground” means next

1. Editor integrity / soft validation (MAP-4).
2. Wire `speed_limit`.
3. Asset pipeline check (ortho + car sprites).
4. Named maps UI.
5. Then a real signal at a junction.

Do not reintroduce named-map special cases in Python. Put map knowledge in JSON.

---

## 8. Working agreements

- Tiny, testable slices. Chat voice: Jeeves. Sim stays Arcade-free. Commit only when asked.

---

*End of snapshot.*
