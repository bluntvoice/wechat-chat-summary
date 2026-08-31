# 微信群聊总结（wechat-chat-summary）

读取 `WeChatDataAnalysis` 提供的本地 API，按指定群聊和时间范围生成结构化统计、
AI 总结、统一结构 JSON、完整 HTML 及 300 DPI PNG 摘要长图。v0.2.0 已包含 Windows 桌面端闭环、
SQLite 历史数据底座、当日链接/文件整理、真实阶段进度、人工屏蔽，以及面向手机分享的日报长图。

## 项目来源与使用说明

本项目参考并使用了以下两个公开 GitHub 项目：

- [wzj042/wechat-auto-insight](https://github.com/wzj042/wechat-auto-insight)：本仓库的基础项目。保留并改造了其中的 `group_insight` 总结流程、报告渲染及可选微信发送能力；已移除不再可用的 `wechat-decrypt` 上游解密模块依赖。
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
GROUP_INSIGHT_OUTPUT_ROOT=D:\WeChatData\群聊总结
```

`.env` 仅供本机使用，已被 Git 忽略。输出目录应与源码和软件安装目录分离。

桌面端配置默认保存在 `D:\工具\WeChat Chat Summary\data`：普通设置写入
`config.json`，API Key 写入本机私有的 `secrets.env`。软件升级只能替换未来的
`program` 目录，不得覆盖 `data` 或用户选择的报告目录。

## 桌面端开发运行

依赖目录和缓存均可固定在 D 盘源码目录：

```powershell
cd desktop
$env:npm_config_cache = "D:\工具\wechat-chat-summary\.dev-cache\npm"
$env:CARGO_HOME = "D:\工具\wechat-chat-summary\.dev-cache\cargo-home"
$env:CARGO_TARGET_DIR = "D:\工具\wechat-chat-summary\.dev-cache\cargo-target"
npm install
npm run tauri dev
```

当前阶段提供源码可运行的桌面闭环，并提供不依赖源码目录的本地 Windows 测试安装包
构建脚本。测试包默认安装到 `D:\工具\WeChat Chat Summary\program`，允许用户改选
目录；程序数据和报告目录位于 `program` 之外，升级或卸载测试程序不会删除它们。
当前历史数据底座和本地 FTS 已建立，但历史中心页面、搜索界面、热力图、MCP、正式签名、
自动更新与 GitHub Release 尚未完成，不应将这些后续界面描述为已实现。

桌面端默认按单日生成，并可切换自定义日期区间；成功生成后会记住上次群聊。AI 区域提供
独立“保存设置”和“测试 API”按钮，生成过程中显示真实阶段、百分比和已用时间。完成后可
分别打开 PNG 摘要长图、完整 HTML 或报告所在目录。

报告生成后可进入“编辑并屏蔽内容”，按模块逐项勾选热点、讨论、成员、结论、行动、
问题、风险、引用和资源。屏蔽只在本机读取既有结构化 JSON 并重新渲染，不重新读取群聊、
不再次调用 AI；结果保存为 `_v2`、`_v3` 等新版本，原报告不被覆盖。屏蔽版 JSON、HTML、
PNG 和搜索索引不保留被屏蔽条目的标题、成员或总结，只显示所属时间及“已屏蔽，建议在群内查看”。
“轻松插曲”不再作为报告模块展示，但玩笑/反话识别仍用于阻止其进入正式结论。

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
`YYYY-MM-DD_至_YYYY-MM-DD`。报告 JSON 使用 `report schema 2.0`，与 HTML、PNG 和
SQLite 历史索引共用结构；报告目录和历史库均不保存完整原始消息分片。屏蔽记录进入
`report_redactions` 表，被屏蔽正文不会写入新版本或 FTS 索引。

SQLite 历史库默认位于 `D:\工具\WeChat Chat Summary\data\history.sqlite3`。软件会安全
索引当前导出根目录中的既有报告 JSON，不修改旧文件。当前仅提供数据底座，历史中心与搜索
界面属于后续版本。

## 测试

```powershell
python -m unittest discover -s tests -v
python -m compileall -q group_insight tests
cd desktop
npm run build
cd src-tauri
cargo check
```

## 隐私

- 只处理本人合法持有或已获授权的数据。
- `.env`、真实消息快照、密钥和报告不得提交到 Git。
- 本地 API 默认只连接 `127.0.0.1`，不要无必要开放到局域网。
- 发布前应检查默认群名、发送目标和绝对路径，避免暴露个人信息。

## 授权状态

本仓库当前不附带 LICENSE，也不宣称整体采用 MIT。两个上游项目当前均未在仓库
根目录声明许可证；公开可见不等同于授予复制、修改或再分发许可。后续如取得明确
授权或完成独立重写，再单独确定本项目许可证。
