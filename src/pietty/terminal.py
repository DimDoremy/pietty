from __future__ import annotations

import os
import shlex
import signal

import pyte

from pietty.render import Utf8Decoder


def _resolve_shell(spec: str) -> list[str]:
    if spec.startswith("$"):
        val = os.environ.get(spec[1:], "")
        if val:
            return shlex.split(val)
    return shlex.split(spec) or ["/bin/sh"]


def _default_env(term: str, locale: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "TERM": term,
        "LANG": locale,
        "LC_ALL": locale,
        "COLORTERM": "truecolor",
    })
    return env


class TerminalModel:
    """纯逻辑：屏幕状态 + 解码，无 PTY 依赖，便于测试。"""

    def __init__(self, cols: int = 80, rows: int = 24,
                 history: int = 10000) -> None:
        self.screen = pyte.HistoryScreen(cols, rows, history=history)
        self.stream = pyte.Stream(self.screen)
        self._dec = Utf8Decoder()

    def feed_bytes(self, data: bytes) -> None:
        self.stream.feed(self._dec.feed(data))

    def resize(self, rows: int, cols: int) -> None:
        self.screen.resize(lines=rows, columns=cols)

    def key_to_bytes(self, key: str, character: str | None) -> bytes | None:
        """把 Textual 按键转为写入 PTY 的字节。

        返回 None 表示该键不产生输入（忽略）。
        优先用 character（真实字符，避免把 key 规范名如 'comma' 写进去）。
        """
        # 1) 可打印字符优先
        if character:
            return character.encode("utf-8")
        # 2) 命名键查表（方向键/功能键）
        if key in _KEYMAP:
            return _KEYMAP[key]
        # 3) ctrl+<单字符> 转为控制码 (Ctrl+A -> \x01 ... Ctrl+Z -> \x1a)
        if key.startswith("ctrl+") and len(key) == 6:
            ch = key[5]
            if "a" <= ch <= "z":
                return bytes([ord(ch) - ord("a") + 1])
            if "@" <= ch <= "_":
                return bytes([ord(ch.upper()) - ord("A") + 1])
        # 4) 其余修饰组合（alt+/shift+ 功能键等）暂忽略
        return None


# 精简但覆盖常见键的 ANSI 序列（仅为 character=None 的功能键）
_KEYMAP: dict[str, bytes] = {
    "up": b"\x1b[A",
    "down": b"\x1b[B",
    "right": b"\x1b[C",
    "left": b"\x1b[D",
    "home": b"\x1b[H",
    "end": b"\x1b[F",
    "delete": b"\x1b[3~",
    "pageup": b"\x1b[5~",
    "pagedown": b"\x1b[6~",
    "tab": b"\t",
    "enter": b"\r",
    "escape": b"\x1b",
    "backspace": b"\x7f",
}


import asyncio  # noqa: F401  (保留供未来 async 用)

from rich.text import Text
from rich.style import Style
from textual.reactive import reactive
from textual.widget import Widget

from pietty.render import screen_to_rich, char_to_style

# 在 _refresh_paused 期间返回的空白 Text 常量（保证同一对象，使合成器免于重复重绘）
_PAUSED_TEXT = Text()
_PAUSED_STYLE = Style()

try:
    import ptyprocess
except ImportError:  # 测试环境可能无
    ptyprocess = None  # type: ignore


