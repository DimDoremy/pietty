"""侧边栏面板列表（niri 风格）。"""
from __future__ import annotations

from textual.widgets import Static
from textual.containers import Vertical


class SidebarItem(Static):
    """单个面板条目。"""

    DEFAULT_CSS = """
    SidebarItem {
        padding: 0 1;
        width: 100%;
    }
    SidebarItem.focused-item {
        background: $accent 30%;
        color: $text;
    }
    """


class Sidebar(Vertical):
    """左侧面板列表。每个条目对应一个 TerminalWidget。"""

    DEFAULT_CSS = """
    Sidebar {
        width: 16;
        height: 100%;
        overflow-y: auto;
        background: $surface;
        border-right: solid $boost;
        padding: 0 0;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._entries: list[str] = []
        self._highlighted: int = 0

    def add_entry(self, label: str) -> None:
        self._entries.append(label)
        self.mount(SidebarItem(label))

    def remove_entry(self, idx: int) -> None:
        if 0 <= idx < len(self._entries):
            self._entries.pop(idx)
            children = list(self.children)
            if idx < len(children):
                children[idx].remove()

    def move_highlight(self, delta: int) -> int:
        n = len(self._entries)
        if n == 0:
            return 0
        old = self._highlighted
        self._highlighted = (self._highlighted + delta) % n
        self._refresh_highlight(old)
        return self._highlighted

    def set_highlight(self, idx: int) -> None:
        old = self._highlighted
        self._highlighted = max(0, min(idx, len(self._entries) - 1))
        self._refresh_highlight(old)

    def _refresh_highlight(self, old: int) -> None:
        children = list(self.children)
        if 0 <= old < len(children):
            children[old].remove_class("focused-item")
        if 0 <= self._highlighted < len(children):
            children[self._highlighted].add_class("focused-item")
