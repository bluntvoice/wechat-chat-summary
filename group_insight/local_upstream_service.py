"""按需启动本地 WeChatDataAnalysis 源码分支后端。"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


class LocalUpstreamServiceError(RuntimeError):
    """本地上游源码服务无法安全启动或验证。"""


def derive_upstream_output_dir(accounts_payload: dict[str, Any], account: str = "") -> Path:
    """从正式服务的账号信息推导共享 ``output`` 目录。"""

    infos = accounts_payload.get("accountInfos") or accounts_payload.get("items") or []
    candidates = [item for item in infos if isinstance(item, dict)]
    wanted = str(account or accounts_payload.get("default_account") or "").strip()
    if wanted:
        selected = next(
            (item for item in candidates if str(item.get("account") or "").strip() == wanted),
            None,
        )
        candidates = [selected] if selected is not None else []
    for item in candidates:
        account_dir = Path(str(item.get("accountDir") or "").strip())
        if account_dir.name and account_dir.parent.name.casefold() == "databases":
            return account_dir.parent.parent
    raise LocalUpstreamServiceError("正式服务未返回可复用的 WeChatDataAnalysis 数据目录。")


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        try:
            listener.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _health_ready(base_url: str, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url}/api/health", timeout=timeout) as response:
            return 200 <= int(response.status) < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


class LocalUpstreamService:
    """启动源码分支的仅本机临时后端，并在退出上下文时清理进程树。"""

    def __init__(
        self,
        source_dir: str | Path,
        *,
        output_dir: str | Path,
        port: int = 10393,
        startup_timeout: float = 60.0,
    ) -> None:
        self.source_dir = Path(source_dir).expanduser().resolve()
        self.output_dir = Path(output_dir).expanduser().resolve()
        self.port = int(port)
        self.startup_timeout = float(startup_timeout)
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.process: subprocess.Popen[str] | None = None
        self._log: Any = None

    def _validate(self) -> tuple[Path, Path]:
        if self.port < 1024 or self.port > 65535:
            raise LocalUpstreamServiceError("本地上游源码服务端口必须在 1024 到 65535 之间。")
        if not _port_available(self.port):
            raise LocalUpstreamServiceError(
                f"本地上游源码服务端口 {self.port} 已被占用，未接管未知进程。"
            )
        main_path = self.source_dir / "main.py"
        bootstrap = self.source_dir / "desktop" / "src" / "source-native-core-bootstrap.cjs"
        package_dir = self.source_dir / "src" / "wechat_decrypt_tool"
        if not main_path.is_file() or not bootstrap.is_file() or not package_dir.is_dir():
            raise LocalUpstreamServiceError("配置的目录不是完整的 WeChatDataAnalysis 源码目录。")
        python = self.source_dir / ".venv" / "Scripts" / "python.exe"
        if not python.is_file():
            raise LocalUpstreamServiceError("本地上游源码目录缺少 .venv\\Scripts\\python.exe。")
        if not self.output_dir.is_dir():
            raise LocalUpstreamServiceError("WeChatDataAnalysis 共享数据目录不存在。")
        return python, bootstrap

    def _prepare_native_core(self, bootstrap: Path, environment: dict[str, str]) -> Path:
        node = shutil.which("node.exe") or shutil.which("node")
        if not node:
            raise LocalUpstreamServiceError("未找到 Node.js，无法校验本地上游源码运行时。")
        cache_dir = self.source_dir.parent / f"{self.source_dir.name}-runtime"
        environment["WCE_NATIVE_CORE_SOURCE_CACHE_DIR"] = str(cache_dir)
        if os.name == "nt":
            system_root = environment.get("SystemRoot", r"C:\Windows")
            system32 = str(Path(system_root) / "System32")
            environment["PATH"] = system32 + os.pathsep + environment.get("PATH", "")
        script = (
            "const m=require(process.argv[1]);"
            "const r=m.ensureSourceNativeCore({env:process.env});"
            "process.stdout.write(JSON.stringify({nativeDir:r.nativeDir}));"
        )
        try:
            completed = subprocess.run(
                [node, "-e", script, str(bootstrap)],
                cwd=str(self.source_dir),
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=650,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise LocalUpstreamServiceError(f"本地上游源码运行时准备失败: {exc}") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()[-1200:]
            raise LocalUpstreamServiceError(f"本地上游源码运行时校验失败: {detail}")
        try:
            native_dir = Path(json.loads(completed.stdout)["nativeDir"])
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise LocalUpstreamServiceError("本地上游源码运行时引导返回了无效结果。") from exc
        if not native_dir.is_dir():
            raise LocalUpstreamServiceError("本地上游源码运行时目录不存在。")
        return native_dir

    def start(self) -> "LocalUpstreamService":
        python, bootstrap = self._validate()
        environment = os.environ.copy()
        environment.update(
            {
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
                "PYTHONPATH": str(self.source_dir / "src"),
                "WECHAT_TOOL_HOST": "127.0.0.1",
                "WECHAT_TOOL_PORT": str(self.port),
                "WECHAT_TOOL_OUTPUT_DIR": str(self.output_dir),
                "WECHAT_TOOL_DATA_DIR": str(self.output_dir),
                "WECHAT_TOOL_REALTIME_AUTOSYNC": "0",
                "WECHAT_TOOL_SNS_AUTOSYNC": "0",
                "WECHAT_TOOL_RELOAD": "0",
            }
        )
        native_dir = self._prepare_native_core(bootstrap, environment)
        environment["WCE_NATIVE_CORE_SOURCE_DIR"] = str(native_dir)
        self._log = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            self.process = subprocess.Popen(
                [str(python), str(self.source_dir / "main.py")],
                cwd=str(self.source_dir),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=self._log,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                creationflags=creationflags,
            )
        except OSError as exc:
            self._close_log()
            raise LocalUpstreamServiceError(f"本地上游源码服务启动失败: {exc}") from exc

        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                detail = self._read_log_tail()
                self.stop()
                raise LocalUpstreamServiceError(
                    f"本地上游源码服务提前退出。{detail}".strip()
                )
            if _health_ready(self.base_url):
                return self
            time.sleep(0.25)
        detail = self._read_log_tail()
        self.stop()
        raise LocalUpstreamServiceError(f"等待本地上游源码服务启动超时。{detail}".strip())

    def _read_log_tail(self) -> str:
        if self._log is None:
            return ""
        try:
            self._log.flush()
            self._log.seek(0)
            content = self._log.read()
            return content[-1200:].strip()
        except OSError:
            return ""

    def _close_log(self) -> None:
        if self._log is not None:
            try:
                self._log.close()
            finally:
                self._log = None

    def stop(self) -> None:
        process = self.process
        self.process = None
        if process is not None and process.poll() is None:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill.exe", "/pid", str(process.pid), "/t", "/f"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    check=False,
                )
            else:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        self._close_log()

    def __enter__(self) -> "LocalUpstreamService":
        return self.start()

    def __exit__(self, _exc_type: Any, _exc: Any, _traceback: Any) -> None:
        self.stop()
