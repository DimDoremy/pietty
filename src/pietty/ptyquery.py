"""PTY 终端查询应答器。

交互式 shell（bash/zsh/fish）启动时会发终端能力查询。
其中 readline 会主动读取并依赖的查询必须应答，否则 shell 卡死：
  - ``\\x1b[6n``  DSR — 报告光标位置（readline 依赖，阻塞等待）
  - ``\\x1b[5n``  DSR — 报告设备状态

**不**应答 OSC 11（\\x1b]11;?）背景色查询：
  它由 prompt 主题（powerline/starship 等）发送，发送方不主动读取应答，
  若应答则泄漏为命令行可见字符（如 "11;rgb:0c0c/0c0c/0c0c"）。
  缺省时 shell 回退默认对比度，功能不受影响。
"""
from __future__ import annotations

import re

# DSR 光标位置: \x1b[6n  （CSI Ps n）
_RE_DSR_CURSOR = re.compile(rb"\x1b\[6n")
# DSR 状态: \x1b[5n
_RE_DSR_STATUS = re.compile(rb"\x1b\[5n")


class ReplyBuffer:
    """扫描 shell 输出字节流，对终端查询生成应答。

    cursor 默认 (1, 1)；外部（TerminalWidget）在每次渲染后
    用 pyte screen 的真实光标位置调用 update_cursor()。
    """

    def __init__(self, cursor: tuple[int, int] = (1, 1),
                 bg: str = "#0c0c0c") -> None:
        self.cursor = cursor  # (row, col) 1-indexed
        self.bg = bg  # 保留: 未来若需 OSC 应答可启用（当前不使用）
        self.pending: list[str] = []

    def update_cursor(self, row: int, col: int) -> None:
        self.cursor = (row, col)

    def feed(self, data: bytes) -> None:
        row, col = self.cursor
        # DSR 光标位置应答: ESC [ <row> ; <col> R （ANSI 是 row;col，1-indexed）
        # readline 会主动读取此应答（依赖它定位），不泄漏。
        for _ in _RE_DSR_CURSOR.finditer(data):
            self.pending.append(f"\x1b[{row};{col}R")
        for _ in _RE_DSR_STATUS.finditer(data):
            self.pending.append("\x1b[0n")
        # OSC 11 不应答（见模块文档：会泄漏为可见输入）


# 向后兼容：diag 脚本引用
_RE_OSC11 = re.compile(rb"\x1b\]11;\?(?:\x1b\\|\x07)")

def _hex_to_osc_rgb(hexcolor: str) -> str:  # 仅供诊断脚本用
    h = hexcolor.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"rgb:{r}{r}/{g}{g}/{b}{b}"
