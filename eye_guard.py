"""
SeeEye - 护眼桌面提示器
每隔 20 分钟弹出提醒，引导用户远眺 20 秒。
运行后在系统托盘常驻，右键可暂停/退出。
"""

import threading
import tkinter as tk
from tkinter import font as tkfont
import pystray
from PIL import Image, ImageDraw
import time


# ── 配置 ──────────────────────────────────────────────────────────────────────
WORK_MINUTES = 20       # 工作间隔（分钟）
REST_SECONDS = 20       # 休息时长（秒）
WINDOW_BG = "#1a1a2e"
ACCENT = "#e94560"
TEXT_COLOR = "#ffffff"
PROGRESS_BG = "#16213e"
PROGRESS_FG = "#0f3460"
PROGRESS_ACTIVE = "#e94560"


# ── 托盘图标生成 ───────────────────────────────────────────────────────────────
def make_tray_icon(color="#e94560"):
    """画一个简单的眼睛图标作为托盘图标"""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 外轮廓（眼白区域）
    d.ellipse([4, 18, 60, 46], fill="white", outline=color, width=3)
    # 瞳孔
    d.ellipse([22, 22, 42, 42], fill=color)
    d.ellipse([28, 28, 36, 36], fill="white")
    return img


# ── 提醒窗口 ──────────────────────────────────────────────────────────────────
class ReminderWindow:
    def __init__(self, on_done):
        self.on_done = on_done
        self.remaining = REST_SECONDS
        self._build()

    def _build(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)       # 无边框
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.92)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w, h = 480, 260
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.configure(bg=WINDOW_BG)

        # 标题
        title_font = tkfont.Font(family="Microsoft YaHei UI", size=16, weight="bold")
        tk.Label(
            self.root, text="👁  护眼时间到！", bg=WINDOW_BG,
            fg=ACCENT, font=title_font
        ).pack(pady=(28, 4))

        # 说明
        desc_font = tkfont.Font(family="Microsoft YaHei UI", size=11)
        tk.Label(
            self.root,
            text="请望向 6 米以外的远处，放松眼部肌肉",
            bg=WINDOW_BG, fg=TEXT_COLOR, font=desc_font
        ).pack(pady=(0, 18))

        # 倒计时数字
        count_font = tkfont.Font(family="Segoe UI", size=36, weight="bold")
        self.count_var = tk.StringVar(value=str(self.remaining))
        tk.Label(
            self.root, textvariable=self.count_var,
            bg=WINDOW_BG, fg=ACCENT, font=count_font
        ).pack()

        # 进度条（用 Canvas 画）
        self.canvas = tk.Canvas(
            self.root, width=360, height=10,
            bg=PROGRESS_BG, highlightthickness=0
        )
        self.canvas.pack(pady=(10, 0))
        self.bar = self.canvas.create_rectangle(0, 0, 360, 10, fill=PROGRESS_ACTIVE, width=0)

        # 跳过按钮
        skip_font = tkfont.Font(family="Microsoft YaHei UI", size=9)
        tk.Button(
            self.root, text="跳过", command=self._skip,
            bg=PROGRESS_BG, fg="#888888", relief="flat",
            font=skip_font, cursor="hand2", bd=0,
            activebackground=PROGRESS_BG, activeforeground=ACCENT
        ).pack(pady=(14, 0))

        self._tick()

    def _tick(self):
        if self.remaining <= 0:
            self._finish()
            return
        self.count_var.set(str(self.remaining))
        # 更新进度条
        ratio = (REST_SECONDS - self.remaining) / REST_SECONDS
        self.canvas.coords(self.bar, 0, 0, int(360 * ratio), 10)
        self.remaining -= 1
        self.root.after(1000, self._tick)

    def _skip(self):
        self._finish()

    def _finish(self):
        self.root.destroy()
        self.on_done()

    def show(self):
        self.root.mainloop()


# ── 核心计时器 ────────────────────────────────────────────────────────────────
class EyeGuard:
    def __init__(self):
        self.paused = False
        self._stop_event = threading.Event()
        self._reminder_lock = threading.Lock()
        self._tray = None

    # 托盘菜单
    def _build_tray(self):
        icon_img = make_tray_icon()
        menu = pystray.Menu(
            pystray.MenuItem("SeeEye 护眼助手", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "暂停提醒",
                self._toggle_pause,
                checked=lambda item: self.paused
            ),
            pystray.MenuItem("立即提醒", self._remind_now),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._quit),
        )
        self._tray = pystray.Icon("SeeEye", icon_img, "SeeEye 护眼助手", menu)

    def _toggle_pause(self):
        self.paused = not self.paused

    def _remind_now(self):
        threading.Thread(target=self._show_reminder, daemon=True).start()

    def _quit(self):
        self._stop_event.set()
        if self._tray:
            self._tray.stop()

    # 计时主循环（后台线程）
    def _timer_loop(self):
        interval = WORK_MINUTES * 60
        elapsed = 0
        while not self._stop_event.is_set():
            time.sleep(1)
            if self.paused:
                continue
            elapsed += 1
            if elapsed >= interval:
                elapsed = 0
                self._show_reminder()

    def _show_reminder(self):
        with self._reminder_lock:   # 防止同时弹多个窗口
            done = threading.Event()
            def on_done():
                done.set()
            # tkinter 必须在主线程创建，用新线程 + 自己的 mainloop
            def run():
                w = ReminderWindow(on_done)
                w.show()
            t = threading.Thread(target=run, daemon=True)
            t.start()
            done.wait()

    def run(self):
        self._build_tray()
        timer_thread = threading.Thread(target=self._timer_loop, daemon=True)
        timer_thread.start()
        # pystray.run() 会阻塞主线程，接管消息循环
        self._tray.run()


# ── 入口 ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    EyeGuard().run()
