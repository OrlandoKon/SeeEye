"""
SeeEye — 提醒弹窗 (PyQt6)

EyeRestReminder  : 右下角浮动小窗，20 秒护眼提醒，可手动关闭
BreakReminder    : 全屏久坐提醒，60 分钟触发，可跳过

依赖：pip install PyQt6
"""

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QVBoxLayout, QWidget,
)

# ── 全局配色（自然·愉悦风格）──────────────────────────────────────────────────
_C = {
    "bg_popup":    "#f0fbf4",           # 极浅薄荷——小弹窗背景
    "bg_overlay":  "rgba(220,245,230,242)",  # 半透明浅绿——全屏遮罩
    "border":      "#95d5b2",           # 柔和鼠尾草绿——边框
    "title":       "#1b4332",           # 深森林绿——标题
    "count":       "#2d6a4f",           # 中森林绿——倒计时数字
    "body":        "#52796f",           # 灰绿——正文
    "muted":       "#95b2a5",           # 浅灰绿——次要说明
    "prog_fill":   "#74c69d",           # 清新草绿——进度条
    "prog_bg":     "#d8f3dc",           # 极浅绿——进度条底
    "skip_text":   "#52796f",
    "skip_hover":  "#2d6a4f",
    "skip_border": "#95d5b2",
}

_FONT = "'Microsoft YaHei UI', 'Segoe UI', sans-serif"


# ── 20 秒护眼小窗 ──────────────────────────────────────────────────────────────

class EyeRestReminder(QWidget):
    """右下角浮动小窗，20 秒护眼倒计时，可随时手动关闭。"""

    W, H = 300, 118

    def __init__(self):
        super().__init__()
        self.remaining = 20
        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)
        self._build_ui()
        self._position_center()

    def show(self):
        super().show()
        self._timer.start(1000)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(self.W, self.H)

        card = QWidget(self, objectName="card")
        card.setGeometry(0, 0, self.W, self.H)
        card.setStyleSheet(f"""
            QWidget#card {{
                background-color: {_C['bg_popup']};
                border: 1.5px solid {_C['border']};
                border-radius: 14px;
            }}
        """)

        outer = QVBoxLayout(card)
        outer.setContentsMargins(16, 12, 16, 14)
        outer.setSpacing(7)

        # 标题行
        top = QHBoxLayout()
        title = QLabel("👁  护眼提醒")
        title.setStyleSheet(
            f"color:{_C['title']}; font-size:14px; font-weight:bold; font-family:{_FONT};"
        )
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(20, 20)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background:transparent; color:{_C['muted']};
                border:none; font-size:12px;
            }}
            QPushButton:hover {{ color:{_C['title']}; }}
        """)
        close_btn.clicked.connect(self._close)
        top.addWidget(title)
        top.addStretch()
        top.addWidget(close_btn)
        outer.addLayout(top)

        # 提示文字
        desc = QLabel("望向 6 米外，放松眼部肌肉")
        desc.setStyleSheet(
            f"color:{_C['body']}; font-size:12px; font-family:{_FONT};"
        )
        outer.addWidget(desc)

        # 进度条 + 倒计时
        row = QHBoxLayout()
        row.setSpacing(8)
        self._progress = QProgressBar()
        self._progress.setRange(0, 20)
        self._progress.setValue(0)
        self._progress.setFixedHeight(6)
        self._progress.setTextVisible(False)
        self._progress.setStyleSheet(f"""
            QProgressBar        {{ background:{_C['prog_bg']}; border-radius:3px; }}
            QProgressBar::chunk {{ background:{_C['prog_fill']}; border-radius:3px; }}
        """)
        self._count = QLabel("20s")
        self._count.setFixedWidth(28)
        self._count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._count.setStyleSheet(
            f"color:{_C['count']}; font-size:12px; font-weight:bold; font-family:'Segoe UI';"
        )
        row.addWidget(self._progress)
        row.addWidget(self._count)
        outer.addLayout(row)

    def _position_center(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            screen.center().x() - self.W // 2,
            screen.center().y() - self.H // 2,
        )

    def _tick(self):
        self.remaining -= 1
        self._count.setText(f"{self.remaining}s")
        self._progress.setValue(20 - self.remaining)
        if self.remaining <= 0:
            self._close()

    def _close(self):
        self._timer.stop()
        self.hide()
        self.deleteLater()  # 释放 Qt 对象，避免长时间运行内存堆积


# ── 全屏久坐提醒 ───────────────────────────────────────────────────────────────

class BreakReminder(QWidget):
    """
    全屏久坐提醒弹窗，可跳过。
    使用方式：
        reminder = BreakReminder(duration=300)
        reminder.reminder_closed.connect(on_done)
        reminder.activate()
    """

    reminder_closed = pyqtSignal()

    def __init__(self, duration: int = 300):
        super().__init__()
        self.duration  = duration
        self.remaining = duration
        self._timer    = QTimer()
        self._timer.timeout.connect(self._tick)
        self._build_ui()

    def activate(self):
        self.showFullScreen()
        self._timer.start(1000)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {_C['bg_overlay']};
                font-family: {_FONT};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(20)

        title = QLabel("🌿  起身活动一下吧")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"color:{_C['title']}; font-size:40px; font-weight:bold;"
        )
        layout.addWidget(title)

        desc = QLabel("已连续工作 60 分钟\n建议站起来活动、眺望远处，放松肩颈")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet(
            f"color:{_C['body']}; font-size:16px; line-height:1.8;"
        )
        layout.addWidget(desc)

        self._count_label = QLabel(self._fmt(self.remaining))
        self._count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._count_label.setStyleSheet(
            f"color:{_C['count']}; font-size:96px; font-weight:bold; font-family:'Segoe UI';"
        )
        layout.addWidget(self._count_label)

        self._progress = QProgressBar()
        self._progress.setRange(0, self.duration)
        self._progress.setValue(0)
        self._progress.setFixedWidth(520)
        self._progress.setFixedHeight(8)
        self._progress.setTextVisible(False)
        self._progress.setStyleSheet(f"""
            QProgressBar        {{ background:{_C['prog_bg']}; border-radius:4px; }}
            QProgressBar::chunk {{ background:{_C['prog_fill']}; border-radius:4px; }}
        """)
        layout.addWidget(self._progress, alignment=Qt.AlignmentFlag.AlignCenter)

        note = QLabel("休息结束后自动消失 · 也可点击跳过")
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note.setStyleSheet(f"color:{_C['muted']}; font-size:13px;")
        layout.addWidget(note)

        skip_btn = QPushButton("跳过，继续工作")
        skip_btn.setFixedWidth(160)
        skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        skip_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {_C['skip_text']};
                border: 1.5px solid {_C['skip_border']};
                border-radius: 8px;
                padding: 7px 16px;
                font-size: 13px;
            }}
            QPushButton:hover  {{ color:{_C['skip_hover']}; border-color:{_C['skip_hover']}; }}
            QPushButton:pressed {{ color:{_C['title']}; }}
        """)
        skip_btn.clicked.connect(self._close)
        layout.addWidget(skip_btn, alignment=Qt.AlignmentFlag.AlignCenter)

    # ── 倒计时 ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _fmt(secs: int) -> str:
        return f"{secs // 60:02d}:{secs % 60:02d}"

    def _tick(self):
        self.remaining -= 1
        self._count_label.setText(self._fmt(self.remaining))
        self._progress.setValue(self.duration - self.remaining)
        if self.remaining <= 0:
            self._timer.stop()
            self._close()

    def _close(self):
        self._timer.stop()
        self.hide()
        self.reminder_closed.emit()
