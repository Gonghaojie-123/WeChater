"""采集层：把不同来源的聊天记录统一成 Message 流。

生产路径是 **UI 自动化**（UIAutomation 驱动官方 PC 微信客户端）。
这是 2026 年唯一还能用、且不注入进程 / 不解密数据库的合规友好路线；
解密本地库的老方案（ChatLog / PyWxDump / WeChatMsg）已于 2025-10
被微信官方集中发函下架，不要再依赖。

三种后端：
  file   从本地 JSONL 记录文件读（通用、可离线测试、也可喂其他工具导出的数据）
  wxauto 驱动官方 PC 微信客户端读新消息（只读，不发送）
  http   轮询一个自建 HTTP 端点
"""
from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

from .models import Message


def _parse_time(value) -> float:
    """把多种时间表示统一成 Unix 时间戳。"""
    if value is None:
        return time.time()
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    try:  # ISO 8601 兜底
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return time.time()


class BaseCollector(ABC):
    """采集器接口：返回「全部当前可见」的消息，去重交给 Store。"""

    @abstractmethod
    def poll(self) -> list[Message]:
        ...


class FileCollector(BaseCollector):
    """从 JSONL 文件读取。每行一个对象：
    {"chat": "产品群", "sender": "李经理", "content": "...",
     "time": "2026-10-16 09:30", "is_group": true, "is_at_me": true, "id": "..."}
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def poll(self) -> list[Message]:
        if not self.path.exists():
            return []
        messages: list[Message] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            messages.append(Message(
                chat=obj.get("chat", "未知会话"),
                sender=obj.get("sender", "未知"),
                content=obj.get("content", ""),
                timestamp=_parse_time(obj.get("time")),
                is_group=bool(obj.get("is_group", False)),
                is_at_me=bool(obj.get("is_at_me", False)),
                msg_id=str(obj.get("id", "")),
            ))
        return messages


class WxautoCollector(BaseCollector):
    """驱动官方 PC 微信客户端读取新消息（UIAutomation，只读）。

    依赖可选包 wxauto，且需要 Windows + 已登录的 PC 微信。
    注意：wxauto 各版本 API 有差异，此处按经典稳定接口实现，
    如遇 AttributeError 请对照你安装版本调整 _read_chat()。
    """

    def __init__(self, chats: list[str], interval: int = 60):
        try:
            from wxauto import WeChat  # 延迟导入：非生产环境无需安装
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "未安装 wxauto。请先 `pip install wxauto`，或改用 collector: file。"
            ) from exc
        self.wx = WeChat()
        self.chats = chats
        self.interval = interval

    def _read_chat(self, chat: str) -> list[Message]:
        self.wx.ChatWith(chat)
        raw = self.wx.GetAllMessage()  # 各版本可能是 GetAllNewMessage()
        out: list[Message] = []
        for m in raw:
            content = getattr(m, "content", "") or getattr(m, "sender", "")
            sender = getattr(m, "sender", "未知")
            out.append(Message(
                chat=chat,
                sender=sender,
                content=content,
                timestamp=time.time(),
                is_group=True,
                is_at_me="@我" in content or "＠我" in content,
            ))
        return out

    def poll(self) -> list[Message]:
        messages: list[Message] = []
        for chat in self.chats:
            try:
                messages.extend(self._read_chat(chat))
                time.sleep(self.interval / max(len(self.chats), 1))
            except Exception as exc:  # 单个会话失败不影响其它
                print(f"[collector] 读取会话“{chat}”失败：{exc}")
        return messages


class HttpCollector(BaseCollector):
    """轮询自建 HTTP 端点，期望返回 JSON 数组。"""

    def __init__(self, url: str):
        import requests
        self.requests = requests
        self.url = url

    def poll(self) -> list[Message]:
        if not self.url:
            return []
        resp = self.requests.get(self.url, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            data = data.get("messages", [])
        return [
            Message(
                chat=o.get("chat", "未知会话"),
                sender=o.get("sender", "未知"),
                content=o.get("content", ""),
                timestamp=_parse_time(o.get("time")),
                is_group=bool(o.get("is_group", False)),
                is_at_me=bool(o.get("is_at_me", False)),
                msg_id=str(o.get("id", "")),
            )
            for o in data
        ]


def build_collector(cfg: dict) -> BaseCollector:
    """按配置构造采集器。"""
    from .config import resolve_path

    backend = cfg["wechat"]["collector"]
    if backend == "file":
        return FileCollector(resolve_path(cfg, cfg["wechat"]["file_path"]))
    if backend == "wxauto":
        return WxautoCollector(
            chats=cfg["wechat"]["whitelist"]["chats"],
            interval=int(cfg["wechat"]["wxauto"]["interval"]),
        )
    if backend == "http":
        return HttpCollector(cfg["wechat"]["http"]["url"])
    raise ValueError(f"未知采集后端：{backend}")
