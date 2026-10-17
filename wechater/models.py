"""数据模型：采集层与后续各层之间的统一数据结构。"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional


@dataclass
class Message:
    """一条聊天消息——采集层的统一输出。"""

    chat: str                 # 会话名：群名或联系人昵称
    sender: str               # 发送者昵称
    content: str              # 文本内容
    timestamp: float          # Unix 时间戳（秒）
    is_group: bool = False
    is_at_me: bool = False    # 群里是否 @ 我
    msg_id: str = ""          # 来源提供的唯一 id，缺省时用内容指纹

    @property
    def uid(self) -> str:
        """稳定去重键。有 msg_id 就用它，否则对内容取指纹。"""
        if self.msg_id:
            return f"{self.chat}::{self.msg_id}"
        raw = f"{self.chat}|{self.sender}|{self.timestamp}|{self.content}"
        digest = hashlib.md5(raw.encode("utf-8")).hexdigest()
        return f"{self.chat}::{digest}"


@dataclass
class ExtractedItem:
    """从消息里抽取出来的一条结构化信息。"""

    type: str                 # todo / event / question / commitment
    text: str                 # 事项内容
    who: str                  # 相关的人
    chat: str                 # 来自哪个会话
    importance: float         # 0.0 - 1.0
    reason: str = ""          # 判重要度的理由（可复核）
    due: Optional[str] = None # 截止 / 时间，能解析就填
    source_msg: str = ""      # 来源消息 uid
    created_at: float = 0.0

    @property
    def level(self) -> str:
        """重要度分档：urgent / normal / silent。"""
        if self.importance >= 0.8:
            return "urgent"
        if self.importance >= 0.5:
            return "normal"
        return "silent"
