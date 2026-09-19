"""Dialog chrome and z-order manager."""
from __future__ import annotations

from typing import Callable, Iterator

from draw_compat import ipx, round_rect_filled
from ui.font import ui_text
from ui.hotkeys import hint_for
from ui.theme import (
    CHIP_FILL,
    CHIP_FILL_ACTIVE,
    CHIP_H,
    CHIP_RADIUS,
    CHIP_STROKE,
    CHIP_W,
    DIALOG_BORDER_PX,
    DIALOG_FOOTER_H,
    DIALOG_HEADER_H,
    DIALOG_RADIUS,
    DIALOG_SHELL,
    DIALOG_WELL,
    FONT_HOTKEY,
    FONT_TITLE,
    FONT_TYPE,
    FORM_GAP,
    FORM_PAD,
    LABEL_COLOR,
    MUTED_COLOR,
    TOOLBAR_HINT_GAP,
)
from ui.widgets.dropdown import Dropdown
from ui.widgets.protocols import ExpandedHitWidget, FocusableWidget
from ui.widgets.text import TextBox

_FOOTER_HINT_SLOT = 56


class Dialog:
    """Rounded-rect overlay: Esc close, typable title, Ctrl isolate and Del chips. (x, y) is top-left."""

    def __init__(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        title: str,
        *,
        kind: str = "",
        title_editable: bool = False,
    ):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.title = title
        self.kind = kind
        self.visible = True
        self.widgets: list = []
        self.labels: list = []
        self._dragging = False
        self._drag_start: tuple[float, float] | None = None
        self._on_close: Callable | None = None
        self._on_delete: Callable[[], None] | None = None
        self._dialog_manager: DialogManager | None = None
        self._kind_text = ui_text(
            kind, size=FONT_TYPE, color=MUTED_COLOR, anchor_x="center", anchor_y="center",
        )
        self._title_text = ui_text(
            title, size=FONT_TITLE, color=LABEL_COLOR, anchor_x="center", anchor_y="center",
        )
        self._esc_text = ui_text(
            hint_for("escape", "Esc"), size=FONT_HOTKEY, color=LABEL_COLOR,
            anchor_x="center", anchor_y="center",
        )
        self._ctrl_text = ui_text(
            hint_for("select_toggle_overlay", "Ctrl"), size=FONT_HOTKEY, color=LABEL_COLOR,
            anchor_x="center", anchor_y="center",
        )
        self._isolate_hint = ui_text(
            "Isolate", size=FONT_HOTKEY, color=LABEL_COLOR,
            anchor_x="left", anchor_y="center",
        )
        self._del_text = ui_text(
            hint_for("dialog_delete", "Del"), size=FONT_HOTKEY, color=LABEL_COLOR,
            anchor_x="center", anchor_y="center",
        )
        self._delete_hint = ui_text(
            "Delete", size=FONT_HOTKEY, color=LABEL_COLOR,
            anchor_x="left", anchor_y="center",
        )
        self._title_box: TextBox | None = None
        if title_editable:
            self._title_box = TextBox(
                0, 0, 120, 24, title, chrome=False, font_size=FONT_TITLE, align="center",
            )

    def set_dialog_manager(self, manager: "DialogManager") -> None:
        self._dialog_manager = manager

    def set_on_close(self, cb: callable) -> None:
        self._on_close = cb

    def clamp_to_window(self, window_w: float, window_h: float, margin: float = 8) -> None:
        self.x = max(margin, min(window_w - self.width - margin, self.x))
        self.y = max(self.height + margin, min(window_h - margin, self.y))

    def _bottom(self) -> float:
        return self.y - self.height

    def contains(self, x: float, y: float) -> bool:
        left = self.x
        bottom = self._bottom()
        return left <= x <= left + self.width and bottom <= y <= self.y

    def extended_contains(self, x: float, y: float) -> bool:
        if self.contains(x, y):
            return True
        for w in self.widgets:
            if isinstance(w, ExpandedHitWidget) and w.expanded_contains(x, y):
                return True
        return False

    def _iter_widgets(self) -> Iterator:
        if self._title_box is not None:
            yield self._title_box
        yield from self.widgets

    def _esc_rect(self) -> tuple[int, int, int, int]:
        left = ipx(self.x) + FORM_PAD
        bottom = ipx(self.y - DIALOG_HEADER_H / 2 - CHIP_H / 2)
        return left, bottom, CHIP_W, CHIP_H

    def _footer_chip_rect(self, index: int) -> tuple[int, int, int, int]:
        left = ipx(self.x) + FORM_PAD
        bottom = ipx(self._bottom() + DIALOG_FOOTER_H / 2 - CHIP_H / 2)
        stride = CHIP_W + TOOLBAR_HINT_GAP + _FOOTER_HINT_SLOT + FORM_GAP
        return left + index * stride, bottom, CHIP_W, CHIP_H

    def _ctrl_rect(self) -> tuple[int, int, int, int]:
        return self._footer_chip_rect(0)

    def _del_rect(self) -> tuple[int, int, int, int]:
        return self._footer_chip_rect(1)

    def trigger_delete(self) -> bool:
        if self._on_delete is None:
            return False
        self._on_delete()
        return True

    def _header_contains(self, x: float, y: float) -> bool:
        return self.x <= x <= self.x + self.width and self.y - DIALOG_HEADER_H <= y <= self.y

    def _chip_contains(self, rect: tuple[int, int, int, int], x: float, y: float) -> bool:
        l, b, w, h = rect
        return l <= x <= l + w and b <= y <= b + h

    def _layout_title_box(self) -> None:
        if self._title_box is None:
            return
        esc_l, _, esc_w, _ = self._esc_rect()
        width = min(220, ipx(self.width) - FORM_PAD * 2 - CHIP_W)
        left = ipx(self.x + (self.width - width) / 2)
        esc_right = esc_l + esc_w + 4
        if left < esc_right:
            left = esc_right
            width = max(40, ipx(self.x + self.width) - FORM_PAD - left)
        if self.kind:
            bottom = ipx(self.y - DIALOG_HEADER_H + 8)
            height = 26
        else:
            bottom = ipx(self.y - DIALOG_HEADER_H / 2 - 12)
            height = 24
        self._title_box.rect = (left, bottom, width, height)

    def _layout_widgets(self) -> None:
        pass

    def dismiss(self) -> None:
        self.visible = False
        if self._on_close:
            self._on_close(self)

    def _draw_chip(self, rect: tuple[int, int, int, int], label, filled: bool) -> None:
        l, b, w, h = rect
        round_rect_filled(l, b, w, h, CHIP_STROKE, CHIP_RADIUS)
        inner = DIALOG_BORDER_PX
        fill = CHIP_FILL_ACTIVE if filled else CHIP_FILL
        round_rect_filled(l + inner, b + inner, w - inner * 2, h - inner * 2, fill, max(CHIP_RADIUS - inner, 0))
        label.x = l + w / 2
        label.y = b + h / 2
        label.draw()

    def draw(self) -> None:
        if not self.visible:
            return
        self._layout_widgets()
        self._layout_title_box()
        left, bottom = ipx(self.x), ipx(self._bottom())
        width, height = ipx(self.width), ipx(self.height)
        round_rect_filled(left, bottom, width, height, DIALOG_SHELL, DIALOG_RADIUS)
        well_l = left + DIALOG_BORDER_PX
        well_w = width - DIALOG_BORDER_PX * 2
        well_b = bottom + DIALOG_FOOTER_H + DIALOG_BORDER_PX
        well_h = height - DIALOG_HEADER_H - DIALOG_FOOTER_H - DIALOG_BORDER_PX * 2
        if well_h > 0:
            round_rect_filled(well_l, well_b, well_w, well_h, DIALOG_WELL, DIALOG_RADIUS)
        isolate = bool(self._dialog_manager and self._dialog_manager.isolate_active)
        self._draw_chip(self._esc_rect(), self._esc_text, False)
        self._draw_chip(self._ctrl_rect(), self._ctrl_text, isolate)
        cl, cb, cw, ch = self._ctrl_rect()
        self._isolate_hint.x = cl + cw + TOOLBAR_HINT_GAP
        self._isolate_hint.y = cb + ch / 2
        self._isolate_hint.draw()
        self._draw_chip(self._del_rect(), self._del_text, False)
        if self._on_delete is not None:
            dl, db, dw, dh = self._del_rect()
            self._delete_hint.x = dl + dw + TOOLBAR_HINT_GAP
            self._delete_hint.y = db + dh / 2
            self._delete_hint.draw()
        cx = left + width / 2
        if self.kind:
            self._kind_text.value = self.kind
            self._kind_text.x = cx
            self._kind_text.y = ipx(self.y - 14)
            self._kind_text.draw()
        if self._title_box is not None:
            self._title_box.draw()
        else:
            self._title_text.value = self.title
            self._title_text.x = cx
            if self.kind:
                self._title_text.y = ipx(self.y - 38)
            else:
                self._title_text.y = ipx(self.y - DIALOG_HEADER_H / 2)
            self._title_text.draw()
        for label in self.labels:
            label.draw()
        for w in self.widgets:
            w.draw()
        for w in self.widgets:
            if isinstance(w, Dropdown) and w.is_open:
                w.draw_expanded_list()

    def on_mouse_press(self, x: float, y: float) -> bool:
        if not self.extended_contains(x, y) or not self.visible:
            return False
        self._layout_widgets()
        self._layout_title_box()
        if self._chip_contains(self._esc_rect(), x, y):
            self.dismiss()
            return True
        if self._chip_contains(self._ctrl_rect(), x, y):
            if self._dialog_manager and self._dialog_manager.on_isolate_toggle:
                self._dialog_manager.on_isolate_toggle()
            return True
        if self._chip_contains(self._del_rect(), x, y):
            self.trigger_delete()
            return True
        for w in self._iter_widgets():
            if w.on_press(x, y):
                if self._dialog_manager and isinstance(w, FocusableWidget):
                    self._dialog_manager.set_focused_widget(w)
                return True
        if self._header_contains(x, y):
            self._dragging = True
            self._drag_start = (self.x - x, self.y - y)
            if self._dialog_manager:
                self._dialog_manager.set_focused_widget(None)
            return True
        if self._dialog_manager:
            self._dialog_manager.set_focused_widget(None)
        return True

    def on_mouse_drag(self, x: float, y: float, dx: float, dy: float) -> bool:
        if self._dragging and self._drag_start is not None:
            self.x = x + self._drag_start[0]
            self.y = y + self._drag_start[1]
            return True
        for w in self.widgets:
            if w.on_drag(x):
                return True
        return False

    def on_mouse_release(self, x: float, y: float) -> bool:
        if self._dragging:
            self._dragging = False
            self._drag_start = None
            return True
        for w in self.widgets:
            if w.on_release():
                return True
        return False


