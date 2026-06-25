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

    def key_to_bytes(self, key: str) -> bytes:
        return _KEYMAP.get(key, key.encode("utf-8"))


# 精简但覆盖常见键的 ANSI 序列
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

    # ---- lifecycle ----
    def on_mount(self) -> None:
        if ptyprocess is None:
            return
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
        self.refresh(layout=False)

    def _detach_reader(self) -> None:
        if self._fd is not None and getattr(self, "_loop", None) is not None:
            try:
                self._loop.remove_reader(self._fd)
            except Exception:
                pass
        self._closed = True

    def on_unmount(self) -> None:
        self._detach_reader()
        if self._pty is not None:
            try:
                self._pty.close()
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
        b = self.model.key_to_bytes(event.key)
        try:
            os.write(self._fd, b)
        except OSError:
            pass
        event.prevent_default()
