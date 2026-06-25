"""模式状态机单测（Vim 风格 normal/insert）。"""
from pietty.mode import ModeState


def test_default_mode_is_normal():
    m = ModeState()
    assert m.current == "normal"


def test_normal_to_insert():
    m = ModeState()
    assert m.transition("i") is True
    assert m.current == "insert"


def test_normal_to_insert_with_a():
    m = ModeState()
    assert m.transition("a") is True
    assert m.current == "insert"


def test_insert_back_to_normal_with_escape():
    m = ModeState()
    m.transition("i")
    assert m.transition("escape") is True
    assert m.current == "normal"


def test_normal_mode_keys_dont_change_mode():
    """normal 模式下命令键不切换模式（除了 i/a）。"""
    m = ModeState()
    for key in ("s", "v", "o", "O", "c", "q", "h", "j", "k", "l"):
        assert m.transition(key) is False
        assert m.current == "normal"


def test_insert_mode_keys_dont_change_mode():
    """insert 模式下普通键不切换模式（除了 escape）。"""
    m = ModeState()
    m.transition("i")
    for key in ("a", "s", "ctrl+c", "x", "j"):
        assert m.transition(key) is False
        assert m.current == "insert"


def test_ctrl_c_in_insert_does_not_exit():
    """insert 模式下 Ctrl+C 透传 shell，不退出 pietty。"""
    m = ModeState()
    m.transition("i")
    assert m.transition("ctrl+c") is False
    assert m.current == "insert"


def test_unknown_normal_key_ignored():
    m = ModeState()
    assert m.transition("f1") is False
    assert m.current == "normal"
