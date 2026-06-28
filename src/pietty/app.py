"""pietty —— niri 式水平滚动终端复用器。"""
from __future__ import annotations

import asyncio
import os
import sys
import termios
import threading
import time

from textual.app import App, ComposeResult
from textual.containers import HorizontalScroll, Horizontal
from textual.widgets import Static

from pietty.mode import ModeState
from pietty.terminal import TerminalWidget
from pietty.config import load as load_config, css_vars
from pietty.sidebar import Sidebar


_DEBUG_LOG = None


def _dbg(fmt: str, *args) -> None:
    global _DEBUG_LOG
    if _DEBUG_LOG is None:
        try:
            _DEBUG_LOG = open("/tmp/pietty_debug.log", "a", buffering=1)
        except Exception:
            return
    try:
        _DEBUG_LOG.write(f"[{time.perf_counter():.4f}] " + (fmt % args) + "\n")
    except Exception:
        pass


# 面板宽度档位（占视口宽度的比例），r 键循环。
# 默认首面板和新建面板均为 1/2（niri 风格：劈一半）。
# 循环: 1/2 → 2/3 → 全屏 → 1/3 → 1/2
SIZE_TIERS: list[float] = [0.5, 2 / 3, 1.0, 1 / 3]
_SIZE_LABEL = {1.0: "全屏", 2 / 3: "2/3", 0.5: "1/2", 1 / 3: "1/3"}

_NORMAL_HINTS = [
    ("h/l", "h l 切换shell"),
    ("j/k", "j k 切换tab"),
    ("n", "n 新建shell"),
    ("c", "c 关闭"),
    ("r", "r 调整大小"),
    ("g", "g 概览"),
    ("q", "q 退出"),
]
_INSERT_HINTS = [("escape/Alt+q", "Esc Alt+q 回 normal")]


class PaneContainer(HorizontalScroll):
    """承载当前聚焦的 TerminalWidget。非聚焦 pane 以 display=False 隐藏。"""

    def on_resize(self, event) -> None:
        try:
            self.app._apply_all_sizes()
        except Exception:
            pass


class StatusBar(Static):
    """底部状态栏：模式 + 键提示 + pane 计数。"""


