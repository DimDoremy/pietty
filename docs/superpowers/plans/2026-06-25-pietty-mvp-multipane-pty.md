# pietty MVP: 多面板 PTY 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现可运行的 pietty MVP——一个 Textual TUI，支持任意水平/竖直拆分的终端面板，每面板运行真实登录 shell，ANSI/UTF-8 正确无乱码。

**Architecture:** 自建 `TerminalWidget`（`ptyprocess` 管 PTY + `pyte.HistoryScreen` 解析屏幕状态 + 渲染层映射到 Rich Text）；`PaneTree` 递归布局树管理面板；`PiettyApp` Textual 应用壳 + Emacs 风格 `C-x` 系统级快捷键。

**Tech Stack:** Python 3.11+, textual, pyte, ptyprocess, rich, pytest

## Global Constraints

- **硬约束（最高优先级）**：裸登录 shell 下 ANSI 正确、UTF-8 不乱码；绝不在多字节 UTF-8 字符中间截断。
- PTY env 强制注入 `TERM=xterm-256color`、`LANG/LC_*` 取 config（默认 `en_US.UTF-8`）、`COLORTERM=truecolor`。
- shell 缺失降级 `/bin/sh`。
- 默认快捷键 Emacs 风格；光标/编辑键透传 shell，pietty 不拦截；功能键注册在 `C-x`（系统级）。
- 测试用 TDD，先红后绿，每任务一次提交。

## File Structure

- `pyproject.toml` — 依赖、entry point `pietty = "pietty.app:main"`
- `src/pietty/__init__.py`
- `src/pietty/terminal.py` — `TerminalWidget`（PTY + pyte + 渲染）。唯一职责：一个面板的终端生命周期。
- `src/pietty/render.py` — `screen_to_rich(screen) -> rich.text.Text`、颜色映射。纯函数，易测。
- `src/pietty/layout.py` — `PaneTree`、`Pane`、`Split`(Horizontal|Vertical)。布局结构。
- `src/pietty/app.py` — `PiettyApp`、`main()`。组装 + 键绑定。
- `tests/test_render.py` — 渲染/解码单测。
- `tests/test_layout.py` — PaneTree 结构单测。
- `tests/conftest.py` — 公共 fixture。

---

### Task 1: 项目脚手架与依赖

**Files:**
- Modify: `pyproject.toml`
- Create: `src/pietty/__init__.py`, `tests/__init__.py`, `tests/conftest.py`
- Delete: `main.py`（迁入 src 布局）

**Interfaces:** Produces 可 `uv run pietty` / `uv run pytest` 的包结构。

- [ ] **Step 1: 改写 `pyproject.toml`**

```toml
[project]
name = "pietty"
version = "0.1.0"
description = "A textual terminal multiplexer"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "textual>=0.60",
    "pyte>=0.8.0",
    "ptyprocess>=0.7.0",
    "rich>=13",
]

[project.scripts]
pietty = "pietty.app:main"

[tool.uv]
package = true

[dependency-groups]
dev = ["pytest>=8", "pytest-asyncio>=0.23"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 2: 建 src 包与 tests 包**

创建 `src/pietty/__init__.py`（空）、`tests/__init__.py`（空）。删除 `main.py`。

- [ ] **Step 3: 安装并验证**

Run: `uv sync && uv run python -c "import pietty; import pyte; import ptyprocess; import textual; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "chore: scaffold src layout with deps"
```

---

### Task 2: UTF-8 增量解码器（硬约束核心）

**Files:**
- Create: `src/pietty/render.py`, `tests/test_render.py`

**Interfaces:**
- Produces: `class Utf8Decoder`（`feed(bytes) -> str`，缓存不完整尾部），`screen_to_rich` 留到 Task 3。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_render.py
from pietty.render import Utf8Decoder

def test_utf8_decoder_full():
    d = Utf8Decoder()
    assert d.feed("你好".encode("utf-8")) == "你好"

def test_utf8_decoder_partial_then_rest():
    d = Utf8Decoder()
    data = "你好".encode("utf-8")
    head, tail = data[:3], data[3:]
    assert d.feed(head) == ""          # 不完整，暂不输出
    assert d.feed(tail) == "你好"

def test_utf8_decoder_across_multiple_feeds():
    d = Utf8Decoder()
    data = "a😀b".encode("utf-8")
    out = "".join(d.feed(data[i:i+1]) for i in range(len(data)))
    assert out == "a😀b"
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/test_render.py -v`
Expected: FAIL `ImportError: cannot import name 'Utf8Decoder'`

