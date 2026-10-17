"""存储层：已见消息去重 + 待办入库 + 每日查询。"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Iterable, Sequence

from .models import ExtractedItem, Message

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_messages (
    uid     TEXT PRIMARY KEY,
    chat    TEXT,
    sender  TEXT,
    ts      REAL,
    seen_at REAL
);
CREATE TABLE IF NOT EXISTS items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    type        TEXT,
    text        TEXT,
    who         TEXT,
    chat        TEXT,
    importance  REAL,
    reason      TEXT,
    due         TEXT,
    source_msg  TEXT,
    created_at  REAL,
    pushed      INTEGER DEFAULT 0,
    day         TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_items_dedup ON items(source_msg, text);
CREATE INDEX IF NOT EXISTS idx_items_day ON items(day);
"""


class Store:
    def __init__(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ---- 消息去重 ----
    def filter_new(self, messages: Iterable[Message]) -> list[Message]:
        """返回尚未见过的消息（不写库；由 mark_seen 统一落库）。"""
        fresh: list[Message] = []
        for msg in messages:
            row = self.conn.execute(
                "SELECT 1 FROM seen_messages WHERE uid = ?", (msg.uid,)
            ).fetchone()
            if row is None:
                fresh.append(msg)
        return fresh

    def mark_seen(self, messages: Iterable[Message]) -> None:
        now = time.time()
        self.conn.executemany(
            "INSERT OR IGNORE INTO seen_messages(uid, chat, sender, ts, seen_at)"
            " VALUES (?, ?, ?, ?, ?)",
            [(m.uid, m.chat, m.sender, m.timestamp, now) for m in messages],
        )
        self.conn.commit()

    # ---- 待办入库 ----
    def add_item(self, item: ExtractedItem) -> bool:
        """写入一条待办；重复（同来源+同文本）则忽略。返回是否新写入。"""
        day = time.strftime("%Y-%m-%d", time.localtime(item.created_at or time.time()))
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO items"
            "(type, text, who, chat, importance, reason, due, source_msg, created_at, day)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item.type, item.text, item.who, item.chat, item.importance,
             item.reason, item.due, item.source_msg, item.created_at or time.time(), day),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def set_pushed(self, item_ids: Sequence[int]) -> None:
        self.conn.executemany(
            "UPDATE items SET pushed = 1 WHERE id = ?", [(i,) for i in item_ids]
        )
        self.conn.commit()

    def items_for_day(self, day: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM items WHERE day = ? ORDER BY importance DESC, id ASC",
            (day,),
        ).fetchall()

    def count_items(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]

    def close(self) -> None:
        self.conn.close()
