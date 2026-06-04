"""
SeeEye 云端 API — 部署在服务器上
启动命令：uvicorn api_server:app --host 0.0.0.0 --port 8000

建议配合 Nginx 反向代理，对外暴露为 https://eyesight.your-domain.com
"""

from contextlib import contextmanager
import os
import sqlite3
from typing import List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

DB_PATH = os.getenv("SEEEYE_DB", "seeeye.db")

app = FastAPI(title="SeeEye API", version="1.0")


# ── 数据库 ─────────────────────────────────────────────────────────────────────

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS usage_logs (
                device_id     TEXT NOT NULL,
                date          TEXT NOT NULL,
                total_minutes INTEGER DEFAULT 0,
                PRIMARY KEY (device_id, date)
            );
            CREATE TABLE IF NOT EXISTS violations (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                date      TEXT NOT NULL,
                time      TEXT NOT NULL,
                reason    TEXT NOT NULL
            );
        """)


init_db()


# ── 数据模型 ───────────────────────────────────────────────────────────────────

class Violation(BaseModel):
    time: str
    reason: str


class UsageLog(BaseModel):
    device_id: str
    date: str
    total_minutes: int
    violations: List[Violation] = []


# ── 接口 ───────────────────────────────────────────────────────────────────────

@app.post("/api/log")
def post_log(log: UsageLog):
    """上传本设备当日用眼数据，重复上传则覆盖 total_minutes。"""
    with get_db() as db:
        db.execute(
            """INSERT INTO usage_logs (device_id, date, total_minutes)
               VALUES (?, ?, ?)
               ON CONFLICT(device_id, date)
               DO UPDATE SET total_minutes = excluded.total_minutes""",
            (log.device_id, log.date, log.total_minutes),
        )
        if log.violations:
            db.execute(
                "DELETE FROM violations WHERE device_id = ? AND date = ?",
                (log.device_id, log.date),
            )
            db.executemany(
                "INSERT INTO violations (device_id, date, time, reason) VALUES (?,?,?,?)",
                [(log.device_id, log.date, v.time, v.reason) for v in log.violations],
            )
    return {"status": "ok"}


@app.get("/api/stats")
def get_stats(date: str):
    """
    查询指定日期所有设备的汇总数据。
    示例：GET /api/stats?date=2026-06-04
    """
    with get_db() as db:
        rows = db.execute(
            "SELECT device_id, total_minutes FROM usage_logs WHERE date = ?", (date,)
        ).fetchall()
        viols = db.execute(
            "SELECT device_id, time, reason FROM violations WHERE date = ? ORDER BY time",
            (date,),
        ).fetchall()

    devices = {r["device_id"]: r["total_minutes"] for r in rows}
    return {
        "date": date,
        "total_minutes": sum(devices.values()),
        "devices": devices,
        "violations": [dict(v) for v in viols],
    }
