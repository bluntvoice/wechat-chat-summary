"""AI Provider 客户端与群聊日报 prompt 构造。"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .chunking import chunk_payload, compact_direct_chunk_payload, compact_topic_index_payload, compact_topic_section_payload
from .common import safe_json_loads, extract_json_object
from .conversation import compact_prompt_stats
from .settings import (
    DEFAULT_API_URL,
    DEFAULT_DEEPSEEK_MODEL,
    DEFAULT_DEEPSEEK_REASONING_EFFORT,
    DEFAULT_DEEPSEEK_THINKING,
    DEFAULT_STRUCTURED_STAGE_MAX_TOKENS,
    DEFAULT_STRUCTURED_STAGE_MAX_TOKENS_THINKING,
)


class LLMClientProtocol:
    """所有 LLM 客户端需要实现的最小 JSON 对话协议。"""
    provider: str
    model: str

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int | None = None,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        """调用模型并返回解析后的 JSON 对象。"""
        raise NotImplementedError


DEEPSEEK_TEXT_MODELS = {"deepseek-v4-flash", "deepseek-v4-pro"}
LEGACY_DEEPSEEK_MODELS = {
    "deepseek-chat": "deepseek-v4-flash",
    "deepseek-reasoner": "deepseek-v4-flash",
}


def normalize_deepseek_model(model: str) -> str:
    """规范化并校验当前支持的 DeepSeek 文本模型。"""

    normalized = LEGACY_DEEPSEEK_MODELS.get((model or "").strip().lower(), (model or "").strip().lower())
    if normalized not in DEEPSEEK_TEXT_MODELS:
        choices = "、".join(sorted(DEEPSEEK_TEXT_MODELS))
        raise ValueError(f"DeepSeek 模型必须选择：{choices}")
    return normalized


def normalize_chat_completions_url(value: str, provider: str) -> str:
    """把 Provider 的 Base URL 或 endpoint 规范化为 Chat Completions URL。"""

    raw = (value or "").strip().rstrip("/")
    if not raw:
        raise ValueError("API URL 不能为空。")
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("API URL 必须是有效的 http/https 地址。")
    if parsed.username or parsed.password:
        raise ValueError("API URL 不得包含用户名或密码。")
    path = parsed.path.rstrip("/")
    if not path:
        path = "/chat/completions" if provider == "deepseek" else "/v1/chat/completions"
    elif not path.endswith("/chat/completions"):
        path += "/chat/completions"
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, ""))


class OpenAICompatibleClient(LLMClientProtocol):
    """通用 OpenAI Compatible Chat Completions JSON 客户端。"""

    def __init__(
        self,
        api_key: str,
        model: str,
        api_url: str = "",
        timeout: int = 180,
        max_retries: int = 3,
        allow_json_repair: bool = False,
    ) -> None:
        """初始化客户端配置和限频/重试参数。"""
        self.provider = "openai-compatible"
        self.api_key = (api_key or "").strip()
        self.model = (model or "").strip()
        if not self.api_key:
            raise ValueError("AI API Key 不能为空。")
        if not self.model:
            raise ValueError("模型名称不能为空。")
        self.api_url = normalize_chat_completions_url(api_url, self.provider)
        self.timeout = timeout
        self.max_retries = max_retries
        self.allow_json_repair = allow_json_repair
        self.last_response_model = ""

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int | None = None,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        """调用模型并返回解析后的 JSON 对象。"""
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            content = ""
            try:
                content = self._request_content(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                if not content.strip():
                    raise ValueError(f"{self.provider} 返回空内容")
                return safe_json_loads(content)
            except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, ValueError, RuntimeError) as exc:
                last_error = self._redact_error(exc)
                if isinstance(exc, json.JSONDecodeError) and self.allow_json_repair:
                    try:
                        repaired = self._repair_json(
                            broken_json=content,
                            max_tokens=max_tokens,
                        )
                        if repaired:
                            return safe_json_loads(repaired)
                    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, ValueError, RuntimeError) as repair_exc:
                        last_error = self._redact_error(repair_exc)
                if attempt >= self.max_retries:
                    break
                time.sleep(attempt * 2)
        raise RuntimeError(f"{self.provider} 调用失败: {last_error}") from last_error

    def _redact_error(self, error: Exception) -> Exception:
        """避免上游错误正文回显当前 API Key。"""

        message = str(error).replace(self.api_key, "[REDACTED]")
        return RuntimeError(message)

    def _request_content(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int | None,
        temperature: float,
    ) -> str:
        """发送一次 HTTP 请求并返回模型原始文本内容。"""
        payload = self._build_payload(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.api_url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:
                detail = ""
            if detail:
                safe_detail = detail.replace(self.api_key, "[REDACTED]")
                raise RuntimeError(f"HTTP {exc.code} {exc.reason}: {safe_detail[:1000]}") from exc
            raise
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError(f"{self.provider} 返回了非对象响应")
        self.last_response_model = str(parsed.get("model") or "").strip()
        choices = parsed.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ValueError(f"{self.provider} 响应缺少 choices")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise ValueError(f"{self.provider} 响应缺少 message")
        content = message.get("content", "")
        if not isinstance(content, str):
            raise ValueError(f"{self.provider} 返回了非文本 content")
        return content

    def _build_payload(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int | None,
        temperature: float,
    ) -> dict[str, Any]:
        """构造通用 Chat Completions 请求体。"""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": temperature,
            "stream": False,
        }
        if max_tokens is not None and max_tokens > 0:
            payload["max_tokens"] = max_tokens
        return payload

    def _repair_json(self, broken_json: str, max_tokens: int | None) -> str:
        """在 Provider 返回 JSON 截断或损坏时请求模型修复。"""
        candidate = extract_json_object(broken_json) or broken_json
        candidate = candidate.strip()
        if not candidate:
            raise ValueError("empty broken json")

        repair_system_prompt = """
