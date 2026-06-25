from pietty.render import Utf8Decoder


def test_utf8_decoder_full():
    d = Utf8Decoder()
    assert d.feed("你好".encode("utf-8")) == "你好"


def test_utf8_decoder_partial_then_rest():
    d = Utf8Decoder()
    data = "你好".encode("utf-8")
    head, tail = data[:4], data[4:]
    assert d.feed(head) == "你"
    assert d.feed(tail) == "你好"


def test_utf8_decoder_across_multiple_feeds():
    d = Utf8Decoder()
    data = "a😀b".encode("utf-8")
    out = "".join(d.feed(data[i:i + 1]) for i in range(len(data)))
    assert out == "a😀b"
