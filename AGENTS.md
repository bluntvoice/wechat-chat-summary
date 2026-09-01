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
- `group_insight/report_paths.py`：导出图/报告数据分层与版本保留。
- `group_insight/desktop_bridge.py`：桌面端与 Python 核心的 UTF-8 JSONL 桥接。
- `group_insight/desktop_config.py`：桌面端本机设置与私有密钥。
- `group_insight/cli.py`：命令行装配。
- `desktop/`：Tauri 2 + React/TypeScript Windows 桌面端。

## 配置与隐私

- CLI 读取仓库根目录 `.env`；桌面端普通设置、Key、SQLite 与任务进度必须使用 Tauri 解析的
  Windows App Local Data 目录，不得新增个人盘符或用户名硬编码。
- 不得提交 `.env`、令牌、消息快照、桌面私有配置或报告。
- 数据源配置：`WECHAT_DATA_API_URL`、`WECHAT_DATA_ACCOUNT`、
  `WECHAT_DATA_SOURCE`。
- CLI 独立输出根目录：`GROUP_INSIGHT_OUTPUT_ROOT`；未配置时必须 fail-fast。桌面端新用户导出
  目录默认为空，首次生成前要求选择并保存，不得回退到源码、安装目录或开发机路径。
- 默认输出不得放在源码仓库或 `WeChatDataAnalysis` 安装目录中。
- 未来安装器/升级器只允许替换软件根目录的 `program`；不得删除或覆盖 `data`、
  软件根目录下用户选择的 `reports`，或任何其他用户自定义报告目录。
- PNG 按 `<群聊>\导出图\YYYY\MM\YYYY-MM-DD报告.png` 保存；HTML/JSON 与派生
  分析数据按 `<群聊>\报告数据\YYYY-MM-DD报告数据` 保存。
- 同日重复生成必须使用 `_v2`、`_v3` 递增版本，不得覆盖旧文件。
- map 原始消息输入不得写入报告目录；统计和派生分析结果允许保存。
- 旧固定数据目录只允许执行“校验复制且保留源目录”的兼容迁移；目标已有配置时不得覆盖。

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
- 修改桌面端后还需运行 `npm run build` 与 `cargo check`；缓存位置可配置，但不得依赖个人盘符或用户名。

## 版本、构建与发布规则

- `desktop/package.json` 是桌面版本的人工输入源；`package-lock.json`、`tauri.conf.json`、
  `Cargo.toml` 与 `Cargo.lock` 必须通过 `desktop/scripts/version.mjs` 同步。CI 和打包前必须
  执行版本一致性检查，冲突时 fail-fast。
- Windows 安装包必须复用 `desktop/scripts/build-windows-test-package.ps1` 和现有 sidecar
  架构，不得另建依赖本机绝对路径、API Key、微信数据或 WeChatDataAnalysis 实例的打包链路。
- 测试安装包只能通过 `build-test.yml` 或脚本的 `Test` 模式生成，不创建 Tag 和 GitHub Release。
- 正式发布只能人工触发 `release.yml`。全部测试与安装包构建成功后，工作流才允许提交版本文件、
  推送默认分支与 Tag；Stable 使用 `x.y.z`，Prerelease 使用含后缀的 SemVer 并必须标为 Prerelease。
- 发布说明必须包含“版本亮点”，并同步写入 `CHANGELOG.md`。正式 Release 前必须复核上游许可、
  用户可见变化、测试结果、安装包内容和发布通道；不得覆盖既有 Tag。
- GitHub Actions 构建不得读取或打包 `.env`、`secrets.env`、本地配置、聊天数据、SQLite、
  用户报告或安装包之外的本地运行时数据。

## 历史基础与桌面桥接规则

- SQLite 结构升级必须追加显式 migration；每步在事务内幂等执行，成功后才更新
  `PRAGMA user_version`，失败不得静默吞掉或删除历史数据。Database Schema Version 与
  Report Schema 2.2 是两个概念。
- 群聊每日统计以 `chat_id + date` 独立保存，可在没有报告的日期存在；报告可以写入或引用统计，
  统计不得依赖非空 `report_id`。不得为填满热力图主动扫描全年聊天。
- 中文历史搜索基础采用 SQLite FTS5 + 本地子串回退；不得仅因 FTS 表存在就宣称中文子词可靠，
  必须覆盖群名、成员、话题、行动、文件、资源、URL 和中英混合测试。
- 历史 UI 模块必须在查询层从 Report Schema 2.2 派生；结论、行动、开放问题、风险、原话和资源
  取自 `content.topics[*]` 的嵌套字段及资源表，不得为历史页面改回旧顶层结构或重复展示内容。
- “已总结”唯一事实来源是 SQLite 中该 `chat_id` 至少一份有效报告。`settings.summarized_chat_ids`
  只作为桥接缓存，每次生成、定时生成、导入或显式刷新后都应由历史库重建；不得按群名匹配。
- 生成页只对当前 WeChatDataAnalysis 返回的群做置顶和筛选；历史中心必须继续展示数据库中的旧群。
- CLI 可保留人类可读日志，但桌面端生成结果必须读取版本化结构化协议，不得解析中文 stdout 标签。
- `open_questions` 与 decisions/action_items/risk_flags 使用相同的 tone/confidence 严肃性过滤；
  旧报告缺少这些字段时继续读取，引用原话不因玩笑语气被统一删除。

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

- 已实现：真实数据 API、结构化统计、DeepSeek/OpenAI Compatible API、独立输出、
  版本保留、300 DPI PNG，以及源码可运行的 Windows 桌面端最小闭环。
- 报告 schema 当前为向后兼容的 2.2，并继续读取 2.0/2.1。HTML 与 PNG 必须共享完整正文，不得自动精简或维护
  两套内容结构。报告一级顺序为“今日总览 → 今日速览 → 今日主要话题 → AI 今日观察 →
  今日活跃情况 → 报告结尾”。
- 同一语义话题跨不连续时段时合并并保留多个时间区间；时间相邻不得单独作为话题合并依据，
  必须核对讨论对象、核心问题、上下文指向及回复承接关系。每个主要话题以 `discussion_flow` 为核心，
  `outcome`、行动、问题、风险、引用和资源为可选嵌套细节；没有可靠内容时不得生成占位文本。
  不得重新引入“关键观点”“讨论转折”或独立的“详细讨论脉络”等重复模块，也不得对外展示“轻松插曲”。
- 日报视觉继续参考 `wzj042/wechat-auto-insight` 的米白—浅绿页面渐变、绿—黄头图及
  “圆形序号 + 右侧正文”讨论脉络结构；改变该产品行为前先向用户确认。
- 本地 Windows 测试安装包和 GitHub Actions 测试/发布工作流已建立；自动化发布不等同于代码签名。
- 后续迭代：每日活跃热力图、MCP Server、检查更新、代码签名与自动更新。
