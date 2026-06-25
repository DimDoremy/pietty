"""PTY 终端查询应答器。

交互式 shell（bash/zsh/fish）启动时通常会发终端能力查询并等待应答，
否则会卡死：
  - ``\\x1b[6n``  DSR — 报告光标位置
  - ``\\x1b[5n``  DSR — 报告设备状态
  - ``\\x1b]11;?ST``  OSC 11 — 查询默认背景色（ST 是 \\x1b\\\\ 或 \\x07）

pietty 作为 PTY master 必须代替物理终端应答这些查询，
否则 shell 不会显示 prompt、输入也不被处理。
"""
from __future__ import annotations

import re

# DSR 光标位置: \x1b[6n  （CSI Ps n）
_RE_DSR_CURSOR = re.compile(rb"\x1b\[6n")
# DSR 状态: \x1b[5n
_RE_DSR_STATUS = re.compile(rb"\x1b\[5n")
# OSC 11 查询背景色: \x1b]11;?\x1b\\ 或 \x1b]11;?\x07
_RE_OSC11 = re.compile(rb"\x1b\]11;\?(?:\x1b\\|\x07)")


class ReplyBuffer:
    """扫描 shell 输出字节流，对终端查询生成应答。

    cursor 默认 (1, 1)；外部（TerminalWidget）在每次渲染后
    用 pyte screen 的真实光标位置调用 update_cursor()。
    """

    def __init__(self, cursor: tuple[int, int] = (1, 1),
                 bg: str = "#0c0c0c") -> None:
        self.cursor = cursor  # (row, col) 1-indexed
        self.bg = bg
        self.pending: list[str] = []

    def update_cursor(self, row: int, col: int) -> None:
        self.cursor = (row, col)

    def _hex_to_osc_rgb(self, hexcolor: str) -> str:
        # #rrggbb -> rgb:rrrr/gggg/bbbb （xterm 格式，每通道 16 位）
        h = hexcolor.lstrip("#")
        r, g, b = h[0:2], h[2:4], h[4:6]
        return f"rgb:{r}{r}/{g}{g}/{b}{b}"

    def feed(self, data: bytes) -> None:
        row, col = self.cursor
        # DSR 光标位置应答: ESC [ <row> ; <col> R （ANSI 是 row;col，1-indexed）
        for _ in _RE_DSR_CURSOR.finditer(data):
            self.pending.append(f"\x1b[{row};{col}R")
        for _ in _RE_DSR_STATUS.finditer(data):
            self.pending.append("\x1b[0n")
        for _ in _RE_OSC11.finditer(data):
            self.pending.append(
                f"\x1b]11;{self._hex_to_osc_rgb(self.bg)}\x1b\\"
            )
