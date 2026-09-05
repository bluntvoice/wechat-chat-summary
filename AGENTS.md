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
- `group_insight/mcp_service.py`：MCP 受控数据访问、Schema 校验与报告归档闭环。
- `group_insight/mcp_server.py`：本机 Streamable HTTP MCP Server 与 tools 注册。
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
- 数据源和分析提供方必须解耦。软件自身生成直接调用可配置 AI API；MCP Server 供外部 AI 客户端
  调用，二者不是二选一模式。本软件当前不是 MCP Client，MCP Server 不是 AI Provider。
- MCP Server 默认关闭，只允许绑定 `127.0.0.1`，由桌面程序托管子进程；不得创建 Windows Service
  或在软件退出后残留服务。原始消息必须按明确范围临时读取并限制范围、条数和字符数，不得写入
  SQLite 或报告目录。
- 缺少群聊、时间范围、本地 API 或关键配置时应 fail-fast，不添加静默兜底。
- 调试优先使用 `--dry-run --no-image --no-send-after-run`。
- 修改后至少运行：
  `python -m unittest discover -s tests -v`、`python -m compileall -q group_insight tests`
  和 `git diff --check`。
- 修改桌面端后还需运行 `npm test`、`npm run build` 与 `cargo check`；缓存位置可配置，但不得依赖个人盘符或用户名。

## 版本、构建与发布规则

- `desktop/package.json` 是桌面版本的人工输入源；`package-lock.json`、`tauri.conf.json`、
  `Cargo.toml` 与 `Cargo.lock` 必须通过 `desktop/scripts/version.mjs` 同步。CI 和打包前必须
  执行版本一致性检查，冲突时 fail-fast。
- Windows 安装包必须复用 `desktop/scripts/build-windows-test-package.ps1` 和现有 sidecar
  架构，不得另建依赖本机绝对路径、API Key、微信数据或 WeChatDataAnalysis 实例的打包链路。
- 测试安装包只能通过 `build-test.yml` 或脚本的 `Test` 模式生成，不创建 Tag 和 GitHub Release。
- 正式发布只能人工触发 `release.yml`。全部测试与安装包构建成功后，工作流才允许提交版本文件、
  推送默认分支与 Tag；Stable 使用 `x.y.z`，Prerelease 使用含后缀的 SemVer 并必须标为 Prerelease。
- Stable Release 的同一次版本提交必须自动同步 README 当前版本、徽章、下载说明、项目状态和简版版本日志；
  Prerelease 不得覆盖 README 的 Stable 版本状态。README 不是版本号权威来源。
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
- 热力图必须先查询 `chat_daily_stats`，由 Python 判断缺口并只对用户选择的群聊与最多 366 天范围
  按需补齐；连续缺口按最多 31 天分段读取，不得逐日请求。成功扫描的空白日期才可写 0，读取或
  SQLite 写入失败时必须保留 unknown。补齐过程不得调用 AI，也不得保存原始消息正文。
- 热力图指标切换只读取既有聚合数据，不重复请求数据源；桌面端必须用请求身份避免旧请求覆盖
  用户新选择。报告日期跳转复用历史中心的 chat/date/report 参数，不建立第二套历史状态。
- 中文历史搜索基础采用 SQLite FTS5 + 本地子串回退；不得仅因 FTS 表存在就宣称中文子词可靠，
  必须覆盖群名、成员、话题、文件、资源、URL 和中英混合测试。
- 历史 UI 模块必须在查询层从 Report Schema 2.2 派生；结论、开放问题、风险、原话和资源
  取自 `content.topics[*]` 的嵌套字段及资源表，不得为历史页面改回旧顶层结构或重复展示内容。
- “已总结”唯一事实来源是 SQLite 中该 `chat_id` 至少一份有效报告。`settings.summarized_chat_ids`
  只作为桥接缓存，每次生成、定时生成、导入或显式刷新后都应由历史库重建；不得按群名匹配。
- 生成页只对当前 WeChatDataAnalysis 返回的群做置顶和筛选；历史中心必须继续展示数据库中的旧群。
- CLI 可保留人类可读日志，但桌面端生成结果必须读取版本化结构化协议，不得解析中文 stdout 标签。
- `open_questions` 与 decisions/risk_flags 使用相同的 tone/confidence 严肃性过滤；
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

- 已实现：真实数据 API、结构化统计、独立的 DeepSeek/OpenAI Compatible Provider、独立输出、
  版本保留、300 DPI PNG、设置页、本机 Streamable HTTP MCP Server，以及源码可运行的 Windows 桌面端闭环。
- 报告 schema 当前为向后兼容的 2.2，并继续读取 2.0/2.1。HTML 与 PNG 必须共享完整正文，不得自动精简或维护
  两套内容结构。报告一级顺序为“今日总览 → 今日速览 → 今日主要话题 → AI 今日观察 →
  今日活跃情况 → 报告结尾”。
