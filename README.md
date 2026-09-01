# 微信群聊总结（wechat-chat-summary）

读取 `WeChatDataAnalysis` 提供的本地 API，按指定群聊和时间范围生成结构化统计、
AI 总结、统一结构 JSON、完整 HTML 及 300 DPI PNG 完整长图。当前代码已包含 Windows 桌面端闭环、
SQLite 历史中心与搜索、当日链接/文件整理、真实阶段进度、人工屏蔽、成员名称碰撞防护，以及面向
手机分享的日报长图。

## 项目来源与使用说明

本项目参考并使用了以下两个公开 GitHub 项目：

- [wzj042/wechat-auto-insight](https://github.com/wzj042/wechat-auto-insight)：本仓库的基础项目。保留并改造了其中的 `group_insight` 总结流程、报告渲染及可选微信发送能力；日报继续参考其米白—浅绿页面渐变、绿—黄头图和圆形序号讨论脉络设计；已移除不再可用的 `wechat-decrypt` 上游解密模块依赖。
- [LifeArchiveProject/WeChatDataAnalysis](https://github.com/LifeArchiveProject/WeChatDataAnalysis)：作为真实微信数据读取工具。本项目通过其本地 REST API 获取会话、成员和消息数据，并在 `group_insight/wechat_data_api.py` 中实现兼容适配；仓库不包含该工具本体、用户数据库或解密后的聊天数据。

可选的微信 UI 自动发送功能继续使用 `pywechat` 子模块；数据读取和报告生成不依赖该功能。

## 当前架构

- `WeChatDataAnalysis`：负责微信 4.x 数据读取、解密和本地 API。
- `group_insight/`：负责消息归一化、统计、分片、AI 分析、资源整理、统一报告结构、SQLite 历史索引和报告渲染。
- `desktop/`：Tauri 2 + React/TypeScript 桌面端，通过 UTF-8 JSONL 调用 Python 核心。
- `pywechat/`：可选的微信 UI 自动发送子模块。
- AI 分析支持 DeepSeek 与通用 OpenAI Compatible API；MCP 属于后续阶段。

旧 `wechat-decrypt` gitlink 仍存在于上游提交历史中，但当前代码、依赖和运行流程均不再使用它。

## 配置

先启动 `WeChatDataAnalysis` 并完成账号数据加载。复制 `.env.example` 为 `.env`，
填写 API Key 和独立输出目录：

```dotenv
DEEPSEEK_API_KEY=<API_KEY_PLACEHOLDER>
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_API_URL=https://api.deepseek.com/chat/completions
WECHAT_DATA_API_URL=http://127.0.0.1:10392
GROUP_INSIGHT_OUTPUT_ROOT=<用户选择的独立报告目录>
```

`.env` 仅供本机使用，已被 Git 忽略。输出目录应与源码和软件安装目录分离。

桌面端的软件自身数据目录由 Tauri 使用 Windows 标准 App Local Data API 确定，通常位于
`%LOCALAPPDATA%\com.bluntvoice.wechat-chat-summary`；普通设置、API Key、SQLite 和任务进度
分别保存在其中。报告目录始终独立：新用户默认为空，首次生成前必须在界面选择，选择后继续沿用。
若旧版 `D:\工具\WeChat Chat Summary\data` 存在且新目录尚未使用，软件会校验后复制配置、
密钥和历史库，保留旧目录作为回退；新目录已有文件时不会覆盖。

## 桌面端开发运行

安装依赖后从 `desktop` 目录启动；npm、Cargo 等工具使用各自的标准缓存，也可由开发者
通过环境变量改到任意有足够空间的目录：

```powershell
cd desktop
npm ci
npm run tauri dev
```

当前阶段提供源码可运行的桌面闭环，并提供不依赖源码目录的本地 Windows 测试安装包
构建脚本。安装向导默认使用当前 Windows 用户的本地应用程序目录，并允许改选目录；
程序数据和报告目录独立管理，升级或卸载测试程序不会删除它们。
当前已建立独立历史中心：按群聊查看日期、报告、历史版本和逻辑模块，支持日期、模块与关键词筛选，
并可打开对应 PNG、HTML 和 JSON。生成页的已总结群按 SQLite 历史记录置顶，并可切换“全部 / 已总结”；
新生成、定时生成和切换导出目录重新导入后会即时刷新。热力图、MCP、正式签名、自动更新尚未完成。
GitHub Actions 已可生成测试安装包和执行人工确认的正式 Release，但不会因此自动发布新版本。
第五阶段仍为每日活跃热力图；第六阶段仍为 MCP、设置 / 关于完善、检查更新、代码签名与自动更新。

桌面端默认按单日生成，并可切换自定义日期区间；成功生成后会记住上次群聊。AI 区域提供
独立“保存设置”和“测试 API”按钮；DeepSeek 模型通过 Flash / Pro 下拉框明确选择，测试成功
时会显示服务端实际响应模型。生成过程中显示真实阶段、百分比和已用时间。完成后可
分别打开完整 PNG 长图、完整 HTML 或报告所在目录。PNG 与 HTML 使用相同的信息模块，
按“今日总览 → 今日速览 → 今日主要话题 → AI 今日观察 → 今日活跃情况 → 报告结尾”呈现。
主要话题采用圆形序号和连续讨论脉络，同一语义话题可保留多个不连续时间区间；时间相邻
不会被单独用作合并依据。讨论落点、行动、问题、风险、引用和资源仅在确有内容且可可靠
关联时嵌入对应话题，不再重复展示“关键观点”“讨论转折”或“暂无结论”等占位内容。

报告生成后可进入“编辑并屏蔽内容”，按模块逐项勾选热点、讨论、成员、结论、行动、
问题、风险、引用和资源。屏蔽只在本机读取既有结构化 JSON 并重新渲染，不重新读取群聊、
不再次调用 AI；结果保存为 `_v2`、`_v3` 等新版本，原报告不被覆盖。屏蔽版 JSON、HTML、
PNG 和搜索索引不保留被屏蔽条目的标题、成员或总结，只显示所属时间及“已屏蔽，建议在群内查看”。
“轻松插曲”不再作为报告模块展示，但玩笑/反话识别仍用于阻止其进入正式结论。

报告中的成员名称优先使用群昵称，其次使用微信网名，不使用本机联系人备注；若上游将同一
显示名同时分配给两个及以上不同账号，软件会将其视为名称碰撞，并分别回退到微信网名或账号
ID。群关键词会做规范化去重。资源整理会在提取阶段忽略微信红包消息、疑似红包领取页与红包素材链接。

桌面端还支持可关闭的每日定时生成，可固定群聊与时间。该功能属于软件内置定时器：只有
软件保持运行时才会触发，每天最多自动尝试一次，不创建 Windows 任务计划，也不会在软件
关闭期间后台运行。

## 运行

真实数据干跑会生成统计与 HTML，但不调用模型、不导出图片、不发送微信：

```powershell
python -m group_insight `
  --chat "群聊完整名称" `
  --start "2026-08-28 00:00:00" `
  --end "2026-08-28 23:59:59" `
  --dry-run `
  --no-image `
  --no-send-after-run
```

完整分析和 PNG 导出：

```powershell
python -m group_insight `
  --chat "群聊完整名称" `
  --start "2026-08-28 00:00:00" `
  --end "2026-08-28 23:59:59" `
  --image-dpi 300 `
  --no-send-after-run
```

默认视口宽度为 760 CSS 像素，浏览器以 2 倍缩放导出约 1520 像素宽的长图。
PNG 会写入 300 DPI 的 `pHYs` 元数据，不会为了修改 DPI 而重采样图片。

## 输出

```text
<报告根目录>\<对话名>\
  导出图\YYYY\MM\YYYY-MM-DD报告.png
  报告数据\YYYY-MM-DD报告数据\
    <对话名>_YYYY-MM-DD_群聊总结.json
    <对话名>_YYYY-MM-DD_群聊总结.html
```

同日重复生成使用 `_v2`、`_v3` 递增版本，不覆盖旧报告。多日总结使用
`YYYY-MM-DD_至_YYYY-MM-DD`。报告 JSON 使用向后兼容的 `report schema 2.2`，并继续读取 2.0/2.1 历史报告；它与 HTML、PNG 和
SQLite 历史索引共用结构；报告目录和历史库均不保存完整原始消息分片。屏蔽记录进入
`report_redactions` 表，被屏蔽正文不会写入新版本或 FTS 索引。

SQLite 历史库位于上述 Windows 用户数据目录的 `history.sqlite3`。数据库使用独立于
Report Schema 2.2 的 schema migration 版本；群聊每日统计按 `chat + date` 独立保存，不要求
当天已经生成报告。历史搜索底层采用 FTS5，并在 FTS 无法命中的中文子词场景使用本地子串回退，
可检索群聊、一句话总结、成员、话题及嵌套细节、资源标题、文件名和 URL。历史 UI 的逻辑模块由
Schema 2.2 查询层派生，不改变报告 JSON；2.0/2.1 历史报告仍可读取。热力图页面属于后续版本。

## 测试

```powershell
python -m unittest discover -s tests -v
python -m compileall -q group_insight tests
cd desktop
npm run build
cd src-tauri
cargo check
```

## GitHub Actions 构建与发布

仓库提供三个 Windows 工作流：`CI` 只做轻量检查；`Build Windows test installer` 生成
测试安装包但不创建 Tag 或 Release；`Release Windows installer` 在测试、构建全部成功后，
同步版本、更新 CHANGELOG、推送 Tag 并创建 GitHub Release。版本以
`desktop/package.json` 为唯一人工输入源，其余版本文件由脚本同步并在 CI 中校验。

在 GitHub 网页生成测试安装包：

1. 打开仓库的 **Actions** 页面，选择 **Build Windows test installer**；
2. 点击 **Run workflow**，选择要构建的分支并确认；
3. 任务成功后，在该次运行页面底部 **Artifacts** 下载
   `wechat-chat-summary-v<版本>-windows-test`；压缩包内含安装程序及 `.sha256` 文件。

发布 Prerelease 或 Stable：

1. 打开 **Actions → Release Windows installer → Run workflow**，必须从默认分支运行；
2. `version` 不要填写 `v`：正式版如 `0.3.0`，预发布版如 `0.3.0-beta.1`，且必须高于当前版本；
3. `channel` 选择 `prerelease` 或 `stable`；
4. `release_notes` 填写本次真实的版本亮点正文；工作流会自动添加 `## 版本亮点` 标题，
   并把同一份内容写入 CHANGELOG 和 GitHub Release；
5. 勾选真实发布确认；若距上一 Tag 不足 24 小时，还需单独勾选 24 小时内发布确认；
6. 成功后到仓库 **Releases** 下载安装程序和 SHA-256 校验文件。Prerelease 会明确标记为
   预发布，不会作为正式 Latest；Stable 会标记为 Latest。

Release 仅在测试和安装包构建通过后提交版本文件。任何步骤失败都不会创建 GitHub Release；
可打开该次 Actions 运行，展开带红色失败标记的步骤查看完整日志。若失败发生在版本提交和
Tag 已成功推送之后、Release 创建之前，需要先检查仓库 Tag/Release 状态再重试，禁止覆盖既有 Tag。

## 隐私

- 只处理本人合法持有或已获授权的数据。
- `.env`、真实消息快照、密钥和报告不得提交到 Git。
- 本地 API 默认只连接 `127.0.0.1`，不要无必要开放到局域网。
- 发布前应检查默认群名、发送目标和绝对路径，避免暴露个人信息。
- 正式 Release 前必须复核依赖、子模块与上游代码的许可证/授权边界。

## 授权状态

本仓库当前不附带 LICENSE，也不宣称整体采用 MIT。两个上游项目当前均未在仓库
根目录声明许可证；公开可见不等同于授予复制、修改或再分发许可。后续如取得明确
授权或完成独立重写，再单独确定本项目许可证。
