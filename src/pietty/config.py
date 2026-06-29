"""pietty 配置加载：config.toml → Theme，失败回退+告警。"""
from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Theme:
    background: str = "#0c0c0c"
    foreground: str = "#e0e0e0"
    border: str = "#fea62b"       # $primary
    accent: str = "#fda62b"       # $accent
    boost: str = "#141414"        # $boost
    success: str = "#00af00"      # $success
    surface: str = "#1c1c1c"      # $surface
    panel: str = "#262626"        # $panel
    text: str = "#888888"         # $text


@dataclass
class Config:
    theme: Theme = field(default_factory=Theme)
    history_lines: int = 10000


def _config_path() -> Path:
    """按 XDG 规范找配置文件，不存在时返回路径但不创建。"""
    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(xdg) / "pietty" / "config.toml"


def load() -> Config:
    """加载 ~/.config/pietty/config.toml，合并内置默认值。

    文件不存在、格式错误或字段非法时都**不回退**——用全部默认值并打印一条
    stderr 告警。单个字段非法（如颜色格式不对）也会被忽略并告警。
    """
    cfg = Config()
    path = _config_path()
    if not path.exists():
        return cfg

    try:
        raw = tomllib.loads(path.read_text())
    except Exception as exc:
        print(f"[pietty] 警告: 配置 {path} 加载失败 ({exc})，使用默认配置",
              file=sys.stderr)
        return cfg

    # 合并 theme 字段（忽略非法值）
    theme_raw = raw.get("theme", {})
    if not isinstance(theme_raw, dict):
        print("[pietty] 警告: [theme] 非 dict，忽略", file=sys.stderr)
    else:
        for key in cfg.theme.__dataclass_fields__:
            val = theme_raw.get(key)
            if val is not None:
                if isinstance(val, str) and val.startswith("#") and len(val) in (4, 5, 7, 9):
                    setattr(cfg.theme, key, val)
                else:
                    print(f"[pietty] 警告: theme.{key}={val!r} 不是合法颜色，跳过",
                          file=sys.stderr)

    # history_lines
    hl = raw.get("history_lines")
    if isinstance(hl, int) and hl > 0:
        cfg.history_lines = hl

    return cfg


def css_vars(t: Theme) -> str:
    """从 Theme 生成 Textual CSS 变量。"""
    return f"""
$background: {t.background};
$foreground: {t.foreground};
$border: {t.border};
$accent: {t.accent};
$boost: {t.boost};
$success: {t.success};
$surface: {t.surface};
$panel: {t.panel};
$text: {t.text};
"""
