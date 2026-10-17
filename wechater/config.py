"""配置加载：合并默认值 + YAML + 环境变量展开。"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS: dict[str, Any] = {
    "wechat": {
        "collector": "file",
        "file_path": "data/messages.jsonl",
        "wxauto": {"interval": 60},
        "http": {"url": ""},
        "whitelist": {
            "chats": [],
            "require_at_me_in_group": False,
            "keywords": ["截止", "deadline", "尽快", "记得", "麻烦", "请",
                         "帮我", "安排", "明天", "今天", "会议", "@我"],
        },
    },
    "llm": {
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com",
        "api_key": "",
        "model": "deepseek-chat",
        "min_importance_push": 0.5,
        "max_msgs_per_call": 40,
    },
    "notify": {
        "provider": "ntfy",
        "server": "https://ntfy.sh",
        "topic": "wechater",
        "levels": {"urgent": 5, "normal": 3, "silent": 2},
    },
    "schedule": {
        "poll_interval": 120,
        "digest_time": "08:00",
        "digest_enabled": True,
    },
    "store": {"db_path": "data/wechater.db"},
    "dryrun": False,
}

_ENV_RE = re.compile(r"\$\{(\w+)\}")


def _expand_env(obj: Any) -> Any:
    if isinstance(obj, str):
        return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), ""), obj)
    if isinstance(obj, dict):
        return {k: _expand_env(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env(v) for v in obj]
    return obj


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, val in (override or {}).items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def load_config(path: str | Path | None = None) -> dict:
    """读取配置；缺省读 ROOT/config.yaml，文件不存在则全用默认值。"""
    cfg_path = Path(path) if path else ROOT / "config.yaml"
    raw: dict = {}
    if cfg_path.exists():
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    cfg = _deep_merge(DEFAULTS, raw)
    cfg = _expand_env(cfg)
    cfg["_config_path"] = str(cfg_path)
    cfg["_root"] = str(ROOT)
    return cfg


def resolve_path(cfg: dict, relative: str) -> Path:
    """把配置里的相对路径解析到项目根目录下。"""
    p = Path(relative)
    return p if p.is_absolute() else Path(cfg["_root"]) / p
