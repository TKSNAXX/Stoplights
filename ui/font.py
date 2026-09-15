"""Liberator loader for dialog type."""
from __future__ import annotations

from pathlib import Path

import arcade

from ui.theme import LABEL_COLOR

_FAMILY = "Liberator"
_LOADED = False

_FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_EXTRA_DIRS = (
    Path(r"C:\Windows\Fonts"),
    Path.home() / "AppData" / "Local" / "Microsoft" / "Windows" / "Fonts",
)


def _candidate_files() -> list[Path]:
    names = (
        "Liberator.ttf",
        "Liberator.otf",
        "liberator.ttf",
        "liberator.otf",
        "Liberator-Regular.ttf",
        "Liberator-Regular.otf",
        "Liberator-Medium.ttf",
        "Liberator-Medium.otf",
    )
    out: list[Path] = []
    for folder in (_FONT_DIR, *_EXTRA_DIRS):
        if not folder.is_dir():
            continue
        for name in names:
            p = folder / name
            if p.is_file():
                out.append(p)
        try:
            for p in folder.iterdir():
                if p.is_file() and "liberat" in p.name.lower() and p.suffix.lower() in (".ttf", ".otf"):
                    if p not in out:
                        out.append(p)
        except OSError:
            pass
    return out


def load_ui_font() -> str:
    """Register Liberator from assets/fonts (or a system copy). Call once at startup."""
    global _LOADED, _FAMILY
    if _LOADED:
        return _FAMILY
    _LOADED = True
    files = _candidate_files()
    if files:
        try:
            import pyglet
            pyglet.font.add_file(str(files[0]))
        except Exception:
            pass
    return _FAMILY


def font_family() -> str:
    return load_ui_font()


def ui_text(
    text: str,
    x: float = 0,
    y: float = 0,
    *,
    size: int,
    color=None,
    **kwargs,
) -> arcade.Text:
    load_ui_font()
    return arcade.Text(
        text,
        x,
        y,
        color=color if color is not None else LABEL_COLOR,
        font_size=size,
        font_name=_FAMILY,
        **kwargs,
    )