你是一个 JSON 修复器。你会收到一段损坏或截断的 JSON。

要求：
1. 只输出一个合法 JSON 对象。
2. 不要添加 markdown、解释、注释。
3. 尽量保留原字段和原值。
4. 若局部截断无法恢复，删除损坏字段或把该字段改为空数组/空字符串，但必须保持整体 JSON 合法。
5. 所有括号、引号、逗号都必须正确闭合。
""".strip()
        repair_user_prompt = f"""
请把下面这段损坏 JSON 修复成合法 JSON 对象，只输出修复后的 JSON：

{candidate}
""".strip()
        return self._request_content(
            system_prompt=repair_system_prompt,
            user_prompt=repair_user_prompt,
            max_tokens=min(max_tokens, 4096) if max_tokens is not None else 4096,
            temperature=0.0,
        )


class DeepSeekClient(OpenAICompatibleClient):
    """在通用协议上增加 DeepSeek 专属能力。"""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_DEEPSEEK_MODEL,
        api_url: str = DEFAULT_API_URL,
        timeout: int = 180,
        max_retries: int = 3,
        allow_json_repair: bool = False,
        thinking_enabled: bool = DEFAULT_DEEPSEEK_THINKING,
        reasoning_effort: str = DEFAULT_DEEPSEEK_REASONING_EFFORT,
    ) -> None:
        normalized_model = normalize_deepseek_model(model)
        super().__init__(
            api_key=api_key,
            model=normalized_model,
            api_url=api_url,
            timeout=timeout,
            max_retries=max_retries,
            allow_json_repair=allow_json_repair,
        )
        self.provider = "deepseek"
        self.api_url = normalize_chat_completions_url(api_url, self.provider)
        self.thinking_enabled = bool(thinking_enabled)
        self.reasoning_effort = (reasoning_effort or "").strip().lower()
        if self.reasoning_effort not in {"high", "max"}:
            raise ValueError("DeepSeek Reasoning Effort 只能是 high 或 max。")

    def _build_payload(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int | None,
        temperature: float,
    ) -> dict[str, Any]:
        payload = super()._build_payload(system_prompt, user_prompt, max_tokens, temperature)
        payload["thinking"] = {"type": "enabled" if self.thinking_enabled else "disabled"}
        if self.thinking_enabled:
            payload["reasoning_effort"] = self.reasoning_effort
        return payload

    def get_user_balance(self) -> dict[str, Any]:
        """查询当前 DeepSeek 账号余额。"""

        request = urllib.request.Request(
            build_deepseek_balance_url(self.api_url),
            headers={"Accept": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            if detail:
                safe_detail = detail.replace(self.api_key, "[REDACTED]")
                raise RuntimeError(f"HTTP {exc.code} {exc.reason}: {safe_detail[:1000]}") from exc
            raise
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise RuntimeError("DeepSeek 余额接口返回了非对象响应")
        return parsed


def llm_cache_identity(client: LLMClientProtocol | None) -> str:
    """生成用于阶段缓存指纹的 LLM 配置标识。"""
    if client is None:
        return ""
    parts = [client.provider, client.model]
    thinking_enabled = getattr(client, "thinking_enabled", None)
    if thinking_enabled is not None:
        parts.append("thinking=enabled" if thinking_enabled else "thinking=disabled")
    reasoning_effort = getattr(client, "reasoning_effort", "")
    if thinking_enabled and reasoning_effort:
        parts.append(f"effort={reasoning_effort}")
    return "|".join(parts)


def build_deepseek_balance_url(api_url: str) -> str:
    """从 chat completions 地址推导余额查询地址。"""
    parsed = urllib.parse.urlsplit(api_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"无法从 API URL 推导余额接口地址: {api_url}")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/user/balance", "", ""))


def format_balance_snapshot(snapshot: dict[str, Any]) -> str:
    """把余额快照格式化为易读文本。"""
    status = "available" if snapshot.get("is_available") else "unavailable"
    infos = snapshot.get("balance_infos", [])
    if not isinstance(infos, list) or not infos:
        return f"status={status}"
    parts: list[str] = [f"status={status}"]
    for info in infos:
        if not isinstance(info, dict):
            continue
        currency = str(info.get("currency") or "UNKNOWN")
        total = str(info.get("total_balance") or "0")
        granted = str(info.get("granted_balance") or "0")
        topped_up = str(info.get("topped_up_balance") or "0")
        parts.append(f"{currency}: total={total} granted={granted} topped_up={topped_up}")
    return " | ".join(parts)


def format_balance_delta(before: dict[str, Any], after: dict[str, Any]) -> str:
    """对比两次余额快照并输出差值。"""
    before_infos = {
        str(item.get("currency") or "UNKNOWN"): item
        for item in before.get("balance_infos", [])
        if isinstance(item, dict)
    }
    after_infos = {
        str(item.get("currency") or "UNKNOWN"): item
        for item in after.get("balance_infos", [])
        if isinstance(item, dict)
    }
    currencies = sorted(set(before_infos) | set(after_infos))
    if not currencies:
        return "no balance info"
    parts: list[str] = []
    for currency in currencies:
        before_total = float(before_infos.get(currency, {}).get("total_balance") or 0)
        after_total = float(after_infos.get(currency, {}).get("total_balance") or 0)
        delta = after_total - before_total
        parts.append(
            f"{currency}: {before_total:.4f} -> {after_total:.4f} (delta {delta:+.4f})"
        )
    return " | ".join(parts)


def structured_stage_max_tokens_for_client(
    client: LLMClientProtocol | None,
    base_max_tokens: int = DEFAULT_STRUCTURED_STAGE_MAX_TOKENS,
) -> int:
    """为固定结构化阶段选择合适的输出预算。"""
    if client is None or client.provider != "deepseek":
        return base_max_tokens
    if not getattr(client, "thinking_enabled", False):
        return base_max_tokens
    return max(base_max_tokens, DEFAULT_STRUCTURED_STAGE_MAX_TOKENS_THINKING)


MAP_SCHEMA_EXAMPLE = {
    "shard_id": "shard-001",
    "time_range": {"start": "2026-04-08 09:00", "end": "2026-04-08 10:30"},
    "summary": "该时间片主要围绕一个或多个连续话题展开。",
    "theme_cards": [
        {
            "title": "主题标题",
            "summary": "该主题在这个时间片里的简明总结。",
            "evidence_ids": ["m_xxx", "m_yyy"],
        }
    ],
    "highlight_sections": [
        {
            "topic_key": "稳定的话题标识，例如 sushi-queue",
            "title": "一个可单独成段的话题簇标题",
            "start_time": "2026-04-08 09:12",
            "end_time": "2026-04-08 09:35",
            "discussion_flow": "用连续叙述说明这个话题如何被提起、展开和推进。",
            "outcome": None,
            "action_items": [],
            "open_questions": [],
            "risk_flags": [],
            "quotes": [],
            "resource_ids": [],
            "evidence_ids": ["m_xxx", "m_yyy"],
        }
    ],
    "participant_notes": [
        {
            "name": "[[user:wxid_xxx]]",
            "observation": "[[user:wxid_xxx]] 在本片段中的作用或表现。",
            "evidence_ids": ["m_xxx"],
        }
    ],
    "light_moments": [{"content": "群友间的玩笑或调侃", "evidence_ids": ["m_xxx"], "tone": "joke"}],
    "mood": {
        "label": "活跃/理性/轻松/焦虑/冲突等",
        "reason": "判断依据",
        "evidence_ids": ["m_xxx"],
    },
}


REDUCE_SCHEMA_EXAMPLE = {
    "bundle_id": "reduce-001",
    "summary": "多片段合并后的摘要",
    "theme_cards": [
        {"title": "核心主题", "summary": "主题归纳", "source_refs": ["shard-001"]}
    ],
    "highlight_sections": [
        {
            "topic_key": "跨片段保持一致的话题标识",
            "title": "重要话题簇",
            "time_ranges": [
                {"start": "2026-04-08 09:12", "end": "2026-04-08 10:30"},
                {"start": "2026-04-08 15:10", "end": "2026-04-08 15:35"},
            ],
            "discussion_flow": "跨片段合并后的连续讨论脉络",
            "outcome": None,
            "action_items": [],
            "open_questions": [],
            "risk_flags": [],
            "quotes": [],
            "resource_ids": [],
            "source_refs": ["shard-001", "shard-002"],
        }
    ],
    "participant_notes": [
        {"name": "[[user:wxid_xxx]]", "observation": "[[user:wxid_xxx]] 的角色观察", "source_refs": ["shard-001"]}
    ],
    "light_moments": [{"content": "轻松插曲", "source_refs": ["shard-001"], "tone": "joke"}],
    "mood": {"label": "整体氛围", "reason": "原因", "source_refs": ["shard-001"]},
}


FINAL_REPORT_SCHEMA_EXAMPLE = {
    "headline": "一句报告总标题",
    "tagline": "一句短副标题",
    "lead_summary": "1-2 段的默认总结",
    "one_line_summary": "一句精炼自然的当日摘要",
    "theme_cards": [
        {"title": "主题一", "summary": "适合展示在摘要卡片中的简短文本"}
    ],
    "sections": [
        {
            "id": "topic-sushi-queue",
            "title": "话题簇标题",
            "start_time": "2026-04-08 09:12",
            "end_time": "2026-04-08 10:30",
            "time_ranges": [
                {"start": "2026-04-08 09:12", "end": "2026-04-08 10:30"},
                {"start": "2026-04-08 15:10", "end": "2026-04-08 15:35"},
            ],
            "discussion_flow": "讨论如何被提起。\n不同成员分别补充了什么观点。\n讨论最后推进到什么状态。",
            "outcome": None,
            "action_items": [],
            "open_questions": [{"question": "仍需解决的严肃问题", "tone": "formal", "confidence": 0.88}],
            "risk_flags": [{"content": "需要继续观察的风险", "tone": "formal", "confidence": 0.85}],
            "quotes": [{"speaker": "[[user:wxid_xxx]]", "time": "2026-04-08 09:23", "quote": "一句代表性原话"}],
            "resource_ids": ["res_xxx"],
        }
    ],
    "ai_observations": [
        {"title": "整体氛围", "content": "克制、基于证据的观察", "kind": "mood"}
    ],
    "participant_insights": [
        {"name": "[[user:wxid_xxx]]", "insight": "[[user:wxid_xxx]] 的关键作用或状态"}
    ],
    "light_moments": [{"content": "明确的玩笑、调侃或轻松插曲", "tone": "joke"}],
    "mood": {"label": "整体氛围", "reason": "判断依据"},
    "conclusion": "一句简短自然的报告结语",
}


def build_map_prompts(chat_name: str, chunk: MessageChunk) -> tuple[str, str]:
    """构造 map 阶段对单个消息片段的分析提示词。"""
    system_prompt = f"""
