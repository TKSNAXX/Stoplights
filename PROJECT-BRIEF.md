# Stoplights — Project Brief & Context

*Everything you’ve told me, captured in one place. Use this to bring a new agent (or future you) up to speed.*

---

## 1. The Big Picture

- **Stoplights** is an **isometric sandbox game** focused on **micromanaging traffic patterns** lane by lane, hour by hour.
- Long-term it’s a **sim that captures the complexity of road construction**.
- You’re a **total newbie developer** — we do everything **tiny-bit by tiny-bit**. No grand work that doesn’t immediately pay off; every step must be **digestible and testable** by you.
- You want **indie dev best practices** and may eventually release via **Steam** if it’s fun. You don’t know those practices yet; the agent is your **sensei as well as your butler** (Jeeves).

---

## 2. What You Want (Game Design)

- **Cars** are the thing flowing through the map. They have an **origin** and a **destination**. They must be able to **go and stop** based on what’s in front of them: no running into other cars, no blowing traffic signals (later). Eventually other elements will give them personalities that mix up the system.
- **Map** has **places**: Housing, Shopping, Offices, Parks, etc. For now each place is **discrete** (no roads inside neighbourhoods or parking lots). Throughout the day, each place will **generate or attract traffic** on a variable clock (e.g. offices attract morning, generate afternoon; shopping heavy afternoon, nothing at night). **For now we keep them steady.**
- **Roads** have **lanes** that cars occupy. Lanes have a **direction**. Eventually lanes will be **dynamic** (gameplay + car navigation). Roads cross at **intersections**; at an intersection, lanes start/stop and give options to enter lanes on different roads (or same road if continuing straight). A **lane is a discrete object between intersections** (not continuing through them).
- Everything occupies **grid space**, roughly **RCT (RollerCoaster Tycoon) scale**.

---

## 3. Tech Choices (What You Decided)

- **Backend in Python.** You’re good with **Method A**: all game logic and display in Python for now, with a **clear sim/display split** so the display could be swapped to another technology later if needed.
- **Engine / display**: **Arcade** (Python) chosen over Pygame — easier to grok, good docs. Use **simple isometric pixel graphics** (RCT-style but less detail). Placeholder art is fine while the display is developed; you have tools to make assets later.
- **Version control**: You’re setting up **Git**. The project should live in a **local directory managed by Git** (not only on Google Drive) so you can move the workspace and keep the agent’s context via the repo (rules, plan, code).

---

## 4. Voice / Behaviour in Chat

- You asked the agent to **speak like Jeeves** (P.G. Wodehouse) in chat: deferential, understated, impeccably polite; “sir”; dry warmth, not obsequious. This was committed to a **Cursor rule** in `.cursor/rules/jeeves-voice.mdc` so it persists in this workspace.

---

## 5. First Pass — What We’re Building

- **Tiny self-playing version**, no player input.
- **One crossroad** with **free-for-all** (no stoplight yet — just a stop sign idea later). Cars **stop whenever something blocks them**, then **resume when clear**.
- **Four places** at N, E, S, W:
  - **N: Office**
  - **E: Park**
  - **S: Housing**
  - **W: Shopping**
- **Roads**: ~10 spaces long between intersection and each place. **Intersection**: 2×2, **2 lanes × 2 lanes**. Two lanes make up two-way traffic on each road (2 toward center, 2 away).
- **Places**: each **6×6** grid cells.
- **Traffic**: steady flow between places (no time-of-day yet). Cars have origin and destination; they follow lanes, stop if blocked, go when clear.
- **Graphics (first pass)**:
  - **Land**: white isometric grid on **black** background (dark theme).
  - **Cars**: red cubes.
  - **Lanes**: broad grey lines.
  - **Intersection**: large grey area over its cells.

---

## 6. Execution Plan (High Level)

1. **Project setup** — Python, Arcade, folder structure (sim vs display), blank window runs.
2. **Isometric grid** — White grid on black; world size from spec (intersection 2×2, roads ~10, places 6×6).
3. **Sim: world and lanes** — Grid, intersection, four roads, lanes as discrete directed segments (no cars yet).
4. **Sim: places and car spawn** — Four places, steady spawn; cars have origin/destination and start on the correct lane.
5. **Sim: car movement and blocking** — Tick; cars advance unless blocked (free-for-all); simple path A → intersection → B; remove at destination.
6. **Display: lanes and intersection** — Grey lines and grey intersection from sim state.
7. **Display: cars and game loop** — Red cubes at car positions; fixed timestep loop; runs itself.

**Architecture**: Sim layer = pure Python (no Arcade). Display layer = Arcade, only reads sim state. So the display can be replaced later without rewriting game logic.

---

## 7. Moving the Project to a Local Git Repo

- You wanted to **move the workspace** from Google Drive to a **local directory managed by Git** without losing the “agent.”
- Guidance given: (1) Create local folder (e.g. `C:\Dev\Stoplights`). (2) Copy **Stoplights** and **`.cursor`** (rules) into it. (3) `git init`, add `.gitignore`, first commit. (4) In Cursor: **File → Open Folder** on the new local path. (5) Copy or reference the plan into the new repo so the new workspace has full context. The “agent” is preserved by having the same rules, code, and plan in the new folder; the chat may be a new one in the new workspace.

---

## 8. Misc

- **Spelling**: You asked about “Kapeesh” — the correct form is **capisce** (from Italian), sometimes written *capiche*.
- **Plan file**: The formal execution plan was saved as a Cursor plan (e.g. under `c:\Users\User\.cursor\plans\`); this MD is the human-readable summary of everything you said and what we agreed.

---

*End of brief. Good luck on the other side, sir.*
