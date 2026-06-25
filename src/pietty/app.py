from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Static

from pietty.layout import PaneTree, tree_desc
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
    """承载布局树的容器根。"""


class StatusBar(Static):
    """底部状态栏：模式指示 + 键提示。"""


class PiettyApp(App):
    CSS = """
    Screen { layout: vertical; }
    PaneArea { layers: base; }
    TerminalWidget { layer: base; border: round $primary; }
    TerminalWidget.focused-pane { border: round $accent; }
    PaneArea Horizontal { height: 100%; }
    PaneArea Vertical { width: 100%; }
    StatusBar {
        height: 1;
        dock: bottom;
        background: $boost;
        color: $text;
        padding: 0 1;
    }
    StatusBar.mode-insert {
        background: $success 50%;
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
    def _make_widget(self, pane_id: int) -> TerminalWidget:
        """创建或复用一个 TerminalWidget（PTY 在创建时即启动，不随布局重建销毁）。"""
        if pane_id in self._widgets:
            return self._widgets[pane_id]
        w = TerminalWidget(id=f"pane-{pane_id}")
        self._widgets[pane_id] = w
        return w

    def _spawn_pane(self, pane_id: int) -> None:
        """首次创建 pane 的 widget（启动 PTY）。"""
        if pane_id in self._widgets:
            return
        self._make_widget(pane_id)

    # ---- 布局重建 ----
    async def _mount_desc(self, parent, desc: dict) -> None:
        """递归按描述把布局挂到 parent 下（父必须已 mounted）。"""
        if desc["type"] == "leaf":
            w = self._widgets[desc["id"]]
            # widget 可能仍在旧树上，先 detach
            try:
                if w.parent is not None:
                    w.remove()
            except Exception:
                pass
            await parent.mount(w)
            return
        # 创建容器并先挂到 parent
        if desc["type"] == "h":
            container = Horizontal()
        else:
            container = Vertical()
        await parent.mount(container)
        ratio = desc["ratio"]
        c1d, c2d = desc["children"]
        await self._mount_desc(container, c1d)
        await self._mount_desc(container, c2d)
        c1 = container.children[0]
        c2 = container.children[1]
        if desc["type"] == "h":
            c1.styles.width = f"{int(ratio * 100)}fr"
            c2.styles.width = f"{int((1 - ratio) * 100)}fr"
        else:
            c1.styles.height = f"{int(ratio * 100)}fr"
            c2.styles.height = f"{int((1 - ratio) * 100)}fr"

    async def _relayout_async(self) -> None:
        """异步重建布局：卸载旧树 → 按 PaneTree 重建 → 聚焦。"""
        area = self.query_one(PaneArea)
        # 卸载现有子节点（widget 复用，不销毁 PTY）
        for child in list(area.children):
            child.remove()
        await self._mount_desc(area, tree_desc(self.panes))
        self._focus_current()

    def _relayout(self) -> None:
        """同步入口：调度异步重建。"""
        self.call_after_refresh(self._relayout_async)

    def _focus_current(self) -> None:
        focused = self.panes.focused
        for pid, w in self._widgets.items():
            w.remove_class("focused-pane")
        w = self._widgets.get(focused)
        if w is not None:
            w.add_class("focused-pane")
            try:
                w.focus()
            except Exception:
                pass

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
        # insert 模式：交给 focused widget 透传 shell

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
            self._focus_current()
        elif key == "O":
            self.panes.prev_pane()
            self._focus_current()
        elif key == "c":
            closing = self.panes.focused
            if len(self.panes.leaves()) <= 1:
                return  # 至少保留一个 pane
            self.panes.close(closing)
            if (w := self._widgets.pop(closing, None)) is not None:
                w.shutdown()
                w.remove()
            self._relayout()
        elif key == "q":
            for w in self._widgets.values():
                w.shutdown()
            self.exit()


def main() -> None:
    PiettyApp().run()
