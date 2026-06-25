"""niri 式水平滚动布局的纯逻辑测试。

模型: pane 有序列表 + 当前聚焦索引 + 视口宽度(列) + 每列固定宽度。
计算: 给定聚焦 pane, 应滚动到的 x 偏移(让聚焦 pane 完整可见)。
"""
from pietty.scroll import ScrollLayout


def test_empty():
    s = ScrollLayout(pane_width=80, viewport_width=120)
    assert s.scroll_offset_for(focused=0) == 0


def test_focus_first_no_scroll():
    # 3 pane 各 80 宽, 视口 120: 聚焦 0 不需滚动
    s = ScrollLayout(pane_width=80, viewport_width=120)
    s.count = 3
    assert s.scroll_offset_for(focused=0) == 0


def test_focus_offscreen_scrolls_right():
    # pane0 在 0-80, 视口 0-120; pane1 在 80-160 部分可见;
    # pane2 在 160-240 完全不可见, 聚焦 pane2 应滚到 160
    s = ScrollLayout(pane_width=80, viewport_width=120)
    s.count = 3
    assert s.scroll_offset_for(focused=2) == 120  # 160-40=120 让 pane2 左对齐
    # 实际: 让 pane2 完整可见, 偏移 = max(0, 160 - (120-80)) = 120


def test_focus_keeps_in_view_if_visible():
    # pane1 在 80-160, 视口 120 宽: pane1 右端 160 超出 120
    # 聚焦 pane1 需滚动使其完整: offset = 160-120 = 40
    s = ScrollLayout(pane_width=80, viewport_width=120)
    s.count = 3
    assert s.scroll_offset_for(focused=1) == 40


def test_scroll_offset_clamped_to_zero():
    s = ScrollLayout(pane_width=80, viewport_width=200)
    s.count = 3
    assert s.scroll_offset_for(focused=0) == 0


def test_total_width():
    s = ScrollLayout(pane_width=80, viewport_width=120)
    s.count = 4
    assert s.total_width() == 320


def test_max_scroll():
    s = ScrollLayout(pane_width=80, viewport_width=120)
    s.count = 4
    # total 320, viewport 120, max scroll = 320-120 = 200
    assert s.max_scroll() == 200
