"""pietty —— niri 式水平滚动终端复用器。"""
from __future__ import annotations

import asyncio
import os
import sys
import termios
import threading
import time

from textual.app import App, ComposeResult
from textual.containers import HorizontalScroll
from textual.widgets import Static

from pietty.mode import ModeState
from pietty.terminal import TerminalWidget


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
    ("i", "i 插入"),
    ("n", "n 新建"),
    ("h", "h 左 / l 右"),
    ("r", "r 调整大小"),
    ("c", "c 关闭"),
    ("q", "q 退出"),
]
_INSERT_HINTS = [("escape", "Esc 回 normal")]


class PaneScroll(HorizontalScroll):
    """承载所有 TerminalWidget 的水平滚动容器。"""

    def on_resize(self, event) -> None:
        # 终端尺寸变化时，按各 pane 的比例重算宽度。
        try:
            self.app._apply_all_sizes()
        except Exception:
            pass


class StatusBar(Static):
    """底部状态栏：模式 + 键提示 + pane 计数。"""


class PiettyApp(App):
    CSS = """
    Screen { layout: vertical; }
    PaneScroll { height: 1fr; }
    TerminalWidget {
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

    def __init__(self) -> None:
        super().__init__()
        self._panes: list[TerminalWidget] = []
        self._focused: int = 0
        self.modes = ModeState()
        self._close_pending: int | None = None  # 关闭确认: 待关闭 pane 索引
        self._pane_seq: int = 0  # 单调递增的 pane ID 序号（避免与隐藏 widget 冲突）
        # 保存原始终端属性，用于强制退出时恢复（避免留下 raw mode）
        try:
            self._saved_termios = termios.tcgetattr(sys.stdin.fileno())
        except Exception:
            self._saved_termios = None

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
        self._pane_seq += 1
        w = TerminalWidget(id=f"pane-{self._pane_seq}")
        self._panes.append(w)
        self._focused = len(self._panes) - 1
        scroll = self.query_one(PaneScroll)
        asyncio.create_task(self._mount_and_focus(w, scroll))

    async def _mount_and_focus(self, w: TerminalWidget, scroll: PaneScroll) -> None:
        await scroll.mount(w)
        self._apply_pane_size(w)
        self._focus_and_scroll()
        # 强制重算(延迟一帧, 避免连续 mount 时重入)
        self.call_after_refresh(self._force_layout)

    def _close_pane(self) -> None:
        _dbg("_close_pane enter, panes=%d focused=%d", len(self._panes), self._focused)
        if not self._panes:
            return
        idx = self._focused
        w = self._panes[idx]
        # 先检查 shell 是否有运行中的子进程（不论 pane 数量）
        has_running = (w._pty is not None and w._pty.pid is not None
                       and self._has_children(w._pty.pid))
        _dbg("_close_pane: idx=%d has_running=%s", idx, has_running)
        if has_running:
            self._close_pending = idx
            self._refresh_status(pending_close=True)
            return
        # 无运行中子进程: 直接关。仅剩 1 个 pane 时退出整个进程。
        if len(self._panes) <= 1:
            _dbg("_close_pane: only 1 pane, quit process")
            self._quit_now()
            return
        self._do_close(idx)

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

    def _do_close(self, idx: int) -> None:
        """实际关闭 pane（异步 task，避免同步 remove + layout 卡死）。"""
        _dbg("_do_close enter idx=%d", idx)
        w = self._panes.pop(idx)
        self._focused = min(idx, len(self._panes) - 1)
        _dbg("_do_close: popped, panes=%d focused=%d", len(self._panes), self._focused)
        asyncio.create_task(self._close_task(w))

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
        except Exception as e:
            _dbg("_force_layout err %r", e)

    # ---- 面板尺寸 ----
    def _viewport_cols(self) -> int:
        """当前可用宽度（列）。优先 PaneScroll 的尺寸，回退到屏幕宽度。"""
        try:
            w = self.query_one(PaneScroll).size.width
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
        # 仅切换 "focused-pane" 视觉样式；不再调用 w.focus()。
        # 原因: 在内容溢出 viewport 的 HorizontalScroll 中调用 widget.focus()
        # 会触发 Textual(8.x) 每帧全屏重绘（渲染风暴），导致整个 app 卡死。
        # 按键路由改为由 App.on_key 统一处理，无需 widget 焦点。
        for w in self._panes:
            w.remove_class("focused-pane")
        w = self.focused_widget
        if w is not None:
            w.add_class("focused-pane")

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
        pos = f"[{self._focused + 1}/{count}]" if count else "[-]"
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
                idx = self._close_pending
                self._close_pending = None
                _dbg("pending: k confirm")
                # 确认终止: 若是最后一个 pane 则退出进程，否则关闭该 pane
                if len(self._panes) <= 1:
                    self._quit_now()
                else:
                    self._do_close(idx)
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
            # _close_pane 内部已调了 _refresh_status (pending 或 normal)，
            # 此处不再调，避免把 pending 状态的状态栏覆盖回 NORMAL。
        elif key == "r":
            self._cycle_pane_size()
        elif key == "q":
            self._quit_now()

    def _quit_now(self) -> None:
        """关闭所有 PTY 并退出整个进程。

        先尝试 Textual 的优雅退出（exit 发送 ExitApp 消息让消息泵解绕）；
        同时挂一个守护线程兜底——若 0.5s 后进程仍未退出，则手动恢复
        termios 后 os._exit 强制退出。进程若已正常退出，守护线程随
        之销毁，不会误触发。

        注意：不调 loop.stop()——那会导致 asyncio.run() 抛 RuntimeError
        ("Event loop stopped before Future completed")。
        """
        for w in self._panes:
            w.shutdown()
        self._panes.clear()
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