class PiettyApp(App):
    CSS = """
    Screen { layout: vertical; }
    #main-row { height: 1fr; }
    Sidebar { width: 6; }
    PaneContainer { height: 100%; width: 1fr; }
    TerminalWidget {
        height: 100%;
        width: 100%;
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
    #overlay {
        layout: grid;
        grid-size: 2 2;
        height: 100%;
    }
    """

    BINDINGS: list = []

    def __init__(self) -> None:
        super().__init__()
        self._cfg = load_config()
        self.CSS = css_vars(self._cfg.theme) + self.CSS
        self._panes: list[TerminalWidget] = []
        self._grid: list[list[int]] = []  # 网格: 每行是 pane 索引列表
        self._focused_row: int = 0
        self._focused_col: int = 0
        self.modes = ModeState()
        self._close_pending: int | None = None
        self._pane_seq: int = 0
        self._overview: bool = False
        try:
            self._saved_termios = termios.tcgetattr(sys.stdin.fileno())
        except Exception:
            self._saved_termios = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="main-row"):
            yield Sidebar()
            yield PaneContainer()
        yield StatusBar("")

    def on_mount(self) -> None:
        self._new_pane()
        self._sync_pane_visibility()
        self._refresh_status()

    # ---- pane 管理 ----
    @property
    def sidebar(self) -> Sidebar:
        return self.query_one(Sidebar)

    @property
    def pane_container(self) -> PaneContainer:
        return self.query_one(PaneContainer)

    @property
    def focused_widget(self) -> TerminalWidget | None:
        if self._grid and 0 <= self._focused_row < len(self._grid):
            row = self._grid[self._focused_row]
            if 0 <= self._focused_col < len(row):
                idx = row[self._focused_col]
                if 0 <= idx < len(self._panes):
                    return self._panes[idx]
        return None

    def _new_pane(self, new_row: bool = False) -> None:
        """新建 pane。

        new_row=False: 在当前 tab 右侧水平新建 shell。
        new_row=True:  新建 tab（新行）。
        """
        self._pane_seq += 1
        w = TerminalWidget(id=f"pane-{self._pane_seq}")
        self._panes.append(w)
        idx = len(self._panes) - 1
        created_row = False

        if new_row or not self._grid:
            if not self._grid:
                self._grid.append([idx])
                self._focused_row = 0
                self._focused_col = 0
            else:
                self._grid.insert(self._focused_row + 1, [idx])
                self._focused_row += 1
                self._focused_col = 0
            created_row = True
        else:
            # 当前行右插
            row = self._grid[self._focused_row]
            row.insert(self._focused_col + 1, idx)
            self._focused_col += 1

        container = self.pane_container
        asyncio.create_task(self._mount_and_focus(w, container, created_row))

    async def _mount_and_focus(self, w: TerminalWidget,
                               container: PaneContainer | None = None,
                               new_tab: bool = False) -> None:
        if container is None:
            container = self.pane_container
        await container.mount(w)
        if new_tab:
            self.sidebar.add_entry(str(self._focused_row + 1))
        self._sync_pane_visibility()
        self._apply_pane_size(w)
        self._focus_and_scroll()
        self.call_after_refresh(self._force_layout)

    def _close_pane(self) -> None:
        _dbg("_close_pane enter, rows=%d", len(self._grid))
        if not self._panes:
            return
        w = self.focused_widget
        if w is None:
            return
        has_running = (w._pty is not None and w._pty.pid is not None
                       and self._has_children(w._pty.pid))
        _dbg("_close_pane: has_running=%s", has_running)
        if has_running:
            self._close_pending = (self._focused_row, self._focused_col)
            self._refresh_status(pending_close=True)
            return
        if len(self._panes) <= 1:
            _dbg("_close_pane: only 1 pane, quit process")
            self._quit_now()
            return
        self._do_close_grid(self._focused_row, self._focused_col)

    def _do_close_grid(self, row: int, col: int) -> None:
        """关闭网格中 (row, col) 位置的 pane。"""
        idx = self._grid[row][col]
        w = self._panes[idx]
        # 从网格移除
        del self._grid[row][col]
        if not self._grid[row]:
            del self._grid[row]
            self.sidebar.remove_entry_by_seq(str(row + 1))
        self._panes.pop(idx)

        # 调整焦点
        nr = len(self._grid)
        if nr == 0:
            self._focused_row = self._focused_col = 0
        else:
            self._focused_row = min(self._focused_row, nr - 1)
            self._focused_col = min(self._focused_col,
                                    len(self._grid[self._focused_row]) - 1)

        if w:
            asyncio.create_task(self._close_task(w))

    @staticmethod
    def _has_children(pid: int) -> bool:
        """检查 PID 是否有运行中的子进程（用于判断 shell 内是否有命令在跑）。

        优先读 /proc/<pid>/task/<tid>/children（O(1)，单文件），兼容性最好。
        /proc/<pid>/children 需要 CONFIG_PROC_CHILDREN，很多内核未启用。
        """
        try:
            with open(f"/proc/{pid}/task/{pid}/children") as f:
                return bool(f.read().strip())
        except OSError:
            pass
        # fallback: 扫描 /proc/*/stat 的 PPID 字段
        try:
            for name in os.listdir("/proc"):
                if not name.isdigit():
                    continue
                try:
                    with open(f"/proc/{name}/stat", "rb") as f:
                        stat = f.read()
                except OSError:
                    continue
                rpar = stat.rfind(b")")
                if rpar < 0:
                    continue
                fields = stat[rpar + 2:].split()
                if len(fields) >= 2 and int(fields[1]) == pid:
                    return True
        except Exception:
            pass
        return False

    async def _close_task(self, w: TerminalWidget) -> None:
        """关闭 task：shutdown -> remove -> layout。"""
        _dbg("_close_task: shutdown start")
        w.shutdown()
        _dbg("_close_task: shutdown done")
        await asyncio.sleep(0)
        _dbg("_close_task: remove start")
        try:
            # 用 display=False 隐藏而非 remove()：在含活跃 PTY reader 的
            # HorizontalScroll 中调用 remove() 会触发 Textual 合成器死锁
            # （关闭后整个 app 不再渲染/响应）。隐藏 widget 保留在 DOM 中
            # 但其 PTY 已 shutdown（reader 已 detach、进程已 kill），开销极小。
            w.display = False
        except Exception as e:
            _dbg("_close_task: remove err %r", e)
        _dbg("_close_task: remove done")
        # 多帧 sleep 确保 DOM 摘除与 prune 完成
        await asyncio.sleep(0.05)
        _dbg("_close_task: post-remove sleep done")
        self._close_pending = None
        for pw in self._panes:
            pw._refresh_paused = False
        _dbg("_close_task: focus start")
        self._focus_and_scroll()
        self._refresh_status()
        _dbg("_close_task: ALL DONE (no force_layout)")

    def _cancel_pending(self) -> None:
        self._close_pending = None
        for w in self._panes:
            w._refresh_paused = False
        self._refresh_status()

    def _timeout_pending(self) -> None:
        """pending 超时自动取消（防止按键无法送达时永久卡死）。"""
        if self._close_pending is not None:
            _dbg("_timeout_pending: auto-cancel after 5s")
            self._cancel_pending()

    def _move_focus(self, d_row: int, d_col: int) -> None:
        """在网格中移动焦点。"""
        if not self._grid:
            return
        nr = len(self._grid)
        new_r = max(0, min(self._focused_row + d_row, nr - 1))
        new_c = max(0, min(self._focused_col + d_col, len(self._grid[new_r]) - 1))
        if (new_r, new_c) != (self._focused_row, self._focused_col):
            self._focused_row, self._focused_col = new_r, new_c
            self._focus_and_scroll()
            self._refresh_status()

    def _move_pane(self, d_tab: int, d_col: int) -> None:
        """Alt+快捷键移动当前 pane。

        d_tab != 0 (Alt+j/k): 把 pane 移到相邻 tab（行），边界时新建 tab。
        d_col != 0 (Alt+h/l): 在当前 tab 内左右交换 pane 顺序。
        """
        if not self._grid:
            return
        r, c = self._focused_row, self._focused_col
        cur_idx = self._grid[r][c]

        if d_tab != 0:
            # --- 移到相邻 tab ---
            # 从当前行移除
            del self._grid[r][c]
            row_emptied = not self._grid[r]
            if row_emptied:
                del self._grid[r]
                self.sidebar.remove_entry_by_seq(str(r + 1))

            target = r + d_tab
            if 0 <= target < len(self._grid) and not row_emptied:
                # 加入已有 tab（放末尾）
                self._grid[target].append(cur_idx)
                self._focused_row = target
                self._focused_col = len(self._grid[target]) - 1
            elif 0 <= target <= len(self._grid):
                # 新建 tab
                insert_at = max(0, min(target, len(self._grid)))
                self._grid.insert(insert_at, [cur_idx])
                self._focused_row = insert_at
                self._focused_col = 0
                self.sidebar.add_entry(str(self._focused_row + 1))
            else:
                # 越界回退：放回原位
                if row_emptied:
                    self._grid.insert(r, [cur_idx])
                    self.sidebar.add_entry(str(r + 1))
                else:
                    self._grid[r].insert(c, cur_idx)
                return
        elif d_col != 0:
            # --- 同 tab 内左右交换 ---
            row = self._grid[r]
            tc = c + d_col
            if tc < 0 or tc >= len(row):
                return
            row[c], row[tc] = row[tc], row[c]
            self._focused_col = tc

        self._sync_pane_visibility()
        self._focus_and_scroll()
        self._refresh_status()

    def _sync_pane_visibility(self) -> None:
        """显示当前 tab（行）的所有 pane，隐藏其他行。"""
        for i, w in enumerate(self._panes):
            visible = False
            if self._grid and self._focused_row < len(self._grid):
                visible = i in self._grid[self._focused_row]
            w.display = visible or self._overview

    def _toggle_overview(self) -> None:
        """g: 切换概览模式（显示所有 pane 平铺）。"""
        self._overview = not getattr(self, "_overview", False)
        if self._overview:
            for w in self._panes:
                w.display = True
        else:
            self._sync_pane_visibility()

    # ---- 布局/滚动 ----
    def _force_layout(self) -> None:
        """动态 mount/remove 后强制重算布局。"""
        try:
            self.screen._layout_required = True
            self.screen._refresh_layout()
        except Exception as e:
            _dbg("_force_layout err %r", e)

    # ---- 面板尺寸 ----
    def _viewport_cols(self) -> int:
        """当前可用宽度（列）。优先 PaneContainer 的尺寸，回退到屏幕宽度。"""
        try:
            w = self.pane_container.size.width
            if w > 0:
                return w
        except Exception:
            pass
        try:
            return self.screen.size.width
        except Exception:
            return 80

    def _apply_pane_size(self, w: TerminalWidget) -> None:
        """按 pane 的 size_fraction 设置其宽度（列）。"""
        cols = int(self._viewport_cols() * w.size_fraction)
        cols = max(cols, 20)  # 安全下限
        try:
            w.styles.width = cols
        except Exception as e:
            _dbg("_apply_pane_size err %r", e)

    def _apply_all_sizes(self) -> None:
        """按当前视口宽度重算所有 pane 的宽度（用于终端 resize）。"""
        for w in self._panes:
            self._apply_pane_size(w)

    def _cycle_pane_size(self) -> None:
        """r 键：循环切换聚焦 pane 的宽度档位（全屏→2/3→1/2→1/3→全屏）。"""
        w = self.focused_widget
        if w is None:
            return
        try:
            i = SIZE_TIERS.index(w.size_fraction)
        except ValueError:
            i = -1
        w.size_fraction = SIZE_TIERS[(i + 1) % len(SIZE_TIERS)]
        self._apply_pane_size(w)
        self._refresh_status()

    def _focus_and_scroll(self) -> None:
        for w in self._panes:
            w.remove_class("focused-pane")
        w = self.focused_widget
        if w is not None:
            w.add_class("focused-pane")
        # 高亮侧边栏对应 tab（行索引）
        self.sidebar.set_highlight(self._focused_row)
        self._sync_pane_visibility()

    # ---- 状态栏 ----
    def _refresh_status(self, pending_close: bool = False) -> None:
        bar = self.query_one(StatusBar)
        if self.modes.current == "insert":
            bar.update("-- INSERT --   "
                       + "  ".join(t for _, t in _INSERT_HINTS))
            bar.set_class(True, "mode-insert")
            return
        if pending_close:
            bar.set_class(False, "mode-insert")
            bar.update("-- CLOSE? --   (k) 终止  (b) 保留后台  (escape) 取消")
            _dbg("_refresh_status: set _refresh_paused on %d panes", len(self._panes))
            for w in self._panes:
                w._refresh_paused = True
            # 保险：5秒后自动取消 pending，防止按键无法送达时永久卡死
            try:
                loop = asyncio.get_event_loop()
                loop.call_later(5.0, self._timeout_pending)
            except Exception:
                pass
            return
        count = len(self._panes)
        pos = f"[T{self._focused_row + 1} S{self._focused_col + 1}/{count}]" if count else "[-]"
        size_lbl = ""
        fw = self.focused_widget
        if fw is not None:
            size_lbl = " " + _SIZE_LABEL.get(fw.size_fraction, "?")
        bar.update(f"-- NORMAL -- {pos}{size_lbl}   "
                   + "  ".join(t for _, t in _NORMAL_HINTS))
        bar.set_class(False, "mode-insert")

    # ---- 按键路由 ----
    def on_key(self, event) -> None:
        key = event.key

        # 关闭确认待处理: 拦截 k/b/escape
        if self._close_pending is not None:
            _dbg("pending key: %r", event.key)
            if key == "k":
                row, col = self._close_pending
                self._close_pending = None
                _dbg("pending: k confirm")
                if len(self._panes) <= 1:
                    self._quit_now()
                else:
                    self._do_close_grid(row, col)
            elif key == "b":
                _dbg("pending: b background")
                self._cancel_pending()
            elif key == "escape":
                _dbg("pending: escape cancel")
                self._cancel_pending()
            # 其他键忽略
            event.prevent_default()
            event.stop()
            return

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

        # insert 模式: 把按键透传到当前聚焦 pane 的 shell。
        # （widget 不再持有 Textual 焦点，按键统一在此路由）
        w = self.focused_widget
        if w is not None:
            w.send_key(key, getattr(event, "character", None))
        event.prevent_default()
        event.stop()

    def _handle_normal_command(self, key: str) -> None:
        if key == "n":
            self._new_pane(new_row=False)
            self._refresh_status()
        elif key == "alt+n":
            self._new_pane(new_row=True)
            self._refresh_status()
        elif key == "k":
            self._move_focus(-1, 0)   # 上一个 tab
            self._refresh_status()
        elif key == "j":
            self._move_focus(1, 0)    # 下一个 tab
            self._refresh_status()
        elif key == "h":
            self._move_focus(0, -1)   # 左一个 shell
            self._refresh_status()
        elif key == "l":
            self._move_focus(0, 1)    # 右一个 shell
            self._refresh_status()
        elif key == "alt+k":
            self._move_pane(-1, 0)    # 移到上一个 tab
        elif key == "alt+j":
            self._move_pane(1, 0)     # 移到下一个 tab
        elif key == "alt+h":
            self._move_pane(0, -1)    # 同 tab 左移
        elif key == "alt+l":
            self._move_pane(0, 1)     # 同 tab 右移
        elif key == "c":
            self._close_pane()
        elif key == "r":
            self._cycle_pane_size()
        elif key == "g":
            self._toggle_overview()
        elif key == "q":
            self._quit_now()

    def _quit_now(self) -> None:
        """关闭所有 PTY 并退出整个进程。"""
        for w in self._panes:
            w.shutdown()
        self._panes.clear()
        # 先恢复 termios（在替换 stdin 之前，确保 Textual 能正确恢复终端）
        if self._saved_termios is not None:
            try:
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW,
                                  self._saved_termios)
            except Exception:
                pass
        # 将 stdin 替换为 /dev/null，使 Textual 输入线程的最终 read() 得到
        # 干净的 EOF 而非 EIO（OSError errno 5），避免输入线程崩溃后 app 卡死。
        try:
            devnull_fd = os.open(os.devnull, os.O_RDONLY)
            os.dup2(devnull_fd, 0)
            os.close(devnull_fd)
        except Exception:
            pass
        self.exit()
        t = threading.Timer(0.5, self._force_exit)
        t.daemon = True
        t.start()

    def _force_exit(self) -> None:
        """兜底强制退出：恢复 termios 后 os._exit。"""
        if self._saved_termios is not None:
            try:
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW,
                                  self._saved_termios)
            except Exception:
                pass
        os._exit(0)


def main() -> None:
    PiettyApp().run()
