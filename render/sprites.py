"""Sprite loading and pooling utilities."""
from __future__ import annotations

from pathlib import Path

import arcade


CAR_DIRECTION_NAMES = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def load_lane_textures(assets_dir: Path) -> dict[str, arcade.Texture] | None:
    try:
        textures = {c: arcade.load_texture(str(assets_dir / f"lane_{c}.png")) for c in ("N", "S", "E", "W")}
        return textures if all(textures.values()) else None
    except Exception:
        return None


def load_car_textures(assets_dir: Path) -> list[arcade.Texture] | None:
    try:
        textures = [arcade.load_texture(str(assets_dir / f"car_{direction}.png")) for direction in CAR_DIRECTION_NAMES]
        return textures if all(textures) else None
    except Exception:
        return None


class CarSpritePool:
    """Reusable sprite pool to avoid per-frame Sprite allocations."""

    def __init__(self, textures_by_dir: list[arcade.Texture], scale: float = 1.5):
        self._textures_by_dir = textures_by_dir
        self._scale = scale
        self.sprite_list = arcade.SpriteList()
        self._pool: list[arcade.Sprite] = []

    def _ensure_capacity(self, count: int) -> None:
        while len(self._pool) < count:
            spr = arcade.Sprite(self._textures_by_dir[0], scale=self._scale)
            spr.alpha = 0
            self._pool.append(spr)
            self.sprite_list.append(spr)

    def begin_frame(self, needed_count: int) -> None:
        self._ensure_capacity(needed_count)
        for sprite in self._pool:
            sprite.alpha = 0

    def set_sprite(
        self,
        index: int,
        direction_index: int,
        center_x: float,
        center_y: float,
        color: tuple[int, int, int],
    ) -> None:
        spr = self._pool[index]
        spr.texture = self._textures_by_dir[direction_index % len(self._textures_by_dir)]
        spr.center_x = center_x
        spr.center_y = center_y
        spr.color = color
        spr.alpha = 255