- 同一语义话题跨不连续时段时合并并保留多个时间区间；时间相邻不得单独作为话题合并依据，
  必须核对讨论对象、核心问题、上下文指向及回复承接关系。每个主要话题以 `discussion_flow` 为核心，
  问题、风险、引用和资源为可选嵌套细节；没有可靠内容时不得生成占位文本。
  不得重新引入“关键观点”“讨论转折”或独立的“详细讨论脉络”等重复模块，也不得对外展示“轻松插曲”。
- “今日主要话题”每项必须先显示标题，再以普通正文样式显示时间范围，不使用胶囊外框；今日速览和话题内容中的
  成员占位符、唯一昵称及已知账号 ID 必须统一解析为蓝色加粗昵称；唯一昵称匹配忽略空白差异，存在跨成员歧义时不得猜测；较长讨论脉络按讨论顺序、成员观点或子问题显示为 2–5 个短段。
- 新报告不生成或展示讨论落点和行动事项，Schema 2.2 的 `outcome` 仅为兼容保留并固定为 `null`，`action_items` 仅为兼容保留并固定为空数组；
  旧讨论落点数据不删除并继续按原样展示，旧行动事项不删除但在报告渲染、历史模块、筛选、搜索和人工屏蔽入口中均不展示。AI 今日观察不生成“讨论弱点 / 不足 / 短板”。
- MCP 新报告必须先严格校验 Report Schema 2.2，再分配版本和写入文件/HistoryStore；只接受
  `topics[*]` 嵌套的问题、风险、引用和资源关联；`outcome` 必须为 `null`，`action_items` 必须为空数组。非法报告不得污染 SQLite。
- 日报视觉继续参考 `wzj042/wechat-auto-insight` 的米白—浅绿页面渐变、绿—黄头图及
  “圆形序号 + 右侧正文”讨论脉络结构；改变该产品行为前先向用户确认。
- 本地 Windows 测试安装包和 GitHub Actions 测试/发布工作流已建立；自动化发布不等同于代码签名。
- 已实现：独立历史中心、中文历史搜索、已总结群管理，以及按需补齐且区分 unknown/zero 的
  群聊日历热力图（消息数、参与人数、有效消息数）。
- 关于页必须优先显示 Tauri 安装包运行时版本，以便核对 Release 实际版本；浏览器开发预览才回退
  `desktop/package.json`。版本来源仍遵循统一同步脚本，不得在页面另维护手写版本常量。
- 桌面一级导航使用统一许可图标，不使用页面名称首字作为占位图标；流程步骤使用简单数字。首次使用
  指南必须可关闭并可从侧栏重新打开，关闭后不得每次启动强制弹出。切换一级页面应回到顶部。
- WeChatDataAnalysis 是需要单独下载安装并运行的数据源。生成页只显示简洁的未就绪状态及“重新检测 / 如何配置”入口；现有指南负责“安装 → 启动并准备数据 → 返回重新检测”三步说明；设置页长期提供 API 地址、连接状态、官方主页与 Releases 入口。仅凭本地 API 连接失败不得断言软件未安装，也不得返回 `not_installed`。
- 生成百分比只允许来自后端真实阶段事件；界面耗时可使用本地时钟持续刷新，不得让百分比随时间伪增长。
  历史详情和人工屏蔽列表必须解析 `[[user:...]]` 成员占位符，不展示内部 ID、Schema 或原始对象键。
- 历史中心默认详情必须与报告一级板块一致：今日总览由详情头部承载，其后为今日速览、今日主要话题、
  AI 今日观察、今日活跃情况和报告结尾。新报告不生成讨论落点；话题内问题、风险、原话及资源不得在默认详情重复拆卡，旧报告已有讨论落点继续原样显示；
  今日活跃情况不得重复详情头部已有的统计总数；成员观察卡片标题已显示昵称时不得再次显示相同的 `name` 字段。
- 历史详情预览是主要屏蔽入口，只允许选择 Report Schema 中完整可屏蔽条目，不做任意文字级删除；
  完整目标列表折叠保留用于批量和查漏。React 提交的 `redaction_target_id` 必须由 Python 针对当前
  报告 JSON 重新校验，仍生成递增新版本并保留原报告。
- 更新检查必须由用户在关于页手动触发，只访问本项目官方 GitHub Stable Release；不得启动检查、后台
  检查、自动降级或把 Prerelease 推送给普通通道。正式 installer 和 `.sha256` 使用现有 Release 精确
  命名，下载到系统临时目录，校验一致并经用户确认后方可启动；只有启动成功才退出当前软件。
- 安装器只可递归替换或删除安装根目录中的 `program`，不得删除 App Local Data、SQLite、API/MCP
  设置、热力图缓存、用户报告目录或安装根目录中的其他用户文件。SHA-256 只能表述为文件完整性校验；
  当前不宣称 Windows 代码签名。
- 安装器和卸载器检测到群聊拾遗正在运行时，先向主窗口发送正常关闭请求并等待；未能退出时只提示用户
  手动关闭后重试或取消，不强制结束进程。自定义连续日期
  默认按日串行生成、最多 7 天，并保留合并模式；无消息日不调用 AI，失败日继续后续任务且可单独重试。
- 后续迭代：代码签名；MCP Client 不在当前产品范围。
