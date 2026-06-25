"""诊断 OSC/DSR 应答哪个会泄漏成可见输入。

策略: 分别测试 只答DSR / 只答OSC11 / 都答, 看 bash 命令行是否出现乱码。
通过让 bash 执行 `echo MARKER:$?` 并检查输出里是否含泄漏字符。
"""
import os
import select
import time

import ptyprocess
from pietty.ptyquery import ReplyBuffer


def run_case(answer_dsr: bool, answer_osc: bool) -> str:
    env = os.environ.copy()
    env["TERM"] = "xterm-256color"
    env["PS1"] = "PROMPT$ "  # 极简 prompt，减少干扰
    p = ptyprocess.PtyProcess.spawn(["bash", "--norc", "-i"], env=env)
    p.setwinsize(24, 80)
    os.set_blocking(p.fd, False)
    rb = ReplyBuffer(bg="#0c0c0c")
    from pietty import ptyquery as pq
    buf = b""
    deadline = time.perf_counter() + 1.5
    while time.perf_counter() < deadline:
        r, _, _ = select.select([p.fd], [], [], 0.05)
        if r:
            try:
                d = os.read(p.fd, 4096)
            except OSError:
                break
            if d:
                buf += d
                # 选择性应答
                rb.pending = []
                if answer_dsr:
                    for _ in pq._RE_DSR_CURSOR.finditer(d):
                        rb.pending.append("\x1b[1;1R")
                    for _ in pq._RE_DSR_STATUS.finditer(d):
                        rb.pending.append("\x1b[0n")
                if answer_osc:
                    for _ in pq._RE_OSC11.finditer(d):
                        rb.pending.append(
                            f"\x1b]11;{rb._hex_to_osc_rgb('#0c0c0c')}\x1b\\")
                for x in rb.pending:
                    try:
                        os.write(p.fd, x.encode())
                    except OSError:
                        break
    # 发一个命令，捕获命令行可见内容
    os.write(p.fd, b"echo DONE\n")
    deadline = time.perf_counter() + 1.0
    out2 = b""
    while time.perf_counter() < deadline:
        r, _, _ = select.select([p.fd], [], [], 0.05)
        if r:
            try:
                d = os.read(p.fd, 4096)
            except OSError:
                break
            out2 += d
    p.close()
    allout = (buf + out2).decode("utf-8", "replace")
    return allout


for dsr, osc in [(True, False), (False, True), (True, True)]:
    out = run_case(dsr, osc)
    leak_osc = "11;rgb" in out
    has_done = "DONE" in out
    print(f"=== DSR={dsr} OSC={osc}: leak_osc11={leak_osc} DONE可见={has_done} ===")
    # 打印 prompt 后的可见行
    if "PROMPT" in out:
        seg = out[out.index("PROMPT"):]
        print("  around prompt:", repr(seg[:120]))
    print()