你是一个严谨的群聊分析师。请基于用户提供的群聊时间片消息做结构化分析，并只输出 json。

要求：
1. 只基于提供的消息内容，不要补充外部事实。
2. 所有数组字段都必须存在，没内容时返回空数组。
3. evidence_ids 必须引用输入消息中的 id。
4. 主题和亮点要偏“可直接上报表”的表达，不要写成学术论文。
5. 允许保留轻度口语化，但不能夸张、不能编造。
6. 控制片段输出长度，但要保留话题缘起、观点变化和阶段结果所需的信息。
7. theme_cards 最多 3 条，highlight_sections 最多 4 条，participant_notes 最多 4 条。
8. 每个话题以 discussion_flow 为核心，通常 50-250 个汉字；信息较少就短写，不得为了长度重复同义内容。信息较多时使用 2-5 个换行分隔的短段，优先按讨论顺序、不同成员观点或子问题组织；同一成员连续表达的内容必须保留在同一段，不能仅因字数较长拆成两段，不要输出 Markdown 项目符号。
9. outcome 固定返回 null，不生成讨论落点；open_questions/risk_flags/quotes/resource_ids 是可选细节，没有可靠内容就返回空数组。action_items 固定返回空数组，不提取行动事项。
10. 每个话题 quotes 默认 0-1 条、最多 2 条；open_questions 最多 2 条；其余可选项只保留直接影响后续理解的信息。
11. highlight_sections 表示语义话题而不是机械时间切段；时间相邻只是弱线索。只有讨论对象、核心问题与上下文指向相同，或存在明确回复/承接关系时才能合并。
12. 同一时间窗口出现不同讨论对象时必须拆开，时间范围允许重叠；严禁把先后出现但语义无关的话题串成同一个 discussion_flow。
13. 不要只写最显眼的主线，持续时间较短但消息量可观、内容明确的次级话题也要覆盖。
14. 输入里会提供 member_directory；提到具体成员时，请统一使用对应的 `[[user:sender_id]]` 占位符，不要直接输出昵称。
15. 必须区分正式讨论、轻松闲聊、玩笑、夸张、反话与调侃；明显或高度疑似玩笑不得写入 open_questions/risk_flags。
16. open_questions/risk_flags 必须提供 tone 与 confidence；证据不足、可能是玩笑或只是随口一提时省略或放入 light_moments。
17. 为同一语义话题生成稳定、简短的 topic_key；同一时间片内再次出现的同一话题不要拆成多个 key。

