"""One exclusive tool at a time. Default is select."""
from __future__ import annotations

from ui.tools.base import Tool
from ui.tools.host import ToolHost


class ToolManager:
    def __init__(self, host: ToolHost, default: Tool) -> None:
        self._host = host
        self._default = default
        self._active = default
        self._by_action: dict[str, Tool] = {}
        if default.id:
            self._by_action[default.id] = default
        self._sync_chrome()

    def register(self, action: str, tool: Tool) -> None:
        self._by_action[action] = tool

    @property
    def active(self) -> Tool:
        return self._active

    @property
    def inspect(self) -> Tool:
        return self._default

    @property
    def select(self) -> Tool:
        return self._default

    def is_create_active(self) -> bool:
        return self._active is not self._default

    def activate_select(self) -> None:
        if self._active is not self._default:
            self._active.exit()
            self._active = self._default
            self._default.enter()
        self._sync_chrome()

    def activate_inspect(self) -> None:
        self.activate_select()

    def toggle_action(self, action: str) -> bool:
        tool = self._by_action.get(action)
        if tool is None:
            return False
        if tool is self._default:
            self.activate_select()
            return True
        if self._active is tool:
            self.activate_select()
            return True
        if self._active is not self._default:
            self._active.exit()
        self._active = tool
        tool.enter()
        self._sync_chrome()
        return True

    def _sync_chrome(self) -> None:
        self._host.toolbar.active_action = self._active.active_action
        mode = getattr(self._default, "mode", None)
        if mode is not None:
            self._host.toolbar.select_mode = mode
        if getattr(self._host, "_tool_manager", None) is self:
            self._host.sync_toolbar_bottom()
