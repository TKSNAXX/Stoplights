"""Read-only car details dialog."""
from __future__ import annotations

from sim import routes
from ui.dialogs.base import Dialog
from ui.dialogs.layout import ParamLabel, dialog_height, form_row, well_rect
from ui.theme import DATUM_HEIGHT, DIALOG_WIDTH, FORM_PAD, FORM_ROW_H
from ui.widgets.text import DatumBox


class CarDeetsDialog(Dialog):
    """Read-only dialog showing car speed, origin, destination."""

    _FIELDS = (
        ("Origin", "origin"),
        ("Destination", "dest"),
        ("Route", "route"),
        ("Speed", "speed"),
        ("Awareness", "aware"),
        ("On", "on"),
        ("Next", "next"),
        ("Lane", "lane"),
        ("Next Cars", "next_cars"),
        ("Sister", "sister"),
    )

    def __init__(self, x: float, y: float, car, game) -> None:
        super().__init__(x, y, DIALOG_WIDTH, dialog_height(10, extra=32), "Details", kind="Car")
        self._car = car
        self._game = game
        self._rows: list[tuple[ParamLabel, DatumBox, str]] = []
        for title, key in self._FIELDS:
            wrap = key in ("route", "on")
            self._rows.append((ParamLabel(title), DatumBox(wrap=wrap), key))
        self.labels = [pair[0] for pair in self._rows]

    @property
    def car(self):
        return self._car

    def _values(self) -> dict[str, str]:
        if self._car not in self._game.cars:
            return {"origin": "Car Departed"}
        itinerary = routes.format_route_nodes(getattr(self._car, "route", ()))
        k = int(getattr(self._car, "awareness", 0))
        names = " ".join(getattr(self._car, "observe_skills", ()) or ())
        ahead = getattr(self._car, "cars_ahead", None)
        behind = getattr(self._car, "cars_behind", None)
        if ahead is None or behind is None:
            lane = "—"
        else:
            lane = f"{ahead} Ahead, {behind} Behind"
        nfc = getattr(self._car, "next_feature_cars", None)
        sa = getattr(self._car, "sister_ahead", None)
        sb = getattr(self._car, "sister_behind", None)
        if sa is None or sb is None:
            sister = "—"
        else:
            sister = f"{sa} Ahead, {sb} Behind"
        return {
            "origin": str(self._car.origin),
            "dest": str(self._car.destination),
            "route": itinerary if itinerary else "—",
            "speed": f"{self._car.base_speed_multiplier:.2f}x",
            "aware": f"{k}" + (f"  {names}" if names else ""),
            "on": getattr(self._car, "on_feature", "") or "—",
            "next": getattr(self._car, "next_feature", "") or "—",
            "lane": lane,
            "next_cars": str(nfc) if nfc is not None else "—",
            "sister": sister,
        }

    def _layout_widgets(self) -> None:
        live = self._car in self._game.cars
        if not live:
            row = form_row(self, 0)
            label, box, _key = self._rows[0]
            label.place(row.label_x, row.label_y)
            box.rect = (row.control_left, row.control_bottom, row.control_width, DATUM_HEIGHT)
            self.labels = [label]
            return
        self.labels = [pair[0] for pair in self._rows]
        wl, wb, _ww, wh = well_rect(self)
        y = wb + wh - FORM_PAD
        control_left = None
        control_width = None
        for _i, (label, box, key) in enumerate(self._rows):
            h = 40 if key in ("route", "on") else DATUM_HEIGHT
            row_h = max(FORM_ROW_H, h + 6)
            y -= row_h
            cy = y + row_h / 2
            if control_left is None:
                sample = form_row(self, 0)
                control_left = sample.control_left
                control_width = sample.control_width
                label_x = sample.label_x
            else:
                label_x = form_row(self, 0).label_x
            label.place(label_x, cy)
            box.rect = (control_left, y + (row_h - h) / 2, control_width, h)

    def draw(self) -> None:
        values = self._values()
        live = self._car in self._game.cars
        if not live:
            self._rows[0][0]._text.value = "Origin"
            self._rows[0][1].set_value("Car Departed")
            super().draw()
            self._rows[0][1].draw()
            return
        for label, box, key in self._rows:
            box.set_value(values.get(key, "—"))
        super().draw()
        for _label, box, _key in self._rows:
            box.draw()
