from __future__ import annotations

import os
import shlex

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
from textual.reactive import reactive
from textual.widget import Widget

from pietty.render import screen_to_rich

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
                 id: str | None = None) -> None:
        super().__init__(id=id)
        self._shell = shell
        self._cwd = cwd or os.getcwd()
        self._term = term
        self._locale = locale
        self.model = TerminalModel()
        self._pty = None
        self._fd: int | None = None
        self._closed = False
        self._spawned = False  # 防止布局重建 re-mount 时重复 spawn PTY
        from pietty.ptyquery import ReplyBuffer
        self._reply = ReplyBuffer(bg="#0c0c0c")

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
            # PTY 子进程退出后 read 报 EIO
            self._detach_reader()
            return
        if not data:
            self._detach_reader()
            return
        self.model.feed_bytes(data)
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
        self.refresh(layout=False)

    def _detach_reader(self) -> None:
        if self._fd is not None and getattr(self, "_loop", None) is not None:
            try:
                self._loop.remove_reader(self._fd)
            except Exception:
                pass

    def on_unmount(self) -> None:
        # 布局重建会先 unmount 再 mount：只 detach reader，不销毁 PTY
        self._detach_reader()

    def shutdown(self) -> None:
        """真正关闭 PTY（仅退出/关闭面板时调用）。"""
        self._detach_reader()
        self._closed = True
        if self._pty is not None:
            try:
                self._pty.close(force=True)
            except Exception:
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
        return screen_to_rich(self.model.screen)

    def on_key(self, event) -> None:
        if self._pty is None or self._fd is None:
            return
        # escape 让 App 处理模式切换（先 return，不写 PTY）
        if event.key == "escape":
            return
        # 仅 insert 模式透传 shell；normal 模式由 App 拦截命令键
        if getattr(self.app, "modes", None) is not None:
            if self.app.modes.current != "insert":
                return
        b = self.model.key_to_bytes(event.key,
                                   getattr(event, "character", None))
        if b is None:
            return
        try:
            os.write(self._fd, b)
        except OSError:
            pass
        event.prevent_default()
        event.stop()  # 阻止冒泡，避免与 C-x 前缀处理冲突