输出 json schema 示例：
{json.dumps(MAP_SCHEMA_EXAMPLE, ensure_ascii=False, indent=2)}
""".strip()
    user_prompt = f"""
请分析群聊“{chat_name}”的一个时间片，并输出严格 json。

时间片数据：
{json.dumps(chunk_payload(chunk), ensure_ascii=False, indent=2)}
""".strip()
    return system_prompt, user_prompt


def build_reduce_prompts(bundle_id: str, items: list[dict[str, Any]]) -> tuple[str, str]:
    """构造 reduce 阶段合并多个片段结果的提示词。"""
    system_prompt = f"""
你是一个群聊分析 reducer。你会收到多个 shard 分析结果或中间 reduce 结果，请将它们合并成一个更高层摘要，并只输出 json。

要求：
1. 只整合输入中的已有信息，不要引入外部信息。
2. 去重同类主题和话题内部重复细节；信息较多的 discussion_flow 保留 2-5 个有推进关系的短段。同一成员连续表达必须合并在同一段，只有发言人、子问题或讨论阶段发生变化时才分段；不要拆成同义要点，不要输出 Markdown 项目符号。
3. highlight_sections 应按语义话题整理；跨 shard 只有在讨论对象、核心问题和上下文指向一致，或存在明确回复/承接关系时才合并，并用 time_ranges 保留多个区间。
4. source_refs 必须引用输入里的 shard_id 或 bundle_id。
5. outcome 固定返回 null，不生成讨论落点；open_questions/risk_flags/quotes/resource_ids 是可选细节，无可靠内容就返回空数组。action_items 固定返回空数组，不提取行动事项。
6. discussion_flow 通常 50-250 个汉字；保留理解讨论发展所需的缘起、观点、补充、转折或结果，但不重复同义信息；较长内容用换行分成 2-5 个短段。
7. theme_cards 最多 4 条，highlight_sections 最多 6 条，participant_notes 最多 6 条。
8. 每个话题 quotes 默认 0-1 条、最多 2 条，open_questions 最多 2 条。
9. 合并时检查是否遗漏持续但相对次级的话题，不要只保留最热主线。
10. 不要求每个 shard/bundle 都形成一个 section；普通闲聊或无独立信息量的片段可以不进入主要话题。
11. 时间接近或相邻不能单独作为合并依据；讨论对象不同、问题不同或没有承接关系时必须分开。
12. 如果输入里出现 `[[user:sender_id]]` 占位符，输出时保留该占位符，不要改写成昵称。
13. 合并时保留 tone/confidence；疑似玩笑、调侃、夸张或反话不能升级成开放问题或风险。

