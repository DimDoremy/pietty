from __future__ import annotations

import codecs

import pyte
from rich.color import Color
from rich.style import Style
from rich.text import Text


class Utf8Decoder:
    """增量 UTF-8 解码：绝不在多字节字符中间截断。"""

    def __init__(self) -> None:
        self._dec = codecs.getincrementaldecoder("utf-8")(errors="strict")

    def feed(self, data: bytes) -> str:
        return self._dec.decode(data)


_NAMED_16 = {"default", "black", "red", "green", "yellow", "blue",
             "magenta", "cyan", "white", "bright_black", "bright_red",
             "bright_green", "bright_yellow", "bright_blue",
             "bright_magenta", "bright_cyan", "bright_white",
             "transparent"}

_COLOR_CACHE: dict[str, object] = {}


def _to_color(val: str):
    if not val or val in ("default", "transparent"):
        return None
    cached = _COLOR_CACHE.get(val)
    if cached is not None:
        return cached
    if val in _NAMED_16:
        try:
            c = Color.parse(val)
        except Exception:
            c = None
    else:
        try:
            c = Color.parse("#" + val[-6:])
        except Exception:
            c = None
    _COLOR_CACHE[val] = c
    return c


# Style 缓存：终端里绝大多数 cell 共享同一种样式（默认/光标/选中），
# 缓存后避免每次渲染创建 ~1840 个 Style 对象。
_STYLE_CACHE: dict[tuple, Style] = {}


def char_to_style(char) -> Style:
    key = (char.fg, char.bg, bool(char.bold), bool(char.italics),
           bool(char.underscore), bool(char.strikethrough), bool(char.reverse))
    style = _STYLE_CACHE.get(key)
    if style is None:
        style = Style(
            color=_to_color(char.fg),
            bgcolor=_to_color(char.bg),
            bold=bool(char.bold),
            italic=bool(char.italics),
            underline=bool(char.underscore),
            strike=bool(char.strikethrough),
            reverse=bool(char.reverse),
        )
        _STYLE_CACHE[key] = style
    return style


def screen_to_rich(screen: pyte.Screen) -> Text:
    text = Text()
    for y in range(screen.lines):
        line = screen.buffer[y]
        for x in range(screen.columns):
            ch = line[x]
            data = ch.data or " "
            text.append(data, style=char_to_style(ch))
        if y != screen.lines - 1:
            text.append("\n")
    return text
