# pietty 设计文档

**日期：** 2026-06-25
**状态：** 已批准

## 0. 项目定位与硬约束

- 终端复用器，基于 Textual TUI，后端 `pyte` + `ptyprocess`（自建 PTY 终端 widget）。
- **最高优先级硬约束**：裸登录 shell 下 ANSI 正确、UTF-8 不乱码。这是验收底线，任何功能都不得破坏它。
- 脱离桌面环境必须可用；有桌面环境时增强（读取字体/配色 css，仅作用于 pietty 自身 Textual theme，不改宿主终端模拟器）。

## 1. 架构分层

```
┌─────────────────────────────────────────────────┐
│  Textual App (pietty)                           │
│  ├─ TabBar        (tab 栏拆分)                  │
│  ├─ Sidebar       (文件树，跟随激活 tab 的 cwd) │
│  ├─ HelpFooter    (快捷键提示，可开关)          │
│  └─ StatusBar                                  │
├─────────────────────────────────────────────────┤
│  PaneTree (布局树)                              │
│   └─ Pane → TerminalWidget                      │
│              ├─ ptyprocess.PtyProcess (交互式)  │
│              ├─ pyte.Stream → pyte.Screen       │
│              └─ 渲染层 (Screen grid → Rich Text)│
├─────────────────────────────────────────────────┤
│  JobManager (后台任务托管)                      │
│   └─ Job → 独立 PtyProcess → 新 tab 的 Terminal │
├─────────────────────────────────────────────────┤
│  Config (toml 加载 + 桌面感知)                  │
└─────────────────────────────────────────────────┘
```

关键决策：

- **每 pane 独占一个 PTY**，交互式 pane 跑登录 shell。
- **后台 job 用独立 PTY**，pietty 自己 fork 并托管进程生命周期（Route C），stdout 接到新 tab 的 TerminalWidget。
- **布局用树**（PaneTree）而非平铺数组：支持任意递归水平/竖直拆分。每个内部节点是 `Horizontal|Vertical` 容器，叶子节点是 Pane。这样 `C-x o` 聚焦轮转、`C-x 0/1` 关闭/最大化都好实现。

## 2. 核心 widget：TerminalWidget（最关键）

这是 ANSI/乱码问题的命门。设计要点：

- **PTY 设置**：fork 登录 shell 时显式传入 `env={TERM, LANG/LC_*, COLORTERM=true}`，`TERM=xterm-256color`（与 pyte 的 `Screen` 交替一致）。`ptyprocess` 以 UTF-8 字节流读写，读取时按完整 UTF-8 序列切分（不足时缓存尾部字节，绝不在多字节字符中间截断）。
- **pyte.Screen**：作为唯一的屏幕状态真相。`pyte.Stream` 喂字节流。开启 `history` 滚动回溯。pyte 原生支持 256 色 + truecolor（SGR 38;5;n 与 38;2;r;g;b）、粗体/斜体/下划线/反色/暗色等全部属性。
- **渲染映射**：TerminalWidget 持有一个异步循环，定期把 pyte Screen 的 grid（含每个 cell 的 fg/bg/style/光标）映射为 Rich `Text`/`Segment`，刷新到 Textual。颜色映射表覆盖 16/256/truecolor 三种，缺失项回退到默认对，确保不丢色。
- **resize 同步**：pane 尺寸变化 → 换算成行列 → `screen.resize(lines, columns)` + `setwinsize` 到 PTY master，保证全屏 TUI（vim/htop）正确重排。
- **输入转发**：按键事件 → 字节序列（含功能键/方向键的 ANSI 序列）→ 写入 PTY master。
- **裸 shell 验证用例**：开机进 init 3 / `tty2`（无 DISPLAY）启动 pietty，跑 `htop`/`vim`/`cmatrix`/中文 `echo`/emoji/256 色测试脚本，确认不乱码。

## 3. 文件树侧边栏 + cwd 跟随

- Sidebar 监听"激活 pane 的 cwd"。如何获取 cwd：周期性 `os.readlink('/proc/<pid>/cwd')`（Linux），回退到解析 `/proc/<pid>/environ` 的 PWD。无 /proc 平台则从 `pyte` 输出启发式不可靠，仅 Linux 一等公民。
- 切换激活 tab/pane → 侧边栏根目录随之更新。
- 选中文件 → 回车可在激活 pane 注入命令（`cd`/`$EDITOR` 等，可配）。

## 4. 后台任务托管（Route C）

