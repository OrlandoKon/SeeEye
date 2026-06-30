"""
SeeEye — 护眼桌面助手 (PyQt6 主程序)

运行：python main.py

功能：
  - 20-20-20 护眼提醒（每 20 分钟弹出小窗）
  - 60 分钟久坐提醒（全屏提醒，可跳过）
  - 活跃用眼时长统计，每 30 分钟同步到云端
  - 托盘菜单支持开机自启动开关
"""

import os
import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from eye_break import BreakReminder, EyeRestReminder
from time_tracker import TimeTracker, _win_is_locked

# ── 请将此处替换为你的实际地址 ──────────────────────────────────────────────────
API_BASE = ""          # 例如 "http://192.168.1.100:8000"，暂不使用留空

EYE_INTERVAL_SEC   = 20 * 60
WORK_INTERVAL_SEC  = 60 * 60
BREAK_DURATION_SEC =  5 * 60

_APP_NAME = "SeeEye"
_REG_KEY  = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _exe_path() -> str:
    """返回当前可执行文件的路径（打包后是 .exe，开发时是 python main.py）。"""
    if getattr(sys, "frozen", False):
        return sys.executable
    return f'"{sys.executable}" "{os.path.abspath(__file__)}"'


def _resource(filename: str) -> str:
    """兼容 PyInstaller 打包后的资源路径。"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, filename)


# ── 开机自启动（写注册表）──────────────────────────────────────────────────────

def _is_autostart() -> bool:
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_KEY)
        winreg.QueryValueEx(key, _APP_NAME)
        winreg.CloseKey(key)
        return True
    except Exception:
        return False


def _set_autostart(enable: bool):
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _REG_KEY, 0, winreg.KEY_SET_VALUE
        )
        if enable:
            winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, _exe_path())
        else:
            winreg.DeleteValue(key, _APP_NAME)
        winreg.CloseKey(key)
    except Exception:
        pass


# ── 主应用 ─────────────────────────────────────────────────────────────────────

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
        self._tray = QSystemTrayIcon(QIcon(_resource("Eye.svg")))
        self._tray.setToolTip("SeeEye 护眼助手")

        menu = QMenu()

        self._stats_action = menu.addAction("今日用眼：统计中…")
        self._stats_action.setEnabled(False)
        menu.addSeparator()

        self._pause_action = menu.addAction("暂停提醒")
        self._pause_action.setCheckable(True)
        self._pause_action.toggled.connect(lambda c: setattr(self, "_paused", c))

        menu.addAction("立即护眼提醒（20 秒）").triggered.connect(self._show_eye_notice)
        menu.addAction("立即久坐提醒（5 分钟）").triggered.connect(self._trigger_forced_break)
        menu.addSeparator()

        self._autostart_action = menu.addAction("开机自启动")
        self._autostart_action.setCheckable(True)
        self._autostart_action.setChecked(_is_autostart())
        self._autostart_action.toggled.connect(_set_autostart)

        menu.addSeparator()
        menu.addAction("退出").triggered.connect(self._quit)

        self._tray.setContextMenu(menu)
        self._tray.show()

    # ── 定时器 ─────────────────────────────────────────────────────────────────

    def _setup_timers(self):
        self._tick_timer = QTimer()
        self._tick_timer.timeout.connect(self._on_tick)
        self._tick_timer.start(1000)

        self._stats_timer = QTimer()
        self._stats_timer.timeout.connect(self._refresh_stats)
        self._stats_timer.start(60_000)

        # 锁屏检测在主线程运行，避免 OpenInputDesktop 与 Qt 消息泵死锁
        if sys.platform == "win32":
            self._lock_timer = QTimer()
            self._lock_timer.timeout.connect(self._check_lock_state)
            self._lock_timer.start(5_000)

    def _check_lock_state(self):
        self.tracker.set_locked(_win_is_locked())

    def _on_tick(self):
        if self._paused or self._break_active:
            return
        if not self.tracker.is_active:
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
        # 关闭上一个还未消失的护眼小窗，避免 Qt 对象堆积
        existing = getattr(self, "_eye_win", None)
        if existing is not None:
            try:
                existing._close()
            except RuntimeError:
                pass  # C++ 对象已被 Qt 回收，忽略
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
        if hasattr(self, "_lock_timer"):
            self._lock_timer.stop()
        self.tracker.stop()
        QApplication.quit()

    def run(self):
        sys.exit(self.app.exec())


if __name__ == "__main__":
    SeeEyeApp().run()
