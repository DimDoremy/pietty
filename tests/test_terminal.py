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


def test_key_to_bytes_printable_char():
    m = TerminalModel()
    assert m.key_to_bytes("a", "a") == b"a"
    assert m.key_to_bytes("comma", ",") == b","
    assert m.key_to_bytes("semicolon", ";") == b";"


def test_key_to_bytes_named_function_keys():
    m = TerminalModel()
    assert m.key_to_bytes("left", None) == b"\x1b[D"
    assert m.key_to_bytes("up", None) == b"\x1b[A"
    assert m.key_to_bytes("enter", None) == b"\r"


def test_key_to_bytes_ctrl_letter():
    m = TerminalModel()
    assert m.key_to_bytes("ctrl+a", None) == b"\x01"
    assert m.key_to_bytes("ctrl+c", None) == b"\x03"
    assert m.key_to_bytes("ctrl+z", None) == b"\x1a"


def test_key_to_bytes_unknown_returns_none():
    m = TerminalModel()
    assert m.key_to_bytes("f1", None) is None
    assert m.key_to_bytes("ctrl+comma", None) is None


def test_key_to_bytes_does_not_write_key_name():
    """回归：不能把 'comma' 这样的规范名直接写入。"""
    m = TerminalModel()
    assert m.key_to_bytes("comma", ",") != b"comma"
