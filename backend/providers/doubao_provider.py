"""Doubao Coding Plan provider."""

import os
import re
import time
from typing import Type, TypeVar

from openai import OpenAI
from pydantic import BaseModel

from .base import LLMProvider

T = TypeVar("T", bound=BaseModel)

_DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/coding/v3"
_DEFAULT_MODEL = "ark-code-latest"
# ark-code-latest caps output at 32000 tokens; complex boss bundles (template +
# config + skills + links + loot + summon tree) hit the endpoint limit at 8192
# ("The output is incomplete due to a max_tokens length limit"), so default
# higher. Override with ARK_CODING_MAX_TOKENS.
_DEFAULT_MAX_TOKENS = 16384


def _unique_nonempty(*values: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        value = (value or "").strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _is_unavailable_model_error(err: Exception) -> bool:
    msg = str(err).lower()
    return (
        "invalidendpointormodel.notfound" in msg
        or "unsupportedmodel" in msg
        or "does not support the coding plan" in msg
        or "does not exist" in msg
        or "not found" in msg
        or ("model" in msg and "not exist" in msg)
    )


def _resolve_api_key() -> str:
    return (
        os.environ.get("ARK_CODING_API_KEY", "").strip()
        or os.environ.get("DOUBAO_API_KEY", "").strip()
        or os.environ.get("ARK_API_KEY", "").strip()
    )


def _resolve_max_tokens() -> int:
    raw = os.environ.get("ARK_CODING_MAX_TOKENS", "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return _DEFAULT_MAX_TOKENS


def _resolve_no_thinking() -> bool:
    """ARK_CODING_NO_THINKING: default ON (thinking disabled).

    ark-code-latest is a reasoning model whose thinking phase consumes the
    output token budget; on complex prompts this yields empty content
    (finish_reason=length). Structured config generation does not need the
    thinking phase, so disable it unless explicitly re-enabled with "0".
    """
    return os.environ.get("ARK_CODING_NO_THINKING", "1").strip() != "0"


def _repair_note(err: Exception) -> str:
    """Build a retry nudge. Empty output gets a targeted instruction;
    validation errors get a trimmed copy (pydantic errors embed the whole
    failed JSON, which would blow up the retry prompt)."""
    msg = str(err)
    if "empty output" in msg:
        return (
            "\n\n[上次输出为空：请务必直接输出完整的 JSON 对象，"
            "不要输出任何解释文字，并确保 JSON 以 } 结尾]"
        )
    if "EOF while parsing" in msg or "json_invalid" in msg:
        return (
            "\n\n[上次输出不是合法 JSON（可能被截断，或被 ```json 代码块包裹）："
            "请直接输出一个完整的 JSON 对象，不要使用任何 Markdown 代码块标记，"
            "确保所有字段与括号闭合，以 } 结尾]"
        )
    return f"\n\n[Previous attempt failed validation: {msg[:400]}]"


def _extract_json_content(content: str) -> str:
    """Strip Markdown code fences and surrounding whitespace.

    The Coding Plan endpoint does not reliably enforce
    response_format=json_object, so the model occasionally wraps the payload
    in ```json fences. Strip them before validation.
    """
    text = (content or "").strip()
    if text.startswith("```"):
        text = text[3:]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    return text


def _usage_dict(usage) -> dict:
    """Normalize an OpenAI usage object into a plain dict (None-safe)."""
    if usage is None:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "reasoning_tokens": 0}
    details = getattr(usage, "completion_tokens_details", None)
    reasoning_tokens = (getattr(details, "reasoning_tokens", 0) or 0) if details else 0
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
        "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
        "total_tokens": getattr(usage, "total_tokens", 0) or 0,
        "reasoning_tokens": reasoning_tokens,
    }


