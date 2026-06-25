import os
import time

import ptyprocess
import pyte

from pietty.render import screen_to_rich, char_to_style, Utf8Decoder

env = os.environ.copy()
env["TERM"] = "xterm-256color"
env["LANG"] = "en_US.UTF-8"
env["LC_ALL"] = "en_US.UTF-8"
env.pop("DISPLAY", None)
env.pop("WAYLAND_DISPLAY", None)

p = ptyprocess.PtyProcess.spawn(["bash", "--norc", "-i"], env=env)
p.setwinsize(24, 80)
dec = Utf8Decoder()
scr = pyte.HistoryScreen(80, 24)
st = pyte.Stream(scr)

cmd = 'printf "\\033[38;2;10;20;30mTC\\033[0m 你好😀\\n"; printf "\\033[38;5;200mC256\\033[0m ok\\n"; exit\n'
p.write(cmd.encode("utf-8"))

time.sleep(0.8)
try:
    while True:
        data = p.read(4096)
        if not data:
            break
        st.feed(dec.feed(data))
except (EOFError, OSError):
    pass

plain = screen_to_rich(scr).plain
print("utf8 你好:", "你好" in plain)
print("emoji 😀:", "😀" in plain)
print("truecolor TC:", "TC" in plain)
print("256color C256:", "C256" in plain)

# 检查颜色：找到含 TC 的行
for y in range(scr.lines):
    row = "".join(scr.buffer[y][x].data for x in range(scr.columns))
    if "TC" in row:
        # 找 T 的格子
        for x in range(scr.columns):
            if scr.buffer[y][x].data == "T":
                s = char_to_style(scr.buffer[y][x])
                print("T truecolor:", s.color)
                break
    if "C256" in row:
        for x in range(scr.columns):
            if scr.buffer[y][x].data == "C":
                s = char_to_style(scr.buffer[y][x])
                print("C 256color:", s.color)
                break
print("END")
