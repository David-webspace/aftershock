"""模型轉接：這個專案只需要一件事，就是強制模型呼叫一個工具，回傳符合 schema 的結構化結果。

- anthropic：Claude 官方 API（tool_choice 指定工具）
- openai_compatible：Azure OpenAI、vLLM、Ollama 等（tool_choice 指定函式；不支援的伺服器退回從文字抓 JSON）
"""

import json
import re
from dataclasses import dataclass
from typing import Protocol

from app.config import settings


@dataclass
class Extraction:
    args: dict | None
    model: str
    input_tokens: int
    output_tokens: int
    raw: str = ""


class LLM(Protocol):
    def extract(self, system: str, user: str, tool_name: str, tool_description: str, schema: dict) -> Extraction: ...


class AnthropicLLM:
    def __init__(self) -> None:
        import anthropic

        self.client = anthropic.Anthropic(api_key=settings.llm_api_key, base_url=settings.llm_base_url or None)

    def extract(self, system, user, tool_name, tool_description, schema) -> Extraction:
        r = self.client.messages.create(
            model=settings.llm_model, max_tokens=2048, system=system, messages=[{"role": "user", "content": user}],
            tools=[{"name": tool_name, "description": tool_description, "input_schema": schema}],
            tool_choice={"type": "tool", "name": tool_name})
        call = next((b for b in r.content if b.type == "tool_use"), None)
        return Extraction(dict(call.input) if call else None, r.model, r.usage.input_tokens, r.usage.output_tokens)


_JSON = re.compile(r"\{.*\}", re.S)
_THINK = re.compile(r"<think>.*?</think>", re.S)


class OpenAICompatibleLLM:
    def __init__(self) -> None:
        import openai

        self.client = openai.OpenAI(api_key=settings.llm_api_key or "not-needed", base_url=settings.llm_base_url)

    def extract(self, system, user, tool_name, tool_description, schema) -> Extraction:
        kwargs = dict(model=settings.llm_model, max_tokens=2048,
                      messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                      tools=[{"type": "function", "function": {"name": tool_name, "description": tool_description, "parameters": schema}}],
                      tool_choice={"type": "function", "function": {"name": tool_name}})
        if settings.llm_reasoning_effort:
            kwargs["reasoning_effort"] = settings.llm_reasoning_effort
        r = self.client.chat.completions.create(**kwargs)
        m = r.choices[0].message
        raw = m.tool_calls[0].function.arguments if m.tool_calls else _THINK.sub("", m.content or "")
        try:
            args = json.loads(raw) if m.tool_calls else json.loads(_JSON.search(raw).group(0))
        except (json.JSONDecodeError, AttributeError):
            args = None
        u = r.usage
        return Extraction(args, r.model or settings.llm_model, u.prompt_tokens if u else 0, u.completion_tokens if u else 0, raw)


PROVIDERS = {"anthropic": AnthropicLLM, "openai_compatible": OpenAICompatibleLLM}
_client: LLM | None = None


def not_configured() -> str | None:
    if settings.llm_provider not in PROVIDERS:
        return f"不支援的 LLM_PROVIDER「{settings.llm_provider}」"
    if settings.llm_provider == "anthropic" and not settings.llm_api_key:
        return "尚未設定 LLM_API_KEY"
    if settings.llm_provider == "openai_compatible" and not settings.llm_base_url:
        return "openai_compatible 需要設定 LLM_BASE_URL"
    return None


def get_llm() -> LLM:
    global _client
    if _client is None:
        _client = PROVIDERS[settings.llm_provider]()
    return _client
