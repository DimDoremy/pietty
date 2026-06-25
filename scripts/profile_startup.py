"""定位 pietty 启动各阶段耗时。"""
import os
import time

T0 = time.perf_counter()


def tag(msg):
    print(f"[{time.perf_counter() - T0:6.3f}s] {msg}", flush=True)


tag("start")
import textual  # noqa
import pyte  # noqa
import ptyprocess  # noqa
tag("imports done")

# 测量交互式 shell spawn
env = os.environ.copy()
env["TERM"] = "xterm-256color"
shell = os.environ.get("SHELL", "/bin/bash")
tag(f"shell = {shell}")

t = time.perf_counter()
p = ptyprocess.PtyProcess.spawn([shell, "-i"], env=env)
p.setwinsize(24, 80)
tag(f"spawn returned (+{time.perf_counter()-t:.3f}s)")

# 读直到出现提示符或超时
import select
os.set_blocking(p.fd, False)
buf = b""
deadline = time.perf_counter() + 10
while time.perf_counter() < deadline:
    r, _, _ = select.select([p.fd], [], [], 0.1)
    if r:
        try:
            d = os.read(p.fd, 4096)
            buf += d
        except OSError:
            break
    # 等到有 prompt 输出且静默 0.5s
    if buf and time.perf_counter() - t > 0.5:
        if not r:
            break
tag(f"shell ready, output {len(buf)} bytes (+{time.perf_counter()-t:.3f}s total)")
p.close()
tag("done")
