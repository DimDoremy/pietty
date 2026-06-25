"""niri 式水平滚动布局逻辑。

所有 pane 等宽水平排列成一条，聚焦 pane 滚入视口。
纯逻辑，无 UI 依赖，便于测试。
"""
from __future__ import annotations


class ScrollLayout:
    """水平滚动平铺：count 个 pane，每个 pane_width 列宽。"""

    def __init__(self, pane_width: int = 80, viewport_width: int = 80) -> None:
        self.pane_width = pane_width
        self.viewport_width = viewport_width
        self.count = 0  # pane 数量

    def pane_x(self, index: int) -> int:
        """pane[index] 的起始 x。"""
        return index * self.pane_width

    def total_width(self) -> int:
        return self.count * self.pane_width

    def max_scroll(self) -> int:
        return max(0, self.total_width() - self.viewport_width)

    def scroll_offset_for(self, focused: int) -> int:
        """计算让 pane[focused] 完整可见的最小滚动偏移。

        策略：若 pane 右端超出视口右端，向右滚到 pane 右端贴齐视口右端；
        若 pane 左端已在视口内则不滚（避免不必要的左移）。
        """
        if self.count == 0 or focused >= self.count:
            return 0
        pane_left = self.pane_x(focused)
        pane_right = pane_left + self.pane_width
        if pane_right <= self.viewport_width:
            # 完全在视口内（从 0 起）
            return 0
        # 滚到 pane 左端贴齐视口左端的最小偏移（让整 pane 可见）
        offset = pane_right - self.viewport_width
        # 若 pane 比视口宽，左对齐
        if self.pane_width >= self.viewport_width:
            offset = pane_left
        return min(max(0, offset), self.max_scroll())
