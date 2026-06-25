from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.events import Resize
from textual.geometry import Size
from textual.widgets import Static

from pietty.gridlayout import grid_map, grid_size
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
    """平铺所有 TerminalWidget 的网格容器。"""


class StatusBar(Static):
    """底部状态栏：模式指示 + 键提示。"""


class PiettyApp(App):
    CSS = """
    Screen { layout: vertical; }
    PaneArea { height: 1fr; }
    PaneArea Horizontal,
    PaneArea Vertical,
    PaneArea TerminalWidget { width: 1fr; height: 1fr; }
    PaneArea Horizontal { layout: horizontal; }
    PaneArea Vertical { layout: vertical; }
    TerminalWidget {
        border: round $primary;
        width: 1fr;
        height: 1fr;
    }
    TerminalWidget.focused-pane { border: round $accent; }
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
    def _spawn_pane(self, pane_id: int) -> None:
        """首次创建 pane 的 widget（启动 PTY）。"""
        if pane_id in self._widgets:
            return
        w = TerminalWidget(id=f"pane-{pane_id}")
        self._widgets[pane_id] = w

    # ---- 布局重建（嵌套 Horizontal/Vertical + _screen_resized 触发重算） ----
    async def _mount_desc(self, parent, desc: dict) -> None:
        """递归按描述把布局挂到 parent 下（父必须已 mounted）。"""
        if desc["type"] == "leaf":
            w = self._widgets[desc["id"]]
            try:
                if w.parent is not None:
                    w.remove()
            except Exception:
                pass
            self._reset_styles(w)
            # TerminalWidget 内容会撜疮自身宽度, 必须强制参与 fr 分配
            w.styles.width = "1fr"
            w.styles.height = "1fr"
            await parent.mount(w)
            return
        container = Horizontal() if desc["type"] == "h" else Vertical()
        await parent.mount(container)
        ratio = desc["ratio"]
        c1d, c2d = desc["children"]
        await self._mount_desc(container, c1d)
        await self._mount_desc(container, c2d)
        r1 = max(1, int(ratio * 100))
        r2 = max(1, int((1 - ratio) * 100))
        c1, c2 = container.children[0], container.children[1]
        self._reset_styles(c1)
        self._reset_styles(c2)
        if desc["type"] == "h":
            c1.styles.width = f"{r1}fr"
            c2.styles.width = f"{r2}fr"
        else:
            c1.styles.height = f"{r1}fr"
            c2.styles.height = f"{r2}fr"

    def _reset_styles(self, w) -> None:
        try:
            w.styles.width = None
            w.styles.height = None
        except Exception:
            pass

    def _trigger_layout(self) -> None:
        """Textual 动态 mount/remove 后不重算 fr 布局（_layout_required
        靠 idle 循环异步处理，交互场景下不及时）。
        同步置标志 + 调 _refresh_layout 立即强制重算。
        """
        try:
            self.screen._layout_required = True
            self.screen._refresh_layout()
        except Exception:
            pass

    async def _relayout_async(self) -> None:
        """异步重建布局：卸载旧树 → 按 PaneTree 重建 → 触发重算 → 聚焦。"""
        area = self.query_one(PaneArea)
        for child in list(area.children):
            child.remove()
        self._trigger_layout()
        await asyncio.sleep(0)
        await self._mount_desc(area, tree_desc(self.panes))
        self._trigger_layout()
        await asyncio.sleep(0)
        self._trigger_layout()
        self._focus_current()  # [DEBUG] restored

    def _relayout(self) -> None:
        asyncio.create_task(self._relayout_async())

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

        if self.modes.transition(key):
            self._refresh_status()
            event.prevent_default()
            event.stop()
            return

        if self.modes.current == "normal":
            self._handle_normal_command(key)
            event.prevent_default()
            event.stop()
            return

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
                return
            self.panes.close(closing)
            if (w := self._widgets.get(closing)) is not None:
                w.shutdown()
            self._relayout()
        elif key == "q":
            for w in self._widgets.values():
                w.shutdown()
            self.exit()


def main() -> None:
    PiettyApp().run()
