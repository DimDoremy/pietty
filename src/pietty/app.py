from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Static

from pietty.layout import PaneTree
from pietty.mode import ModeState
from pietty.terminal import TerminalWidget

# normal 模式命令键 -> 描述（用于状态栏提示）
_NORMAL_HINTS = [
    ("i", "i 插入"),
    ("s", "s 水平拆分"),
    ("v", "v 竖直拆分"),
    ("o", "o 切换面板"),
    ("c", "c 关闭面板"),
    ("q", "q 退出"),
]
_INSERT_HINTS = [("escape", "Esc 回 normal")]


class PaneArea(Container):
    pass


class StatusBar(Static):
    """底部状态栏：模式指示 + 键提示。"""


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
    StatusBar.mode-insert {
        background: $success 40%;
        color: $text;
    }
    """

    BINDINGS: list = []  # 全部在 on_key 手动路由

    def __init__(self) -> None:
        super().__init__()
        self.panes: PaneTree = PaneTree()
        self._widgets: dict[int, TerminalWidget] = {}
        self.modes = ModeState()

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
        try:
            w.focus()
        except Exception:
            pass

    def _relayout(self) -> None:
        """简易：仅聚焦 pane 可见，其余隐藏（完整比例排版留后续）。"""
        focused = self.panes.focused
        if (w := self._widgets.get(focused)) is not None:
            try:
                w.focus()
            except Exception:
                pass
        for pid, w in self._widgets.items():
            w.set_class(pid != focused, "hidden")

    # ---- status bar ----
    def _refresh_status(self) -> None:
        bar = self.query_one(StatusBar)
        if self.modes.current == "insert":
            bar.update("-- INSERT --   "
                       + "  ".join(t for _, t in _INSERT_HINTS))
            bar.set_class(True, "mode-insert")
        else:
            bar.update("-- NORMAL --   "
                       + "  ".join(t for _, t in _NORMAL_HINTS))
            bar.set_class(False, "mode-insert")

    # ---- key routing ----
    def on_key(self, event) -> None:
        key = event.key

        # 模式切换优先（两种模式下 escape/i/a 都可能触发切换）
        if self.modes.transition(key):
            self._refresh_status()
            event.prevent_default()
            event.stop()
            return

        if self.modes.current == "normal":
            # normal 模式：所有键归 pietty，不透传 shell
            self._handle_normal_command(key)
            event.prevent_default()
            event.stop()
            return
        # insert 模式：交给 focused widget 透传 shell（widget 的 on_key 处理）

    def _handle_normal_command(self, key: str) -> None:
        if key == "s":
            new = self.panes.split(self.panes.focused, "horizontal")
            self._spawn_pane(new)
            self._relayout()
        elif key == "v":
            new = self.panes.split(self.panes.focused, "vertical")
            self._spawn_pane(new)
            self._relayout()
        elif key == "o":
            self.panes.next_pane()
            self._relayout()
        elif key == "O":
            self.panes.prev_pane()
            self._relayout()
        elif key == "c":
            closing = self.panes.focused
            self.panes.close(closing)
            if (w := self._widgets.pop(closing, None)) is not None:
                w.remove()
            self._relayout()
        elif key == "q":
            self.exit()
        # 其余键在 normal 模式忽略


def main() -> None:
    PiettyApp().run()
