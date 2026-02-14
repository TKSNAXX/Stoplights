# Stoplights

A minimal self-playing isometric traffic sim: one crossroad with four places, lanes as discrete objects, and cars that flow between places and stop when blocked.

## Setup

```bash
# Optional: use a virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
# source venv/bin/activate

pip install -r requirements.txt
```

## Run

```bash
python main.py
```

## Architecture

- **Sim layer** (`sim/`): pure Python — world grid, lanes, places, cars, tick. No rendering.
- **Display layer** (`main.py`): Arcade window reads sim state and draws; runs game loop and calls `sim.tick()`.
