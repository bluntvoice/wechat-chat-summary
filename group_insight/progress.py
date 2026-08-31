"""跨进程可轮询的报告生成阶段进度。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class ProgressReporter:
    def __init__(self, path: str | Path | None) -> None:
        self.path = Path(path) if path else None
        self.started_at = time.time()

    def update(self, stage: str, percent: int, message: str, **detail: Any) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "stage": stage,
            "percent": max(0, min(100, int(percent))),
            "message": message,
            "elapsed_seconds": round(time.time() - self.started_at, 1),
            "updated_at": time.time(),
            **detail,
        }
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.path)


def read_progress(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"stage": "waiting", "percent": 0, "message": "等待分析任务启动…", "elapsed_seconds": 0}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}