class DoubaoProvider(LLMProvider):
    """OpenAI-compatible provider for Ark Coding Plan."""

    # Candidates for reducing the reasoning/thinking phase, probed in order.
    # Which one is accepted depends on the model that ark-code-latest routes to
    # (observed: GLM-style models reject `thinking.type=disabled` and
    # `reasoning_effort=minimal` but accept `reasoning_effort=low`).
    _THINKING_EXTRAS = {
        "thinking_disabled": {"thinking": {"type": "disabled"}},
        "reasoning_minimal": {"reasoning_effort": "minimal"},
        "reasoning_low": {"reasoning_effort": "low"},
    }

    def __init__(self, model: str = None):
        api_key = _resolve_api_key()
        if not api_key:
            raise ValueError(
                "ARK_CODING_API_KEY (or DOUBAO_API_KEY / ARK_API_KEY) environment variable not set"
            )

        self.base_url = os.environ.get("ARK_CODING_BASE_URL", _DEFAULT_BASE_URL).strip() or _DEFAULT_BASE_URL
        env_model = (model or os.environ.get("ARK_CODING_MODEL", "") or os.environ.get("ARK_MODEL", "")).strip()
        configured_fallbacks = [
            item.strip()
            for item in os.environ.get("ARK_CODING_MODEL_FALLBACKS", "").split(",")
            if item.strip()
        ]
        self.models = _unique_nonempty(env_model, _DEFAULT_MODEL, *configured_fallbacks)
        self.client = OpenAI(base_url=self.base_url, api_key=api_key)
        self.model = self.models[0]
        # Output token budget: complex bundles (e.g. boss monsters with summon
        # trees) truncated mid-JSON when the endpoint default was too small.
        self.max_tokens = _resolve_max_tokens()
        # Disable the reasoning/thinking phase by default: it consumes the
        # output token budget and causes empty content on complex prompts.
        self.no_thinking = _resolve_no_thinking()
        # "probe" = not yet learned which param the routed model accepts;
        # None = thinking left enabled (no_thinking off or nothing accepted).
        self._thinking_mode = "probe" if self.no_thinking else None
        # Token usage of the last successful call (for observability).
        self.last_usage: dict | None = None

        print(f"[DoubaoProvider] BaseURL: {self.base_url}")
        print(f"[DoubaoProvider] Model candidates: {', '.join(self.models)}")
        print(f"[DoubaoProvider] max_tokens: {self.max_tokens}")
        print(f"[DoubaoProvider] thinking: {'reduce' if self.no_thinking else 'enabled'}")

    def _create(self, base_kwargs: dict):
        """chat.completions.create wrapper that adaptively reduces the thinking
        phase. The model routed behind ark-code-latest decides which parameter
        (if any) is accepted; probe once on first call, cache the winner."""
        if self._thinking_mode is None:
            return self.client.chat.completions.create(**base_kwargs)
        if self._thinking_mode != "probe":
            return self.client.chat.completions.create(
                **base_kwargs, extra_body=self._THINKING_EXTRAS[self._thinking_mode]
            )
        for mode, extra in self._THINKING_EXTRAS.items():
            try:
                resp = self.client.chat.completions.create(**base_kwargs, extra_body=extra)
                self._thinking_mode = mode
                print(f"[DoubaoProvider] thinking reduced via {mode}")
                return resp
            except Exception as err:
                msg = str(err).lower()
                if "invalidparameter" in msg and ("thinking" in msg or "reasoning_effort" in msg):
                    continue  # this param shape is rejected; try the next one
                raise
        # None of the reduction params are accepted: run with default thinking.
        self._thinking_mode = None
        print("[DoubaoProvider] thinking cannot be reduced by this model; running with default thinking")
        return self.client.chat.completions.create(**base_kwargs)

    def _call_json(self, system_prompt: str, user_prompt: str, schema: Type[T], max_retries: int) -> T:
        last_err = None
        for model in self.models:
            retry_err = None
            for attempt in range(max_retries + 1):
                prompt = user_prompt
                if retry_err:
                    prompt += retry_err
                try:
                    kwargs = {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": prompt},
                        ],
                        "response_format": {"type": "json_object"},
                        "max_tokens": self.max_tokens,
                    }
                    resp = self._create(kwargs)
                    self.model = model
                    msg = resp.choices[0].message
                    content = _extract_json_content(msg.content)
                    if not content:
                        finish_reason = resp.choices[0].finish_reason
                        reasoning_len = len(msg.reasoning_content or "")
                        raise ValueError(
                            f"model returned empty output "
                            f"(finish_reason={finish_reason}, reasoning_chars={reasoning_len})"
                        )
                    self.last_usage = _usage_dict(getattr(resp, "usage", None))
                    return schema.model_validate_json(content)
                except Exception as err:
                    last_err = err
                    if "invalidparameter" in str(err).lower():
                        # Permanent API parameter error: retrying is pointless.
                        raise
                    if _is_unavailable_model_error(err) or "empty output" in str(err):
                        # Model-level failure: try the next candidate model.
                        print(f"[DoubaoProvider] switching away from model: {model} ({err})")
                        break
                    retry_err = _repair_note(err)
                    if attempt == max_retries:
                        raise RuntimeError(
                            f"Doubao generation failed on model {model} "
                            f"after {max_retries + 1} attempts: {err}"
                        ) from err
                    time.sleep(0.5 * (attempt + 1))  # backoff before retry

        raise RuntimeError(f"Doubao generation failed: no compatible Coding Plan model: {last_err}")

    def _call_text(self, system_prompt: str, user_prompt: str, max_retries: int) -> str:
        last_err = None
        for model in self.models:
            for _ in range(max_retries + 1):
                try:
                    kwargs = {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                    }
                    resp = self._create(kwargs)
                    self.model = model
                    content = resp.choices[0].message.content
                    self.last_usage = _usage_dict(getattr(resp, "usage", None))
                    return content
                except Exception as err:
                    last_err = err
                    if "invalidparameter" in str(err).lower():
                        raise
                    if _is_unavailable_model_error(err):
                        print(f"[DoubaoProvider] model unavailable: {model}")
                        break
                    if _ == max_retries:
                        raise RuntimeError(
                            f"Doubao text generation failed on model {model} "
                            f"after {max_retries + 1} attempts: {err}"
                        ) from err

        raise RuntimeError(f"Doubao text generation failed: no compatible Coding Plan model: {last_err}")

    def generate_structured(self, system_prompt, user_prompt, schema: Type[T], max_retries: int = 2) -> T:
        return self._call_json(system_prompt, user_prompt, schema, max_retries)

    def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        return self._call_text(system_prompt, user_prompt, max_retries=2)
