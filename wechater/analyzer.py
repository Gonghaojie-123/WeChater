"""分析层：LLM 抽取 + 重要度打分。

两条路径：
  * DeepSeekAnalyzer —— 调用云端 API（OpenAI 兼容），效果好。
  * HeuristicAnalyzer —— 纯规则打分，无需联网，用于 dryrun / 兜底。
两者输出同一结构 ExtractedItem 列表，可无缝替换。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .models import ExtractedItem, Message

PROMPT_FILE = Path(__file__).resolve().parent.parent / "prompts" / "extract.md"


def _load_system_prompt() -> str:
    if PROMPT_FILE.exists():
        return PROMPT_FILE.read_text(encoding="utf-8")
    return "从聊天记录中抽取待办/事件/问题，输出 JSON：{\"items\": [...] }"


def _messages_to_payload(messages: list[Message]) -> str:
    rows = [
        {
            "time": time.strftime("%Y-%m-%d %H:%M", time.localtime(m.timestamp)),
            "chat": m.chat,
            "sender": m.sender,
            "at_me": m.is_at_me,
            "content": m.content,
        }
        for m in messages
    ]
    return json.dumps(rows, ensure_ascii=False, indent=1)


class DeepSeekAnalyzer:
    def __init__(self, cfg: dict):
        import requests
        self.requests = requests
        self.base_url = cfg["llm"]["base_url"].rstrip("/")
        self.api_key = cfg["llm"]["api_key"]
        self.model = cfg["llm"]["model"]
        self.system = _load_system_prompt()

    def analyze(self, messages: list[Message]) -> list[ExtractedItem]:
        if not messages:
            return []
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system},
                {"role": "user", "content": _messages_to_payload(messages)},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "stream": False,
        }
        resp = self.requests.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return _parse_items(content, messages)


def _parse_items(raw: str, messages: list[Message]) -> list[ExtractedItem]:
    """把模型返回的 JSON 文本解析成 ExtractedItem。容错处理。"""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = data.get("items", [])
    if not isinstance(data, list):
        return []

    # 用发送者做个粗糙的归属：模型没给 who 时，挂到最近一条 @我 的人
    fallback_chat = messages[0].chat if messages else ""
    out: list[ExtractedItem] = []
    now = time.time()
    for obj in data:
        if not isinstance(obj, dict) or not obj.get("text"):
            continue
        try:
            score = float(obj.get("importance", 0.5))
        except (TypeError, ValueError):
            score = 0.5
        out.append(ExtractedItem(
            type=str(obj.get("type", "todo")),
            text=str(obj["text"]).strip(),
            who=str(obj.get("who", "")),
            chat=str(obj.get("chat", fallback_chat)),
            importance=max(0.0, min(1.0, score)),
            reason=str(obj.get("reason", "")),
            due=obj.get("due") or None,
            created_at=now,
        ))
    return out


# ---- 规则兜底：不联网也能产出可用结果 ----

_DUE_WORDS = ("截止", "deadline", "ddl", "尽快", "今天", "明天", "后天",
              "本周", "今晚", "hour", "点前", "之前")
_ACTION_WORDS = ("记得", "麻烦", "请", "帮我", "安排", "需要", "要", "确认",
                 "回复", "提交", "发我", "给我")
_EVENT_WORDS = ("会议", "开会", "碰", "约", "聚餐", "面试", "评审", "同步")


class HeuristicAnalyzer:
    """关键词打分兜底。够用、可解释、零成本、离线。"""

    def analyze(self, messages: list[Message]) -> list[ExtractedItem]:
        now = time.time()
        out: list[ExtractedItem] = []
        for m in messages:
            content = m.content.strip()
            if len(content) < 2:
                continue
            score = 0.3
            reasons: list[str] = []

            if m.is_at_me:
                score += 0.35
                reasons.append("@我")
            if any(w in content for w in _DUE_WORDS):
                score += 0.2
                reasons.append("含时效词")
            if any(w in content for w in _ACTION_WORDS):
                score += 0.15
                reasons.append("含行动词")
            if any(w in content for w in _EVENT_WORDS):
                score += 0.1
                reasons.append("疑似活动")

            score = min(score, 1.0)
            if score < 0.4:
                continue  # 噪音，丢弃

            if "?" in content or "？" in content or content.endswith("吗"):
                item_type = "question"
            elif any(w in content for w in _EVENT_WORDS):
                item_type = "event"
            else:
                item_type = "todo"

            out.append(ExtractedItem(
                type=item_type,
                text=content[:40],
                who=m.sender,
                chat=m.chat,
                importance=round(score, 2),
                reason="、".join(reasons) or "关键词命中",
                due=_guess_due(content),
                source_msg=m.uid,
                created_at=now,
            ))
        return out


def _guess_due(content: str) -> str | None:
    """从文本里粗略抓日期/时间，抓不到返回 None。"""
    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]", content)
    if m:
        return f"{time.strftime('%Y')}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    m = re.search(r"(\d{1,2})[:：](\d{2})", content)
    if m:
        return f"今天 {int(m.group(1)):02d}:{m.group(2)}"
    if "明天" in content:
        return "明天"
    if "今天" in content or "今晚" in content:
        return "今天"
    return None


def build_analyzer(cfg: dict):
    """按配置选择分析器。dryrun 或没配 key 时走规则兜底。"""
    if cfg.get("dryrun") or not cfg["llm"]["api_key"]:
        return HeuristicAnalyzer()
    return DeepSeekAnalyzer(cfg)
