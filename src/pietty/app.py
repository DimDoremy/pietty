from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Container

from pietty.layout import PaneTree
from pietty.terminal import TerminalWidget


class PaneArea(Container):
    pass


class PiettyApp(App):
    CSS = """
    Screen { layout: vertical; }
    PaneArea { layers: base; }
    TerminalWidget { layer: base; }
    .hidden { display: none; }
    """

    BINDINGS: list = []  # C-x 在 on_key 手动处理

    def __init__(self) -> None:
        super().__init__()
        self.tree = PaneTree()
        self._widgets: dict[int, TerminalWidget] = {}
        self._cx_pending = False  # 是否已按 C-x，等待下一键

    def compose(self) -> ComposeResult:
        yield PaneArea()

    def on_mount(self) -> None:
        self._spawn_pane(self.tree.focused)
        self._relayout()

    # ---- pane <-> widget ----
    def _spawn_pane(self, pane_id: int) -> None:
        area = self.query_one(PaneArea)
        w = TerminalWidget(id=f"pane-{pane_id}")
        self._widgets[pane_id] = w
        area.mount(w)

    def _relayout(self) -> None:
        """简易：仅聚焦 pane 可见，其余隐藏（完整比例排版留后续）。"""
        focused = self.tree.focused
        for pid, w in self._widgets.items():
            w.set_class(pid != focused, "hidden")

    # ---- key handling ----
    def on_key(self, event) -> None:
        if event.key == "ctrl+x":
            self._cx_pending = True
            event.prevent_default()
            event.stop()
            return
        if not self._cx_pending:
            return  # 交给 widget
        self._cx_pending = False
        event.prevent_default()
        event.stop()
        k = event.key
        if k == "2":
            new = self.tree.split(self.tree.focused, "vertical")
            self._spawn_pane(new)
            self._relayout()
        elif k == "3":
            new = self.tree.split(self.tree.focused, "horizontal")
            self._spawn_pane(new)
            self._relayout()
        elif k == "0":
            closing = self.tree.focused
            self.tree.close(closing)
            if (w := self._widgets.pop(closing, None)) is not None:
                w.remove()
            self._relayout()
        elif k == "o":
            self.tree.next_pane()
            self._relayout()
        elif k == "ctrl+c":
            self.exit()


def main() -> None:
    PiettyApp().run()