class TerminalWidget(Widget):

    DEFAULT_CSS = """
    TerminalWidget { background: #0c0c0c; color: #e0e0e0; }
    """

    can_focus = True  # 可聚焦，否则按键不会分发给 widget

    _tick = reactive(0, init=False)  # 保留: 未来需驱动的 reactive 计数器

    def __init__(self, shell: str = "$SHELL", cwd: str | None = None,
                 term: str = "xterm-256color", locale: str = "en_US.UTF-8",
                 id: str | None = None, history_lines: int = 10000) -> None:
        super().__init__(id=id)
        self._shell = shell
        self._cwd = cwd or os.getcwd()
        self._term = term
        self._locale = locale
        self.model = TerminalModel(history=history_lines)
        self._pty = None
        self._fd: int | None = None
        self._closed = False
        self._spawned = False
        from pietty.ptyquery import ReplyBuffer
        self._reply = ReplyBuffer(bg="#0c0c0c")
        self._dirty = False
        self._term_cache = None
        self._refresh_scheduled = False
        self._refresh_paused = False
        self.size_fraction: float = 0.5
        self._scrollback_mode = False  # v 键切换的回看模式
        self._alt_screen: bool = False
        self._alt_screen_saved = None  # alt-screen 进入时保存的屏幕状态
        # viewer 模式状态
        self._viewer_active: bool = False
        self._viewer_row: int = 0
        self._viewer_col: int = 0
        self._viewer_sel_start: tuple[int, int] | None = None
        self._viewer_sel_end: tuple[int, int] | None = None

    # ---- lifecycle ----
    def on_mount(self) -> None:
        if ptyprocess is None:
            return
        if self._spawned:
            # 布局重建 re-mount：重新注册 reader，不重复 spawn
            if self._fd is not None and not self._closed:
                os.set_blocking(self._fd, False)
                self._loop = asyncio.get_event_loop()
                self._loop.add_reader(self._fd, self._on_readable)
            return
        self._spawned = True
        argv = _resolve_shell(self._shell)
        try:
            self._pty = ptyprocess.PtyProcess.spawn(
                argv, cwd=self._cwd,
                env=_default_env(self._term, self._locale))
        except Exception:
            argv = ["/bin/sh"]
            self._pty = ptyprocess.PtyProcess.spawn(
                argv, cwd=self._cwd,
                env=_default_env(self._term, self._locale))
        self.model.resize(self.size.height, self.size.width)
        self._pty.setwinsize(self.size.height, self.size.width)
        # 非阻塞 fd + asyncio 原生 reader（避免阻塞线程池与退出挂起）
        self._fd = self._pty.fd
        os.set_blocking(self._fd, False)
        self._loop = asyncio.get_event_loop()
        self._loop.add_reader(self._fd, self._on_readable)

    def _on_readable(self) -> None:
        if self._fd is None or self._closed:
            return
        try:
            data = os.read(self._fd, 65536)
        except BlockingIOError:
            return
        except OSError:
            self._detach_reader()
            return
        if not data:
            self._detach_reader()
            return

        # 手动 alt-screen 支持（pyte 不处理 \x1b[?1049h/l）
        if b"\x1b[?1049h" in data and not self._alt_screen:
            self._alt_screen = True
            # 保存当前屏幕（浅拷贝每个可见行的 Char 数据）
            self._alt_screen_saved = [
                [c.copy() for c in line.values()]
                for line in self.model.screen.buffer
            ]
        elif b"\x1b[?1049l" in data and self._alt_screen:
            self._alt_screen = False

        self.model.feed_bytes(data)

        # alt-screen 退出时恢复保存的内容
        if self._alt_screen_saved is not None and not self._alt_screen:
            screen = self.model.screen
            for y, row_data in enumerate(self._alt_screen_saved):
                if y < screen.lines:
                    for x, c in enumerate(row_data):
                        if x < screen.columns:
                            screen.buffer[y][x] = c
            self._alt_screen_saved = None

        # pyte 不识别 1049 模式 → 强制清除序列中的模式设置，
        # 确保 feed_bytes 后屏幕内容正确。
        if b"\x1b[?1049" in data:
            self._term_cache = None
            self._dirty = True

        # 用 pyte screen 的真实光标位置更新应答器
        # 用 pyte screen 的真实光标位置更新应答器
        try:
            self._reply.update_cursor(
                row=self.model.screen.cursor.y + 1,
                col=self.model.screen.cursor.x + 1,
            )
        except Exception:
            pass
        # 扫描 shell 发出的终端查询并应答（否则 shell 卡死）
        self._reply.feed(data)
        if self._reply.pending:
            replies = self._reply.pending
            self._reply.pending = []
            for r in replies:
                try:
                    os.write(self._fd, r.encode("utf-8"))
                except OSError:
                    break
        # 节流: 仅标记脏, 每 ~33ms (30fps) 合并刷新一次, 避免高频 PTY 数据
        # 触发过多 refresh 把 Textual 合成器压垮（渲染风暴/卡死）。
        self._dirty = True
        self._term_cache = None
        if not getattr(self, "_refresh_scheduled", False):
            self._refresh_scheduled = True
            asyncio.get_event_loop().call_later(0.033, self._do_refresh_safe)

    def _do_refresh_safe(self) -> None:
        """节流刷新入口（由 call_later 调度）。"""
        self._refresh_scheduled = False
        if self._closed or not self.is_mounted:
            return
        if self._refresh_paused:
            return
        if self._dirty:
            self._dirty = False
            try:
                self.refresh(layout=False)
            except Exception:
                pass

    def _do_refresh(self) -> None:
        self._refresh_scheduled = False
        if self._closed:
            return
        if self._dirty:
            self._dirty = False
            self.refresh(layout=False)

    def _detach_reader(self) -> None:
        if self._fd is not None and getattr(self, "_loop", None) is not None:
            try:
                self._loop.remove_reader(self._fd)
            except Exception:
                pass

    def on_unmount(self) -> None:
        self._detach_reader()

    def shutdown(self) -> None:
        """真正关闭 PTY（仅退出/关闭面板时调用）。
        用 os.close/os.kill 绕过 ptyprocess.close() 的 time.sleep 阻塞。
        """
        self._detach_reader()
        self._closed = True
        if self._pty is not None:
            pid = self._pty.pid
            try:
                if self._fd is not None:
                    os.close(self._fd)
            except OSError:
                pass
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
            try:
                os.waitpid(pid, os.WNOHANG)
            except OSError:
                pass
        self._pty = None
        self._fd = None

    def on_resize(self, event) -> None:
        r, c = self.size.height, self.size.width
        if r <= 0 or c <= 0:
            return
        self.model.resize(r, c)
        if self._pty is not None:
            self._pty.setwinsize(r, c)

    def render(self) -> Text:
        if self._viewer_active:
            return self._render_viewer()
        if self._term_cache is None and not self._refresh_paused:
            self._term_cache = screen_to_rich(self.model.screen)
        return self._term_cache or _PAUSED_TEXT

    @property
    def _viewer_total_lines(self) -> int:
        """历史 + 当前屏幕的总行数。"""
        return len(self.model.screen.history.top) + self.model.screen.lines

    def _viewer_clamp(self) -> None:
        """限制光标不越界。"""
        total = self._viewer_total_lines
        cols = self.model.screen.columns
        self._viewer_row = max(0, min(self._viewer_row, total - 1))
        self._viewer_col = max(0, min(self._viewer_col, cols - 1))

    def _get_viewer_line(self, abs_row: int) -> dict | None:
        """获取 viewer 中绝对行号 abs_row 对应行的 Char dict。"""
        screen = self.model.screen
        n_history = len(screen.history.top)
        if abs_row < n_history:
            return screen.history.top[abs_row]
        screen_row = abs_row - n_history
        if 0 <= screen_row < screen.lines:
            return screen.buffer[screen_row]
        return None

    def _render_viewer(self) -> Text:
        """渲染 viewer 模式：viewport 内的历史/屏幕内容 + 光标 + 选区。"""
        self._viewer_clamp()
        screen = self.model.screen
        total = self._viewer_total_lines
        visible = min(self.size.height or 24, total)  # 视口高度
        # 计算可见窗口：光标居中
        view_start = max(0, min(self._viewer_row - visible // 2,
                                total - visible))
        view_end = min(view_start + visible, total)
        text = Text()
        for abs_row in range(view_start, view_end):
            line_dict = self._get_viewer_line(abs_row)
            for x in range(screen.columns):
                ch = line_dict[x] if line_dict is not None else None
                data = ch.data or " " if ch else " "
                style = char_to_style(ch) if ch else _PAUSED_STYLE

                # 选区高亮
                if self._viewer_sel_start is not None and self._viewer_sel_end is not None:
                    sr, sc = self._viewer_sel_start
                    er, ec = self._viewer_sel_end
                    sr, er = min(sr, er), max(sr, er)
                    if sr == er:
                        in_sel = (abs_row == sr and sc <= x <= ec)
                    else:
                        in_sel = ((abs_row == sr and x >= sc)
                                  or (abs_row == er and x <= ec)
                                  or (sr < abs_row < er))
                    if in_sel:
                        style = style + Style(bgcolor="white", color="black")

                # 光标高亮
                if abs_row == self._viewer_row and x == self._viewer_col:
                    style = Style(bgcolor="white", color="black", bold=True)

                text.append(data, style=style)
            text.append("\n")
        return text

    def send_key(self, key: str, character: str | None) -> None:
        """由 App.on_key 路由调用: 把按键转为字节写入 PTY（insert 模式）。

        焦点不再设在 TerminalWidget 上（避免在溢出的 HorizontalScroll 中
        聚焦导致 Textual 全屏重绘风暴），因此按键统一由 App 路由。
        """
        if self._pty is None or self._fd is None or self._closed:
            return
        b = self.model.key_to_bytes(key, character)
        if b is None:
            return
        try:
            os.write(self._fd, b)
        except OSError:
            pass

    def on_key(self, event) -> None:
        # 兜底: 若 widget 仍意外获得焦点，按 insert 模式透传
        if self._pty is None or self._fd is None:
            return
        if event.key == "escape":
            return
        if getattr(self.app, "modes", None) is not None:
            if self.app.modes.current != "insert":
                return
        self.send_key(event.key, getattr(event, "character", None))
        event.prevent_default()
        event.stop()
