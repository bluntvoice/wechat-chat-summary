"""报告目录、日期标签与同日版本分配。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .common import ensure_dir, slugify


def _parse_date(value: str) -> datetime:
    normalized = value.strip().replace("T", " ")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"无法识别日期时间: {value}") from exc


def build_report_date_label(start_time: str, end_time: str) -> str:
    """生成单日或多日报告使用的稳定日期标签。"""

    start_date = _parse_date(start_time).strftime("%Y-%m-%d")
    end_date = _parse_date(end_time).strftime("%Y-%m-%d")
    if start_date == end_date:
        return start_date
    return f"{start_date}_至_{end_date}"


@dataclass(frozen=True)
class ReportPaths:
    """一次报告运行使用的报告数据目录和独立 PNG 路径。"""

    chat_dir: Path
    data_dir: Path
    image_dir: Path
    data_stem: str
    image_path: Path
    date_label: str
    version: int


def allocate_report_paths(
    output_root: Path,
    chat_name: str,
    start_time: str,
    end_time: str,
) -> ReportPaths:
    """按“群聊/导出图+报告数据”结构分配一个不覆盖旧文件的新版本。"""

    chat_slug = slugify(chat_name)
    date_label = build_report_date_label(start_time, end_time)
    start_date = _parse_date(start_time)
    chat_dir = ensure_dir(output_root.expanduser() / chat_slug)
    data_root = ensure_dir(chat_dir / "报告数据")
    image_dir = ensure_dir(
        chat_dir / "导出图" / start_date.strftime("%Y") / start_date.strftime("%m")
    )

    version = 1
    while True:
        suffix = "" if version == 1 else f"_v{version}"
        data_dir = data_root / f"{date_label}报告数据{suffix}"
        image_path = image_dir / f"{date_label}报告{suffix}.png"
        if not data_dir.exists() and not image_path.exists():
            data_dir.mkdir(parents=True, exist_ok=False)
            return ReportPaths(
                chat_dir=chat_dir,
                data_dir=data_dir,
                image_dir=image_dir,
                data_stem=f"{chat_slug}_{date_label}_群聊总结{suffix}",
                image_path=image_path,
                date_label=date_label,
                version=version,
            )
        version += 1
