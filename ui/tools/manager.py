"""One exclusive tool at a time. Default is inspect."""
from __future__ import annotations

from ui.tools.base import Tool
from ui.tools.host import ToolHost


class ToolManager:
    def __init__(self, host: ToolHost, inspect: Tool) -> None:
        self._host = host
        self._inspect = inspect
        self._active = inspect
        self._by_action: dict[str, Tool] = {}

    def register(self, action: str, tool: Tool) -> None:
        self._by_action[action] = tool

    @property
    def active(self) -> Tool:
        return self._active

    @property
    def inspect(self) -> Tool:
        return self._inspect

    def is_create_active(self) -> bool:
        return self._active is not self._inspect

    def activate_inspect(self) -> None:
        if self._active is self._inspect:
            return
        self._active.exit()
        self._active = self._inspect
        self._inspect.enter()
        self._sync_chrome()

    def toggle_action(self, action: str) -> bool:
        tool = self._by_action.get(action)
        if tool is None:
            return False
        if self._active is tool:
            self.activate_inspect()
            return True
        if self._active is not self._inspect:
            self._active.exit()
        self._active = tool
        tool.enter()
        self._sync_chrome()
        return True

    def _sync_chrome(self) -> None:
        self._host.toolbar.active_action = self._active.active_action
        self._host.sync_toolbar_bottom()