输出 json schema 示例：
{json.dumps(REDUCE_SCHEMA_EXAMPLE, ensure_ascii=False, indent=2)}
""".strip()
    user_prompt = f"""
请把以下多个群聊分析结果合并为一个中间 bundle，并输出严格 json。

目标 bundle_id: {bundle_id}

输入：
{json.dumps(items, ensure_ascii=False, indent=2)}
""".strip()
    return system_prompt, user_prompt


def build_final_prompts(
    chat_name: str,
    start_time: str,
    end_time: str,
    stats: dict[str, Any],
    bundles: list[dict[str, Any]],
    resources: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    """构造 final 阶段生成最终日报结构的提示词。"""
    system_prompt = f"""
你是一个中文群聊洞察报表编辑。你会收到本地统计数据和一组最终 reduce bundles，请产出适合日报/周报页面渲染的最终结构化结果，并只输出 json。

要求：
1. 只基于输入，不得补充不存在的数字。
2. theme_cards 是“今日速览”，动态生成约 3-5 条短卡片；不强制凑足，不展开完整讨论过程。
3. sections 是“今日主要话题”，表示语义话题而不是机械时间段；数量根据当天内容动态决定，不设最低数量。
4. 报表语言要像运营洞察报告，不要写成泛泛总结。
5. 每个 section 以 discussion_flow 为唯一必需正文，自然叙述缘起、展开、观点、补充、转折与进展；通常 50-250 个汉字，信息少就短写，禁止同义反复。内容较长时使用 2-5 个换行分隔的短段，按讨论顺序、不同成员观点或子问题选择最自然的组织方式；同一成员连续表达必须保留在同一段，不能仅因字数较长拆成两段，不要输出 Markdown 项目符号。
6. outcome 固定返回 null，不生成讨论落点；open_questions/risk_flags/quotes/resource_ids 为话题内可选字段，没有可靠内容就返回空数组。action_items 固定返回空数组，不提取行动事项。
7. theme_cards 最多 5 条且每条只做速览，不复述完整 discussion_flow；participant_insights 最多 6 条。
8. 每个 section 的 quotes 默认 0-1 条、最多 2 条；open_questions 最多 2 条；其余可选细节从严保留。
9. 如果多个话题的主要活跃时间交叠，允许不同 sections 的 start_time / end_time 重叠，不要为了避免重叠而把不同主题强行糅合成一段。
10. 覆盖当日所有明显成型且有信息量的话题；普通闲聊不必为了覆盖时间线而进入 sections。
11. 同一话题上午出现、下午继续时必须合并为一个 section，并用 time_ranges 记录多个区间。
12. 不要因为时间不连续拆分同一话题，也不要为了减少数量合并无关话题；时间相邻只是弱线索，必须同时核对讨论对象、核心问题、语义和回复承接关系。
13. 如果输入里的 bundles 使用 `[[user:sender_id]]` 占位符，最终输出请保留这些占位符，不要改写成昵称。
14. one_line_summary 必须精炼自然，概括当天真正有区分度的内容，避免机械复述消息数，建议不超过 60 个汉字。
15. 特别区分正式讨论与轻松闲聊、玩笑、夸张、反话和群友调侃。明显或高度疑似玩笑不得作为客观事实、结论、开放问题或风险；light_moments 仅用于内部过滤，不作为对外报告模块。
16. open_questions/risk_flags 采用高判定门槛。结构化对象必须提供 tone/confidence，并如实保留；不得把 casual/joke/sarcasm/teasing/uncertain 升级为 formal。
17. section.resource_ids 只能引用资源清单中真实存在的 resource_id；只有资源标题、上下文或原消息与该话题语义明确一致时才关联，不能可靠归类时不要塞进任何话题。
18. ai_observations 回答“从今天这些聊天中可以观察到什么”，不得重复话题摘要，不得推测成员性格、关系或真实意图，也不得生成“讨论弱点”“讨论不足”“讨论短板”等对群聊质量的泛化批评。
19. 结论、问题、风险和引用直接放入所属 section；无法可靠关联时省略，不得强行归类。
20. 不论讨论是否形成结论，outcome 都必须返回 null；必要进展只在 discussion_flow 中客观叙述，不另设讨论落点。
21. conclusion 是简短结语，不复述整份报告，不包含虚构事实。

