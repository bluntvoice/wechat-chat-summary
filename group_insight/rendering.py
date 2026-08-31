"""统一报告文档的移动端 HTML 与日报长图排版。"""

from __future__ import annotations

import html
import json
import re
import shutil
from pathlib import Path
from typing import Any

from .redaction import REDACTION_NOTICE


def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _member_names(stats: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in stats.get("member_aliases", []) or []:
        sender_id = str(item.get("sender_id") or "")
        sender_name = str(item.get("sender_name") or "")
        if sender_id and sender_name:
            result[sender_id] = sender_name
    return result


def _resolve(value: Any, names: dict[str, str]) -> str:
    text = str(value or "")
    return re.sub(r"\[\[user:([^\]]+)\]\]", lambda match: names.get(match.group(1), "群成员"), text)


def _text(item: Any, *keys: str) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        for key in keys:
            value = item.get(key)
            if value:
                return str(value)
    return ""


def _is_redacted(item: Any) -> bool:
    return isinstance(item, dict) and bool(item.get("redacted"))


def _redacted_html(item: dict[str, Any], tag: str = "article") -> str:
    time_label = _esc(item.get("time_label") or "当日")
    return (
        f'<{tag} class="redacted-card"><span>所属时间 · {time_label}</span>'
        f'<strong>{_esc(item.get("notice") or REDACTION_NOTICE)}</strong></{tag}>'
    )


def _legacy_document(kwargs: dict[str, Any]) -> dict[str, Any]:
    report = kwargs.get("report", {})
    stats = kwargs.get("stats", {})
    chat_name = str(kwargs.get("chat_name") or "群聊")
    start = str(kwargs.get("start_time") or "")
    date = start[:10]
    return {
        "schema_version": "legacy",
        "metadata": {
            "chat": {"id": kwargs.get("chat_id", ""), "name": chat_name},
            "period": {"start": start, "end": kwargs.get("end_time", ""), "report_date": date},
            "generated_at": "",
        },
        "stats": stats,
        "content": {
            "headline": f"{chat_name}：{date.replace('-', '')} 总结",
            "one_line_summary": report.get("one_line_summary") or report.get("tagline") or report.get("lead_summary", ""),
            "lead_summary": report.get("lead_summary", ""),
            "themes": report.get("theme_cards", []),
            "topics": report.get("sections", []),
            "members": report.get("participant_insights", []) or stats.get("top_speakers", []),
            "quotes": report.get("quotes", []),
            "decisions": report.get("decisions", []),
            "action_items": report.get("action_items", []),
            "open_questions": report.get("open_questions", []),
            "risk_flags": report.get("risk_flags", []),
            "mood": report.get("mood", {}),
            "resources": {"count": 0, "groups": []},
        },
    }


def render_html_report(document: dict[str, Any] | None = None, **legacy_kwargs: Any) -> str:
    """将 report schema v2 渲染为完整 HTML；PNG 模式仅保留摘要模块。"""
    if document is None:
        document = _legacy_document(legacy_kwargs)
    metadata = document.get("metadata", {})
    stats = document.get("stats", {})
    content = document.get("content", {})
    chat = metadata.get("chat", {})
    period = metadata.get("period", {})
    names = _member_names(stats)

    def resolved(value: Any) -> str:
        return _esc(_resolve(value, names))

    themes = content.get("themes", []) or []
    topics = content.get("topics", []) or []
    members = content.get("members", []) or stats.get("top_speakers", []) or []
    resources = content.get("resources", {}) or {}
    groups = resources.get("groups", []) or []

    metric_candidates = [
        ("今日消息", stats.get("message_count", 0), "条"),
        ("今日字数", stats.get("effective_char_count", 0), "字"),
        ("参与人数", stats.get("participant_count", 0), "人"),
    ]
    if resources.get("count", 0):
        metric_candidates.append(("整理资源", resources.get("count", 0), "项"))
    metric_html = "".join(
        f'<div class="metric"><span>{_esc(label)}</span><strong>{_esc(value)}</strong><small>{_esc(unit)}</small></div>'
        for label, value, unit in metric_candidates
    )

    theme_html = "".join(
        _redacted_html(item)
        if _is_redacted(item)
        else f'<article class="topic-card"><h3>{resolved(_text(item, "title"))}</h3><p>{resolved(_text(item, "summary"))}</p></article>'
        for item in themes[:5]
        if _is_redacted(item) or _text(item, "title", "summary")
    ) or '<p class="empty">今天没有形成明确的主题卡片。</p>'

    member_html = "".join(
        _redacted_html(item, "li")
        if _is_redacted(item)
        else f'<li><span class="rank">{index:02d}</span><div><strong>{resolved(_text(item, "name"))}</strong><p>{resolved(_text(item, "insight") or (str(item.get("message_count", 0)) + " 条消息" if isinstance(item, dict) else ""))}</p></div></li>'
        for index, item in enumerate(members[:6], 1)
    ) or '<li class="empty">暂无成员观察</li>'

    word_cloud = stats.get("word_cloud", []) or []
    words_html = "".join(
        f'<span class="word" style="--w:{min(5, 1 + int(item.get("count", 1)) // 4)}">{resolved(item.get("word", ""))}</span>'
        for item in word_cloud[:24]
        if item.get("word")
    ) or '<span class="empty">暂无关键词</span>'

    time_segments = stats.get("time_segment_breakdown", []) or []
    max_time = max([int(item.get("count", 0)) for item in time_segments] or [1])
    time_html = "".join(
        f'<div class="time-row"><span>{resolved(item.get("label", ""))}</span><i><b style="width:{max(3, round(100 * int(item.get("count", 0)) / max_time))}%"></b></i><strong>{_esc(item.get("count", 0))}</strong></div>'
        for item in time_segments
    )

    def render_resource_group(group: dict[str, Any]) -> str:
        if _is_redacted(group):
            return _redacted_html(group)
        items_html = "".join(
            _redacted_html(item, "div")
            if _is_redacted(item)
            else '<div class="resource-item">'
            f'<span class="resource-kind">{"文件" if item.get("type") == "file" else "链接"}</span>'
            f'<div><strong>{resolved(item.get("title") or item.get("file_name") or item.get("url"))}</strong>'
            f'<p>{resolved(item.get("context_summary", ""))}</p>'
            f'<small>{resolved(item.get("sender", ""))} · {resolved(item.get("sent_at", ""))}</small>'
            + (f'<a href="{_esc(item.get("url"))}" rel="noreferrer">查看链接</a>' if str(item.get("url", "")).startswith(("http://", "https://")) else "")
            + '</div></div>'
            for item in group.get("items", []) or []
        )
        return (
            '<article class="resource-group">'
            f'<header><h3>{resolved(group.get("topic", "其他 / 未归类"))}</h3><span>{len(group.get("items", []) or [])} 项</span></header>'
            f'<p class="group-note">{resolved(group.get("summary", ""))}</p>{items_html}</article>'
        )

    resource_groups_html = "".join(render_resource_group(group) for group in groups if isinstance(group, dict)) or '<p class="empty">当日未识别到可整理的链接或文件。</p>'

    detail_topics = "".join(
        _redacted_html(item)
        if _is_redacted(item)
        else '<article class="detail-topic">'
        f'<div class="topic-meta">{resolved(item.get("start_time", ""))} — {resolved(item.get("end_time", ""))}</div>'
        f'<h3>{resolved(item.get("title", "讨论主题"))}</h3><p>{resolved(item.get("summary", ""))}</p>'
        + (f'<ul>{"".join(f"<li>{resolved(bullet)}</li>" for bullet in item.get("bullets", []) or [])}</ul>' if item.get("bullets") else "")
        + (f'<blockquote>{resolved(item.get("takeaway", ""))}</blockquote>' if item.get("takeaway") else "")
        + '</article>'
        for item in topics
        if isinstance(item, dict)
    )

    def detail_list(title: str, items: list[Any], *keys: str) -> str:
        rows = [
            _redacted_html(item, "li") if _is_redacted(item) else f'<li>{resolved(_text(item, *keys))}</li>'
            for item in items
            if _is_redacted(item) or _text(item, *keys)
        ]
        if not rows:
            return ""
        return f'<section class="card html-detail"><h2>{_esc(title)}</h2><ul class="plain-list">' + "".join(rows) + '</ul></section>'

    mood = content.get("mood") if isinstance(content.get("mood"), dict) else {}
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{resolved(content.get('headline', '群聊总结'))}</title>
<style>
:root{{--ink:#24332b;--muted:#6d7b72;--green:#6eb982;--paper:#f4faef;--yellow:#fff7cf;--pink:#fff0f1;--blue:#edf7fb;}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font-family:"Microsoft YaHei UI","PingFang SC",sans-serif;line-height:1.65}}
.page{{width:min(100%,640px);margin:0 auto;padding:18px 16px 30px}} .hero{{padding:24px 22px;border-radius:18px;background:linear-gradient(145deg,#91d178,#b9e997);box-shadow:0 8px 24px #6da76822}}
.eyebrow{{display:inline-flex;padding:3px 10px;border-radius:99px;background:#efffe9aa;font-size:12px;font-weight:800;letter-spacing:.12em}} h1{{font-size:25px;line-height:1.3;margin:13px 0 9px;letter-spacing:-.02em}} .one-line{{font-size:14px;margin:0;color:#314b37}}
.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:18px}} .metric{{background:#ffffffbd;border:1px solid #ffffff91;border-radius:11px;padding:10px 9px;min-width:0}} .metric span{{display:block;font-size:10px;color:var(--muted)}} .metric strong{{font-size:20px;margin-right:2px}} .metric small{{font-size:10px}}
.card{{background:#fff;border:1px solid #e7efe2;border-radius:15px;margin-top:12px;padding:17px;box-shadow:0 3px 14px #748b6c0d}} .card h2{{font-size:16px;margin:0 0 12px;display:flex;align-items:center;gap:7px}} .card h2:before{{content:"";width:7px;height:7px;border-radius:50%;background:var(--green)}}
.topic-grid{{display:grid;gap:8px}} .topic-card{{padding:12px 13px;border-radius:11px;background:#fbfdf9;border-left:3px solid var(--green)}} .topic-card:nth-child(2n){{background:var(--yellow);border-color:#e6c75a}} .topic-card:nth-child(3n){{background:var(--pink);border-color:#e49ba5}} h3{{font-size:14px;margin:0 0 4px}} p{{margin:0;font-size:13px;color:#526159}}
.member-list{{list-style:none;padding:0;margin:0;display:grid;gap:6px}} .member-list li{{display:flex;gap:10px;padding:9px 10px;background:#f7fbf5;border-radius:10px}} .rank{{font:700 12px ui-monospace;color:var(--green);padding-top:2px}} .member-list strong{{font-size:13px}} .member-list p{{font-size:12px}}
.words{{display:flex;gap:8px 11px;align-items:baseline;flex-wrap:wrap;padding:6px 2px}} .word{{color:#4b8e60;font-weight:700;font-size:calc(11px + var(--w) * 1.5px)}} .time-row{{display:grid;grid-template-columns:35px 1fr 28px;align-items:center;gap:8px;font-size:11px;margin:7px 0}} .time-row i{{height:8px;border-radius:8px;background:#edf2e9;overflow:hidden}} .time-row b{{display:block;height:100%;background:linear-gradient(90deg,#8bd092,#5eae79);border-radius:8px}} .time-row strong{{text-align:right}}
.fun-grid{{display:grid;grid-template-columns:1fr 1fr;gap:8px}} .fun{{padding:11px;background:var(--blue);border-radius:10px}} .fun:nth-child(2){{background:var(--pink)}} .fun span{{display:block;font-size:11px;color:var(--muted)}} .fun strong{{font-size:14px}}
.resource-group{{border:1px solid #edf0df;border-radius:12px;padding:12px;margin-top:9px;background:#fffdf4}} .resource-group header{{display:flex;justify-content:space-between;gap:10px}} .resource-group header span{{font-size:11px;color:var(--muted)}} .group-note{{font-size:12px;margin-bottom:7px}} .resource-item{{display:grid;grid-template-columns:36px 1fr;gap:8px;border-top:1px dashed #e8e6d7;padding:9px 0}} .resource-kind{{font-size:10px;color:#48775a;background:#dff0df;border-radius:6px;height:max-content;text-align:center;padding:2px}} .resource-item strong{{font-size:12px;display:block}} .resource-item p,.resource-item small,.resource-item a{{display:block;font-size:10px;color:var(--muted)}} .resource-item a{{color:#3b79bb}}
.detail-topic{{padding:13px 0;border-top:1px dashed #dfe8da}} .detail-topic:first-of-type{{border-top:0}} .topic-meta{{font-size:10px;color:var(--green);font-weight:700}} .detail-topic ul,.plain-list{{padding-left:18px;font-size:12px}} blockquote{{margin:8px 0 0;padding:7px 9px;background:#f3f8f0;border-left:3px solid var(--green);font-size:12px;color:#526159}}
.redacted-card{{display:flex!important;flex-direction:column;align-items:flex-start;gap:4px;padding:12px 13px!important;margin:6px 0;border:1px dashed #d5b96a!important;border-radius:10px;background:#fff9e5!important;list-style:none}} .redacted-card span{{font-size:10px;color:#91783a}} .redacted-card strong{{font-size:12px;color:#6b5a32}}
.footer{{text-align:center;padding:20px 6px 0;font-size:10px;color:#8b978f}} .empty{{font-size:12px;color:#87928b}} body.export-png .html-detail{{display:none!important}} body.export-png .resource-group:nth-of-type(n+4),body.export-png .resource-item:nth-of-type(n+3){{display:none}}
@media(max-width:520px){{.page{{padding:0 10px 20px}}.hero{{border-radius:0 0 18px 18px;margin:0 -10px}}.metrics{{grid-template-columns:repeat(2,1fr)}}}}
</style></head><body><main class="page">
<header class="hero"><span class="eyebrow">群聊拾遗</span><h1>{resolved(content.get('headline'))}</h1><p class="one-line">{resolved(content.get('one_line_summary'))}</p><div class="metrics">{metric_html}</div></header>
<section class="card"><h2>今日热点</h2><div class="topic-grid">{theme_html}</div></section>
<section class="card"><h2>活跃成员</h2><ol class="member-list">{member_html}</ol></section>
<section class="card"><h2>群关键词</h2><div class="words">{words_html}</div></section>
<section class="card"><h2>活跃时段</h2>{time_html}</section>
<section class="card"><h2>今日侧写</h2><div class="fun-grid"><div class="fun"><span>整体氛围</span><strong>{resolved(mood.get('label', '平稳'))}</strong></div><div class="fun"><span>有效对话</span><strong>{_esc(stats.get('effective_message_count', 0))} 条</strong></div></div></section>
<section class="card"><h2>当日资源整理</h2>{resource_groups_html}</section>
<section class="card html-detail"><h2>详细讨论脉络</h2><p>{resolved(content.get('lead_summary'))}</p>{detail_topics}</section>
{detail_list('明确结论', content.get('decisions', []) or [], 'content')}
{detail_list('行动事项', content.get('action_items', []) or [], 'task')}
{detail_list('开放问题', content.get('open_questions', []) or [], 'question')}
{detail_list('风险提示', content.get('risk_flags', []) or [], 'content')}
{detail_list('引用原话', content.get('quotes', []) or [], 'content', 'text')}
<footer class="footer">报告由群聊拾遗生成 · {_esc(chat.get('name'))} · {_esc(period.get('report_date'))}</footer>
</main><script>if(new URLSearchParams(location.search).get('export')==='png')document.body.classList.add('export-png');</script></body></html>"""


def invalidate_cached_outputs_if_needed(output_dir: Path, signature: dict[str, Any]) -> None:
    """当运行签名变化时清理当前报告数据目录中的过期阶段缓存。"""
    signature_path = output_dir / "snapshot" / "run_signature.json"
    try:
        previous_signature = json.loads(signature_path.read_text(encoding="utf-8")) if signature_path.exists() else None
    except Exception:
        previous_signature = {}
    if previous_signature == signature:
        return
    for dirname in ("map", "reduce", "final"):
        target_dir = output_dir / dirname
        if target_dir.exists():
            shutil.rmtree(target_dir)
    for pattern in ("group_insight_report.json", "group_insight_report.html", "group_insight_report.png", "*_群聊总结.json", "*_群聊总结.html", "*_群聊总结.png"):
        for target_file in output_dir.glob(pattern):
            if target_file.is_file():
                target_file.unlink()
