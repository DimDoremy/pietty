import pytest
from pietty.layout import PaneTree, Horizontal, Vertical


def test_initial_single_pane():
    t = PaneTree()
    leaves = t.leaves()
    assert len(leaves) == 1
    assert t.focused == leaves[0].id


def test_split_horizontal_creates_h_node():
    t = PaneTree()
    new = t.split(t.focused, "horizontal")
    assert isinstance(t.root, Horizontal)
    ids = {p.id for p in t.leaves()}
    assert {t.focused, new} <= ids
    assert len(t.leaves()) == 2


def test_split_vertical_nested():
    t = PaneTree()
    a = t.focused
    b = t.split(a, "horizontal")
    c = t.split(b, "vertical")
    assert isinstance(t.root, Horizontal)
    assert isinstance(t.root.children[1], Vertical)


def test_close_pane_promotes_sibling():
    t = PaneTree()
    a = t.focused
    b = t.split(a, "horizontal")
    t.close(b)
    assert len(t.leaves()) == 1
    assert t.leaves()[0].id == a


def test_next_pane_cycles():
    t = PaneTree()
    a = t.focused
    b = t.split(a, "horizontal")
    t.focus(a)
    t.next_pane()
    assert t.focused == b
    t.next_pane()
    assert t.focused == a
