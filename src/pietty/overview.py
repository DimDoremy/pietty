"""概览窗口：显示所有 shell 状态，支持关闭/标记/跳转/移动。"""
from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Static


def _pane_status(w) -> str:
    """返回 pane 当前状态的描述字符串。"""
    if w._pty is None or w._pty.pid is None:
        return "(无 PTY)"
    pid = w._pty.pid
    # 查运行中的子进程
    try:
        with open(f"/proc/{pid}/task/{pid}/children") as f:
            children = f.read().strip().split()
        if children:
            # 读子进程的 cmdline
            try:
                cmdline = Path(f"/proc/{children[0]}/cmdline").read_bytes()
                parts = cmdline.replace(b"\x00", b" ").decode("utf-8", "replace").strip()
                return parts[:60] if parts else f"pid:{children[0]}"
            except OSError:
                return f"pid:{children[0]}"
    except OSError:
        pass
    # 无子进程：显示 shell 名
    try:
        return Path(f"/proc/{pid}/comm").read_text().strip()
    except OSError:
        return "shell"


class _TabLabel(Static):
    DEFAULT_CSS = """
    _TabLabel { width: 100%; padding: 0 1; text-align: center; }
    _TabLabel.sel { background: $accent 40%; }
    """


class _ShellRow(Static):
    DEFAULT_CSS = """
    _ShellRow { width: 100%; padding: 0 1; }
    _ShellRow.sel { background: $accent 30%; }
    _ShellRow.pinned { color: $warning; }
    """


