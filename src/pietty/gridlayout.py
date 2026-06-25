"""把 PaneTree 映射到网格坐标，用于 CSS Grid 平铺布局。"""
from __future__ import annotations

from pietty.layout import PaneTree, Horizontal, Vertical, Pane


def _assign(node, r0: int, c0: int, rows: int, cols: int, out: dict) -> None:
    """把矩形 (r0,c0,rows,cols) 分配给 node 的子树。"""
    if isinstance(node, Pane):
        out[node.id] = (r0, c0, rows, cols)
        return
    c1, c2 = node.children
    if isinstance(node, Horizontal):  # 左右分: 列对半
        half = max(1, cols // 2)
        _assign(c1, r0, c0, rows, half, out)
        _assign(c2, r0, c0 + half, rows, cols - half, out)
    else:  # Vertical: 上下分
        half = max(1, rows // 2)
        _assign(c1, r0, c0, half, cols, out)
        _assign(c2, r0 + half, c0, rows - half, cols, out)


def grid_map(tree: PaneTree) -> dict:
    """返回 {pane_id: (row, col, rowspan, colspan)}。"""
    rows, cols = grid_size(tree)
    out: dict = {}
    _assign(tree.root, 0, 0, rows, cols, out)
    return out


def _dims(node) -> tuple[int, int]:
    if isinstance(node, Pane):
        return (1, 1)
    c1, c2 = node.children
    r1, c1c = _dims(c1)
    r2, c2c = _dims(c2)
    if isinstance(node, Horizontal):  # 列相加，行取max
        return (max(r1, r2), c1c + c2c)
    return (r1 + r2, max(c1c, c2c))  # Vertical: 行相加，列取max


def grid_size(tree: PaneTree) -> tuple[int, int]:
    """返回网格总 (rows, cols)。"""
    return _dims(tree.root)
