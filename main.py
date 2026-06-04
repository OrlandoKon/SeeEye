"""
SeeEye — 护眼桌面助手 (PyQt6 主程序)

运行：python main.py

功能：
  - 20-20-20 护眼提醒（每 20 分钟系统托盘通知）
  - 60 分钟强制久坐提醒（全屏遮罩，5 分钟无法跳过）
  - 活跃用眼时长统计，每 30 分钟同步到云端
"""

import os
import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from eye_break import BreakReminder, EyeRestReminder
from time_tracker import TimeTracker

# ── 请将此处替换为你的实际域名 ─────────────────────────────────────────────────
API_BASE = "https://eyesight.your-domain.com"
# 如暂时不使用云同步，留空即可：API_BASE = ""

EYE_INTERVAL_SEC   = 20 * 60   # 20 分钟护眼提醒
WORK_INTERVAL_SEC  = 60 * 60   # 60 分钟久坐提醒
BREAK_DURATION_SEC = 5  * 60   # 强制休息 5 分钟


class SeeEyeApp:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        self.tracker = TimeTracker(api_base=API_BASE)
        self.tracker.start()

        self._eye_elapsed  = 0
        self._work_elapsed = 0
        self._paused       = False
        self._break_active = False
        self._overlay: BreakReminder | None = None

        self._setup_tray()
        self._setup_timers()

    # ── 系统托盘 ───────────────────────────────────────────────────────────────

    def _setup_tray(self):
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Eye.svg")
        self._tray = QSystemTrayIcon(QIcon(icon_path))
        self._tray.setToolTip("SeeEye 护眼助手")

        menu = QMenu()

        self._stats_action = menu.addAction("今日用眼：统计中…")
        self._stats_action.setEnabled(False)
        menu.addSeparator()

        self._pause_action = menu.addAction("暂停提醒")
        self._pause_action.setCheckable(True)
        self._pause_action.toggled.connect(lambda c: setattr(self, "_paused", c))

        menu.addAction("立即护眼提醒（20 秒）").triggered.connect(
            self._show_eye_notice
        )
        menu.addAction("立即久坐提醒（5 分钟）").triggered.connect(
            self._trigger_forced_break
        )
        menu.addSeparator()
        menu.addAction("退出").triggered.connect(self._quit)

        self._tray.setContextMenu(menu)
        self._tray.show()

    # ── 定时器 ─────────────────────────────────────────────────────────────────

    def _setup_timers(self):
        self._tick_timer = QTimer()
        self._tick_timer.timeout.connect(self._on_tick)
        self._tick_timer.start(1000)

        # 每分钟刷新一次托盘显示的统计数字
        self._stats_timer = QTimer()
        self._stats_timer.timeout.connect(self._refresh_stats)
        self._stats_timer.start(60_000)

    def _on_tick(self):
        if self._paused or self._break_active:
            return
        self._eye_elapsed  += 1
        self._work_elapsed += 1

        if self._eye_elapsed >= EYE_INTERVAL_SEC:
            self._eye_elapsed = 0
            self._show_eye_notice()

        if self._work_elapsed >= WORK_INTERVAL_SEC:
            self._work_elapsed = 0
            self._trigger_forced_break()

    # ── 提醒逻辑 ───────────────────────────────────────────────────────────────

    def _show_eye_notice(self):
        self._eye_win = EyeRestReminder()
        self._eye_win.show()

    def _trigger_forced_break(self):
        if self._break_active:
            return
        self._break_active = True
        self._overlay = BreakReminder(duration=BREAK_DURATION_SEC)
        self._overlay.reminder_closed.connect(self._on_break_done)
        self._overlay.activate()

    def _on_break_done(self):
        self._break_active = False
        self._work_elapsed = 0
        self._overlay = None

    # ── 统计刷新 ───────────────────────────────────────────────────────────────

    def _refresh_stats(self):
        mins = self.tracker.today_minutes
        self._stats_action.setText(f"今日用眼：{mins} 分钟")
        self._tray.setToolTip(f"SeeEye — 今日 {mins} 分钟")

    # ── 退出 ───────────────────────────────────────────────────────────────────

    def _quit(self):
        self.tracker.stop()   # 强制同步数据
        QApplication.quit()

    def run(self):
        sys.exit(self.app.exec())


if __name__ == "__main__":
    SeeEyeApp().run()
