# group_insight

`group_insight` 通过 WeChatDataAnalysis 本地 API 读取微信消息、构造 LLM 分析流程、生成 JSON/HTML/PNG，并在需要时通过 PC 微信 UI 自动化发送报表图片。

默认从仓库根目录执行下面的命令。

## 配置 `.env`

复制样例文件：

```powershell
Copy-Item .env.example .env
```

至少填写 DeepSeek 的 Key：

```dotenv
DEEPSEEK_API_KEY=<API_KEY_PLACEHOLDER>
DEEPSEEK_MODEL=deepseek-v4-flash
THINKING=false
THINKING_LEVEL=high
DEEPSEEK_API_URL=https://api.deepseek.com/chat/completions
WECHAT_DATA_API_URL=http://127.0.0.1:10392
GROUP_INSIGHT_OUTPUT_ROOT=<用户选择的独立报告目录>
```

`.env` 是本机私有文件，不要提交。当前文档口径只支持仓库根目录 `.env` 作为本地配置入口；已经存在于系统环境变量里的同名 Key 不会被覆盖。

验证 `.env` 是否能被日报脚本读到：

```powershell
.\.venv\Scripts\python.exe -c "import os; import group_insight.settings; print(bool(os.environ.get('DEEPSEEK_API_KEY')))"
```

输出 `True` 表示 DeepSeek Key 已进入当前进程环境。

其中：

- `THINKING=false` 表示默认走非思考模式。
- `THINKING_LEVEL` 仅在 `THINKING=true` 时生效，当前支持 `high` / `max`。

## 运行原则

当前推荐用法强调显式配置和 fail-fast：

- 群聊、时间窗、API Key、发送目标等关键输入缺失时，优先直接修正参数或仓库根目录 `.env`。
- 主流程固定走 `map -> reduce -> final`，不再暴露 `direct_range` / `topic-first` 这类分支模式。
- LLM 返回 JSON 自动修复按显式开关理解，默认关闭；需要时显式传 `--allow-json-repair`。
- DeepSeek 默认显式传 `max_tokens` 预算，避免 JSON 输出链路在思考模式或异常情况下失控扩张；如需改预算，优先从命令行参数或代码常量调整。
- LLM 花费改为按任务前后余额快照对比，不再在每次请求后动态打印 usage 计费估算。
- 文档只保留当前推荐参数，不再展开旧兼容入口。

## 微信数据准备

数据库读取由已安装的 `WeChatDataAnalysis` 提供。第一次运行前确认：

- Windows PC 微信已登录；`WeChatDataAnalysis` 已完成账号数据加载。
- 本地服务可访问，默认地址为 `http://127.0.0.1:10392`。
- 多账号时可在 `.env` 中设置 `WECHAT_DATA_ACCOUNT`；通常留空即可。
- 不需要初始化或运行旧 `wechat-decrypt` 子模块。

## 生成日报

默认运行：

```powershell
.\.venv\Scripts\python.exe -m group_insight
```

指定群聊和时间窗：

```powershell
.\.venv\Scripts\python.exe -m group_insight --chat "群聊完整名称" --start "2026-04-14 23:59" --end "2026-04-15 23:59"
```

只验证读取、分片、渲染链路，不调用模型、不发送：

```powershell
.\.venv\Scripts\python.exe -m group_insight --dry-run --no-image --no-send-after-run
```

生成 HTML 但跳过 PNG：

```powershell
.\.venv\Scripts\python.exe -m group_insight --no-image --no-send-after-run
```

`python -m group_insight` 会在发现仓库 `.venv` 存在时自动切换到 `.venv\Scripts\python.exe`。如果确实要使用当前解释器，可以临时设置：

```powershell
$env:GROUP_INSIGHT_NO_VENV_REDIRECT = "1"
```

输出目录默认在独立报告根目录，并将图片与分析数据分开：

```text
<报告根目录>\<对话名>\
  导出图\YYYY\MM\YYYY-MM-DD报告.png
  报告数据\YYYY-MM-DD报告数据\
    <对话名>_YYYY-MM-DD_群聊总结.json
    <对话名>_YYYY-MM-DD_群聊总结.html
```

每次运行会生成 JSON、HTML、PNG 和派生阶段缓存。同日重复生成使用 `_v2`、
`_v3` 递增版本；多日总结使用 `YYYY-MM-DD_至_YYYY-MM-DD`。map 原始消息输入只在
内存中参与分析，不会写入报告目录。PNG 默认写入 300 DPI 元数据，可通过
`--image-dpi` 调整。

