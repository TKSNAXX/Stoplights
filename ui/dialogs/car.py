"""Read-only car details dialog."""
from __future__ import annotations

import arcade

from sim import routes
from ui.dialogs.base import Dialog
from ui.theme import LABEL_COLOR


class CarDeetsDialog(Dialog):
    """Read-only dialog showing car speed, origin, destination."""

    def __init__(self, x: float, y: float, car, game) -> None:
        super().__init__(x, y, 240, 220, "Car details")
        self._car = car
        self._game = game
        self._origin_label = arcade.Text("", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._dest_label = arcade.Text("", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._route_label = arcade.Text("", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._speed_label = arcade.Text("", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._aware_label = arcade.Text("", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._on_label = arcade.Text("", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._next_label = arcade.Text("", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._lane_label = arcade.Text("", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._next_cars_label = arcade.Text("", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")
        self._sister_label = arcade.Text("", 0, 0, color=LABEL_COLOR, font_size=10, anchor_x="left", anchor_y="center")

    def _layout_widgets(self) -> None:
        pass

    def draw(self) -> None:
        left = self.x + 12
        content_top = self.y - 32
        self._origin_label.x = left
        self._origin_label.y = content_top - 12
        self._dest_label.x = left
        self._dest_label.y = content_top - 28
        self._route_label.x = left
        self._route_label.y = content_top - 44
        self._speed_label.x = left
        self._speed_label.y = content_top - 60
        self._aware_label.x = left
        self._aware_label.y = content_top - 76
        self._on_label.x = left
        self._on_label.y = content_top - 92
        self._next_label.x = left
        self._next_label.y = content_top - 108
        self._lane_label.x = left
        self._lane_label.y = content_top - 124
        self._next_cars_label.x = left
        self._next_cars_label.y = content_top - 140
        self._sister_label.x = left
        self._sister_label.y = content_top - 156

        if self._car in self._game.cars:
            self._origin_label.value = f"Origin: {self._car.origin}"
            self._dest_label.value = f"Destination: {self._car.destination}"
            itinerary = routes.format_route_nodes(getattr(self._car, "route", ()))
            self._route_label.value = f"Route: {itinerary}" if itinerary else "Route: —"
            self._speed_label.value = f"Speed: {self._car.base_speed_multiplier:.2f}x"
            k = int(getattr(self._car, "awareness", 0))
            names = " ".join(getattr(self._car, "observe_skills", ()) or ())
            self._aware_label.value = f"Awareness: {k}" + (f"  {names}" if names else "")
            on_feat = getattr(self._car, "on_feature", "") or "—"
            self._on_label.value = f"On: {on_feat}"
            nxt = getattr(self._car, "next_feature", "") or "—"
            self._next_label.value = f"Next: {nxt}"
            ahead = getattr(self._car, "cars_ahead", None)
            behind = getattr(self._car, "cars_behind", None)
            if ahead is None or behind is None:
                self._lane_label.value = "Lane: —"
            else:
                self._lane_label.value = f"Lane: {ahead} ahead, {behind} behind"
            nfc = getattr(self._car, "next_feature_cars", None)
            self._next_cars_label.value = f"Next cars: {nfc}" if nfc is not None else "Next cars: —"
            sa = getattr(self._car, "sister_ahead", None)
            sb = getattr(self._car, "sister_behind", None)
            if sa is None or sb is None:
                self._sister_label.value = "Sister: —"
            else:
                self._sister_label.value = f"Sister: {sa} ahead, {sb} behind"
        else:
            self._origin_label.value = "Car departed"
            self._dest_label.value = ""
            self._route_label.value = ""
            self._speed_label.value = ""
            self._aware_label.value = ""
            self._on_label.value = ""
            self._next_label.value = ""
            self._lane_label.value = ""
            self._next_cars_label.value = ""
            self._sister_label.value = ""

        super().draw()
        self._origin_label.draw()
        self._dest_label.draw()
        self._route_label.draw()
        self._speed_label.draw()
        self._aware_label.draw()
        self._on_label.draw()
        self._next_label.draw()
        self._lane_label.draw()
        self._next_cars_label.draw()
        self._sister_label.draw()
