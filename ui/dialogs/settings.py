"""Global settings dialog."""
from __future__ import annotations

from typing import Callable

import arcade

from sim.scenario import clamp_color_hue, clamp_color_sat
from ui.dialogs.base import Dialog
from ui.theme import COLOR_HUE_NUM_STEPS, COLOR_SAT_NUM_STEPS, LABEL_COLOR
from ui.widgets.slider import Slider
from ui.widgets.switch import Switch


class SettingsDialog(Dialog):
    """Dialog for global settings. Edge pan, grass-click dismiss, world colour grade."""

    def __init__(
        self,
        x: float,
        y: float,
        edge_pan_enabled: bool,
        grass_close_enabled: bool,
        color_hue: int = 0,
        color_sat: float = 1.0,
        on_edge_pan_change: Callable[[bool], None] | None = None,
        on_grass_close_change: Callable[[bool], None] | None = None,
        on_color_change: Callable[[int, float], None] | None = None,
    ):
        super().__init__(x, y, 240, 210, "Settings")
        self._on_edge_pan_change = on_edge_pan_change
        self._on_grass_close_change = on_grass_close_change
        self._on_color_change = on_color_change
        self._switch = Switch(0, 0, 50, 24, initial_value=edge_pan_enabled)
        self._grass_switch = Switch(0, 0, 50, 24, initial_value=grass_close_enabled)
        hue_step = min(COLOR_HUE_NUM_STEPS - 1, clamp_color_hue(color_hue) // 10)
        sat_step = max(0, min(COLOR_SAT_NUM_STEPS - 1, int(clamp_color_sat(color_sat) * 10.0 + 0.5)))
        self._hue_slider = Slider(0, 0, 160, 20, COLOR_HUE_NUM_STEPS, hue_step, (100, 100, 100), (180, 180, 180))
        self._sat_slider = Slider(0, 0, 160, 20, COLOR_SAT_NUM_STEPS, sat_step, (100, 100, 100), (180, 180, 180))
        self._label = arcade.Text("Edge pan", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._grass_label = arcade.Text("Grass close", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._colors_label = arcade.Text("Colors", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._hue_label = arcade.Text("", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._sat_label = arcade.Text("", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self.widgets = [self._switch, self._grass_switch, self._hue_slider, self._sat_slider]
        self._last_hue = self._hue_degrees()
        self._last_sat = self._sat_value()

    def _hue_degrees(self) -> int:
        return (self._hue_slider.value * 10) % 360

    def _sat_value(self) -> float:
        return self._sat_slider.value * 0.1

    def _emit_colors(self) -> None:
        hue, sat = self._hue_degrees(), self._sat_value()
        if hue == self._last_hue and sat == self._last_sat:
            return
        self._last_hue = hue
        self._last_sat = sat
        if self._on_color_change:
            self._on_color_change(hue, sat)

    def _layout_widgets(self) -> None:
        left = self.x + 12
        content_top = self.y - 32
        label_w = 88
        self._label.x = left
        self._label.y = content_top - 12
        self._switch.rect = (left + label_w, content_top - 24, 50, 24)
        self._grass_label.x = left
        self._grass_label.y = content_top - 44
        self._grass_switch.rect = (left + label_w, content_top - 56, 50, 24)
        self._colors_label.x = left
        self._colors_label.y = content_top - 84
        self._hue_label.x = left
        self._hue_label.y = content_top - 104
        self._hue_slider.rect = (left, content_top - 124, 216, 20)
        self._sat_label.x = left
        self._sat_label.y = content_top - 144
        self._sat_slider.rect = (left, content_top - 164, 216, 20)

    def draw(self) -> None:
        self._layout_widgets()
        hue_disp = self._hue_slider.value * 10
        self._hue_label.value = f"Hue: {hue_disp}°"
        self._sat_label.value = f"Sat: {self._sat_slider.value * 10}%"
        super().draw()
        self._label.draw()
        self._grass_label.draw()
        self._colors_label.draw()
        self._hue_label.draw()
        self._sat_label.draw()

    def on_mouse_press(self, x: float, y: float) -> bool:
        self._layout_widgets()
        result = super().on_mouse_press(x, y)
        if self._switch.contains(x, y) and self._on_edge_pan_change:
            self._on_edge_pan_change(self._switch.value)
        if self._grass_switch.contains(x, y) and self._on_grass_close_change:
            self._on_grass_close_change(self._grass_switch.value)
        self._emit_colors()
        return result

    def on_mouse_drag(self, x: float, y: float, dx: float, dy: float) -> bool:
        if self._dragging:
            return super().on_mouse_drag(x, y, dx, dy)
        self._layout_widgets()
        result = super().on_mouse_drag(x, y, dx, dy)
        self._emit_colors()
        return result

    def on_mouse_release(self, x: float, y: float) -> bool:
        result = super().on_mouse_release(x, y)
        self._emit_colors()
        return result
