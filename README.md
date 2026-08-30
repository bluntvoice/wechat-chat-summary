# 微信群聊总结（wechat-chat-summary）

读取 `WeChatDataAnalysis` 提供的本地 API，按指定群聊和时间范围生成结构化统计、
AI 总结、JSON、HTML 及 300 DPI PNG 长图。真实聊天数据和报告只保存在用户选定
的独立数据目录中。

## 项目来源与使用说明

本项目参考并使用了以下两个公开 GitHub 项目：

- [wzj042/wechat-auto-insight](https://github.com/wzj042/wechat-auto-insight)：本仓库的基础项目。保留并改造了其中的 `group_insight` 总结流程、报告渲染及可选微信发送能力；已移除不再可用的 `wechat-decrypt` 上游解密模块依赖。
- [LifeArchiveProject/WeChatDataAnalysis](https://github.com/LifeArchiveProject/WeChatDataAnalysis)：作为真实微信数据读取工具。本项目通过其本地 REST API 获取会话、成员和消息数据，并在 `group_insight/wechat_data_api.py` 中实现兼容适配；仓库不包含该工具本体、用户数据库或解密后的聊天数据。

可选的微信 UI 自动发送功能继续使用 `pywechat` 子模块；数据读取和报告生成不依赖该功能。

## 当前架构

- `WeChatDataAnalysis`：负责微信 4.x 数据读取、解密和本地 API。
- `group_insight/`：负责消息归一化、统计、分片、DeepSeek 分析和报告渲染。
- `pywechat/`：可选的微信 UI 自动发送子模块。
- AI 分析当前支持 DeepSeek 兼容 API；通过 MCP 交给外部 AI 客户端分析属于后续接口。

旧 `wechat-decrypt` gitlink 仍存在于上游提交历史中，但当前代码、依赖和运行流程均不再使用它。

## 配置

先启动 `WeChatDataAnalysis` 并完成账号数据加载。复制 `.env.example` 为 `.env`，
填写 API Key 和独立输出目录：

```dotenv
DEEPSEEK_API_KEY=sk-your-deepseek-api-key
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_API_URL=https://api.deepseek.com/chat/completions
WECHAT_DATA_API_URL=http://127.0.0.1:10392
GROUP_INSIGHT_OUTPUT_ROOT=D:\WeChatData\群聊总结
```

`.env` 仅供本机使用，已被 Git 忽略。输出目录应与源码和软件安装目录分离。

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
D:\WeChatData\群聊总结\<对话名>\YYYY-MM-DD\
  <对话名>_YYYY-MM-DD_群聊总结.json
  <对话名>_YYYY-MM-DD_群聊总结.html
  <对话名>_YYYY-MM-DD_群聊总结.png
```

## 测试

```powershell
python -m unittest discover -s tests -v
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