最终 json schema 示例：
{json.dumps(FINAL_REPORT_SCHEMA_EXAMPLE, ensure_ascii=False, indent=2)}
""".strip()
    user_prompt = f"""
请为群聊“{chat_name}”生成最终结构化报表 json。

统计区间：{start_time} ~ {end_time}

本地精确统计：
{json.dumps(stats, ensure_ascii=False, indent=2)}

最终 reduce 输入：
{json.dumps(bundles, ensure_ascii=False, indent=2)}

当日资源清单（只按 resource_id 引用，不要改写 URL）：
{json.dumps(resources or [], ensure_ascii=False, indent=2)}
""".strip()
    return system_prompt, user_prompt


def build_direct_final_prompts(
    chat_name: str,
    start_time: str,
    end_time: str,
    stats: dict[str, Any],
    chunk: MessageChunk,
) -> tuple[str, str]:
    """构造 direct_range 模式下直接生成最终日报的提示词。"""
    compact_stats = compact_prompt_stats(stats)
    system_prompt = """
你是一个中文群聊洞察报表编辑。你会收到本地统计数据和完整群聊消息，请直接产出适合日报/周报页面渲染的最终结构化结果，并只输出 json。

要求：
1. 只基于输入，不得补充不存在的数字。
2. 这是 direct_range 模式，请直接从原始消息提炼主题，不要先按连续时间片机械概括。
3. sections 是报告主体，表示“话题簇”而不是机械时间段；数量控制在 8-15 段，允许时间范围重叠。
4. 不要只保留抽象结论；保留关键人、具体事件、分歧点、工具/食物/运动/祝福等可复述细节。
5. 重复寒暄和刷屏内容可以合并，但持续时间较短且内容明确的话题也要覆盖。
6. sections 每段 bullets 最多 3 条；每条 bullet 应包含具体信息，不要写空泛评价。
7. theme_cards 最多 4 条，participant_insights 最多 8 条，quotes 最多 6 条。
8. action_items 固定返回空数组，不提取行动事项；open_questions/risk_flags 只有在确实没有明确问题或风险时才返回空数组。
9. 消息中的 sender_ref 已是 `[[user:sender_id]]` 占位符；提到具体成员时保留该占位符，不要改写成昵称。
10. 输出必须是合法 JSON 对象，不要添加 markdown 或解释。
11. JSON 字段：headline, tagline, lead_summary, theme_cards, sections, participant_insights, quotes, decisions, action_items, open_questions, risk_flags, mood。
12. sections 字段：title, start_time, end_time, summary, bullets, takeaway。
13. decisions/open_questions/risk_flags 必须提供 tone 与 confidence；玩笑、调侃、反话、随口夸张或低置信度内容不得进入这些严肃模块。
""".strip()
    user_prompt = f"""
