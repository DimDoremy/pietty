from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count
from typing import Literal, Optional, Union

Direction = Literal["horizontal", "vertical"]
NodeId = int


@dataclass
class Pane:
    id: NodeId
    parent: Optional["Node"] = None


@dataclass
class _Container:
    children: list["Node"] = field(default_factory=list)
    parent: Optional["Node"] = None
    ratio: float = 0.5


class Horizontal(_Container):
    pass


class Vertical(_Container):
    pass


Node = Union[Pane, Horizontal, Vertical]


class PaneTree:
    def __init__(self) -> None:
        self._ids = count()
        self.root: Node = self._new_pane()
        self.focused: NodeId = self.root.id

    def _new_pane(self) -> Pane:
        return Pane(id=next(self._ids))

    def leaves(self) -> list[Pane]:
        out: list[Pane] = []

        def walk(n: Node) -> None:
            if isinstance(n, Pane):
                out.append(n)
            else:
                for c in n.children:
                    walk(c)

        walk(self.root)
        return out

    def _find(self, node: Node, pane_id: NodeId) -> Optional[Node]:
        if isinstance(node, Pane):
            return node if node.id == pane_id else None
        for c in node.children:
            r = self._find(c, pane_id)
            if r is not None:
                return r
        return None

    def split(self, pane_id: NodeId, direction: Direction) -> NodeId:
        target = self._find(self.root, pane_id)
        assert isinstance(target, Pane), "can only split a Pane"
        parent = target.parent
        new_pane = self._new_pane()
        container = Horizontal() if direction == "horizontal" else Vertical()
        container.children = [target, new_pane]
        container.ratio = 0.5
        target.parent = container
        new_pane.parent = container
        container.parent = parent
        if parent is None:
            self.root = container
        else:
            idx = parent.children.index(target)
            parent.children[idx] = container
        self.focused = new_pane.id
        return new_pane.id

    def close(self, pane_id: NodeId) -> None:
        target = self._find(self.root, pane_id)
        assert isinstance(target, Pane)
        parent = target.parent
        if parent is None:
            return  # 根 pane 不允许关
        sibling = next(c for c in parent.children if c is not target)
        grand = parent.parent
        sibling.parent = grand
        if grand is None:
            self.root = sibling
        else:
            idx = grand.children.index(parent)
            grand.children[idx] = sibling
        self.focused = (sibling.id if isinstance(sibling, Pane)
                        else self.leaves()[0].id)

    def focus(self, pane_id: NodeId) -> None:
        if self._find(self.root, pane_id) is not None:
            self.focused = pane_id

    def next_pane(self) -> None:
        ls = self.leaves()
        idx = next(i for i, p in enumerate(ls) if p.id == self.focused)
        self.focused = ls[(idx + 1) % len(ls)].id

    def prev_pane(self) -> None:
        ls = self.leaves()
        idx = next(i for i, p in enumerate(ls) if p.id == self.focused)
        self.focused = ls[(idx - 1) % len(ls)].id


def tree_desc(tree: "PaneTree") -> dict:
    """把布局树转成与 UI 无关的中间描述，便于渲染/测试。

    返回:
      {"type": "leaf", "id": pane_id}
      {"type": "h"|"v", "ratio": float, "children": [desc, ...]}
    """
    return _desc(tree.root)


def _desc(node: Node) -> dict:
    if isinstance(node, Pane):
        return {"type": "leaf", "id": node.id}
    kind = "h" if isinstance(node, Horizontal) else "v"
    return {
        "type": kind,
        "ratio": node.ratio,
        "children": [_desc(c) for c in node.children],
    }
