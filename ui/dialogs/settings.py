"""Global settings dialog."""
from __future__ import annotations

from typing import Callable

from sim.persistence import list_saved_maps, sanitize_save_name
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
    ICON_BUTTON_GAP,
    ICON_BUTTON_SIZE,
    SLIDER_THUMB,
    SLIDER_TRACK,
)
from ui.widgets.buttons import CommitButton, RemoveButton
from ui.widgets.dropdown import Dropdown
from ui.widgets.slider import Slider
from ui.widgets.switch import Switch
from ui.widgets.text import DatumBox, TextBox

_NONE_SAVE = "(none)"


def _load_options(names: list[str] | None = None) -> list[str]:
    names = list(names) if names is not None else list_saved_maps()
    return names if names else [_NONE_SAVE]


class SettingsDialog(Dialog):
    """Dialog for global settings. Map snapshots, edge pan, grass-click dismiss, police, cars, colour grade."""

    def __init__(
        self,
        x: float,
        y: float,
        edge_pan_enabled: bool,
        grass_close_enabled: bool,
        color_hue: int = 0,
        color_sat: float = 1.0,
        police_enabled: bool = True,
        on_edge_pan_change: Callable[[bool], None] | None = None,
        on_grass_close_change: Callable[[bool], None] | None = None,
        on_police_change: Callable[[bool], None] | None = None,
        on_color_change: Callable[[int, float], None] | None = None,
        on_clear_cars: Callable[[], None] | None = None,
        on_save_map: Callable[[str], bool] | None = None,
        on_load_map: Callable[[str], bool] | None = None,
        on_new_game: Callable[[], None] | None = None,
    ):
        super().__init__(x, y, DIALOG_WIDTH, dialog_height(9), "Settings")
        self._on_edge_pan_change = on_edge_pan_change
        self._on_grass_close_change = on_grass_close_change
        self._on_police_change = on_police_change
        self._on_color_change = on_color_change
        self._on_save_map = on_save_map
        self._on_load_map = on_load_map
        self._on_new_game = on_new_game
        self._save_box = TextBox(0, 0, 160, DATUM_HEIGHT, extra_ok="_")
        self._save_btn = CommitButton(0, 0, on_click=self._do_save)
        self._load_dropdown = Dropdown(0, 0, 160, DATUM_HEIGHT, _load_options())
        self._load_btn = CommitButton(0, 0, on_click=self._do_load)
        self._new_btn = CommitButton(0, 0, on_click=self._do_new)
        self._switch = Switch(0, 0, 50, DATUM_HEIGHT, initial_value=edge_pan_enabled)
        self._grass_switch = Switch(0, 0, 50, DATUM_HEIGHT, initial_value=grass_close_enabled)
        self._police_switch = Switch(0, 0, 50, DATUM_HEIGHT, initial_value=police_enabled)
        self._clear_cars_btn = RemoveButton(0, 0, on_click=on_clear_cars)
        hue_step = min(COLOR_HUE_NUM_STEPS - 1, clamp_color_hue(color_hue) // 10)
        sat_step = max(0, min(COLOR_SAT_NUM_STEPS - 1, int(clamp_color_sat(color_sat) * 10.0 + 0.5)))
        self._hue_slider = Slider(0, 0, 160, DATUM_HEIGHT, COLOR_HUE_NUM_STEPS, hue_step, SLIDER_TRACK, SLIDER_THUMB)
        self._sat_slider = Slider(0, 0, 160, DATUM_HEIGHT, COLOR_SAT_NUM_STEPS, sat_step, SLIDER_TRACK, SLIDER_THUMB)
        self._hue_datum = DatumBox()
        self._sat_datum = DatumBox()
        self._save_label = ParamLabel("Save")
        self._load_label = ParamLabel("Load")
        self._new_label = ParamLabel("New")
        self._label = ParamLabel("Edge Pan")
        self._grass_label = ParamLabel("Grass Close")
        self._police_label = ParamLabel("Police")
        self._clear_label = ParamLabel("Clear Cars")
        self._hue_label = ParamLabel("Hue")
        self._sat_label = ParamLabel("Sat")
        self.widgets = [
            self._save_box,
            self._save_btn,
            self._load_dropdown,
            self._load_btn,
            self._new_btn,
            self._switch,
            self._grass_switch,
            self._police_switch,
            self._clear_cars_btn,
            self._hue_slider,
            self._sat_slider,
        ]
        self.labels = [
            self._save_label,
            self._load_label,
            self._new_label,
            self._label,
            self._grass_label,
            self._police_label,
            self._clear_label,
            self._hue_label,
            self._sat_label,
        ]
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

    def _commit_row(self, row, field, btn) -> None:
        w = max(48, row.control_width - ICON_BUTTON_SIZE - ICON_BUTTON_GAP)
        field.rect = (row.control_left, row.control_bottom, w, DATUM_HEIGHT)
        btn.rect = (
            row.control_left + w + ICON_BUTTON_GAP,
            row.control_bottom,
            ICON_BUTTON_SIZE,
            ICON_BUTTON_SIZE,
        )

    def _refresh_saved_maps(self, select: str | None = None) -> None:
        opts = _load_options()
        idx = opts.index(select) if select in opts else 0
        self._load_dropdown.set_options(opts, idx)

    def _do_save(self) -> None:
        self._save_box.set_focus(False)
        name = sanitize_save_name(self._save_box.value)
        if name is None or not self._on_save_map:
            return
        if self._on_save_map(name):
            self._save_box.value = name
            self._save_box._text_buffer = name
            self._refresh_saved_maps(select=name)

    def _do_load(self) -> None:
        name = self._load_dropdown.selected()
        if name == _NONE_SAVE or sanitize_save_name(name) is None:
            return
        if self._on_load_map:
            self._on_load_map(name)

    def _do_new(self) -> None:
        if self._on_new_game:
            self._on_new_game()

    def _layout_widgets(self) -> None:
        r0 = form_row(self, 0)
        self._save_label.place(r0.label_x, r0.label_y)
        self._commit_row(r0, self._save_box, self._save_btn)
        r1 = form_row(self, 1)
        self._load_label.place(r1.label_x, r1.label_y)
        self._commit_row(r1, self._load_dropdown, self._load_btn)
        r2 = form_row(self, 2)
        self._new_label.place(r2.label_x, r2.label_y)
        self._new_btn.rect = (r2.control_left, r2.control_bottom, ICON_BUTTON_SIZE, ICON_BUTTON_SIZE)
        r3 = form_row(self, 3)
        self._label.place(r3.label_x, r3.label_y)
        self._switch.rect = (r3.control_left, r3.control_bottom, 50, DATUM_HEIGHT)
        r4 = form_row(self, 4)
        self._grass_label.place(r4.label_x, r4.label_y)
        self._grass_switch.rect = (r4.control_left, r4.control_bottom, 50, DATUM_HEIGHT)
        r5 = form_row(self, 5)
        self._police_label.place(r5.label_x, r5.label_y)
        self._police_switch.rect = (r5.control_left, r5.control_bottom, 50, DATUM_HEIGHT)
        r6 = form_row(self, 6)
        self._clear_label.place(r6.label_x, r6.label_y)
        self._clear_cars_btn.rect = (r6.control_left, r6.control_bottom, ICON_BUTTON_SIZE, ICON_BUTTON_SIZE)
        r7 = form_row(self, 7)
        self._hue_label.place(r7.label_x, r7.label_y)
        self._hue_datum.rect = (r7.control_left, r7.control_bottom, DATUM_WIDTH, DATUM_HEIGHT)
        hs = r7.control_left + DATUM_WIDTH + FORM_GAP
        hw = max(24, r7.control_width - DATUM_WIDTH - FORM_GAP)
        self._hue_slider.rect = (hs, r7.control_bottom, hw, DATUM_HEIGHT)
        r8 = form_row(self, 8)
        self._sat_label.place(r8.label_x, r8.label_y)
        self._sat_datum.rect = (r8.control_left, r8.control_bottom, DATUM_WIDTH, DATUM_HEIGHT)
        ss = r8.control_left + DATUM_WIDTH + FORM_GAP
        sw = max(24, r8.control_width - DATUM_WIDTH - FORM_GAP)
        self._sat_slider.rect = (ss, r8.control_bottom, sw, DATUM_HEIGHT)

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
        if self._police_switch.contains(x, y) and self._on_police_change:
            self._on_police_change(self._police_switch.value)
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
