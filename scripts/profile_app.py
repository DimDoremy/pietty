"""测量真实 App 启动各阶段，时间戳写入文件避免 TUI 干扰。"""
import sys
import time

LOG = open("/tmp/pietty_profile.log", "w", buffering=1)
T0 = time.perf_counter()


def tag(msg):
    LOG.write(f"[{time.perf_counter() - T0:7.3f}s] {msg}\n")


tag("process start")
from pietty.app import PiettyApp
from pietty.terminal import TerminalWidget
tag("imports done")

orig_mount = TerminalWidget.on_mount


def m(self):
    tag("Widget.on_mount ENTER")
    t0 = time.perf_counter()
    try:
        orig_mount(self)
    except Exception as e:
        tag(f"Widget.on_mount ERR {e}")
        raise
    tag(f"Widget.on_mount EXIT +{time.perf_counter() - t0:.3f}s")


TerminalWidget.on_mount = m
tag("about to run")

import signal


def suicide(*_):
    tag(">>> 4s elapsed, exiting")
    try:
        PiettyApp._exit = True
    except Exception:
        pass
    sys.exit(0)


signal.signal(signal.SIGALRM, suicide)
signal.alarm(4)

try:
    PiettyApp().run()
except SystemExit:
    pass
tag("run() returned")
LOG.close()