class OverviewScreen(Screen):
    """概览窗口。左 tab 栏 + 右 shell 列表。"""

    CSS = """
    OverviewScreen { layout: vertical; }
    #ov-main { height: 1fr; }
    #ov-tabs { width: 6; background: $surface; border-right: solid $boost; }
    #ov-list { width: 1fr; }
    #ov-hint { height: 2; dock: bottom; background: $boost; padding: 0 1; }
    #ov-frame { border: round $accent; }
    """

    BINDINGS = [
        Binding("j", "nav(1)", "下一个", show=False),
        Binding("k", "nav(-1)", "上一个", show=False),
        Binding("g,escape", "quit_overview", "退出", show=False),
    ]

    def __init__(self, app_ref) -> None:
        super().__init__()
        self._app = app_ref
        self._flat: list[tuple[int, int, int]] = []  # (row, col, pane_idx)
        self._sel: int = 0
        self._pinned: set[int] = set()

    def compose(self) -> ComposeResult:
        with Vertical(id="ov-frame"):
            with Horizontal(id="ov-main"):
                yield VerticalScroll(id="ov-tabs")
                yield VerticalScroll(id="ov-list")
            yield Static(self._hint_text(), id="ov-hint")

    def on_mount(self) -> None:
        self._rebuild()
        self._refresh_hints()

    def _rebuild(self) -> None:
        """从 app 网格重建列表。"""
        grid = self._app._grid
        panes = self._app._panes
        self._flat = []
        for r, row in enumerate(grid):
            for c, idx in enumerate(row):
                self._flat.append((r, c, idx))
        if self._sel >= len(self._flat):
            self._sel = max(0, len(self._flat) - 1)

        # 左侧 tab 栏
        tabs = self.query_one("#ov-tabs", VerticalScroll)
        for child in list(tabs.children):
            child.display = False
        n_tabs = len(grid)
        existing = list(tabs.children)
        for i in range(n_tabs):
            label = f"{i+1}"
            if i < len(existing):
                existing[i].display = True
                existing[i].update(label)
            else:
                tabs.mount(_TabLabel(label))
        # 右侧 shell 列表
        lst = self.query_one("#ov-list", VerticalScroll)
        for child in list(lst.children):
            child.display = False
        existing = list(lst.children)
        for i, (r, c, idx) in enumerate(self._flat):
            if idx >= len(panes):
                continue
            w = panes[idx]
            status = _pane_status(w)
            pin = " ★" if idx in self._pinned else ""
            text = f"[{r+1},{c+1}] {status}{pin}"
            if i < len(existing):
                existing[i].display = True
                existing[i].update(text)
            else:
                lst.mount(_ShellRow(text))
        # 隐藏多余旧条目
        for i in range(len(self._flat), len(existing)):
            existing[i].display = False
        self._highlight()

    def _highlight(self) -> None:
        """高亮当前选中行和对应 tab。"""
        lst = self.query_one("#ov-list", VerticalScroll)
        items = [c for c in lst.children if c.display]
        for i, item in enumerate(items):
            item.remove_class("sel")
            if i < len(self._flat) and self._flat[i][2] in self._pinned:
                item.add_class("pinned")
            else:
                item.remove_class("pinned")
        if 0 <= self._sel < len(items):
            items[self._sel].add_class("sel")
            items[self._sel].scroll_visible()
        # 高亮 tab
        tabs = self.query_one("#ov-tabs", VerticalScroll)
        tab_items = [c for c in tabs.children if c.display]
        cur_tab = self._flat[self._sel][0] if self._flat else 0
        for i, item in enumerate(tab_items):
            item.remove_class("sel")
        if 0 <= cur_tab < len(tab_items):
            tab_items[cur_tab].add_class("sel")

    @staticmethod
    def _hint_text() -> str:
        return ("j/k 导航  c 关闭  p 标记  u 取消标记  "
                "i 进入(insert)  n 进入(normal)  m 移动  g/esc 退出")

    def _refresh_hints(self) -> None:
        try:
            self.query_one("#ov-hint", Static).update(self._hint_text())
        except Exception:
            pass

    # ---- 按键处理 ----
    def action_nav(self, delta: int) -> None:
        n = len(self._flat)
        if n == 0:
            return
        self._sel = (self._sel + delta) % n
        self._highlight()

    def action_quit_overview(self) -> None:
        self._app._overview = False
        self.app.pop_screen()

    def on_key(self, event) -> None:
        key = event.key
        if key in ("j", "down"):
            self.action_nav(1)
        elif key in ("k", "up"):
            self.action_nav(-1)
        elif key == "c":
            self._close_selected()
        elif key == "p":
            self._pin_selected()
        elif key == "u":
            self._unpin_selected()
        elif key == "i":
            self._enter_selected("insert")
        elif key == "n":
            self._enter_selected("normal")
        elif key == "m":
            self._move_selected()
        elif key in ("g", "escape"):
            self.action_quit_overview()
        else:
            return
        event.prevent_default()
        event.stop()

    def _cur(self) -> tuple[int, int, int] | None:
        if 0 <= self._sel < len(self._flat):
            return self._flat[self._sel]
        return None

    def _close_selected(self) -> None:
        cur = self._cur()
        if cur is None:
            return
        r, c, idx = cur
        app = self._app
        if len(app._panes) <= 1:
            app._quit_now()
            return
        app._do_close_grid(r, c)
        self._rebuild()

    def _pin_selected(self) -> None:
        cur = self._cur()
        if cur:
            self._pinned.add(cur[2])
            self._highlight()

    def _unpin_selected(self) -> None:
        cur = self._cur()
        if cur:
            self._pinned.discard(cur[2])
            self._highlight()

    def _enter_selected(self, mode: str) -> None:
        cur = self._cur()
        if cur is None:
            return
        r, c, _ = cur
        self._app._focused_row = r
        self._app._focused_col = c
        self._app.modes.current = mode
        self._app._overview = False  # 先清除标志，避免 on_key guard 吞键
        self.app.pop_screen()

    def _move_selected(self) -> None:
        """把选中的 pane 移到当前主界面聚焦 pane 的下方（同一 tab 末尾）。"""
        cur = self._cur()
        if cur is None:
            return
        sr, sc, sidx = cur
        app = self._app
        target_row = app._focused_row
        if sr == target_row and sc == len(app._grid[sr]) - 1:
            return  # 已在目标位置
        # 从源行移除
        del app._grid[sr][sc]
        if not app._grid[sr]:
            del app._grid[sr]
        # 加入目标行末尾
        if 0 <= target_row < len(app._grid):
            app._grid[target_row].append(sidx)
        else:
            app._grid.append([sidx])
        self._rebuild()
