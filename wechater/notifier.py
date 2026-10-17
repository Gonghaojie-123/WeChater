"""推送层：ntfy 分级推送。重要度 → priority，实现「屏蔽 vs 强调」。

ntfy priority 语义（Android 通知渠道 / 桌面提示强度）：
  5=max  打断式，最强提示
  4=high 较强
  3=default 普通
  2=low  静默、不发声，只进通知栏
  1=min  完全不打扰
配合 Android 的每个 priority 绑不同铃声/震动，即可做到「强调」与「静默」。
"""
from __future__ import annotations

from .models import ExtractedItem

_LEVEL_TAGS = {
    "urgent": ["rotating_light"],
    "normal": ["memo"],
    "silent": ["zzz"],
}


class NtfyNotifier:
    def __init__(self, cfg: dict):
        import requests
        self.requests = requests
        self.server = cfg["notify"]["server"].rstrip("/")
        self.topic = cfg["notify"]["topic"]
        self.levels = cfg["notify"]["levels"]

    def push(self, item: ExtractedItem) -> None:
        priority = self.levels.get(item.level, 3)
        title = f"[{item.level}] {item.type} · {item.chat}"
        body = item.text
        if item.due:
            body += f"\n截止：{item.due}"
        if item.reason:
            body += f"\n（{item.reason}）"
        self._send(title=title, body=body, priority=priority,
                   tags=_LEVEL_TAGS.get(item.level, []))

    def push_text(self, title: str, body: str, priority: int = 3,
                  tags: list[str] | None = None) -> None:
        self._send(title=title, body=body, priority=priority, tags=tags or [])

    def _send(self, title: str, body: str, priority: int, tags: list[str]) -> None:
        headers = {
            "Title": title.encode("utf-8").decode("latin-1", "ignore"),
            "Priority": str(priority),
            "Markdown": "yes",
        }
        if tags:
            headers["Tags"] = ",".join(tags)
        resp = self.requests.post(
            f"{self.server}/{self.topic}",
            data=body.encode("utf-8"),
            headers=headers,
            timeout=20,
        )
        resp.raise_for_status()


class ConsoleNotifier:
    """dryrun 用：把推送打印到控制台，不联网。"""

    def push(self, item: ExtractedItem) -> None:
        icon = {"urgent": "!!", "normal": " *", "silent": " ."}[item.level]
        due = f"  截止={item.due}" if item.due else ""
        print(f"{icon} [{item.level:<6}] {item.type:<10} {item.text}"
              f"   <{item.chat}/{item.who}>{due}  ({item.reason})")

    def push_text(self, title: str, body: str, priority: int = 3,
                  tags: list[str] | None = None) -> None:
        print(f"\n=== {title} (p{priority}) ===\n{body}\n")


def build_notifier(cfg: dict):
    if cfg.get("dryrun"):
        return ConsoleNotifier()
    return NtfyNotifier(cfg)