- [ ] **Step 3: 实现**

```python
# src/pietty/render.py
import codecs

class Utf8Decoder:
    """增量 UTF-8 解码：绝不在多字节字符中间截断。"""
    def __init__(self) -> None:
        self._dec = codecs.getincrementaldecoder("utf-8")(errors="strict")

    def feed(self, data: bytes) -> str:
        return self._dec.decode(data)
```

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/test_render.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(render): incremental UTF-8 decoder"
```

---

### Task 3: pyte 屏幕状态 → Rich Text 渲染（含颜色）

**Files:**
- Modify: `src/pietty/render.py`, `tests/test_render.py`

**Interfaces:**
- Consumes: `pyte.Screen` 实例（外部构造）。
- Produces: `screen_to_rich(screen) -> rich.text.Text`（含光标行标记由调用方处理）、`char_to_style(char) -> rich.style.Style`。

- [ ] **Step 1: 写失败测试**

```python
# 追加到 tests/test_render.py
import pyte
from rich.style import Style
from pietty.render import screen_to_rich, char_to_style

def _screen(text: str, cols=80, rows=24):
    s = pyte.Screen(cols, rows)
    pyte.Stream(s).feed(text)
    return s

def test_plain_text_rendered():
    s = _screen("hi")
    txt = screen_to_rich(s)
    assert "hi" in txt.plain

def test_bold_style_detected():
    s = _screen("\x1b[1mB\x1b[0m")
    st = char_to_style(s.buffer[0][0])
    assert st.bold

def test_truecolor_style_detected():
    s = _screen("\x1b[38;2;10;20;30mX\x1b[0m")
    st = char_to_style(s.buffer[0][0])
    assert st.color is not None
    assert str(st.color).lower().startswith("#")  # hex truecolor

def test_256color_style_detected():
    s = _screen("\x1b[38;5;200mX\x1b[0m")
    st = char_to_style(s.buffer[0][0])
    assert st.color is not None
```

注：pyte `char.fg` 对于 truecolor 形如 `"000a141e"`（6 位 hex 无 #），256 色形如 `"0000c8"`；默认 `"default"`。`char_to_style` 需把 hex 串转 `rich.color.Color.parse("#" + fg)`。

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/test_render.py -v`
Expected: FAIL ImportError `screen_to_rich`

- [ ] **Step 3: 实现**

```python
# 追加到 src/pietty/render.py
from __future__ import annotations
import pyte
from rich.text import Text
from rich.style import Style
from rich.color import Color

def _to_color(val: str):
    if val in ("default", ""):
        return None
    # pyte 返回 6 位 hex（truecolor）或 256 色的 hex 表示
    try:
        return Color.parse("#" + val[-6:])
    except Exception:
        return None

def char_to_style(char: pyte.screens.Char) -> Style:
    color = _to_color(char.fg)
    bgcolor = _to_color(char.bg)
    return Style(
        color=color,
        bgcolor=bgcolor,
        bold=bool(char.bold),
        italic=bool(char.italics),
        underline=bool(char.underscore),
        strike=bool(char.strikethrough),
        reverse=bool(char.reverse),
    )

def screen_to_rich(screen: pyte.Screen) -> Text:
    text = Text()
    for y in range(screen.lines):
        line = screen.buffer[y]
        for x in range(screen.columns):
            ch = line[x]
            data = ch.data or " "
            text.append(data, style=char_to_style(ch))
        if y != screen.lines - 1:
            text.append("\n")
    return text
```

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/test_render.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(render): pyte screen -> rich text with colors"
```

---

### Task 4: PaneTree 布局结构

**Files:**
- Create: `src/pietty/layout.py`, `tests/test_layout.py`

**Interfaces:**
- Produces:
  - `class Pane`（叶子，持有 `id: int`、`parent`）
  - `class Horizontal`、`class Vertical`（内部节点，持有 `children: list[Node]`、`ratio: float`）
  - `class PaneTree`（`root: Node`、`focused: int`；方法 `split(pane_id, direction) -> int`、`close(pane_id)`、`maximize()`、`next_pane()` / `prev_pane()`、`leaves() -> list[Pane]`）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_layout.py
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
    assert {t.focused, new} <= ids  # 原 pane 仍在
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
    # 关掉 b 后应只剩 a，root 回退为 Pane
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
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/test_layout.py -v`
Expected: FAIL ImportError

