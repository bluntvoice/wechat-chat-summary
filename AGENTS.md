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

## 当前迭代边界

- 已实现：真实数据 API 接入、结构化统计、独立输出与日期命名。
- 后续迭代：长图视觉重构、每日活跃热力图、AI API/MCP 双分析模式、
  SQLite 历史中心、全文搜索和 Windows 桌面端。