- shell 注入：启动交互式 PTY 时附带一个 rc 片段 / trap，捕获命令行末尾的 `&`、`screen ...`、`nohup ... &`。
- 命中时 pietty 不把命令丢给 shell 去后台，而是**自己 fork 子进程**并托管到 JobManager，创建新 tab，新 tab 的 TerminalWidget 接管该子进程 PTY。
- 子进程 stdout 实时流入新 tab（满足"实时查看"）。
- 子进程退出 → 新 tab 显示 `[process exited N] 按任意键关闭`，按键关闭该 tab（满足"运行完成的任务按任意键退出"）。

## 5. 快捷键：Emacs 风格

- **光标移动/编辑类 1:1 还原 Emacs**（在输入转发层透传给 shell，pietty 不拦截）：`C-a/C-e/C-f/C-b/C-n/C-p/M-f/M-b/C-d/M-d/C-k/C-y` 等。
- 其余功能注册在两个前缀下：
  - **`C-x`（系统级）**：面板/窗口/会话管理。
  - **`C-c`（用户级）**：用户自定义动作（通过 config 绑定）。
- tab 语义：`C-x b` = 切换 tab（贴 Emacs buffer 原义）；新建 tab = `C-t`；`C-x <left>/<right>` 也可切 tab。
- 全表：

  ```
  光标/编辑     透传 shell（1:1 emacs）：C-a C-e C-f C-b C-n C-p M-f M-b C-d M-d C-k C-y ...

  C-x 系统级
    C-x 3      split-horizontal
    C-x 2      split-vertical
    C-x 0      close-pane
    C-x 1      maximize-pane (再按还原)
    C-x o / O  next / prev pane
    C-t        new-tab
    C-x b      switch-tab
    C-x <right>/<left>  next/prev tab
    C-x C-d    toggle-sidebar
    C-x ?      toggle-help
    M-v / C-v  scrollback up / down
    C-x C-c    quit

  C-c 用户级    （默认仅占位，由 config [keybindings.user] 绑定）
  ```

## 6. 配置（config.toml + 桌面感知）

- 路径：`~/.config/pietty/config.toml`（合并内置默认）。验证失败回退默认并告警，绝不崩溃。
- schema：

  ```toml
  [layout]
  default_split = "horizontal"
  split_ratio   = 0.5

  [panels]
  sidebar = true; tabs = true; status = true; help_footer = true

  [theme]
  color_scheme = "pietty-dark"
  background = "#0c0c0c"; foreground = "#e0e0e0"; accent = "#7aa2f7"
  font_family = "monospace"   # 仅信息性/状态栏，物理终端忽略

  [desktop]                   # 桌面感知 (Route A)
  detect = "auto"             # auto | always | never
  # 有桌面时：把 css/toml 配色解析后用于 pietty 自身 Textual theme
  # 不改写宿主终端模拟器配置；font_family 仅显示于状态栏

  [terminal]
  shell = "$SHELL"; term = "xterm-256color"; locale = "en_US.UTF-8"
  history_lines = 10000; scrollback = true

  [keybindings]               # 见 §5
  [keybindings.user]          # C-c 前缀下的用户绑定
  ```

- **ANSI/乱码配置项即硬约束**：`terminal.term`/`locale` 在裸 shell 下强制注入 PTY env，覆盖可能缺失的宿主 locale。

## 7. 错误处理 / 测试

- PTY fork 失败、shell 缺失 → 降级到 `/bin/sh` 并在状态栏告警。
- ANSI 解析单测：pyte Stream 喂已知字节序列，断言 grid/颜色/光标；重点覆盖多字节截断、truecolor、`tput`/`htop` 录像回放。
- 布局单测：PaneTree 任意 split/merge 后结构正确。
- Job 托管单测：模拟 `&` 命令 → 断言新 tab 创建 + 退出后可关闭。

## 8. MVP 范围（最先实现）

| 优先级 | 范围 | 理由 |
|---|---|---|
| **MVP（必须最先）** | TerminalWidget(pyte+ptyprocess) + PaneTree 布局 + 基础 `C-x` 拆分键 + 最小 App 壳 | 所有功能的地基；ANSI/UTF-8 硬约束只能在此验证 |
| P1 | config.toml 加载 + theme | 解耦默认值 |
| P1 | tab 栏 | 复用 PaneTree |
| P2 | 文件树侧边栏 + cwd 跟随 | 依赖 pane cwd 获取 |
| P2 | 快捷键提示 footer | |
| P3 | 后台 job 托管（Route C） | 最复杂 |
| P3 | 桌面感知（Route A） | 增强项 |
