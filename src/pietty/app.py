"""pietty —— niri 式水平滚动终端复用器。"""
from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.containers import HorizontalScroll
from textual.widgets import Static

from pietty.mode import ModeState
from pietty.scroll import ScrollLayout
from pietty.terminal import TerminalWidget

# 默认每个 pane 的固定宽度（列）
DEFAULT_PANE_WIDTH = 80

_NORMAL_HINTS = [
    ("i", "i 插入"),
    ("n", "n 新建面板"),
    ("h", "h 左 / l 右"),
    ("c", "c 关闭面板"),
    ("q", "q 退出"),
]
_INSERT_HINTS = [("escape", "Esc 回 normal")]


class PaneScroll(HorizontalScroll):
    """承载所有 TerminalWidget 的水平滚动容器。"""


class StatusBar(Static):
    """底部状态栏：模式 + 键提示 + pane 计数。"""


class PiettyApp(App):
    CSS = """
    Screen { layout: vertical; }
    PaneScroll { height: 1fr; }
    TerminalWidget {
        width: 80;
        height: 100%;
        border: round $primary;
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

    BINDINGS: list = []

    def __init__(self, pane_width: int = DEFAULT_PANE_WIDTH) -> None:
        super().__init__()
        self.pane_width = pane_width
        self._panes: list[TerminalWidget] = []
        self._focused: int = 0
        self.modes = ModeState()

    def compose(self) -> ComposeResult:
        yield PaneScroll()
        yield StatusBar("")

    def on_mount(self) -> None:
        self._new_pane()
        self._refresh_status()

    # ---- pane 管理 ----
    @property
    def focused_widget(self) -> TerminalWidget | None:
        if 0 <= self._focused < len(self._panes):
            return self._panes[self._focused]
        return None

    def _new_pane(self) -> None:
        """新建 pane 并追加到右侧。"""
        pane_id = len(self._panes)
        w = TerminalWidget(id=f"pane-{pane_id}")
        self._panes.append(w)
        self._focused = pane_id
        scroll = self.query_one(PaneScroll)
        self.call_after_refresh(self._mount_and_focus, w, scroll)

    async def _mount_and_focus(self, w: TerminalWidget, scroll: PaneScroll) -> None:
        await scroll.mount(w)
        self._focus_and_scroll()
        # 强制重算(延迟一帧, 避免连续 mount 时重入)
        self.call_after_refresh(self._force_layout)

    def _close_pane(self) -> None:
        if len(self._panes) <= 1:
            return
        idx = self._focused
        w = self._panes[idx]
        alive = w._pty is not None and w._pty.isalive()
        if alive:
            self._prompt_close(idx)
            return
        self._do_close(idx)

    def _prompt_close(self, idx: int) -> None:
        """进程存活时弹出确认对话框。"""
        from textual.screen import ModalScreen, Screen
        from textual.widgets import Label, Button

        class CloseDialog(Screen):
            CSS = """
            Screen { background: $surface 80%; }
            #dialog {
                width: 40;
                height: auto;
                padding: 1;
                border: round $accent;
                background: $panel;
                margin: 4 10;
                align: center middle;
            }
            Label { text-align: center; margin-bottom: 1; }
            #buttons { align: center middle; }
            Button { margin: 0 1; }
            """
            def compose(self):
                from textual.containers import Vertical, Horizontal
                with Vertical(id="dialog"):
                    yield Label("Pane has a running process.")
                    yield Label("What do you want to do?")
                    with Horizontal(id="buttons"):
                        yield Button("保留后台", id="bg")
                        yield Button("终止", id="kill")
                        yield Button("取消", id="cancel")

            def on_button_pressed(self, event):
                self.dismiss(event.button.id)

        def on_choice(choice):
            if choice == "kill":
                self._do_close(idx)
            elif choice == "bg":
                pass  # 保留后台
            self._refresh_status()

        self.push_screen(CloseDialog(), on_choice)

    def _do_close(self, idx: int) -> None:
        """实际关闭 pane（异步通过 call_after_refresh）。"""
        w = self._panes.pop(idx)
        self._focused = min(idx, len(self._panes) - 1)
        # 延迟一帧执行移除（避免同步 remove + layout 卡死）
        self.call_after_refresh(self._exec_close, w)

    def _exec_close(self, w: TerminalWidget) -> None:
        w.shutdown()
        try:
            w.remove()
        except Exception:
            pass
        self.call_after_refresh(self._after_close)

    def _after_close(self) -> None:
        self._force_layout()
        self._focus_and_scroll()
        self._refresh_status()

    def _move_focus(self, delta: int) -> None:
        n = len(self._panes)
        if n == 0:
            return
        self._focused = (self._focused + delta) % n
        self._focus_and_scroll()

    # ---- 布局/滚动 ----
    def _force_layout(self) -> None:
        """动态 mount/remove 后强制重算布局。"""
        try:
            self.screen._layout_required = True
            self.screen._refresh_layout()
        except Exception:
            pass

    def _focus_and_scroll(self) -> None:
        scroll = self.query_one(PaneScroll)
        # 聚焦样式
        for w in self._panes:
            w.remove_class("focused-pane")
        w = self.focused_widget
        if w is not None:
            w.add_class("focused-pane")
            try:
                w.focus()
            except Exception:
                pass
            # 滚动让聚焦 pane 进视图(暂禁用: scroll_to_widget 在测试中卡死)
            # try:
            #     scroll.scroll_to_widget(w, animate=False)
            # except Exception:
            #     pass

    # ---- 状态栏 ----
    def _refresh_status(self) -> None:
        bar = self.query_one(StatusBar)
        if self.modes.current == "insert":
            bar.update("-- INSERT --   "
                       + "  ".join(t for _, t in _INSERT_HINTS))
            bar.set_class(True, "mode-insert")
        else:
            count = len(self._panes)
            pos = f"[{self._focused + 1}/{count}]" if count else "[-]"
            bar.update(f"-- NORMAL -- {pos}   "
                       + "  ".join(t for _, t in _NORMAL_HINTS))
            bar.set_class(False, "mode-insert")

    # ---- 按键路由 ----
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
        if key == "n":
            self._new_pane()
            self._refresh_status()
        elif key == "h":
            self._move_focus(-1)
            self._refresh_status()
        elif key == "l":
            self._move_focus(1)
            self._refresh_status()
        elif key == "c":
            self._close_pane()
            self._refresh_status()
        elif key == "q":
            self.call_after_refresh(self._do_quit)

    def _do_quit(self) -> None:
        for w in self._panes:
            w.shutdown()
        self.exit()


def main() -> None:
    PiettyApp().run()
