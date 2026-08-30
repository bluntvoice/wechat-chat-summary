# AGENTS.md

## 仓库定位

- `group_insight/` 是当前主业务包。
- 微信消息统一通过 `WeChatDataAnalysis` 本地 REST API 读取，默认地址为
  `http://127.0.0.1:10392`。
- 不要恢复对旧 `wechat-decrypt` Python 模块、数据库文件或私有函数的运行依赖。
- `pywechat/` 仅用于可选的 Windows 微信 UI 自动发送，不属于数据读取链路。

## 关键模块

- `group_insight/wechat_data_api.py`：会话解析、联系人兜底和消息分页。
- `group_insight/fetching.py`：把 API 消息转换为 `StructuredMessage`。
- `group_insight/stats.py`：本地统计。
- `group_insight/chunking.py`：消息分片。
- `group_insight/llm.py`、`pipeline.py`：AI API 与 map/reduce/final 流程。
- `group_insight/rendering.py`：JSON 载荷与 HTML 报告。
- `group_insight/transport.py`：可选 PNG 导出和 RPA 发送。
- `group_insight/cli.py`：命令行装配。

## 配置与隐私

- 只读取仓库根目录 `.env`；不得提交 `.env`、令牌、消息快照或报告。
- 数据源配置：`WECHAT_DATA_API_URL`、`WECHAT_DATA_ACCOUNT`、
  `WECHAT_DATA_SOURCE`。
- 独立输出根目录：`GROUP_INSIGHT_OUTPUT_ROOT`。
- 默认输出不得放在源码仓库或 `WeChatDataAnalysis` 安装目录中。
- 报告文件名必须包含 `YYYY-MM-DD`，默认格式为
  `<对话名>_YYYY-MM-DD_群聊总结.<ext>`。

## 开发规则

- Windows 文件读写统一使用 UTF-8。
- 根目录 Python 环境优先使用 `uv`；不要把环境或缓存下载到 C 盘。
- 核心依赖见 `requirements.txt`；RPA 依赖单独见 `requirements-rpa.txt`。
- 数据源和分析提供方必须解耦。后续 AI 分析支持两种模式：
  直接调用可配置 AI API，或通过 MCP 把分析任务交给外部 AI 客户端。
- 缺少群聊、时间范围、本地 API 或关键配置时应 fail-fast，不添加静默兜底。
- 调试优先使用 `--dry-run --no-image --no-send-after-run`。
- 修改后至少运行：
  `python -m unittest discover -s tests -v`、`python -m compileall -q group_insight tests`
  和 `git diff --check`。

## PRD 与开发执行规范

### PRD 优先级

- 根目录 `PRD.md` 是本项目长期维护的产品需求基线。
- 开发前必须阅读 `PRD.md`、本文件、`README.md` 以及与当前任务直接相关的代码和文档。
- 如果当前实现与 PRD 不一致、新需求与 PRD 冲突，或技术实现需要改变已确认的产品行为，不得擅自修改需求、降低要求或迁就现有代码；应先向用户说明并确认。

### 有疑问必须先确认

- 需求、交互、数据结构、技术方案或产品边界存在歧义时，不得自行决定并立即实施。
- 必须先用明确的 A/B/C 等选项说明各方案的优缺点、影响和建议，等待用户明确确认后再执行。
- 不使用开放式问题要求用户重新描述已经可以形成选项的需求；应给出推荐方案及理由。

### 任务范围与现有实现

- 用户只要求修改文档时，不得顺带修改代码；用户只要求某项功能时，不得顺带进行无关的大规模重构。
- 认为额外修改确有必要时，必须先说明原因、影响和范围并取得用户确认。
- `group_insight` 已有的数据读取、统计、AI 分析和报告渲染能力应优先复用和整理；除非有明确技术理由并经过确认，不得为桌面端或其他功能重复实现一套分析核心。

### 文档同步与 PRD 修改

- 每次功能开发完成后，检查并按实际状态同步 `PRD.md`、`README.md`、`group_insight/README.md`、`AGENTS.md`、`.env.example`、测试说明和发布相关文档。
- 不得把“计划实现”写成“已实现”；PRD 中的状态必须真实反映当前代码。
- 技术说明、实现状态等非产品决策内容可按实际情况维护。
- 涉及产品行为、功能删除、需求降级、交互变化或数据保存方式等实质需求变更时，必须先取得用户确认，不得静默改写 PRD。

### 开发前后基本流程

开发任务开始前：

1. 阅读 PRD、相关文档和代码，并判断当前实现状态；
2. 发现疑问时先提出带推荐意见的选项；
3. 等待用户明确确认（如“开始执行”或“执行”）后再修改代码。

开发任务完成后：

1. 汇报已完成内容和修改文件；
2. 汇报测试结果；
3. 说明尚未完成项和新的待确认事项；
4. 检查并说明相关文档是否已经同步。

## 当前迭代边界

- 已实现：真实数据 API 接入、结构化统计、独立输出与日期命名。
- 后续迭代：长图视觉重构、每日活跃热力图、AI API/MCP 双分析模式、
  SQLite 历史中心、全文搜索和 Windows 桌面端。
