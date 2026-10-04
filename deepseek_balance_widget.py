# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════
 DEEPSEEK://BALANCE · 赛博朋克 HUD 桌面小组件 (Windows)
 依据官方文档: https://api-docs.deepseek.com/zh-cn/api/get-user-balance

 用法:
   1. python deepseek_balance_widget.py (或双击 DeepSeekBalance.exe)
   2. 首次运行点窗口右上角 "⚙" 或右键 → 输入 API Key
      Key 保存在 %APPDATA%\\DeepSeekBalanceWidget\\config.json
   3. 右键菜单: 设置 / 刷新 / 三档尺寸 / 置顶 / 退出

 窗口操作:
   - 拖动标题区移动窗口
   - 右下角 ⇲ 拖拽无极缩放 (字体随窗口等比缩放)
   - 双击打开 platform.deepseek.com
═══════════════════════════════════════════════════
"""

import json
import os
import random
import sys
import time
import tkinter as tk
import urllib.request
import base64
from datetime import datetime

API_URL = "https://api.deepseek.com/user/balance"
PLATFORM_URL = "https://platform.deepseek.com/"

APP_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                       "DeepSeekBalanceWidget")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")

# ---------- 赛博配色 ----------
NEON_CYAN = "#00F0FF"
NEON_MAG = "#FF2A6D"
NEON_GRN = "#05FFA1"
BG_TOP = "#04010F"
BG_BOT = "#12032E"

FONT = "Consolas"
SIZES = {"small": (190, 190), "medium": (380, 190), "large": (380, 420)}

CELL = "░▒▒▓▓▓███"  # 索引 0..8 = 该格填充的 1/8 数（与 iOS 原版一致）


def hx(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def mix(a, b, t):
    A, B = hx(a), hx(b)
    return "#%02x%02x%02x" % tuple(round(A[i] + (B[i] - A[i]) * t) for i in range(3))


def CYAN(t):
    return mix(BG_BOT, NEON_CYAN, t)


def MAG(t):
    return mix(BG_BOT, NEON_MAG, t)


def bar(frac, width=12):
    """12 格比例条：四级灰度连续过渡，无断缝（原版算法）"""
    e = round(max(0.0, min(1.0, frac)) * width * 8)
    return "".join(CELL[max(0, min(8, e - i * 8))] for i in range(width))


# ---------- 配置 ----------
def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["api_key"] = base64.b64decode(cfg.get("api_key_b64", "")).decode()
        return cfg
    except Exception:
        return {"api_key": "", "size": "medium", "ontop": True}


def save_config(cfg):
    os.makedirs(APP_DIR, exist_ok=True)
    payload = {
        "api_key_b64": base64.b64encode(cfg.get("api_key", "").encode()).decode(),
        "size": cfg.get("size", "medium"),
        "ontop": cfg.get("ontop", True),
    }
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f)


# ---------- 网络 ----------
def fetch_balance(api_key):
    req = urllib.request.Request(API_URL, headers={
        "Accept": "application/json",
        "Authorization": "Bearer " + api_key,
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode()), resp.status
    except urllib.error.HTTPError as e:
        return None, e.code
    except Exception:
        return None, 0


# ---------- 主窗口 ----------
class DeepSeekWidget:
    def __init__(self):
        self.cfg = load_config()
        self.data = None
        self.err_status = None
        self._drag = None
        self._resize = None
        self.scale = 1.0

        self.root = tk.Tk()
        self.root.title("DEEPSEEK://BALANCE")
        self.size_name = self.cfg.get("size", "medium")
        w, h = SIZES[self.size_name]
        self.root.geometry(f"{w}x{h}+80+80")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", self.cfg.get("ontop", True))
        self.root.configure(bg=BG_BOT)
        self.root.attributes("-alpha", 0.98)

        self.canvas = tk.Canvas(self.root, highlightthickness=0, bd=0, bg=BG_BOT)
        self.canvas.pack(fill="both", expand=True)

        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Button-3>", self._show_menu)
        self.canvas.bind("<Double-Button-1>", lambda e: os.system(f'start "" "{PLATFORM_URL}"'))
        self.root.bind("<Configure>", lambda e: self.redraw())

        self.menu = tk.Menu(self.root, tearoff=0, font=(FONT, 9))
        self.menu.add_command(label="⚙ 设置 API Key", command=self.ask_api_key)
        self.menu.add_command(label="↻ 立即刷新", command=self.refresh)
        self.size_menu = tk.Menu(self.menu, tearoff=0, font=(FONT, 9))
        for name in SIZES:
            self.size_menu.add_command(label=name,
                                       command=lambda n=name: self.set_size(n))
        self.menu.add_cascade(label="窗口尺寸", menu=self.size_menu)
        self.ontop_var = tk.BooleanVar(value=self.cfg.get("ontop", True))
        self.menu.add_checkbutton(label="置顶", variable=self.ontop_var,
                                  command=self.toggle_ontop)
        self.menu.add_separator()
        self.menu.add_command(label="✕ 退出", command=self.root.destroy)

        self.refresh()
        self._tick()

    # ---- 移动 / 缩放 ----
    def _on_press(self, e):
        self._drag = None
        self._resize = None
        W = self.root.winfo_width()
        H = self.root.winfo_height()
        # 右下角 16px 缩放热区
        if e.x > W - 18 and e.y > H - 18:
            self._resize = (e.x, e.y, W, H)
            return
        # 右上角 ⚙
        if e.x > W - 34 and e.y < 28:
            self.ask_api_key()
            return
        self._drag = (e.x, e.y)

    def _on_drag(self, e):
        if self._resize:
            x0, y0, w0, h0 = self._resize
            nw = max(150, w0 + (e.x - x0))
            nh = max(120, h0 + (e.y - y0))
            self.root.geometry(f"{nw}x{nh}")
            return
        if self._drag:
            dx, dy = e.x - self._drag[0], e.y - self._drag[1]
            self.root.geometry(f"+{self.root.winfo_x()+dx}+{self.root.winfo_y()+dy}")

    def _on_release(self, e):
        self._drag = None
        self._resize = None

    def _on_motion(self, e):
        W = self.root.winfo_width()
        H = self.root.winfo_height()
        if e.x > W - 18 and e.y > H - 18:
            self.canvas.config(cursor="size_nw_se")
        else:
            self.canvas.config(cursor="fleur")

    def _show_menu(self, e):
        self.menu.tk_popup(e.x_root, e.y_root)

    # ---- 菜单动作 ----
    def ask_api_key(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("输入 DEEPSEEK API KEY")
        dlg.configure(bg=BG_TOP)
        dlg.attributes("-topmost", True)
        dlg.transient(self.root)
        dlg.grab_set()
        tk.Label(dlg, text="platform.deepseek.com → API keys 页面获取\nKey 仅保存在本机用户目录",
                 bg=BG_TOP, fg=NEON_CYAN, font=(FONT, 9), justify="left").pack(padx=12, pady=(10, 4))
        ent = tk.Entry(dlg, width=42, font=(FONT, 9), bg="#0a0524", fg="#ffffff",
                       insertbackground=NEON_CYAN, relief="flat")
        ent.insert(0, self.cfg.get("api_key", ""))
        ent.pack(padx=12, pady=6)

        def ok():
            key = ent.get().strip()
            if key:
                self.cfg["api_key"] = key
                save_config(self.cfg)
            dlg.destroy()
            self.refresh()

        tk.Button(dlg, text="保存", command=ok, bg="#0a0524", fg=NEON_CYAN,
                  activebackground=NEON_CYAN, activeforeground=BG_TOP,
                  font=(FONT, 9), relief="flat", width=10).pack(pady=(0, 10))
        ent.bind("<Return>", lambda e: ok())
        ent.focus_set()

    def set_size(self, name):
        self.size_name = name
        self.cfg["size"] = name
        save_config(self.cfg)
        w, h = SIZES[name]
        self.root.geometry(f"{w}x{h}")

    def toggle_ontop(self):
        self.root.attributes("-topmost", self.ontop_var.get())
        self.cfg["ontop"] = self.ontop_var.get()
        save_config(self.cfg)

    # ---- 数据 ----
    def refresh(self):
        key = self.cfg.get("api_key", "")
        if not key:
            self.data, self.err_status = None, "NO_KEY"
        else:
            self.data, self.err_status = fetch_balance(key)
            if self.err_status == 401:
                self.cfg["api_key"] = ""
                save_config(self.cfg)
        self.redraw()

    def _tick(self):
        self.refresh()
        self.root.after(60_000, self._tick)

    # ---- 绘制 ----
    def redraw(self):
        c = self.canvas
        c.delete("all")
        W = self.root.winfo_width()
        H = self.root.winfo_height()
        if W < 10:
            W, H = SIZES[self.size_name]
        # 缩放系数：以预设宽度为基准，拖动缩放时字体/间距等比变化
        base_w = SIZES[self.size_name][0]
        self.scale = max(0.6, min(2.2, W / base_w))
        fs = lambda s: max(6, int(round(s * self.scale)))
        seed = int(time.time() // 60)
        rnd = random.Random(seed)

        # 深色渐变基底
        rows = max(1, H // 2)
        for i in range(rows):
            c.create_rectangle(0, i * 2, W, i * 2 + 3, outline="",
                               fill=mix(BG_TOP, BG_BOT, i / max(1, rows - 1)))

        # 网格
        for x in range(0, W, 22):
            c.create_line(x, 0, x, H, fill=CYAN(0.06))
        for y in range(0, H, 22):
            c.create_line(0, y, W, y, fill=CYAN(0.06))

        # 扫描线
        for y in range(0, H, 3):
            c.create_line(0, y, W, y, fill=CYAN(0.035))

        # 右上角霓虹辉光
        gx, gy = W - 32 * self.scale, 10 * self.scale
        for r in range(26, 0, -2):
            t = (1 - r / 26) ** 2 * 0.10
            c.create_oval(gx - r, gy - r, gx + r, gy + r, outline="", fill=CYAN(t))
        for r in (13, 9, 5):
            c.create_oval(gx - r, gy - r, gx + r, gy + r, outline="", fill=CYAN(0.20))
            ri = r - 1.5
            c.create_oval(gx - ri, gy - ri, gx + ri, gy + ri, outline="", fill=CYAN(0.05))

        # HUD 角框
        m, L, T = 5 * self.scale, 16 * self.scale, 3 * self.scale
        for cx, cy, sx, sy in ((m, m, 1, 1), (W - m, m, -1, 1),
                               (m, H - m, 1, -1), (W - m, H - m, -1, -1)):
            x0 = cx if sx > 0 else cx - L
            y0 = cy if sy > 0 else cy - L
            c.create_rectangle(x0, cy - T / 2, x0 + L, cy + T / 2, outline="", fill=CYAN(0.65))
            c.create_rectangle(cx - T / 2, y0, cx + T / 2, y0 + L, outline="", fill=CYAN(0.65))

        # 上下霓虹描边
        c.create_rectangle(0, 0, W, 2, outline="", fill=CYAN(0.55))
        c.create_rectangle(0, H - 2, W, H, outline="", fill=MAG(0.5))

        # 底部均衡器律动条
        base = H - 4 * self.scale
        x = 8 * self.scale
        bw = max(2, 3 * self.scale)
        while x < W - 8 * self.scale:
            bh = rnd.randint(3, 14) * self.scale
            color = MAG(0.55) if rnd.random() > 0.75 else CYAN(0.45)
            c.create_rectangle(x, base - bh, x + bw, base, outline="", fill=color)
            x += 7 * self.scale

        # 右下角缩放手柄
        s = 6 * self.scale
        c.create_line(W - s - 2, H - 2, W - 2, H - s - 2, fill=CYAN(0.5), width=1)
        c.create_line(W - s * 1.7 - 2, H - 2, W - 2, H - s * 1.7 - 2, fill=CYAN(0.3), width=1)

        self._draw_content(W, H, fs)

    def _draw_content(self, W, H, fs):
        c = self.canvas
        data = self.data
        sc = self.scale
        px = 15 * sc

        # 标题
        c.create_text(px, 20 * sc, anchor="w", text="DEEPSEEK",
                      font=(FONT, fs(13), "bold"), fill=NEON_CYAN)
        w1 = self._textwidth("DEEPSEEK", fs(13), True)
        c.create_text(px + w1, 20 * sc, anchor="w", text="://",
                      font=(FONT, fs(13), "bold"), fill=NEON_MAG)
        w2 = self._textwidth("://", fs(13), True)
        c.create_text(px + w1 + w2, 20 * sc, anchor="w", text="BALANCE",
                      font=(FONT, fs(13), "bold"), fill=NEON_CYAN)
        led_color = NEON_GRN if (data and data.get("is_available")) else NEON_MAG
        c.create_text(W - 32 * sc, 18 * sc, anchor="e", text="●", font=(FONT, fs(10)), fill=led_color)
        c.create_text(W - 16 * sc, 18 * sc, anchor="e", text="⚙", font=(FONT, fs(10)), fill=CYAN(0.6))

        if data and data.get("balance_infos"):
            status = "SYS.STATUS: ONLINE" if data.get("is_available") else "SYS.STATUS: LOW BALANCE"
            c.create_text(px, 40 * sc, anchor="w", text=status, font=(FONT, fs(9)), fill=CYAN(0.55))
            ncur = "[%d CUR]" % len(data["balance_infos"])
            c.create_text(W - px, 40 * sc, anchor="e", text=ncur, font=(FONT, fs(9)), fill=MAG(0.6))

            y = 64 * sc
            small = (self.size_name == "small") and sc < 1.2
            for info in data["balance_infos"]:
                sym = "¥" if info.get("currency") == "CNY" else "$"
                c.create_text(px, y, anchor="w", text="▸ " + info.get("currency", "?"),
                              font=(FONT, fs(12), "bold"), fill=NEON_MAG)
                amt = sym + str(info.get("total_balance", "0"))
                c.create_text(W - px, y, anchor="e", text=amt,
                              font=(FONT, fs(17 if small else 26), "bold"), fill=NEON_CYAN)
                y += 28 * sc

                if not small:
                    tot = float(info.get("total_balance") or 0) or 1
                    g = float(info.get("granted_balance") or 0)
                    u = float(info.get("topped_up_balance") or 0)
                    gtxt = "GRT " + bar(g / tot) + " %s%s" % (sym, info.get("granted_balance", "0"))
                    utxt = "TOP " + bar(u / tot) + " %s%s" % (sym, info.get("topped_up_balance", "0"))
                    c.create_text(px, y, anchor="w", text=gtxt, font=(FONT, fs(9)), fill=CYAN(0.45))
                    y += 17 * sc
                    c.create_text(px, y, anchor="w", text=utxt, font=(FONT, fs(9)), fill=MAG(0.45))
                    y += 20 * sc
                y += 6 * sc
        else:
            c.create_text(px, 65 * sc, anchor="w", text="⚠ SIGNAL LOST",
                          font=(FONT, fs(14), "bold"), fill=NEON_MAG)
            if self.err_status == "NO_KEY":
                msg = "未配置 API KEY\n点击右上角 ⚙ 或右键设置"
            elif self.err_status == 401:
                msg = "ERR 401: INVALID KEY\n点击 ⚙ 重新配置"
            else:
                msg = "NET TIMEOUT · 稍后自动重试"
            c.create_text(px, 92 * sc, anchor="w", text=msg, font=(FONT, fs(10)), fill=CYAN(0.5))

        # 底栏
        hh = datetime.now().strftime("%H:%M")
        c.create_text(px, H - 18 * sc, anchor="w", text="SYNC " + hh + " ▮",
                      font=(FONT, fs(9)), fill=CYAN(0.45))
        hexid = "%04X" % random.randint(0, 0xFFFF)
        c.create_text(W - px, H - 18 * sc, anchor="e", text="0x" + hexid + " ▯",
                      font=(FONT, fs(9)), fill=MAG(0.5))

    _measure = {}

    def _textwidth(self, text, size, bold=False):
        key = (text, size, bold)
        if key not in self._measure:
            f = tkfont.Font(family=FONT, size=size, weight="bold" if bold else "normal")
            self._measure[key] = f.measure(text)
        return self._measure[key]

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    try:
        import tkinter.font as tkfont
    except ImportError:
        print("需要 Python 3.x 且带 tkinter")
        sys.exit(1)
    DeepSeekWidget().run()
