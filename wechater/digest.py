"""每日摘要：把当天入库的待办汇总成一份结构化清单并推送。"""
from __future__ import annotations

import time

_TYPE_LABEL = {
    "todo": "待办",
    "event": "事件",
    "question": "待回答",
    "commitment": "承诺",
}


def build_digest(store, day: str | None = None) -> str:
    day = day or time.strftime("%Y-%m-%d")
    rows = store.items_for_day(day)
    if not rows:
        return f"# {day} 日程\n\n今天没有需要关注的条目。"

    lines = [f"# {day} 日程", ""]
    urgent = [r for r in rows if r["importance"] >= 0.8]
    if urgent:
        lines.append("## 紧急")
        for r in urgent:
            lines.append(_fmt(r))
        lines.append("")

    rest = [r for r in rows if r["importance"] < 0.8]
    if rest:
        lines.append("## 其它")
        for r in rest:
            lines.append(_fmt(r))

    lines.append("")
    lines.append(f"共 {len(rows)} 条（紧急 {len(urgent)} 条）")
    return "\n".join(lines)


def _fmt(r) -> str:
    label = _TYPE_LABEL.get(r["type"], r["type"])
    due = f" ⏰{r['due']}" if r["due"] else ""
    who = f" @{r['who']}" if r["who"] else ""
    return f"- [{label}] {r['text']}{due}{who}  — {r['chat']}"


def run_digest(cfg: dict, store, notifier) -> str:
    text = build_digest(store)
    notifier.push_text(
        title=f"WeChater 每日日程 · {time.strftime('%m-%d')}",
        body=text,
        priority=3,
        tags=["calendar"],
    )
    return text
