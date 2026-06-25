from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Static

from pietty.layout import PaneTree
from pietty.terminal import TerminalWidget

# C-x 系统级快捷键速查（name -> 显示文本）
_HINTS = [
    ("3", "C-x 3 水平拆分"),
    ("2", "C-x 2 竖直拆分"),
    ("0", "C-x 0 关闭面板"),
    ("o", "C-x o 切换面板"),
    ("b", "C-x b 切换 tab"),
    ("ctrl+c", "C-x C-c 退出"),
]


class PaneArea(Container):
    pass


class StatusBar(Static):
    """底部操作提示栏。"""


class PiettyApp(App):
    CSS = """
    Screen { layout: vertical; }
    PaneArea { layers: base; }
    TerminalWidget { layer: base; }
    .hidden { display: none; }
    StatusBar {
        height: 1;
        dock: bottom;
        background: $boost;
        color: $text;
        padding: 0 1;
    }
    StatusBar.cx-pending {
        background: $accent 40;
        color: $text;
    }
    """

    BINDINGS: list = []  # C-x 在 on_key 手动处理

    def __init__(self) -> None:
        super().__init__()
        self.panes: PaneTree = PaneTree()
        self._widgets: dict[int, TerminalWidget] = {}
        self._cx_pending = False  # 是否已按 C-x，等待下一键

    def compose(self) -> ComposeResult:
        yield PaneArea()
        yield StatusBar("")

    def on_mount(self) -> None:
        self._spawn_pane(self.panes.focused)
        self._relayout()
        self._refresh_status()

    # ---- pane <-> widget ----
    def _spawn_pane(self, pane_id: int) -> None:
        area = self.query_one(PaneArea)
        w = TerminalWidget(id=f"pane-{pane_id}")
        self._widgets[pane_id] = w
        area.mount(w)

    def _relayout(self) -> None:
        """简易：仅聚焦 pane 可见，其余隐藏（完整比例排版留后续）。"""
        focused = self.panes.focused
        for pid, w in self._widgets.items():
            w.set_class(pid != focused, "hidden")

    # ---- status bar ----
    def _refresh_status(self, pending: bool = False) -> None:
        bar = self.query_one(StatusBar)
        if pending:
            bar.update("C-x … (按 3/2/0/o/b 或 C-c，Esc 取消)")
            bar.set_class(True, "cx-pending")
        else:
            bar.update("  ".join(t for _, t in _HINTS))
            bar.set_class(False, "cx-pending")

    # ---- key handling ----
    def on_key(self, event) -> None:
        # Esc 取消挂起的 C-x
        if self._cx_pending and event.key == "escape":
            self._cx_pending = False
            self._refresh_status(False)
            event.prevent_default()
            event.stop()
            return
        if event.key == "ctrl+x":
            self._cx_pending = True
            self._refresh_status(True)
            event.prevent_default()
            event.stop()
            return
        if not self._cx_pending:
            return  # 交给 widget
        self._cx_pending = False
        event.prevent_default()
        event.stop()
        k = event.key
        if k == "2":
            new = self.panes.split(self.panes.focused, "vertical")
            self._spawn_pane(new)
            self._relayout()
        elif k == "3":
            new = self.panes.split(self.panes.focused, "horizontal")
            self._spawn_pane(new)
            self._relayout()
        elif k == "0":
            closing = self.panes.focused
            self.panes.close(closing)
            if (w := self._widgets.pop(closing, None)) is not None:
                w.remove()
            self._relayout()
        elif k == "o":
            self.panes.next_pane()
            self._relayout()
        elif k == "ctrl+c":
            self.exit()
        self._refresh_status(False)


def main() -> None:
    PiettyApp().run()
