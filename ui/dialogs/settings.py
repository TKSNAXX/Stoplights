"""Global settings dialog."""
from __future__ import annotations

from typing import Callable

from sim.scenario import clamp_color_hue, clamp_color_sat
from ui.dialogs.base import Dialog
from ui.dialogs.layout import ParamLabel, dialog_height, form_row
from ui.theme import (
    COLOR_HUE_NUM_STEPS,
    COLOR_SAT_NUM_STEPS,
    DATUM_HEIGHT,
    DATUM_WIDTH,
    DIALOG_WIDTH,
    FORM_GAP,
    SLIDER_THUMB,
    SLIDER_TRACK,
)
from ui.widgets.slider import Slider
from ui.widgets.switch import Switch
from ui.widgets.text import DatumBox


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
        super().__init__(x, y, DIALOG_WIDTH, dialog_height(4), "Settings")
        self._on_edge_pan_change = on_edge_pan_change
        self._on_grass_close_change = on_grass_close_change
        self._on_color_change = on_color_change
        self._switch = Switch(0, 0, 50, DATUM_HEIGHT, initial_value=edge_pan_enabled)
        self._grass_switch = Switch(0, 0, 50, DATUM_HEIGHT, initial_value=grass_close_enabled)
        hue_step = min(COLOR_HUE_NUM_STEPS - 1, clamp_color_hue(color_hue) // 10)
        sat_step = max(0, min(COLOR_SAT_NUM_STEPS - 1, int(clamp_color_sat(color_sat) * 10.0 + 0.5)))
        self._hue_slider = Slider(0, 0, 160, DATUM_HEIGHT, COLOR_HUE_NUM_STEPS, hue_step, SLIDER_TRACK, SLIDER_THUMB)
        self._sat_slider = Slider(0, 0, 160, DATUM_HEIGHT, COLOR_SAT_NUM_STEPS, sat_step, SLIDER_TRACK, SLIDER_THUMB)
        self._hue_datum = DatumBox()
        self._sat_datum = DatumBox()
        self._label = ParamLabel("Edge Pan")
        self._grass_label = ParamLabel("Grass Close")
        self._hue_label = ParamLabel("Hue")
        self._sat_label = ParamLabel("Sat")
        self.widgets = [self._switch, self._grass_switch, self._hue_slider, self._sat_slider]
        self.labels = [self._label, self._grass_label, self._hue_label, self._sat_label]
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
        r0 = form_row(self, 0)
        self._label.place(r0.label_x, r0.label_y)
        self._switch.rect = (r0.control_left, r0.control_bottom, 50, DATUM_HEIGHT)
        r1 = form_row(self, 1)
        self._grass_label.place(r1.label_x, r1.label_y)
        self._grass_switch.rect = (r1.control_left, r1.control_bottom, 50, DATUM_HEIGHT)
        r2 = form_row(self, 2)
        self._hue_label.place(r2.label_x, r2.label_y)
        self._hue_datum.rect = (r2.control_left, r2.control_bottom, DATUM_WIDTH, DATUM_HEIGHT)
        hs = r2.control_left + DATUM_WIDTH + FORM_GAP
        hw = max(24, r2.control_width - DATUM_WIDTH - FORM_GAP)
        self._hue_slider.rect = (hs, r2.control_bottom, hw, DATUM_HEIGHT)
        r3 = form_row(self, 3)
        self._sat_label.place(r3.label_x, r3.label_y)
        self._sat_datum.rect = (r3.control_left, r3.control_bottom, DATUM_WIDTH, DATUM_HEIGHT)
        ss = r3.control_left + DATUM_WIDTH + FORM_GAP
        sw = max(24, r3.control_width - DATUM_WIDTH - FORM_GAP)
        self._sat_slider.rect = (ss, r3.control_bottom, sw, DATUM_HEIGHT)

    def draw(self) -> None:
        hue_disp = self._hue_slider.value * 10
        self._hue_datum.set_value(f"{hue_disp}°")
        self._sat_datum.set_value(f"{self._sat_slider.value * 10}%")
        super().draw()
        self._hue_datum.draw()
        self._sat_datum.draw()

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