v0.2.2 继续使用向后兼容的统一 `report schema 2.1`：PNG 与 HTML 呈现相同的完整信息，按
“今日总览 → 今日速览 → 今日主要话题 → AI 今日观察 → 今日活跃情况 → 报告结尾”组织；
同一语义话题可合并多个不连续时间区间，结论、行动、问题、风险、引用和资源嵌入对应话题。
无法可靠关联的补充信息进入 AI 今日观察，未归类资源保留为其他资源；JSON 与 SQLite 历史索引
保存同一套结构。链接卡片、普通
URL 与文件元数据会先确定性提取，再由 AI 按当日主题归类；模型遗漏或不可靠归类会本地回退
到相近主题或“其他 / 未归类”。红包消息、疑似红包领取页和红包素材链接在提取阶段过滤。
成员显示名按群昵称、微信网名、账号 ID 的顺序解析，并排除本机联系人备注；同一显示名同时
对应两个及以上不同账号时会判定为上游名称碰撞，忽略该显示名并分别回退到微信网名或账号
ID。群关键词会合并重复短语，并移除与高频长词重复的二字切片。

桌面端生成后的人工屏蔽由 `redaction.py` 在本机完成：它读取既有 schema 2.x JSON，将选中
条目替换为只含所属时间和屏蔽提示的占位对象，再通过同一渲染器生成递增新版本。这个流程
不读取聊天、不调用 AI，被屏蔽正文不会进入新版本 JSON、HTML、PNG、SQLite 模块内容或 FTS。
“轻松插曲”已从对外报告结构和渲染中移除，内部 tone 分类仍用于严肃结论过滤。

桌面端可通过 `--progress-file <path>` 读取原子写入的阶段进度 JSON，并通过
`--result-file <path>` 读取版本化的结构化生成结果，不依赖 CLI 中文日志。历史库默认位于
Tauri 解析的 Windows 用户数据目录，只保存报告结构、独立每日统计、资源与文件路径，不复制
完整聊天正文。SQLite database schema version 与 Report Schema 2.1 分开维护。

v0.2.1 桌面端的“定时生成当日报告”使用软件内置定时器，可随时关闭；软件关闭时不执行，
并与本文件后文供 CLI/RPA 场景使用的 Windows 任务计划注册模块相互独立。

## RPA 发送前预热

自动发送 PNG 依赖 Windows 桌面会话、微信主窗口和 UI Automation 控件树。定时任务或首次启动前，建议先做一次交互式预热。

1. 关闭微信。
2. 打开讲述人模式，保持至少 5 分钟。
3. 打开微信，测试是否可获取相关控件树。

预热成功后，建议再打开一次发送目标会话，确认名称能被自动化库找到：

```powershell
$env:PYTHONPATH = "$PWD\pywechat;$env:PYTHONPATH"
@'
from pyweixin.WeChatTools import Navigator

target = "文件传输助手"
Navigator.open_dialog_window(friend=target, is_maximize=False, search_pages=0)
print("RPA target opened:", target)
'@ | python -
```

如果目标群不在最近会话列表里，可以把 `search_pages=0` 保持为顶部搜索，或先手动在微信里打开目标会话。

执行一次真实发送测试：

```powershell
.\.venv\Scripts\python.exe -m group_insight --dry-run --send-after-run --send-target "文件传输助手"
```

常见问题：

- 报 `微信未运行`：先手动启动并登录 PC 微信，再运行预热。
- 报找不到窗口或控件：确认没有锁屏、远程桌面没有断开、微信没有最小化到托盘。
- 报找不到会话：确认 `--send-target` 是微信里可搜索到的完整备注、好友名或群名。
- 定时任务能生成报表但不能发送：任务必须在用户已登录的交互式桌面会话中运行，不能依赖无人登录的后台会话。

## 自动发送

生成后发送到默认目标：

```powershell
.\.venv\Scripts\python.exe -m group_insight --send-after-run
```

指定一个或多个目标：

```powershell
.\.venv\Scripts\python.exe -m group_insight --send-after-run --send-target "文件传输助手" --send-target "群聊完整名称"
```

## 任务计划

注册每日任务：

```powershell
python -m group_insight.scheduler --time 23:50
```

调度模块默认把任务动作注册为 `python -m group_insight`，并优先把 Python 可执行文件指向仓库 `.venv\Scripts\python.exe`。如果任务曾经用全局 Python 注册过，重新运行一次注册脚本即可更新。

任务计划文档按模块入口收口，不再说明旧的脚本路径兼容入口；缺少模块名、Python 路径或交互式桌面条件时，优先直接修正配置并重新注册。

