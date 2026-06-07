"""
SeeEye — 本地用眼时长追踪 + 云端同步

依赖：pip install pynput requests
"""

import json
import os
import sys
import threading
import time
import uuid
from datetime import date, datetime
from typing import Dict, List

try:
    import requests as _requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

try:
    from pynput import keyboard as _kb
    from pynput import mouse as _mouse
    _HAS_PYNPUT = True
except ImportError:
    _HAS_PYNPUT = False


DEVICE_ID_FILE  = ".device_id"
LOCAL_DATA_FILE = "local_usage.json"
IDLE_THRESHOLD  = 180    # 超过 3 分钟无操作则暂停计时（非 Windows 回退用）
SYNC_INTERVAL   = 1800   # 每 30 分钟自动同步一次
SLEEP_GAP       = 60     # 两次 tick 间隔超过此值，判定为系统休眠/锁屏


def _is_screen_locked() -> bool:
    """
    Windows：通过读取当前输入桌面名称判断是否锁屏。
    正常使用时桌面名为 'Default'；锁屏后切换到 'Winlogon' 桌面。
    仅在后台线程中调用，避免阻塞 Qt 主线程。
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hdesk = user32.OpenInputDesktop(0, False, 0x0100)
        if not hdesk:
            return True  # 无法打开 = 锁屏
        buf = ctypes.create_unicode_buffer(256)
        user32.GetUserObjectInformationW(hdesk, 2, buf, ctypes.sizeof(buf), None)
        user32.CloseDesktop(hdesk)
        return buf.value != "Default"
    except Exception:
        return False


class TimeTracker:
    """
    精确追踪活跃屏幕时间：
    - 监听全局键鼠事件判断用户是否活跃
    - 系统休眠/锁屏时自动暂停
    - 每 30 分钟将数据同步到云端，程序退出时强制同步
    - 启动时从云端拉取今日数据与本地合并（取较大值）
    """

    def __init__(self, api_base: str = ""):
        self.api_base  = api_base.rstrip("/")
        self.device_id = self._load_or_create_device_id()

        self._lock            = threading.Lock()
        self._stop            = threading.Event()
        self._today: str      = str(date.today())
        self._active_sec: int = 0
        self._violations: List[Dict[str, str]] = []
        self._last_activity   = time.monotonic()
        self._last_tick       = time.monotonic()
        self._locked: bool    = False   # 由后台线程更新，主线程只读

        self._load_local()
        if self.api_base:
            threading.Thread(target=self._pull_cloud, daemon=True).start()

    # ── 公开接口 ───────────────────────────────────────────────────────────────

    def start(self):
        """启动活动监听与计时线程。"""
        self._install_listeners()
        threading.Thread(target=self._tick_loop, daemon=True).start()

    def stop(self):
        """停止追踪并强制同步到云端。"""
        self._stop.set()
        self._remove_listeners()
        self.sync_to_cloud()

    def add_violation(self, reason: str):
        """记录一条违规（由外部休息提醒模块调用）。"""
        with self._lock:
            self._violations.append({
                "time":   datetime.now().strftime("%H:%M"),
                "reason": reason,
            })

    @property
    def today_minutes(self) -> int:
        with self._lock:
            return self._active_sec // 60

    @property
    def is_active(self) -> bool:
        if sys.platform == "win32":
            return not self._locked   # 读后台线程缓存，不阻塞主线程
        return (time.monotonic() - self._last_activity) < IDLE_THRESHOLD

    # ── 活动监听 ───────────────────────────────────────────────────────────────

    def _on_activity(self, *_):
        self._last_activity = time.monotonic()

    def _install_listeners(self):
        if not _HAS_PYNPUT:
            return
        self._kb_l = _kb.Listener(on_press=self._on_activity)
        self._ms_l = _mouse.Listener(
            on_move=self._on_activity,
            on_click=self._on_activity,
            on_scroll=self._on_activity,
        )
        self._kb_l.start()
        self._ms_l.start()

    def _remove_listeners(self):
        if not _HAS_PYNPUT:
            return
        if hasattr(self, "_kb_l"):
            self._kb_l.stop()
        if hasattr(self, "_ms_l"):
            self._ms_l.stop()

    # ── 计时主循环 ─────────────────────────────────────────────────────────────

    def _tick_loop(self):
        last_sync = time.monotonic()
        while not self._stop.wait(1.0):
            now   = time.monotonic()
            today = str(date.today())

            # 系统休眠检测：两次 tick 间隔异常大时跳过
            gap = now - self._last_tick
            self._last_tick = now
            if gap > SLEEP_GAP:
                continue

            # 日期跨越
            with self._lock:
                if today != self._today:
                    self._save_local()
                    self._today      = today
                    self._active_sec = 0
                    self._violations = []

            # 每秒刷新锁屏状态缓存（仅在后台线程中调用 Windows API）
            if sys.platform == "win32":
                self._locked = _is_screen_locked()
                counting = not self._locked
            else:
                counting = (now - self._last_activity) < IDLE_THRESHOLD

            if counting:
                with self._lock:
                    self._active_sec += 1

            # 定时同步
            if self.api_base and now - last_sync >= SYNC_INTERVAL:
                threading.Thread(target=self.sync_to_cloud, daemon=True).start()
                last_sync = now

    # ── 本地持久化 ─────────────────────────────────────────────────────────────

    def _load_local(self):
        if not os.path.exists(LOCAL_DATA_FILE):
            return
        try:
            with open(LOCAL_DATA_FILE, encoding="utf-8") as f:
                data = json.load(f)
            entry = data.get(self._today, {})
            with self._lock:
                self._active_sec = entry.get("active_seconds", 0)
                self._violations = entry.get("violations", [])
        except Exception:
            pass

    def _save_local(self):
        data: Dict = {}
        if os.path.exists(LOCAL_DATA_FILE):
            try:
                with open(LOCAL_DATA_FILE, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                pass
        with self._lock:
            data[self._today] = {
                "active_seconds": self._active_sec,
                "violations":     list(self._violations),
            }
        with open(LOCAL_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ── 云端同步 ───────────────────────────────────────────────────────────────

    def _pull_cloud(self):
        """启动时从云端拉取本设备今日数据，取本地与云端的较大值。"""
        if not _HAS_REQUESTS:
            return
        try:
            r = _requests.get(
                f"{self.api_base}/api/stats",
                params={"date": self._today},
                timeout=5,
            )
            if r.status_code == 200:
                cloud_mins = r.json().get("devices", {}).get(self.device_id, 0)
                with self._lock:
                    self._active_sec = max(self._active_sec, cloud_mins * 60)
        except Exception:
            pass

    def sync_to_cloud(self):
        """将当前数据同步到云端，同时保存本地。"""
        self._save_local()
        if not _HAS_REQUESTS or not self.api_base:
            return
        with self._lock:
            payload = {
                "device_id":     self.device_id,
                "date":          self._today,
                "total_minutes": self._active_sec // 60,
                "violations":    list(self._violations),
            }
        try:
            _requests.post(f"{self.api_base}/api/log", json=payload, timeout=5)
        except Exception:
            pass

    # ── 工具 ───────────────────────────────────────────────────────────────────

    @staticmethod
    def _load_or_create_device_id() -> str:
        if os.path.exists(DEVICE_ID_FILE):
            return open(DEVICE_ID_FILE, encoding="utf-8").read().strip()
        dev_id = f"pc_{uuid.uuid4().hex[:8]}"
        with open(DEVICE_ID_FILE, "w", encoding="utf-8") as f:
            f.write(dev_id)
        return dev_id
