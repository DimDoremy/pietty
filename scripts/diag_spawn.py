"""诊断 PTY spawn 在当前环境下到底发生了什么。
直接喂命令给 shell，看是否响应、多久响应。
"""
import os
import select
import time

T0 = time.perf_counter()


def tag(msg):
    print(f"[{time.perf_counter() - T0:7.3f}s] {msg}", flush=True)


import ptyprocess

tag("start")
env = os.environ.copy()
env["TERM"] = "xterm-256color"
shell = os.environ.get("SHELL", "/bin/bash")
tag(f"SHELL={shell}")

tag("calling spawn...")
t = time.perf_counter()
try:
    p = ptyprocess.PtyProcess.spawn([shell, "-i"], env=env)
except Exception as e:
    tag(f"spawn RAISED {type(e).__name__}: {e}")
    raise
tag(f"spawn returned +{time.perf_counter() - t:.3f}s, fd={p.fd}")

p.setwinsize(24, 80)
os.set_blocking(p.fd, False)
tag("set nonblocking + winsize done")

# 读 2 秒看 shell 有没有 prompt 输出
buf = b""
deadline = time.perf_counter() + 2.0
while time.perf_counter() < deadline:
    r, _, _ = select.select([p.fd], [], [], 0.1)
    if r:
        try:
            d = os.read(p.fd, 4096)
            if not d:
                tag("read returned EOF (shell exited)")
                break
            buf += d
        except OSError as e:
            tag(f"read OSError {e}")
            break
tag(f"after 2s: got {len(buf)} bytes from shell")
if buf:
    tag(f"first 80 bytes: {buf[:80]!r}")

# 写命令测响应
tag("writing echo command...")
try:
    n = os.write(p.fd, b"echo PIETTY_SHELL_RESPONDS_$$\n")
    tag(f"wrote {n} bytes")
except OSError as e:
    tag(f"write OSError {e}")

# 读响应
buf2 = b""
deadline = time.perf_counter() + 2.0
while time.perf_counter() < deadline:
    r, _, _ = select.select([p.fd], [], [], 0.1)
    if r:
        try:
            d = os.read(p.fd, 4096)
            buf2 += d
        except OSError:
            break
tag(f"after cmd: got {len(buf2)} bytes")
tag(f"responds marker present: {b'PIETTY_SHELL_RESPONDS' in (buf + buf2)}")

p.close()
tag("done")