请为群聊“{chat_name}”生成最终结构化报表 json。

统计区间：{start_time} ~ {end_time}

紧凑统计：
{json.dumps(compact_stats, ensure_ascii=False, separators=(",", ":"))}

完整 direct_range 消息采用紧凑文本格式，字段顺序为：
time|sender_ref|message_type|text

{json.dumps(compact_direct_chunk_payload(chunk), ensure_ascii=False, separators=(",", ":"))}
""".strip()
    return system_prompt, user_prompt


def build_topic_plan_prompts(
    chat_name: str,
    start_time: str,
    end_time: str,
    stats: dict[str, Any],
    chunk: MessageChunk,
    max_topics: int,
) -> tuple[str, str]:
    """构造 topic-first 第一阶段主题聚类计划提示词。"""
    compact_stats = compact_prompt_stats(stats)
    payload = compact_topic_index_payload(chunk)
    system_prompt = f"""
你是一个群聊主题聚类器。你会收到完整群聊消息的紧凑索引，请只输出 JSON。

任务：
1. 按“话题簇”聚类，而不是按连续时间段切片。
2. 同一时间段内可以有多个 topic；同一条消息也可以被多个 topic 引用。
3. 覆盖主要话题，也保留短但内容明确的支线话题。
4. 每个 topic 的 message_indexes 必须引用输入里的 idx，按相关度和时间顺序列出。
5. topic 数量控制在 8-{max_topics} 个；如果内容不足可以少于 8 个。
6. 输出 JSON 字段：topics。
7. 每个 topic 字段：topic_id, title, summary, message_indexes, start_time, end_time, priority。
8. priority 只能是 major 或 minor。
""".strip()
    user_prompt = f"""
