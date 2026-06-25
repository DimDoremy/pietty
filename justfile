# pietty justfile —— 常用任务
# 用法: just <recipe>

# 默认: 列出可用命令
default:
    @just --list

# ── 开发循环 ──────────────────────────────────────────

# 同步依赖（创建/更新 .venv）
sync:
    uv sync

# 运行 pietty（交互式 TUI）
run:
    uv run pietty

# 以指定 shell 运行（例如: just run-shell /bin/zsh）
run-shell SHELL="$SHELL":
    PIETTY_SHELL="{{SHELL}}" uv run python -c "from pietty.app import main; main()"

# 在无桌面环境下冒烟测试（验证 ANSI/UTF-8）
smoke:
    uv run python scripts/smoke_bare.py

# ── 测试 ──────────────────────────────────────────────

# 跑全部测试
test:
    uv run pytest

# 跑指定测试文件（例如: just test-one tests/test_render.py）
test-one TARGET:
    uv run pytest {{TARGET}}

# 测试 + 覆盖率
test-cov:
    uv run pytest --cov=src/pietty --cov-report=term-missing

# ── 构建 / 安装 ───────────────────────────────────────

# 构建分发包到 dist/
build:
    uv build

# 将当前项目安装到系统（编辑模式）便于全局调用 pietty
install:
    uv pip install -e . --python $(which python3 || echo python3)

# 卸载
uninstall:
    uv pip uninstall pietty --python $(which python3 || echo python3)

# ── 质量 ──────────────────────────────────────────────

# 静态检查（如装了 ruff）
lint:
    @command -v ruff >/dev/null 2>&1 && ruff check src tests || echo "ruff 未安装，跳过（uv tool install ruff 可装）"

# 格式化
fmt:
    @command -v ruff >/dev/null 2>&1 && ruff format src tests || echo "ruff 未安装，跳过"

# ── 清理 ──────────────────────────────────────────────

# 清理构建产物与缓存
clean:
    rm -rf dist build *.egg-info .pytest_cache .coverage htmlcov src/*.egg-info
    find . -type d -name __pycache__ -exec rm -rf {} +

# 深度清理（含 .venv，下次需重新 sync）
distclean: clean
    rm -rf .venv
