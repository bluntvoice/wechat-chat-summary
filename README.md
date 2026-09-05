# 群聊拾遗（wechat-chat-summary）

<!-- release-readme:badges:start -->
![GitHub Downloads](https://img.shields.io/github/downloads/bluntvoice/wechat-chat-summary/total?style=flat&label=Downloads)

![GitHub Release](https://img.shields.io/github/v/release/bluntvoice/wechat-chat-summary?style=flat&label=Release)
<!-- release-readme:badges:end -->

一个基于本地微信聊天数据的微信群聊统计、AI 总结与历史回顾工具。

项目通过 [WeChatDataAnalysis](https://github.com/LifeArchiveProject/WeChatDataAnalysis) 提供的本地 API 读取微信聊天数据。选择指定群聊和日期后，可以自动完成消息统计、AI 内容分析，并生成适合电脑查看和手机分享的 PNG 长图、HTML 报告及结构化 JSON。

除了生成单次总结外，项目还提供历史报告管理、全文搜索、群聊活跃热力图、内容屏蔽、定时生成以及 MCP Server 等功能。

<!-- release-readme:current-version:start -->
> 当前版本：**v1.0.1**
<!-- release-readme:current-version:end -->
<!-- release-readme:release-status:start -->
> 当前主要面向 Windows 桌面环境。
>
> 项目仍在持续开发。
>
> 当前提供 Windows x64 正式安装版本。
<!-- release-readme:release-status:end -->

## 这个项目可以做什么？

微信群消息很多时，我们通常会遇到几个问题：

- 一天没看群，不知道大家讨论了什么；
- 重要讨论和日常闲聊混在一起，很难快速回顾；
- 群里分享过的链接、文件过段时间很难再找到；
- 每天的聊天记录缺少可以长期保存和回看的整理结果；
- 想观察一个群长期以来什么时候活跃、讨论量有什么变化。

「群聊拾遗」希望解决的就是这些问题。

```text
读取本地微信数据
↓
选择群聊和日期
↓
AI 总结
↓
生成长图
↓
自动保存
↓
历史查询与长期回顾
```

本工具不需要通过微信机器人持续监听群聊，而是读取本机已经存在的微信聊天数据。

## 已实现功能

### 1. 微信群聊读取

- 通过 WeChatDataAnalysis 本地 REST API 获取数据；
- 获取群聊列表、群成员及指定日期范围的消息；
- 自动移除成员名称中的 `U+007F`（DEL）占位字符；检测群昵称碰撞或跨成员账号误绑；配置本地上游源码后，会按需启动修复分支服务复读，复读不可用时再按账号读取实时微信名，仍无法确认则停止报告生成；真实同名成员显示为“昵称（01）”“昵称（02）”；
- 统计消息数量、有效消息数量、参与人数、活跃成员、活跃时段等信息；
- 支持搜索群聊，并根据本地历史记录识别和筛选“已总结”群聊。

### 2. 单日 / 自定义时间范围总结

- 默认按单日生成总结；
- 支持自定义连续起止日期，默认按日串行生成最多 7 份独立日报，也可选择合并成一份；
- 无消息日期自动跳过且不调用 AI，单日失败不会阻断后续日期，并可单独重试；
- 成功生成后记住上次使用的群聊；
- 已生成过报告的群聊会置顶显示，并可单独筛选。

### 3. AI 群聊总结

当前支持以下 AI Provider：

- DeepSeek；
- OpenAI Compatible。

AI 分析会整理总体情况、主要讨论话题、讨论脉络、重要结论、开放问题、风险、引用、链接和文件，以及 AI 综合观察。玩笑、调侃、反话和低可信内容会经过严肃性与可信度过滤；“讨论弱点 / 不足 / 短板”类负面复盘标题不会进入报告。

### 4. 多格式报告导出

- PNG 长图；
- HTML 完整报告；
- JSON 结构化报告数据。

PNG 采用适合手机纵向阅读的长图形式，可用于微信群或其他场景分享。HTML 与 PNG 使用同一份完整报告正文。

### 5. 主要话题与讨论脉络

「今日主要话题」不是简单按照时间段切割消息。系统会结合讨论对象、核心问题、上下文、回复关系和语义关联等信息，判断消息是否属于同一个话题。

一个话题即使在当天多个不连续时间段被反复讨论，也可以被归纳到同一个主题中。开放问题、风险、引用和资源会尽可能关联到对应话题；必要进展直接写入讨论脉络，新报告不再另设“讨论落点”。较长讨论脉络会按讨论顺序、成员观点或子问题分成 2–5 个短段；报告正文中的成员引用会先固化为稳定账号占位符，最终按“完整群昵称 → 微信网名 → 账号 ID”解析并统一显示为蓝色加粗，匹配时可忽略空白差异但不会用标准化或缩短后的文本替代完整昵称，存在跨成员歧义时不会猜测。

### 6. 链接与文件整理

- 提取普通 URL、微信链接卡片和文件元数据；
- 尽量把链接和文件归入对应主题；
- 确定性识别小红书、淘宝 / 天猫、公众号、知乎、京东、抖音、哔哩哔哩、微博等平台并显示标签；
- 无法可靠判断归属时进入“其他 / 未归类”；
- 过滤微信红包消息、疑似红包领取页和红包素材链接。

### 7. 历史中心

历史报告按以下层级组织：

```text
群聊 → 日期 → 报告 → 版本
```

可以查看不同日期和版本的报告、报告模块与资源，并打开对应的 PNG、HTML 和 JSON。默认详情按照“今日速览 → 今日主要话题 → AI 今日观察 → 今日活跃情况 → 报告结尾”呈现，今日总览由详情头部承载；新报告的问题、风险、原话和资源保留在对应话题中，不再重复拆成额外卡片，也不再生成讨论落点。成员观察卡片标题已显示昵称时，不再重复显示“成员：昵称”。旧报告已有讨论落点继续按原样查看。旧群聊即使当前数据源中已不可见，已有历史报告仍会保留在历史中心。

### 8. 历史搜索

历史中心使用本机 SQLite 索引，支持按群聊、日期范围和报告一级板块筛选，并搜索总结、成员、话题、开放问题、风险、引用、资源标题、文件名和 URL。新报告不会产生讨论落点索引；旧报告已有讨论落点继续保留。嵌套的话题细节仍可搜索，但搜索结果归入报告所属一级板块。旧报告中的行动事项数据不会删除，但不再展示、筛选或进入搜索结果。中文搜索在全文索引未命中时还会使用本地子串匹配。

### 9. 人工屏蔽内容

生成报告后，可以选择不适合分享的完整内容条目。历史报告预览支持进入屏蔽模式后直接点击报告条目，也保留完整条目列表用于批量选择和查漏。

屏蔽过程：

- 不重新读取聊天；
- 不重新调用 AI；
- 不覆盖原报告；
- 生成 `_v2`、`_v3` 等递增新版本。

被屏蔽内容不会继续进入新版本正文和搜索索引。新版本仅保留所属时间及“已屏蔽，建议在群内查看”的提示，不保留被屏蔽条目的标题、成员、总结、引用或资源详情。

### 10. 群聊活跃热力图

热力图支持按以下指标查看每日活跃程度：

- 消息数量；
- 有效消息数量；
- 参与人数。

时间范围支持最近一年、指定年份和自定义日期范围。缺少缓存时，软件会按当前群聊和范围从本地聊天数据按需计算，不调用 AI；尚未统计与已确认没有消息会分别显示。

### 11. 每日定时生成

桌面端支持为一个固定群聊设置每日生成时间，并可选择生成触发当日或昨日的报告。只有「群聊拾遗」保持运行时才会触发，每个自然日最多自动尝试一次。

桌面端的这一定时功能：

- 不创建 Windows Task Scheduler 任务；
- 不安装 Windows Service；
- 软件关闭后不会继续运行。

### 12. MCP Server

MCP Server 属于高级功能。软件自身生成总结时使用用户配置的 AI API；MCP Server 则向外部 MCP Host 提供受控的群聊数据、统计、历史搜索和报告能力，由外部 AI 完成分析并提交结果。

当前群聊拾遗提供 MCP Server，但不是 MCP Client。当前 tools：

- `list_chats`
- `get_chat_stats`
- `get_chat_analysis_context`
- `get_daily_stats`
- `list_history`
- `search_history`
- `get_report`
- `submit_report`
- `render_report`

## 下载与安装

<!-- release-readme:download:start -->
当前正式版本通过本仓库的 [GitHub Releases](https://github.com/bluntvoice/wechat-chat-summary/releases) 提供。

### Windows

当前正式版本主要面向 Windows x64。用户可从 [最新版下载页](https://github.com/bluntvoice/wechat-chat-summary/releases/latest) 下载：

```text
WeChat-Chat-Summary_1.0.1_x64-setup.exe
WeChat-Chat-Summary_1.0.1_x64-setup.exe.sha256
```

安装步骤：

1. 下载最新版安装程序及同名 `.sha256` 完整性校验文件；
2. 运行安装程序；
3. 首次启动后，根据软件内引导单独安装并运行 WeChatDataAnalysis；
4. 配置 AI API；
5. 选择独立的报告目录；
6. 开始生成群聊总结。
<!-- release-readme:download:end -->

## 前置依赖

### Windows

当前桌面端主要面向 Windows 开发和测试。

### 微信电脑版及本地聊天数据

需要本机已经存在可由 WeChatDataAnalysis 读取的微信聊天数据。

### WeChatDataAnalysis

本项目本身不直接负责微信数据库解密和原始数据读取。相关能力由 [LifeArchiveProject/WeChatDataAnalysis](https://github.com/LifeArchiveProject/WeChatDataAnalysis) 提供；它是需要单独下载安装并运行的前置数据源，可从 [官方 Releases](https://github.com/LifeArchiveProject/WeChatDataAnalysis/releases) 下载。

基本流程：

1. 安装并启动 WeChatDataAnalysis；
2. 完成微信数据加载；
3. 启动本地 API；
4. 再由群聊拾遗连接。

桌面端首次使用指南会按上述流程引导。生成页连接失败时可重新检测或打开配置指南；设置页的数据源区域长期提供连接状态、API 地址、下载入口和重新检测。连接失败只代表当前未检测到服务，不能据此判断软件一定没有安装。

默认本机地址为：

```text
http://127.0.0.1:10392
```

### AI API

- 用户需要自行向 AI 服务商申请 API Key；
- AI 服务费用由对应服务商收取；
- 本项目不提供免费 AI API。

### MCP（可选）

普通用户使用群聊拾遗生成总结不需要配置 MCP。只有需要让外部 MCP Host 调用本机数据与报告能力时，才需要启用 MCP Server。

## 快速开始

1. 启动 WeChatDataAnalysis；
2. 确认本机数据接口可用；
3. 打开群聊拾遗；
4. 在“生成总结”页面测试数据源并读取群聊；
5. 在“设置”页面配置 AI API；
6. 选择独立的报告目录；
7. 选择群聊；
8. 选择单日或自定义日期范围；
9. 生成总结；
10. 打开 PNG、HTML 或报告所在目录；
11. 在“历史中心”查看过去的报告和版本；
12. 需要时通过“热力图”查看长期活跃情况。

桌面端首次使用会显示可以关闭的简短指南。关闭后不会在每次启动时强制弹出，也可以随时从侧栏重新打开。

## 生成的报告包含什么？

当前报告按以下顺序呈现：

1. 今日总览；
2. 今日速览；
3. 今日主要话题；
4. AI 今日观察；
5. 今日活跃情况；
6. 报告结尾。

PNG 适合手机纵向阅读与分享；HTML 适合在电脑上查看完整报告；JSON 用于保存结构化报告数据以及供程序后续读取。

同日重复生成不会覆盖旧报告，而是使用 `_v2`、`_v3` 等递增版本。当前新报告使用 Report Schema 2.2，同时继续兼容读取旧 2.0 / 2.1 报告。

## 本地数据与隐私

### 微信数据读取

微信数据由 WeChatDataAnalysis 从本机读取，群聊拾遗通过其本地 API 获取当前请求所需的群聊、成员和消息数据。

### 群聊拾遗保存的数据

根据当前实现，软件会在 Windows 用户数据目录或用户选择的报告目录中保存：

- 普通设置；
- AI Provider 配置及本机私有 API Key；
- SQLite 历史索引；
- 每日聚合统计与热力图缓存；
- JSON、HTML 和 PNG 报告；
- 任务状态与生成进度。

软件不会为了历史查询额外建立一份完整的原始微信聊天正文数据库。报告目录和 SQLite 历史库也不保存 AI 分析阶段使用的完整原始消息分片。

### AI 数据传输说明

使用第三方 AI API 进行总结时，为完成分析，必要的聊天内容需要发送给用户所配置的 AI 服务商。因此，“微信数据来自本机”并不等同于“所有 AI 分析内容永远不会离开本机”。

使用前请自行了解对应服务商的：

- 隐私政策；
- 数据保存政策；
- API 数据使用规则。

商业秘密、客户信息、内部资料和个人敏感信息应谨慎发送给第三方 AI 服务。

## AI API 与 MCP Server

### AI API

软件自身的“生成总结”调用用户配置的 DeepSeek 或 OpenAI Compatible API。DeepSeek 支持其专属的 Thinking、Reasoning Effort、余额查询和模型校验；通用 OpenAI Compatible 请求不会自动携带 DeepSeek 专属字段。

### MCP Server

外部 MCP Host 可以调用群聊拾遗提供的群聊数据、统计、历史搜索、报告读取和报告生成能力。MCP Server 默认关闭，仅监听本机，软件退出后由桌面程序终止，不安装 Windows Service。

默认地址：

```text
http://127.0.0.1:8765/mcp
```

Codex 配置示例：

```toml
[mcp_servers.wechat_chat_summary]
url = "http://127.0.0.1:8765/mcp"
enabled = true
tool_timeout_sec = 300
```

MCP 分析链路与软件自身的 AI API 生成链路彼此独立。当前软件不是 MCP Client，也不会通过 MCP 调用外部 AI。

## 配置

普通桌面用户可以直接通过软件“设置”页面配置数据源、AI Provider、报告目录和 MCP Server。API Key 会按 Provider 分开保存在 Windows 用户数据目录的私有密钥文件中，不写入公开设置、SQLite、日志或报告。

从源码运行时可以参考 `.env.example`：

```dotenv
DEEPSEEK_API_KEY=<API_KEY>
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_API_URL=https://api.deepseek.com/chat/completions

# 使用 OpenAI Compatible 时按实际服务填写：
# OPENAI_COMPATIBLE_API_KEY=<API_KEY>
# OPENAI_COMPATIBLE_MODEL=<MODEL_NAME>
# OPENAI_COMPATIBLE_API_URL=https://api.example.com/v1

WECHAT_DATA_API_URL=http://127.0.0.1:10392
# 可选：昵称异常时按需启动的 WeChatDataAnalysis 本地上游源码目录与端口
# WECHAT_DATA_LOCAL_SOURCE_DIR=D:\path\to\WeChatDataAnalysis-source
# WECHAT_DATA_LOCAL_SOURCE_PORT=10393

GROUP_INSIGHT_OUTPUT_ROOT=<你的报告目录>
```

`.env` 只供本机源码运行使用，已被 Git 忽略。报告目录应与源码目录、软件安装目录及 WeChatDataAnalysis 安装目录分开。

## 从源码运行

当前 CI 使用 Python 3.12、Node.js 24 和 Rust stable。首次运行前安装 Python 依赖及 Playwright Chromium：

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
```

启动桌面开发版本：

```powershell
cd desktop
npm ci
npm run tauri dev
```

Windows 安装包构建还需要 NSIS 和 `desktop/requirements-build.txt` 中的 PyInstaller，普通源码开发运行不需要执行正式发布工作流。

## 项目结构

```text
wechat-chat-summary
│
├─ desktop/
│  └─ Windows Tauri 2 + React 桌面端
│
├─ group_insight/
│  └─ 消息处理、统计、AI 分析、历史数据及报告生成
│
├─ pywechat/
│  └─ 可选微信 UI 自动操作模块
│
├─ tests/
│  └─ Python 自动化测试
│
├─ PRD.md
└─ requirements.txt
```

## 版本更新日志

<!-- release-readme:history -->

### v1.0.1

修复成员昵称与代表发言显示。

- 修复 偶发HTML、PNG 与历史中心中部分成员昵称未正确显示为蓝色加粗的问题；
- 修复报告中完整群昵称被简写或显示不完整的问题；
- 优化成员引用解析，并根据话题证据保留代表成员，避免主要话题只显示“群友、有人”等泛称。

### v1.0.0

首个正式稳定版本。

- 完成 Windows 桌面端正式发布闭环；
- 支持 WeChatDataAnalysis 数据源安装、连接与故障引导；
- 支持单日及最多 7 天连续日期的群聊 AI 总结；
- 支持 DeepSeek 与 OpenAI Compatible AI Provider；
- 支持 PNG、HTML、JSON 多格式报告导出；
- 提供历史中心、全文搜索、群聊活跃热力图和内容屏蔽；
- 提供定时生成、MCP Server 和手动检查更新；
- 优化成员昵称识别、报告结构与桌面阅读体验；
- 完善 Windows 安装、覆盖升级和卸载流程。

### v0.2.4

- 优化主要话题结构、报告视觉、进度与首次使用指南；
- 增加群聊活跃热力图；
- 增加 DeepSeek / OpenAI Compatible Provider 与 MCP Server；
- 增加手动检查更新及安装包更新闭环；
- 支持最多 7 天连续日期逐日生成；
- 优化历史中心、成员昵称识别、资源标签及报告布局。

<!-- release-readme:prestable-history-note:start -->
<!-- release-readme:prestable-history-note:end -->

### v0.2.3

- 增加独立历史中心；
- 支持历史版本、报告模块、资源和本地搜索；
- 以 SQLite 历史记录识别并筛选已总结群聊。

### v0.2.2

- 修复多个账号共享同一上游显示名时的成员名称碰撞；
- 成员名称优先使用群昵称，其次使用微信网名；真实同名成员按账号排序增加两位序号，无法确认时不生成报告。

### v0.2.1

- 完善桌面端 AI 设置、定时生成、真实进度和报告操作体验；
- 优化 HTML / PNG 报告、资源过滤和人工屏蔽。

### v0.2.0

- 建立结构化报告、HTML / PNG / JSON 输出与历史数据基础；
- 完成桌面端生成报告的基本闭环。

> 更完整的版本变化请查看 [CHANGELOG.md](./CHANGELOG.md)。

## 项目来源与致谢

- [wzj042/wechat-auto-insight](https://github.com/wzj042/wechat-auto-insight)：本项目最初参考并基于其部分群聊总结、报告渲染和可选微信发送能力继续开发。当前历史中心、热力图、Provider、MCP Server、更新闭环等能力已在本仓库中独立扩展。
- [LifeArchiveProject/WeChatDataAnalysis](https://github.com/LifeArchiveProject/WeChatDataAnalysis)：负责微信数据读取，本仓库通过其本地 API 获取会话、成员和消息。本仓库不包含该工具本体，也不包含用户微信数据库。

可选的微信 UI 自动发送功能继续使用 `pywechat` 子模块；数据读取和报告生成不依赖该功能。

## 当前开发状态

<!-- release-readme:development-status:start -->
- Windows x64 正式安装包通过 GitHub Releases 提供；
- Stable / Prerelease 发布流程已经建立；
- 测试安装包继续用于正式发布前验收；
- 用户可在关于页手动检查更新、下载正式安装包并进行 SHA-256 完整性校验；
- 软件启动时不会自动检查更新，也不会后台周期检查；
- Windows 安装包当前仍未进行代码签名。
<!-- release-readme:development-status:end -->

当前仓库没有 `LICENSE` 文件，也不声明整体采用 MIT 或其他开源许可证。公开可见不等同于已经授予复制、修改或再分发许可；正式发布前仍需复核项目及上游依赖的许可边界。

## 免责声明

### 1. 合法使用

使用者应确保自己对所读取、分析和处理的微信聊天数据具有合法权限，并遵守适用法律法规、隐私要求以及第三方合法权益。请勿利用本项目非法获取、分析或传播他人的聊天记录或个人信息。

### 2. 隐私与敏感信息

微信群聊可能包含个人信息、商业秘密、客户信息或其他敏感信息。调用 AI API 或让 MCP Host 获取分析上下文前，应由用户自行判断相关内容是否适合提供给第三方服务或外部 AI 客户端。

### 3. 第三方服务

项目会依赖或连接 WeChatDataAnalysis、AI API、MCP Host 及其他第三方项目或服务。项目作者无法保证第三方服务永久可用、永久兼容、免费，或其数据政策不会发生变化。

### 4. 软件可靠性

本项目仍处于持续开发阶段，不保证不存在错误、中断、数据解析异常、AI 总结错误或其他问题。

### 5. AI 准确性

AI 生成内容仅作为辅助整理结果，不应视为对原始聊天记录的完整、准确或权威还原。重要事项应回到原始聊天记录中核实。

### 6. 数据备份

升级、迁移或修改数据目录前，请自行备份重要报告、历史数据和本机配置。

### 7. 风险承担

使用者应根据自己的数据性质、隐私要求和使用环境，自行判断本项目是否适合相应场景，并承担使用过程中可能产生的风险。

## 反馈

如果发现 Bug，或者对功能有新的建议，可以通过 GitHub Issues 反馈：

https://github.com/bluntvoice/wechat-chat-summary/issues
