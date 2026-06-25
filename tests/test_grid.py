"""把 PaneTree 映射到网格坐标，用于 CSS Grid 平铺布局。

每个叶子得到 (row, col, rowspan, colspan)，避免嵌套容器导致的
Textual 动态布局问题（实测 remove+remount 嵌套容器后 region 归零）。
"""
from pietty.gridlayout import grid_map, grid_size
from pietty.layout import PaneTree


def test_single_pane_grid():
    t = PaneTree()
    assert grid_map(t) == {t.focused: (0, 0, 1, 1)}
    assert grid_size(t) == (1, 1)


def test_horizontal_split_two_columns():
    t = PaneTree()
    a = t.focused
    b = t.split(a, "horizontal")
    gm = grid_map(t)
    assert gm[a] == (0, 0, 1, 1)
    assert gm[b] == (0, 1, 1, 1)
    assert grid_size(t) == (1, 2)


def test_vertical_split_two_rows():
    t = PaneTree()
    a = t.focused
    b = t.split(a, "vertical")
    gm = grid_map(t)
    assert gm[a] == (0, 0, 1, 1)
    assert gm[b] == (1, 0, 1, 1)
    assert grid_size(t) == (2, 1)


def test_h_then_v_nested():
    """水平拆分(a|b)，再对 b 竖直拆分(b 上、c 下)。"""
    t = PaneTree()
    a = t.focused
    b = t.split(a, "horizontal")
    c = t.split(b, "vertical")
    gm = grid_map(t)
    # a 占左列整列(rowspan=2)；b 右上；c 右下
    assert gm[a] == (0, 0, 2, 1)
    assert gm[b] == (0, 1, 1, 1)
    assert gm[c] == (1, 1, 1, 1)
    assert grid_size(t) == (2, 2)
