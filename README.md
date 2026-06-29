# pietty

niri 风格的终端复用器，基于 [Textual](https://textual.textualize.io/) + [pyte](https://github.com/selectel/pyte) 构建。

## 特性

- **多 shell 多 tab**：每个 tab 可包含多个水平排列的 shell，支持无限嵌套
- **vim 风格模态**：normal 模式管理布局，insert 模式透传按键到 shell
- **概览模式**：按 `g` 唤起模态窗口，列出所有 shell 及运行进程，支持跳转/关闭/标记/移动
- **配置文件**：`~/.config/pietty/config.toml` 自定义主题颜色
- **UTF-8 安全**：增量解码器，多字节字符不会截断乱码
- **ANSI 渲染**：truecolor / 256 色 / 16 色 / bold / italic / underline 全支持

## 安装

```bash
git clone <repo-url> && cd pietty
uv sync
just run          # 或 uv run pietty
```

## 快捷键

### normal 模式

| 键 | 功能 |
|---|---|
| `i` | 进入 insert 模式 |
| `n` | 当前 tab 右侧新建 shell |
| `h` / `l` | 当前 tab 内左/右切换 shell |
| `j` / `k` | 下/上一个 tab |
| `c` | 关闭当前 shell（有运行中进程时需确认） |
| `g` | 概览模式 |
| `q` | 退出 pietty |

### `;` 前缀（Alt 替代）

部分终端无法可靠捕获 Alt 组合键，pietty 提供 `;` 前缀作为替代：

| 按键 | 等价 | 功能 |
|---|---|---|
| `;` `n` | Alt+n | 新建 tab |
| `;` `j` | Alt+j | 移 shell 到下一个 tab（边界时尾插新 tab） |
| `;` `k` | Alt+k | 移 shell 到上一个 tab（边界时头插新 tab） |
| `;` `h` | Alt+h | 同 tab 内左移 |
| `;` `l` | Alt+l | 同 tab 内右移 |

`;` 前缀在 normal 和 insert 模式下均可用。

### insert 模式

| 键 | 功能 |
|---|---|
| `Esc` / `;` `q` | 回到 normal 模式 |
| 其他 | 透传到 shell |

### 概览模式（按 `g` 唤起）

| 键 | 功能 |
|---|---|
| `j` / `k` | 导航列表 |
| `c` | 关闭选中 shell |
| `p` | 标记选中 |
| `u` | 取消标记 |
| `i` | 以 insert 模式进入选中 |
| `n` | 以 normal 模式进入选中 |
| `m` | 移动选中到当前 tab 末尾 |
| `g` / `Esc` | 退出概览 |

## 配置

编辑 `~/.config/pietty/config.toml`：

```toml
[theme]
background = "#0c0c0c"
foreground = "#e0e0e0"
border = "#fea62b"
accent = "#fda62b"
```

文件不存在或字段非法时自动回退默认值，并在 stderr 打印告警。

## 项目结构

```
src/pietty/
  app.py        主应用（按键路由、网格管理、状态栏）
  terminal.py   TerminalWidget（PTY + pyte + 渲染 + 输入）
  render.py     pyte 屏幕状态 → Rich Text（含 Style 缓存）
  config.py     config.toml 加载 + theme 解析
  sidebar.py    左侧 tab 编号栏
  overview.py   概览模态窗口
  mode.py       vim 风格模态状态机
  ptyquery.py   终端查询应答器（DSR/OSC）
tests/
  test_render.py / test_terminal.py / test_mode.py / ...
```

## 开发

```bash
uv sync              # 安装依赖
just test            # 运行测试
just lint            # ruff 静态检查
just run             # 运行 pietty
```

## 技术约束

- Python ≥ 3.11
- 依赖 Linux（ptyprocess、/proc）
- 最低 80×24 终端尺寸