- [ ] **Step 3: 实现**

```python
# src/pietty/layout.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal, Optional, Union
from itertools import count

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

class Horizontal(_Container): ...
class Vertical(_Container): ...

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
        def walk(n: Node):
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
        self.focused = sibling.id if isinstance(sibling, Pane) else self.leaves()[0].id

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
```

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/test_layout.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(layout): PaneTree with split/close/focus"
```

---

### Task 5: TerminalWidget（PTY + pyte + 渲染 + resize + 输入转发）

**Files:**
- Create: `src/pietty/terminal.py`

**Interfaces:**
- Consumes: `Utf8Decoder`、`screen_to_rich`（render 模块）；`ptyprocess`、`pyte`。
- Produces: `class TerminalWidget(textual.widget.Widget)`：
  - `__init__(shell, env, cwd, cols, rows)`
  - 内部：`PtyProcess`、`pyte.HistoryScreen`、`Utf8Decoder`、异步读取循环、`on_resize`→`setwinsize`、`on_key`→写 PTY、`render()`→`screen_to_rich`。

这是集成层，难以纯单测；以手动验收 + 复用 render/layout 单测保障。提供 `feed_bytes(b)` 方法以便测试驱动屏幕更新。

- [ ] **Step 1: 写 TerminalWidget 骨架测试**

```python
# tests/test_terminal.py
import pyte
from pietty.terminal import TerminalModel

def test_feed_bytes_updates_screen():
    m = TerminalModel(cols=10, rows=3)
    m.feed_bytes(b"hi")
    # 第一行前两格为 h,i
    assert m.screen.buffer[0][0].data == "h"
    assert m.screen.buffer[0][1].data == "i"

def test_resize_propagates_to_screen():
    m = TerminalModel(cols=10, rows=3)
    m.resize(5, 20)
    assert m.screen.columns == 20
    assert m.screen.lines == 5

def test_feed_ansi_color_sets_attribute():
    m = TerminalModel(cols=10, rows=3)
    m.feed_bytes(b"\x1b[1mA\x1b[0m")
    assert m.screen.buffer[0][0].bold
```

说明：为可测，抽出纯逻辑 `TerminalModel`（持有 screen + decoder，方法 `feed_bytes`/`resize`/`key_to_bytes`），`TerminalWidget`（Textual widget）包装它并接 PTY。

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/test_terminal.py -v`
Expected: FAIL ImportError

- [ ] **Step 3: 实现 TerminalModel**

```python
# src/pietty/terminal.py
from __future__ import annotations
import os, shlex
import pyte
from pietty.render import Utf8Decoder

def _resolve_shell(spec: str) -> list[str]:
    if spec.startswith("$"):
        val = os.environ.get(spec[1:], "")
        if val:
            return shlex.split(val)
    return shlex.split(spec) or ["/bin/sh"]

def _default_env(term: str, locale: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "TERM": term,
        "LANG": locale,
        "LC_ALL": locale,
        "COLORTERM": "truecolor",
    })
    return env

class TerminalModel:
    """纯逻辑：屏幕状态 + 解码，无 PTY 依赖，便于测试。"""
    def __init__(self, cols: int = 80, rows: int = 24,
                 history: int = 10000) -> None:
        self.screen = pyte.HistoryScreen(cols, rows, history=history)
        self.stream = pyte.Stream(self.screen)
        self._dec = Utf8Decoder()

    def feed_bytes(self, data: bytes) -> None:
        self.stream.feed(self._dec.feed(data))

    def resize(self, rows: int, cols: int) -> None:
        self.screen.resize(lines=rows, columns=cols)

    def key_to_bytes(self, key: str) -> bytes:
        # 基础 ANSI 映射；完整表见下方 KEYMAP
        return _KEYMAP.get(key, key.encode("utf-8"))

# 精简但覆盖常见键的 ANSI 序列
_KEYMAP: dict[str, bytes] = {
    "up": b"\x1b[A",
    "down": b"\x1b[B",
    "right": b"\x1b[C",
    "left": b"\x1b[D",
    "home": b"\x1b[H",
    "end": b"\x1b[F",
    "delete": b"\x1b[3~",
    "pageup": b"\x1b[5~",
    "pagedown": b"\x1b[6~",
    "tab": b"\t",
    "enter": b"\r",
    "escape": b"\x1b",
    "backspace": b"\x7f",
}
```

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/test_terminal.py -v`
Expected: 3 passed

- [ ] **Step 5: 实现 TerminalWidget（接 PTY + Textual）**

```python
# 追加到 src/pietty/terminal.py
import asyncio
from textual.widget import Widget
from textual.reactive import reactive
from rich.text import Text
from pietty.render import screen_to_rich
try:
    import ptyprocess
