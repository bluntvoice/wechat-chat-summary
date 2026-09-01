# Windows 桌面端

第一阶段桌面端使用 Tauri 2、React 和 TypeScript，通过 UTF-8 JSONL 协议调用现有
Python 核心。开发模式使用仓库虚拟环境，测试安装包使用 PyInstaller `onedir` 分析引擎，
安装后不依赖源码目录，也不会在运行时把分析引擎解压到系统盘临时目录。

当前完成：

- 测试 WeChatDataAnalysis 并读取/搜索群聊；
- 选择单日或自定义日期范围；
- 配置和测试 DeepSeek / OpenAI Compatible API；
- 选择独立报告根目录；
- 生成 JSON、HTML 和 300 DPI PNG；
- 打开图片、报告数据目录和群聊报告目录；
- 在独立历史中心按群聊、日期、模块和关键词查询本地报告；
- 在独立热力图页查看消息数、参与人数或有效消息数，并从报告日期跳转历史中心；
- 在关于页核对 Tauri 安装包实际运行版本并复制 GitHub 项目地址。

软件自身的配置、密钥、SQLite 与任务进度由 Tauri 定位到 Windows 标准 App Local Data
目录，报告导出目录与其严格分离。新用户未选择报告目录时不会预填开发机路径，首次生成会
明确要求先选择目录。旧版固定数据目录只在新目录尚未使用时执行一次校验复制，且保留原目录。

开发运行：

```powershell
npm ci
npm run tauri dev
```

检查：

```powershell
npm test
npm run build
cd src-tauri
cargo check
```

当前 Rust 桥接在开发模式下优先使用仓库 `.venv\Scripts\python.exe`。正式安装包需在
Release 构建中读取安装目录内的 `engine\group-insight-sidecar.exe`。桌面端与报告子进程通过
专用 JSON 结果文件传递输出路径，不解析 CLI 的中文人类日志；每次请求启动一个 Python 进程的
生命周期本轮保持不变。

前端生成页、历史中心和热力图分别位于 `pages/GeneratePage.tsx`、`pages/HistoryPage.tsx` 与
`pages/HeatmapPage.tsx`；类型、桥接服务、纯数据转换、生成状态 hook 和人工屏蔽组件分别位于
`types/`、`services/`、`hooks/` 与 `components/`。热力图缺口由 Python 判断并按需补齐，React
只负责请求身份、交互和日历绘制。本轮未新增 MCP 页面。
关于页优先通过 Tauri runtime 读取安装包版本，普通浏览器开发预览才回退到
`desktop/package.json`；检查更新仍留在后续阶段。

本地测试安装包（不创建 Tag / GitHub Release）：

```powershell
.\scripts\build-windows-test-package.ps1
```

默认产物目录为仓库根目录下 `artifacts\windows`，安装向导默认安装到当前用户的
`%LOCALAPPDATA%\Programs\WeChat Chat Summary` 并允许改选其他目录。卸载脚本只移除主程序、
分析引擎和快捷方式，不删除用户自定义报告目录。脚本会从参数、`MAKENSIS_PATH`、PATH 和
NSIS 标准安装位置查找 `makensis.exe`，找不到时明确停止；不依赖开发者用户名或固定盘符。

GitHub 网页测试构建使用 `.github/workflows/build-test.yml`；正式发布使用
`.github/workflows/release.yml`。两者复用同一脚本，测试构建不会创建 Tag 或 Release。
