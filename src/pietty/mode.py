"""Vim 风格模态状态机。

两种模式:
  - ``normal``: 默认。按键归 pietty（不透传 shell），彻底避免与 shell
    快捷键冲突。i/a 进 insert。
  - ``insert``: 按键透传 shell（含 C-c/C-a 等）。Esc 回 normal。

设计目标: 默认 normal 最大化避免冲突，shell 收不到任何键直到用户显式进 insert。
"""
from __future__ import annotations

from typing import Literal

Mode = Literal["normal", "insert"]

# normal 模式下进入 insert 的键
_NORMAL_TO_INSERT = {"i", "a"}


class ModeState:
    """模式状态机。transition 返回 True 表示模式发生了切换。"""

    def __init__(self) -> None:
        self.current: Mode = "normal"

    def transition(self, key: str) -> bool:
        """根据按键尝试切换模式。

        返回 True 表示模式已切换（调用方应刷新 UI）；False 表示未切换
        （按键由当前模式的命令路由处理或透传）。
        """
        if self.current == "normal":
            if key in _NORMAL_TO_INSERT:
                self.current = "insert"
                return True
            return False
        else:  # insert
            if key in ("escape", "alt+n"):
                self.current = "normal"
                return True
            return False
