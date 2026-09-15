"""Shared dialog form geometry. Screen space: x right, y up."""
from __future__ import annotations

from dataclasses import dataclass

from draw_compat import ipx
from ui.font import ui_text
from ui.theme import (
    DATUM_HEIGHT,
    DIALOG_BORDER_PX,
    DIALOG_FOOTER_H,
    DIALOG_HEADER_H,
    FONT_PARAM,
    FORM_GAP,
    FORM_LABEL_W,
    FORM_PAD,
    FORM_ROW_H,
    LABEL_COLOR,
)


def dialog_height(n_rows: int, extra: int = 0) -> int:
    well = FORM_PAD * 2 + n_rows * FORM_ROW_H + extra
    return DIALOG_HEADER_H + DIALOG_BORDER_PX + well + DIALOG_BORDER_PX + DIALOG_FOOTER_H


def well_rect(dialog) -> tuple[int, int, int, int]:
    """Inner well (left, bottom, width, height). 2px inset on the sides; header/footer above/below."""
    left = ipx(dialog.x) + DIALOG_BORDER_PX
    width = ipx(dialog.width) - DIALOG_BORDER_PX * 2
    bottom = ipx(dialog.y - dialog.height) + DIALOG_FOOTER_H + DIALOG_BORDER_PX
    height = ipx(dialog.height) - DIALOG_HEADER_H - DIALOG_FOOTER_H - DIALOG_BORDER_PX * 2
    return left, bottom, width, max(height, 0)


@dataclass
class FormRow:
    label_x: int
    label_y: int
    control_left: int
    control_bottom: int
    control_width: int
    row_bottom: int


def form_row(dialog, index: int, control_h: int = DATUM_HEIGHT) -> FormRow:
    wl, wb, ww, wh = well_rect(dialog)
    top = wb + wh - FORM_PAD
    row_bottom = top - (index + 1) * FORM_ROW_H
    cy = row_bottom + FORM_ROW_H // 2
    label_x = wl + FORM_PAD + FORM_LABEL_W
    control_left = label_x + FORM_GAP
    control_right = wl + ww - FORM_PAD
    control_bottom = cy - control_h // 2
    return FormRow(
        label_x=ipx(label_x),
        label_y=ipx(cy),
        control_left=ipx(control_left),
        control_bottom=ipx(control_bottom),
        control_width=max(0, ipx(control_right) - ipx(control_left)),
        row_bottom=ipx(row_bottom),
    )


class ParamLabel:
    """Right-aligned parameter title (15px Liberator)."""

    def __init__(self, text: str):
        self._text = ui_text(text, size=FONT_PARAM, color=LABEL_COLOR, anchor_x="right", anchor_y="center")

    def place(self, x: float, y: float) -> None:
        self._text.x = ipx(x)
        self._text.y = ipx(y)

    def draw(self) -> None:
        self._text.draw()
