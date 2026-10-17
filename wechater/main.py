"""调度入口：实时轮询 + 每日摘要。

用法：
  python -m wechater.main --once                 # 跑一轮采集→分析→推送，退出
  python -m wechater.main                        # 常驻：定时轮询 + 每日摘要
  python -m wechater.main --once --config config.dryrun.yaml   # 离线演示
  python -m wechater.main --digest               # 立刻生成并推送一次摘要
"""
from __future__ import annotations

import argparse
import sys
import traceback

from .analyzer import build_analyzer
from .collector import build_collector
from .config import load_config, resolve_path
from .digest import run_digest
from .models import Message
from .notifier import build_notifier
from .store import Store


def _setup_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _passes_whitelist(cfg: dict, msg: Message) -> bool:
    """白名单 + 群关键词前置过滤——控噪、控成本的第一道闸。"""
    wl = cfg["wechat"]["whitelist"]
    chats = wl.get("chats") or []
    if chats and msg.chat not in chats:
        return False
    if msg.is_group and wl.get("require_at_me_in_group") and not msg.is_at_me:
        return False
    keywords = wl.get("keywords") or []
    if msg.is_group and keywords:
        if not (msg.is_at_me or any(k in msg.content for k in keywords)):
            return False
    return True


def run_cycle(cfg: dict, store: Store, collector, analyzer, notifier) -> dict:
    """一轮：采集 → 去重 → 白名单 → 分析 → 入库 → 分级推送。"""
    messages = collector.poll()
    fresh = store.filter_new(messages)
    if not fresh:
        return {"polled": len(messages), "new": 0, "kept": 0, "items": 0, "pushed": 0}

    kept = [m for m in fresh if _passes_whitelist(cfg, m)]

    items_total = pushed = 0
    limit = max(1, int(cfg["llm"]["max_msgs_per_call"]))
    threshold = float(cfg["llm"]["min_importance_push"])
    for i in range(0, len(kept), limit):
        chunk = kept[i:i + limit]
        try:
            items = analyzer.analyze(chunk)
        except Exception as exc:
            print(f"[analyzer] 分析失败，跳过该批次：{exc}")
            continue
        for item in items:
            items_total += 1
            if store.add_item(item) and item.importance >= threshold:
                try:
                    notifier.push(item)
                    pushed += 1
                except Exception as exc:
                    print(f"[notifier] 推送失败：{exc}")

    store.mark_seen(fresh)
    return {"polled": len(messages), "new": len(fresh), "kept": len(kept),
            "items": items_total, "pushed": pushed}


def build_all(cfg: dict):
    store = Store(resolve_path(cfg, cfg["store"]["db_path"]))
    collector = build_collector(cfg)
    analyzer = build_analyzer(cfg)
    notifier = build_notifier(cfg)
    return store, collector, analyzer, notifier


def main(argv: list[str] | None = None) -> int:
    _setup_stdout()
    parser = argparse.ArgumentParser(description="WeChater 微信聊天助手")
    parser.add_argument("--config", default=None, help="配置文件路径")
    parser.add_argument("--once", action="store_true", help="只跑一轮后退出")
    parser.add_argument("--digest", action="store_true", help="立即生成一次每日摘要")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    mode = "DRYRUN" if cfg.get("dryrun") else "LIVE"
    print(f"[WeChater] 模式={mode} 采集={cfg['wechat']['collector']} "
          f"配置={cfg['_config_path']}")

    try:
        store, collector, analyzer, notifier = build_all(cfg)
    except Exception as exc:
        print(f"[WeChater] 初始化失败：{exc}")
        return 2

    if args.once or args.digest:
        if args.once:
            stats = run_cycle(cfg, store, collector, analyzer, notifier)
            print(f"[轮询] 读取 {stats['polled']} · 新 {stats['new']} · "
                  f"入白名单 {stats['kept']} · 抽取 {stats['items']} · 推送 {stats['pushed']}")
        if args.digest or (args.once and cfg["schedule"]["digest_enabled"]):
            print("\n[每日摘要]")
            run_digest(cfg, store, notifier)
        store.close()
        return 0

    # 常驻模式
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    scheduler = BlockingScheduler()
    interval = int(cfg["schedule"]["poll_interval"])

    def _job():
        try:
            stats = run_cycle(cfg, store, collector, analyzer, notifier)
            if stats["new"]:
                print(f"[轮询 {stats}]")
        except Exception:
            traceback.print_exc()

    scheduler.add_job(_job, IntervalTrigger(seconds=interval), id="poll",
                      max_instances=1, coalesce=True)

    if cfg["schedule"]["digest_enabled"]:
        hh, mm = cfg["schedule"]["digest_time"].split(":")
        scheduler.add_job(lambda: run_digest(cfg, store, notifier),
                          CronTrigger(hour=int(hh), minute=int(mm)), id="digest")

    print(f"[WeChater] 启动调度：每 {interval}s 轮询；"
          f"每日 {cfg['schedule']['digest_time']} 摘要。Ctrl+C 退出。")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("\n[WeChater] 停止。")
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