先预览不写入任务计划：

```powershell
python -m group_insight.scheduler --time 23:50 --args "--no-image" --dry-run
```

传递日报参数：

```powershell
python -m group_insight.scheduler --time 23:50 --args "--chat 群聊完整名称 --send-after-run"
```

使用最高权限注册：

```powershell
python -m group_insight.scheduler --time 23:50 --highest
```

任务计划维护命令：

```powershell
# 查看任务是否存在
Get-ScheduledTask -TaskName GroupInsightReportDaily -ErrorAction SilentlyContinue

# 查看上次运行、下次运行、结果码
Get-ScheduledTaskInfo -TaskName GroupInsightReportDaily

# 查看详细信息
schtasks /Query /TN GroupInsightReportDaily /V /FO LIST

# 立刻手动运行一次
Start-ScheduledTask -TaskName GroupInsightReportDaily

# 禁用任务
Disable-ScheduledTask -TaskName GroupInsightReportDaily

# 重新启用任务
Enable-ScheduledTask -TaskName GroupInsightReportDaily

# 删除任务
Unregister-ScheduledTask -TaskName GroupInsightReportDaily -Confirm:$false
```

重新运行 `python -m group_insight.scheduler` 会 create-or-update 同名任务；修改任务名等于注册新任务，旧任务需要单独删除。

## 常见依赖问题

如果看到下面的错误：

```text
ImportError: cannot import name 'Sentinel' from 'typing_extensions'
```

通常说明当前使用的是全局 Python，里面的 `typing_extensions` 太旧，和 `mcp/pydantic_core` 不兼容。优先使用仓库 `.venv`：

```powershell
.\.venv\Scripts\python.exe -m group_insight --dry-run --no-image --no-send-after-run
```

也可以重新安装根目录依赖：

```powershell
uv pip install -r requirements.txt
```

如果必须修全局 Python：

```powershell
python -m pip install -U typing-extensions
```

## 目录速查

- `group_insight/__main__.py`：`python -m group_insight` 模块入口。
- `group_insight/runtime.py`：`.venv` 重定向等运行时辅助逻辑。
- `group_insight/cli.py`：命令行参数和主流程装配。
- `group_insight/settings.py`：默认值、路径、`.env` 加载和 MCP 懒加载。
- `group_insight/models.py`：领域数据模型（`StructuredMessage`、`MessageChunk` 等）。
- `group_insight/common.py`：跨模块通用工具（文本归一化、slugify、主题相似度、文件读写等）。
- `group_insight/conversation.py`：消息清洗、发言人归一和消息分类。
- `group_insight/fetching.py`：微信消息拉取与成员身份解析。
- `group_insight/rich_content.py`：富媒体消息解析（appmsg XML、链接卡片、合并聊天、回复、拍一拍、红包等）。
- `group_insight/chunking.py`：消息分片策略（数量、字符数、时间跨度、话题连续性）与 prompt 载荷构造。
- `group_insight/stats.py`：本地统计与词云（发言排行、互动榜单、时段分布、词频）。
- `group_insight/llm.py`：LLM 协议、DeepSeek 客户端、余额快照和 prompt 构造。
- `group_insight/pipeline.py`：固定 `map/reduce/final` 分析流水线。
- `group_insight/report_model.py`：最终日报结构修复、去重和 fallback 生成。
- `group_insight/report_schema.py`：统一 report schema 2.1 与 2.0/旧报告只读适配。
- `group_insight/resources.py`：URL、链接卡片、文件资源提取与主题归类。
- `group_insight/redaction.py`：报告条目枚举、无正文屏蔽占位和新版本文档生成。
- `group_insight/history_store.py`：SQLite 历史底座、模块表、日统计和 FTS 索引。
- `group_insight/progress.py`：跨进程阶段进度文件。
- `group_insight/rendering.py`：信息量一致的移动端 HTML 与 PNG 完整长图渲染；视觉参考上游渐变背景和圆形序号讨论脉络。
- `group_insight/transport.py`：PNG 导出和 RPA 发送。
- `group_insight/report_paths.py`：报告目录分层、日期标签和历史版本分配。
- `group_insight/desktop_bridge.py`：桌面端 JSONL 桥接命令。
- `group_insight/desktop_config.py`：桌面端本机配置和私有 Key 存储。
- `group_insight/alerts.py`：异常告警邮件发送（可选）。
- `group_insight/cache_utils.py`：map/reduce/final 阶段缓存工具。
- `group_insight/scheduler.py`：Windows 任务计划注册模块。