except ImportError:  # 测试环境可能无
    ptyprocess = None  # type: ignore

class TerminalWidget(Widget):
    DEFAULT_CSS = """
    TerminalWidget { background: #0c0c0c; color: #e0e0e0; }
    """

    def __init__(self, shell: str = "$SHELL", cwd: str | None = None,
                 term: str = "xterm-256color", locale: str = "en_US.UTF-8",
                 id: str | None = None) -> None:
        super().__init__(id=id)
        self._shell = shell
        self._cwd = cwd or os.getcwd()
        self._term = term
        self._locale = locale
        self.model = TerminalModel()
        self._pty = None
        self._refresh = reactive(False)

    # ---- lifecycle ----
    def on_mount(self) -> None:
        if ptyprocess is None:
            return
        argv = _resolve_shell(self._shell)
        try:
            self._pty = ptyprocess.PtyProcess.spawn(
                argv, cwd=self._cwd, env=_default_env(self._term, self._locale))
        except Exception:
            argv = ["/bin/sh"]
            self._pty = ptyprocess.PtyProcess.spawn(
                argv, cwd=self._cwd, env=_default_env(self._term, self._locale))
        self.model.resize(self.size.height, self.size.width)
        self._pty.setwinsize(self.size.height, self.size.width)
        self._task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        loop = asyncio.get_event_loop()
        assert self._pty is not None
        while True:
            try:
                data = await loop.run_in_executor(None, self._pty.read, 4096)
            except (EOFError, OSError):
                break
            if not data:
                break
            self.model.feed_bytes(data)
            self._refresh = not self._refresh  # 触发重渲染

    def on_unmount(self) -> None:
        if self._pty is not None:
            try:
                self._pty.close()
            except Exception:
                pass

    def on_resize(self, event) -> None:
        r, c = self.size.height, self.size.width
        self.model.resize(r, c)
        if self._pty is not None:
            self._pty.setwinsize(r, c)

    def render(self) -> Text:
        return screen_to_rich(self.model.screen)

    def on_key(self, event) -> None:
        if self._pty is None:
            return
        # 透传：把按键转字节写 PTY（光标/编辑键自然落到 shell）
        b = self.model.key_to_bytes(event.key)
        try:
            self._pty.write(b)
        except OSError:
            pass
        event.prevent_default()
```

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat(terminal): TerminalModel + TerminalWidget with PTY"
```

---

### Task 6: PiettyApp 组装 + Emacs C-x 系统级键绑定

**Files:**
- Create: `src/pietty/app.py`

**Interfaces:**
- Consumes: `PaneTree`、`TerminalWidget`。
- Produces: `class PiettyApp(textual.app.App)`、`def main()`。
  - 维护 `PaneTree`，动态挂载/卸载 TerminalWidget；实现 `C-x` 前缀两段式绑定。

- [ ] **Step 1: 写 App 壳**

