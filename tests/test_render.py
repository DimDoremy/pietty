from pietty.render import Utf8Decoder


def test_utf8_decoder_full():
    d = Utf8Decoder()
    assert d.feed("你好".encode("utf-8")) == "你好"


def test_utf8_decoder_partial_then_rest():
    d = Utf8Decoder()
    data = "你好".encode("utf-8")
    head, tail = data[:4], data[4:]
    assert d.feed(head) == "你"
    assert d.feed(tail) == "好"


def test_utf8_decoder_across_multiple_feeds():
    d = Utf8Decoder()
    data = "a😀b".encode("utf-8")
    out = "".join(d.feed(data[i:i + 1]) for i in range(len(data)))
    assert out == "a😀b"


import pyte
from pietty.render import screen_to_rich, char_to_style


def _screen(text: str, cols=80, rows=24):
    s = pyte.Screen(cols, rows)
    pyte.Stream(s).feed(text)
    return s


def test_plain_text_rendered():
    s = _screen("hi")
    txt = screen_to_rich(s)
    assert "hi" in txt.plain


def test_bold_style_detected():
    s = _screen("\x1b[1mB\x1b[0m")
    st = char_to_style(s.buffer[0][0])
    assert st.bold


def test_truecolor_style_detected():
    s = _screen("\x1b[38;2;10;20;30mX\x1b[0m")
    st = char_to_style(s.buffer[0][0])
    assert st.color is not None


def test_256color_style_detected():
    s = _screen("\x1b[38;5;200mX\x1b[0m")
    st = char_to_style(s.buffer[0][0])
    assert st.color is not None
