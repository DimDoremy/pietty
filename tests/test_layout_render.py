"""测试布局树描述生成。

把 PaneTree 转成与 Textual 无关的中间描述，便于单测：
  {"type": "leaf", "id": N}
  {"type": "h"/"v", "ratio": 0.5, "children": [desc, desc]}
"""
from pietty.layout import PaneTree, Horizontal, Vertical, Pane


def _desc(node) -> dict:
    if isinstance(node, Pane):
        return {"type": "leaf", "id": node.id}
    children = [_desc(c) for c in node.children]
    kind = "h" if isinstance(node, Horizontal) else "v"
    return {"type": kind, "ratio": node.ratio, "children": children}


def tree_desc(tree: PaneTree) -> dict:
    return _desc(tree.root)


def test_single_pane_desc():
    t = PaneTree()
    assert tree_desc(t) == {"type": "leaf", "id": t.focused}


def test_horizontal_split_desc():
    t = PaneTree()
    a = t.focused
    new = t.split(a, "horizontal")
    assert tree_desc(t) == {
        "type": "h", "ratio": 0.5, "children": [
            {"type": "leaf", "id": a},
            {"type": "leaf", "id": new},
        ]}


def test_nested_desc():
    t = PaneTree()
    a = t.focused
    b = t.split(a, "horizontal")
    t.split(b, "vertical")
    d = tree_desc(t)
    assert d["type"] == "h"
    assert d["children"][1]["type"] == "v"
    assert len(d["children"][1]["children"]) == 2
