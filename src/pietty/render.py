import codecs


class Utf8Decoder:
    """增量 UTF-8 解码：绝不在多字节字符中间截断。"""

    def __init__(self) -> None:
        self._dec = codecs.getincrementaldecoder("utf-8")(errors="strict")

    def feed(self, data: bytes) -> str:
        return self._dec.decode(data)
