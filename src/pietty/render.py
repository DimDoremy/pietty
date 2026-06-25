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


def _to_color(val: str):
    if val in ("default", "", "transparent"):
        return None
    if val in _NAMED_16:
        try:
            return Color.parse(val)
        except Exception:
            return None
    # pyte 返回 6 位 hex（truecolor 与 256 色均为此格式）
    try:
        return Color.parse("#" + val[-6:])
    except Exception:
        return None


def char_to_style(char) -> Style:
    color = _to_color(char.fg)
    bgcolor = _to_color(char.bg)
    return Style(
        color=color,
        bgcolor=bgcolor,
        bold=bool(char.bold),
        italic=bool(char.italics),
        underline=bool(char.underscore),
        strike=bool(char.strikethrough),
        reverse=bool(char.reverse),
    )


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