class DialogManager:
    """Manages open dialogs: z-order, input routing, draw."""

    def __init__(self, get_window_size: Callable[[], tuple[float, float]] | None = None):
        self._dialogs: list[Dialog] = []
        self._focused_widget: FocusableWidget | None = None
        self._get_window_size = get_window_size
        self.isolate_active = False
        self.on_isolate_toggle: Callable[[], None] | None = None
        self.on_empty: Callable[[], None] | None = None

    def set_focused_widget(self, widget: FocusableWidget | None) -> None:
        if self._focused_widget is not None:
            self._focused_widget.set_focus(False)
        self._focused_widget = widget
        if widget is not None:
            widget.set_focus(True)

    def get_focused_widget(self) -> FocusableWidget | None:
        return self._focused_widget

    def open(self, dialog: Dialog) -> None:
        if dialog in self._dialogs:
            self._dialogs.remove(dialog)
        self._dialogs.append(dialog)
        dialog.set_dialog_manager(self)
        if self._get_window_size is not None:
            w, h = self._get_window_size()
            dialog.clamp_to_window(w, h)
        dialog.visible = True

    def close(self, dialog: Dialog) -> None:
        if dialog in self._dialogs:
            self._dialogs.remove(dialog)
        dialog.visible = False
        if self._focused_widget is not None:
            for w in dialog._iter_widgets():
                if w is self._focused_widget:
                    self.set_focused_widget(None)
                    break
        self._notify_if_empty()

    def close_all(self) -> None:
        for d in list(self._dialogs):
            d.dismiss()
            if d in self._dialogs:
                self.close(d)
        self._dialogs.clear()
        self.set_focused_widget(None)
        self._notify_if_empty()

    def close_top(self) -> bool:
        if not self._dialogs:
            return False
        top = self._dialogs[-1]
        top.dismiss()
        if top in self._dialogs:
            self.close(top)
        return True

    def trigger_delete_top(self) -> bool:
        if not self._dialogs:
            return False
        top = self._dialogs[-1]
        if not top.visible:
            return False
        return top.trigger_delete()

    def _notify_if_empty(self) -> None:
        if any(d.visible for d in self._dialogs):
            return
        if self.on_empty:
            self.on_empty()

    def contains_point(self, x: float, y: float) -> bool:
        for d in self._dialogs:
            if d.visible and d.extended_contains(x, y):
                return True
        return False

    def iter_open(self):
        for d in self._dialogs:
            if d.visible:
                yield d

    def on_mouse_press(self, x: float, y: float) -> bool:
        for i in range(len(self._dialogs) - 1, -1, -1):
            d = self._dialogs[i]
            if d.extended_contains(x, y) and d.visible:
                if i < len(self._dialogs) - 1:
                    self._dialogs.pop(i)
                    self._dialogs.append(d)
                return d.on_mouse_press(x, y)
        return False

    def on_mouse_drag(self, x: float, y: float, dx: float, dy: float) -> bool:
        if not self._dialogs:
            return False
        top = self._dialogs[-1]
        return top.on_mouse_drag(x, y, dx, dy)

    def on_mouse_release(self, x: float, y: float) -> bool:
        if not self._dialogs:
            return False
        top = self._dialogs[-1]
        return top.on_mouse_release(x, y)

    def draw_all(self) -> None:
        for d in self._dialogs:
            if d.visible:
                d.draw()
