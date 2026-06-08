"""
SeeEye — 本地用眼时长追踪 + 云端同步

Windows：用 GetLastInputInfo 检测空闲，OpenInputDesktop 检测锁屏，无需 pynput hook
其他平台：回退到 pynput 监听键鼠事件

依赖：pip install requests pynput（非 Windows 需要 pynput）
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
IDLE_THRESHOLD  = 180    # 空闲超过 3 分钟则暂停（非 Windows 用）
SYNC_INTERVAL   = 1800   # 每 30 分钟同步一次
SLEEP_GAP       = 60     # tick 间隔超过此值判定为休眠
LOCK_CHECK_FREQ = 5      # 每隔多少秒检测一次锁屏


# ── Windows 原生检测工具 ────────────────────────────────────────────────────────

def _win_idle_seconds() -> float:
    """返回 Windows 系统距上次键鼠输入的秒数。"""
    try:
        import ctypes
        class _Info(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
        info = _Info()
        info.cbSize = ctypes.sizeof(_Info)
        ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
        elapsed_ms = ctypes.windll.kernel32.GetTickCount() - info.dwTime
        return max(0.0, elapsed_ms / 1000.0)
    except Exception:
        return 0.0


def _win_is_locked() -> bool:
    """通过输入桌面名称判断屏幕是否已锁定。"""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hdesk = user32.OpenInputDesktop(0, False, 0x0100)
        if not hdesk:
            return True
        buf = ctypes.create_unicode_buffer(256)
        user32.GetUserObjectInformationW(hdesk, 2, buf, ctypes.sizeof(buf), None)
        user32.CloseDesktop(hdesk)
        return buf.value != "Default"
    except Exception:
        return False


# ── 追踪器 ─────────────────────────────────────────────────────────────────────

class TimeTracker:
    def __init__(self, api_base: str = ""):
        self.api_base  = api_base.rstrip("/")
        self.device_id = self._load_or_create_device_id()

        self._lock            = threading.Lock()
        self._stop            = threading.Event()
        self._today: str      = str(date.today())
        self._active_sec: int = 0
        self._violations: List[Dict[str, str]] = []
        self._last_tick       = time.monotonic()
        self._locked: bool    = False  # 由后台线程维护，主线程只读

        # 非 Windows 平台用 pynput 追踪最后活动时间
        self._last_activity = time.monotonic()

        self._load_local()
        if self.api_base:
            threading.Thread(target=self._pull_cloud, daemon=True).start()

    # ── 公开接口 ───────────────────────────────────────────────────────────────

    def start(self):
        if sys.platform != "win32":
            self._install_pynput()
        threading.Thread(target=self._tick_loop, daemon=True).start()

    def stop(self):
        self._stop.set()
        if sys.platform != "win32":
            self._remove_pynput()
        self.sync_to_cloud()

    def add_violation(self, reason: str):
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
        """供主线程读取，不做任何 IO 或系统调用。"""
        if sys.platform == "win32":
            return not self._locked
        return (time.monotonic() - self._last_activity) < IDLE_THRESHOLD

    # ── pynput（非 Windows）──────────────────────────────────────────────────────

    def _on_activity(self, *_):
        self._last_activity = time.monotonic()

    def _install_pynput(self):
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

    def _remove_pynput(self):
        if not _HAS_PYNPUT:
            return
        for attr in ("_kb_l", "_ms_l"):
            if hasattr(self, attr):
                getattr(self, attr).stop()

    # ── 计时主循环（后台线程）──────────────────────────────────────────────────────

    def _tick_loop(self):
        last_sync       = time.monotonic()
        lock_check_acc  = 0   # 锁屏检测累计秒数

        while not self._stop.wait(1.0):
            now   = time.monotonic()
            today = str(date.today())

            # 休眠检测：两次 tick 间隔过大则跳过
            gap = now - self._last_tick
            self._last_tick = now
            if gap > SLEEP_GAP:
                self._locked = False  # 休眠唤醒后重置
                continue

            # 日期跨越
            with self._lock:
                if today != self._today:
                    self._save_local()
                    self._today      = today
                    self._active_sec = 0
                    self._violations = []

            # 锁屏检测（每 LOCK_CHECK_FREQ 秒检测一次，降低 API 调用频率）
            if sys.platform == "win32":
                lock_check_acc += 1
                if lock_check_acc >= LOCK_CHECK_FREQ:
                    lock_check_acc  = 0
                    self._locked    = _win_is_locked()
                idle_sec = _win_idle_seconds()
                counting = not self._locked and idle_sec < IDLE_THRESHOLD
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
            snapshot = {
                "active_seconds": self._active_sec,
                "violations":     list(self._violations),
            }
        data[self._today] = snapshot
        with open(LOCAL_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ── 云端同步 ───────────────────────────────────────────────────────────────

    def _pull_cloud(self):
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
