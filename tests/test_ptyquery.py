"""测试 PTY 查询应答拦截器。

交互式 shell(bash)启动时会发 OSC/DSR 查询等待终端应答，
若 PTY master 不应答，shell 会卡死。本模块拦截这些查询并返回应答。
"""
from pietty.ptyquery import ReplyBuffer


def test_replies_dsr_cursor_position():
    rb = ReplyBuffer()
    rb.feed(b"\x1b[6n")
    assert rb.pending == ["\x1b[1;1R"]


def test_replies_dsr_cursor_uses_given_position():
    rb = ReplyBuffer(cursor=(5, 10))
    rb.feed(b"\x1b[6n")
    assert rb.pending == ["\x1b[5;10R"]  # ANSI 是 (row;col) 1-indexed


def test_replies_dsr_status_ok():
    rb = ReplyBuffer()
    rb.feed(b"\x1b[5n")
    assert rb.pending == ["\x1b[0n"]


def test_does_not_answer_osc11_background_query():
    # OSC 11 不应答: 发送方不读取应答, 应答会泄漏为可见输入
    rb = ReplyBuffer(bg="#0c0c0c")
    rb.feed(b"\x1b]11;?\x1b\\")
    assert rb.pending == []


def test_does_not_answer_osc11_bel_terminated():
    rb = ReplyBuffer(bg="#0c0c0c")
    rb.feed(b"\x1b]11;?\x07")
    assert rb.pending == []


def test_updates_cursor_position():
    rb = ReplyBuffer()
    assert rb.cursor == (1, 1)
    rb.update_cursor(row=3, col=7)
    assert rb.cursor == (3, 7)
    rb.feed(b"\x1b[6n")
    assert rb.pending == ["\x1b[3;7R"]


def test_non_query_bytes_ignored():
    rb = ReplyBuffer()
    rb.feed(b"hello world \x1b[6n bye")
    assert rb.pending == ["\x1b[1;1R"]