```python
# src/pietty/app.py
from __future__ import annotations
from textual.app import App, ComposeResult
from textual.containers import Container
from textual import binding
from pietty.terminal import TerminalWidget
from pietty.layout import PaneTree

class PaneArea(Container):
    pass

class PiettyApp(App):
    CSS = """
    Screen { layout: vertical; }
    PaneArea { layers: base; }
    TerminalWidget { layer: base; }
    .hidden { display: none; }
    """

    BINDINGS: list[binding.Binding] = []  # C-x 在 on_key 手动处理

    def __init__(self) -> None:
        super().__init__()
        self.tree = PaneTree()
        self._widgets: dict[int, TerminalWidget] = {}
        self._cx_pending = False  # 是否已按 C-x，等待下一键
        self._maximized: int | None = None

    def compose(self) -> ComposeResult:
        yield PaneArea()

    def on_mount(self) -> None:
        self._spawn_pane(self.tree.focused)
        self._relayout()

    # ---- pane <-> widget ----
    def _widget_for(self, pane_id: int) -> TerminalWidget:
        w = TerminalWidget(id=f"pane-{pane_id}")
        self._widgets[pane_id] = w
        return w

    def _spawn_pane(self, pane_id: int) -> None:
        area = self.query_one(PaneArea)
        w = self._widget_for(pane_id)
        area.mount(w)

    def _relayout(self) -> None:
        """简易：仅聚焦 pane 可见，其余隐藏（完整比例排版留后续）。"""
        focused = self.tree.focused
        for pid, w in self._widgets.items():
            w.set_class(pid != focused, "hidden")

    # ---- key handling ----
    def on_key(self, event) -> None:
        # 让聚焦的 TerminalWidget 先处理透传；仅拦截 C-x 前缀
        if event.key == "ctrl+x":
            self._cx_pending = True
            event.prevent_default(); event.stop()
            return
        if not self._cx_pending:
            return  # 交给 widget
        self._cx_pending = False
        event.prevent_default(); event.stop()
        k = event.key
        if k == "2":
            new = self.tree.split(self.tree.focused, "vertical")
            self._spawn_pane(new); self._relayout()
        elif k == "3":
            new = self.tree.split(self.tree.focused, "horizontal")
            self._spawn_pane(new); self._relayout()
        elif k == "0":
            closing = self.tree.focused
            self.tree.close(closing)
            if (w := self._widgets.pop(closing, None)) is not None:
                w.remove()
            self._relayout()
        elif k == "o":
            self.tree.next_pane(); self._relayout()
        elif k == "1":
            self._maximized = None if self._maximized else self.tree.focused
            self._relayout()
        elif k == "ctrl+c":
            self.exit()

def main() -> None:
    PiettyApp().run()
```

注：完整比例排版（按 ratio 真实并列）作为后续迭代，MVP 先用聚焦切换保证可用；但必须保证拆分后多 shell 真实存活（可切回查看）。若你坚持真并列，下一步用 Textual `Horizontal`/`Vertical` 容器按 tree 重建（Task 可加）。

- [ ] **Step 2: 手动验收**

Run: `uv run pietty`
验证：单面板 shell 可输入；`C-x 3` 后 `C-x o` 切换可看到第二个 shell；`C-x 0` 关闭；运行 `echo 你好😀`、`htop`、`vim` 确认不乱码、颜色正确、resize 正常。

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "feat(app): PiettyApp with C-x split/close/focus"
```

---

### Task 7: 裸 shell ANSI/UTF-8 验收（硬约束关卡）

**Files:** 无新增，验收任务。

- [ ] **Step 1: 裸环境验收脚本**

在无 `DISPLAY`/`WAYLAND_DISPLAY` 的 TTY（或 `env -u DISPLAY -u WAYLAND_DISPLAY uv run pietty`）下：

```bash
# 256 色
curl -s https://gist.githubusercontent.com/XVilka/8346728/raw/true-colour.sh | bash
# 中文/emoji
echo "你好世界 😀🎉"
# 全屏 TUI
htop    # 然后 C-x 3 拆分再切回，确认不花屏
vim     # :q 退出
tput bel
```

- [ ] **Step 2: 失败项记录为后续 Task**

若乱码/丢色，回到 Task 3/5 修颜色映射或解码；不放过。

- [ ] **Step 3: 通过后 Commit 验收记录**

```bash
git add -A && git commit -m "docs: MVP ANSI/UTF-8 acceptance verified" --allow-empty
```

---

## Self-Review 记录

- **Spec 覆盖**：MVP 仅覆盖 §2(TerminalWidget)、§1(PaneTree)、§5(C-x 子集)；§3/§4/§6 为 P1+，不在本计划。
- **占位符**：Task 6 `_relayout` 注明为简易聚焦切换，真并列留后续——已显式标注，非隐藏 TODO。
- **类型一致**：`Pane.id`/`focused`、`TerminalModel.feed_bytes/resize/key_to_bytes`、`screen_to_rich`/`char_to_style` 在各任务间一致。
