# Stoplights — Game Requirements

**Version:** 0.2 (draft)  
**Status:** In development — advance as features are decided.  
**Last updated:** 2025-03-06

---

## Purpose

Living requirements document for Stoplights. Features are captured here as they are scoped and approved.

---

## Vision (out of scope for this iteration)

Stoplights aims to be a detailed traffic controls simulator in a Chris Sawyer–like environment: scheduled traffic generation, backups, crashes, emergency vehicles, construction, and the like. All of that is future scope; this iteration focuses on the four features below.

---

## Feature Priority (this iteration)

1. **Dialogs** — place vars, then car deets  
2. **Tiles** — texture mating (ortho → iso transform)  
3. **Zoom** — discrete levels, scroll  
4. **Editable maps** — lanes, places, save/load scenarios  

---

## 1. User-editable maps

### Decisions

- **Editor:** In-game only. Savable/loadable for developing and playing scenarios.
- **Scope:** Lanes and places for now. Intersection types and traffic control devices later. Places need editable spawn/attract vars.
- **Persistence:** Support multiple named maps.
- **Validation:** Soft reject — user can place, but geometry and game logic do not "hook up" until valid. Path of least resistance.

### Requirements

| ID | Requirement | Status |
|----|-------------|--------|
| MAP-1 | In-game map editor; no external tool dependency | Draft |
| MAP-2 | Editable: lanes, places (spawn rate, attract rate) | Draft |
| MAP-3 | Save/load multiple named map files | Draft |
| MAP-4 | Soft validation: allow placement; geometry/logic only connect when valid | Draft |
| MAP-5 | Intersection types and traffic control devices deferred | Deferred |

---

## 2. UI dialogs

### Decisions

- **Content order:** Place vars first (spawn rate, attract rate); car deets second (speed, origin, destination).
- **Layout:** Overlays. Draggable, X (Esc) to close, multiple open ok, title bar at top.
- **Input:** Mouse and basic keyboard shortcuts.

### Requirements

| ID | Requirement | Status |
|----|-------------|--------|
| UI-1 | Place vars dialog: spawn rate, attract rate (editable) | Draft |
| UI-2 | Car deets dialog: speed, origin, destination | Draft |
| UI-3 | Overlay dialogs: draggable, title bar at top | Draft |
| UI-4 | Close via X button or Esc; multiple dialogs may be open | Draft |
| UI-5 | Mouse + keyboard shortcuts for common actions | Draft |

---

## 3. Camera zoom / scroll

### Decisions

- **Zoom:** Discrete. 5 steps. Min = full map view; max = 4 tiles bottom-to-top.
- **Scroll:** Edge pan, arrow keys.
- **Default:** Start zoomed to fit.

### Requirements

| ID | Requirement | Status |
|----|-------------|--------|
| CAM-1 | Discrete zoom: 5 steps | Draft |
| CAM-2 | Zoom range: full map (min) to 4-tiles-height (max) | Draft |
| CAM-3 | Scroll: edge pan + arrow keys | Draft |
| CAM-4 | Initial view: zoomed to fit | Draft |

---

## 4. Tiled environment (texture mating)

### Decisions

- **Problem:** Texture mating. Draw ortho raster textures; auto-transform to iso view. Current tiling is unsatisfactory.
- **Integration:** Replace current lane/intersection sprites. Future layers: buildings, signs, scenery. Need front-layer logic for all sprites (incl. cars).
- **Toolchain:** Source textures from image editor; runtime ortho→iso transform in Stoplights. No Tiled editor.

### Requirements

| ID | Requirement | Status |
|----|-------------|--------|
| TILE-1 | Ortho raster textures → automatic iso transform | Draft |
| TILE-2 | Replace lane/intersection sprites with new tiling system | Draft |
| TILE-3 | Front-layer logic applicable to all sprites (incl. cars) | Draft |
| TILE-4 | Extensible for future layers: buildings, signs, scenery | Draft |
| TILE-5 | Source textures from image editor; runtime ortho→iso transform | Draft |

---

## Requirements log (summary)

| ID | Requirement | Source | Status |
|----|-------------|--------|--------|
| MAP-1 | In-game map editor | Interview | Draft |
| MAP-2 | Editable lanes, places (spawn/attract) | Interview | Draft |
| MAP-3 | Multiple named maps save/load | Interview | Draft |
| MAP-4 | Soft validation on placement | Interview | Draft |
| UI-1 | Place vars dialog | Interview | Draft |
| UI-2 | Car deets dialog | Interview | Draft |
| UI-3 | Draggable overlay dialogs | Interview | Draft |
| UI-4 | X/Esc close; multiple open | Interview | Draft |
| UI-5 | Mouse + keyboard shortcuts | Interview | Draft |
| CAM-1 | Discrete zoom (5 steps) | Interview | Draft |
| CAM-2 | Zoom range (full map ↔ 4-tile height) | Interview | Draft |
| CAM-3 | Edge pan + arrow keys | Interview | Draft |
| CAM-4 | Start zoomed to fit | Interview | Draft |
| TILE-1 | Ortho→iso texture transform | Interview | Draft |
| TILE-2 | Replace lane/intersection sprites | Interview | Draft |
| TILE-3 | Front-layer logic for all sprites | Interview | Draft |
| TILE-4 | Extensible for buildings, signs, scenery | Interview | Draft |
| TILE-5 | Source textures from image editor; runtime ortho→iso | Interview | Draft |

---

## Changelog

| Date | Change |
|------|--------|
| 2025-03-06 | Initial draft; planned features + interview questions |
| 2025-03-06 | v0.2: Incorporated interview answers; requirements derived; vision noted |
