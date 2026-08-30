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
- 打开图片、报告数据目录和群聊报告目录。

开发运行：

```powershell
$env:npm_config_cache = "D:\工具\wechat-chat-summary\.dev-cache\npm"
$env:CARGO_HOME = "D:\工具\wechat-chat-summary\.dev-cache\cargo-home"
$env:CARGO_TARGET_DIR = "D:\工具\wechat-chat-summary\.dev-cache\cargo-target"
npm install
npm run tauri dev
```

检查：

```powershell
npm run build
cd src-tauri
cargo check
```

当前 Rust 桥接在开发模式下优先使用仓库 `.venv\Scripts\python.exe`。正式安装包需在
Release 构建中读取安装目录内的 `engine\group-insight-sidecar.exe`。

本地测试安装包（不创建 Tag / GitHub Release）：

```powershell
.\scripts\build-windows-test-package.ps1
```

默认产物目录为 `D:\工具\WeChat Chat Summary\test-builds`，安装向导默认安装到
`D:\工具\WeChat Chat Summary\program` 并允许改选其他目录。卸载脚本只移除主程序、
分析引擎和快捷方式，不删除同级 `data`、`reports` 或用户自定义报告目录。PyInstaller、
npm 和 Cargo 的构建缓存均写入仓库下 `.dev-cache`（D 盘）。脚本不会自动下载 NSIS；
找不到已确认的 NSIS 路径时会停止并提示。
