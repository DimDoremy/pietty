from pietty.terminal import TerminalModel


def test_feed_bytes_updates_screen():
    m = TerminalModel(cols=10, rows=3)
    m.feed_bytes(b"hi")
    assert m.screen.buffer[0][0].data == "h"
    assert m.screen.buffer[0][1].data == "i"


def test_resize_propagates_to_screen():
    m = TerminalModel(cols=10, rows=3)
    m.resize(5, 20)
    assert m.screen.columns == 20
    assert m.screen.lines == 5


def test_feed_ansi_color_sets_attribute():
    m = TerminalModel(cols=10, rows=3)
    m.feed_bytes(b"\x1b[1mA\x1b[0m")
    assert m.screen.buffer[0][0].bold