请为群聊“{chat_name}”生成主题聚类计划。

统计区间：{start_time} ~ {end_time}

紧凑统计：
{json.dumps(compact_stats, ensure_ascii=False, separators=(",", ":"))}

消息格式：
idx|time|sender_ref|message_type|text

输入消息：
{json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}
""".strip()
    return system_prompt, user_prompt


def build_topic_section_prompts(
    chat_name: str,
    topic: dict[str, Any],
    messages: list[StructuredMessage],
) -> tuple[str, str]:
    """构造 topic-first 单主题 section 分析提示词。"""
    payload = compact_topic_section_payload(topic, messages)
    system_prompt = """
你是一个群聊话题 section 分析器。你会收到一个 topic 的相关原始消息，请只输出 JSON。

要求：
1. 只分析当前 topic，不要扩展到无关话题。
2. 保留具体事件、分歧点、成员动作和可复述细节。
3. section 字段：title, start_time, end_time, summary, bullets, takeaway。
4. bullets 最多 3 条，必须具体。
5. quotes 最多 2 条，字段：speaker, time, quote, message_id, why_it_matters。
6. participant_insights 最多 3 条，字段：name, insight。
7. action_items 固定返回空数组，不提取行动事项；decisions/open_questions/risk_flags 只有在确实没有明确结论、问题或风险时才返回空数组。
8. 提到成员时保留 `[[user:sender_id]]` 占位符。
9. 输出 JSON 字段：topic_id, section, participant_insights, quotes, decisions, action_items, open_questions, risk_flags。
10. decisions/open_questions/risk_flags 必须提供 tone 与 confidence；玩笑、调侃、反话和低置信度内容不得进入严肃模块。
""".strip()
    user_prompt = f"""
请为群聊“{chat_name}”的这个 topic 生成一个详细 section。

输入格式：
message_id|time|sender_ref|message_type|text

topic 与相关消息：
{json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}
""".strip()
    return system_prompt, user_prompt
