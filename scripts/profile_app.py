"""测量真实 App 启动/退出延迟。
时间戳写入 /tmp/pietty_profile.log（避免 TUI 干扰 stderr）。

会真实进入 TUI：启动 → 等待 3 秒 → 调用 app.exit() → 记录退出耗时。
"""
import asyncio
import time

LOG = open("/tmp/pietty_profile.log", "w", buffering=1)
T0 = time.perf_counter()


def tag(msg):
    LOG.write(f"[{time.perf_counter() - T0:7.3f}s] {msg}\n")


tag("process start")
from pietty.app import PiettyApp  # noqa: E402
from pietty.terminal import TerminalWidget  # noqa: E402
tag("imports done")

# 钩子：Widget.on_mount
_orig_wmount = TerminalWidget.on_mount


def _wmount(self):
    tag("Widget.on_mount ENTER")
    t0 = time.perf_counter()
    try:
        _orig_wmount(self)
    except Exception as e:
        tag(f"Widget.on_mount ERR {e}")
        raise
    tag(f"Widget.on_mount EXIT +{time.perf_counter() - t0:.3f}s")


TerminalWidget.on_mount = _wmount

app = PiettyApp()
tag("app created")


# 钩子：App.on_mount（TUI 已就绪）
_orig_amount = PiettyApp.on_mount


def _amount(self):
    tag("App.on_mount ENTER")
    _orig_amount(self)
    tag("App.on_mount EXIT (TUI ready)")
    # 3 秒后退出
    async def _quit():
        await asyncio.sleep(3.0)
        tag(">>> scheduling app.exit()")
        self.exit()

    asyncio.get_event_loop().create_task(_quit())


PiettyApp.on_mount = _amount

tag("about to call run()")
try:
    app.run()
    tag("run() returned normally")
except Exception as e:
    tag(f"run() raised {e}")
LOG.close()
