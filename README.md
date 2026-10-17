# WeChater 微信聊天助手

从微信聊天里**捞出重要信息**（待办 / 会议 / 待回答的问题 / 承诺），自动**规划日程**，
并按重要度**分级推送到 Android 手机和电脑**——重要的打断式强提醒，不重要的静默折叠。

```
微信 ──采集──▶ 白名单过滤 ──DeepSeek 抽取+打分──▶ 入库(SQLite)
                                   │
                                   ├─ importance ≥ 0.5 ──▶ ntfy 分级推送（手机/电脑）
                                   └─ 全部 ─────────────▶ 每日摘要（早 8 点）
```

---

## ⚠️ 先读：关于微信接入的现实（2026）

**解密本地数据库的老方案已经不能用了。** 2025-10-20 微信官方集中发函清理了
`ChatLog`、`PyWxDump`（desc 只剩"删库"）等工具，`WeChatFerry` 亦已归档。

因此本项目**不依赖任何已下架的库**，采集层设计成可插拔，提供三条路线：

| 后端 | 说明 | 风险 |
|---|---|---|
| `wxauto` | UIAutomation 驱动**官方 PC 微信客户端**读消息（只读、不发送） | 相对最低（不注入、不解密） |
| `file` | 从任意**本地记录文件**读（自己导出/其它工具导出/手工整理） | 无 |
| `http` | 轮询一个**自建端点** | 取决于你的实现 |

> 所有非官方接入方式都可能触碰微信用户协议。**建议用专门的小号、保持只读、别做群发**，
> 并自行评估合规风险。本项目仅供个人学习。

---

## 快速开始（离线，零配置）

不联网、不装微信、不花钱，用示例数据跑通全链路：

```bash
pip install PyYAML
python -m wechater.main --once --config config.dryrun.yaml
```

你会看到：10 条消息 → 白名单滤到 7 条 → 抽取 7 条待办 → 6 条按重要度分级"推送"，
最后生成一份每日日程。再跑一次会显示 `新 0`（去重生效）。

---

## 生产接入（三步）

### 1. 采集：选一条路线

**A. `wxauto`（推荐，Windows）**
```bash
pip install wxauto          # 需 Windows + 登录着的 PC 微信客户端
```
```yaml
wechat:
  collector: wxauto
  wxauto: { interval: 60 }
  whitelist: { chats: ["产品群", "老板"] }   # 只盯这些，务必收紧
```

**B. `file`（最省心）** —— 把聊天记录整理成 JSONL，每行一条：
```json
{"chat":"产品群","sender":"李经理","content":"周五 3 点复盘会 @我","time":"2026-10-16 09:12","is_group":true,"is_at_me":true,"id":"g1"}
```
```yaml
wechat: { collector: file, file_path: data/messages.jsonl }
```

**C. `http`** —— 自己搭个返回 `[{chat,sender,content,time}, ...]` 的端点。

### 2. 分析：配 DeepSeek

```bash
export DEEPSEEK_API_KEY=sk-xxxx        # Windows: set DEEPSEEK_API_KEY=sk-xxxx
```
`config.yaml` 里 `llm.api_key` 留 `${DEEPSEEK_API_KEY}` 即可自动读取。
没配 key 时会自动退回**规则打分**（离线可用，效果次之）。

### 3. 推送：配 ntfy

手机装 **ntfy** App，订阅一个别人猜不到的 topic；电脑装 ntfy 桌面客户端订阅同一个：
```yaml
notify:
  server: https://ntfy.sh     # 国内建议自建 ntfy，换成自己的地址更快更稳
  topic: my-secret-topic-8f3a
```

#### "强调"与"屏蔽"是怎么落地的
important 分档 → ntfy `priority`，Android 可为每个 priority 绑不同铃声/震动/免打扰：

```
importance ≥ 0.8   urgent  priority 5   打断式强提醒
     0.5 – 0.8     normal  priority 3   普通提示
     < 0.5         ———     不实时推   只进每日摘要（避免打扰）
```

想更激进地把中等信息也静默推过去，就调低 `llm.min_importance_push`。

---

## 运行

```bash
python -m wechater.main                          # 常驻：定时轮询 + 每日摘要
python -m wechater.main --once                   # 只跑一轮(采集→分析→推送)
python -m wechater.main --digest                  # 立刻生成一次每日摘要
python -m wechater.main --config my.yaml          # 指定配置
```

Windows 开机自启可用「任务计划程序」触发 `python -m wechater.main`。

---

## 配置速查（`config.example.yaml`）

| 键 | 作用 |
|---|---|
| `wechat.collector` | `file` / `wxauto` / `http` |
| `wechat.whitelist.chats` | 只处理这些会话（留空=全部，建议收紧） |
| `wechat.whitelist.require_at_me_in_group` | 群消息必须 @我 才处理 |
| `wechat.whitelist.keywords` | 群消息的关键词闸（命中或 @我 才进分析，控噪控成本） |
| `llm.api_key` | DeepSeek key，建议走环境变量 |
| `llm.min_importance_push` | 低于此分只入库不实时推 |
| `llm.max_msgs_per_call` | 每次送模型的消息上限（控成本） |
| `notify.topic` | ntfy 主题，务必改成猜不到的 |
| `notify.levels` | 分档 → priority 映射 |
| `schedule.poll_interval` | 轮询间隔（秒） |
| `schedule.digest_time` | 每日摘要时间 |
| `dryrun` | `true` = 规则分析 + 控制台输出，完全不联网 |

---

## 目录结构

```
WeChater/
  config.example.yaml     配置模板
  config.dryrun.yaml      离线演示配置
  prompts/extract.md      LLM 抽取提示词
  wechater/
    models.py             Message / ExtractedItem
    config.py             配置加载（含 ${ENV} 展开）
    collector.py          采集层（file / wxauto / http）
    analyzer.py           DeepSeek 抽取打分 + 规则兜底
    notifier.py           ntfy 分级推送 + 控制台输出
    store.py              SQLite 去重与待办
    digest.py             每日摘要
    main.py               调度入口
  data/
    sample_messages.jsonl 示例数据
    wechater.db           运行时生成
```

---

## 隐私提示

启用 LLM 后会**把命中白名单的消息发往 DeepSeek**。若含敏感内容，可把
`wechat.whitelist.keywords` 收紧（本地先过滤），或改用 `dryrun` 的规则分析（不出网）。
