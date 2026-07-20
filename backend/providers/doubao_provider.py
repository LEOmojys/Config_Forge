"""Doubao Coding Plan provider."""

import os
from typing import Type, TypeVar

from openai import OpenAI
from pydantic import BaseModel

from .base import LLMProvider

T = TypeVar("T", bound=BaseModel)

_DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/coding/v3"
_DEFAULT_MODEL = "ark-code-latest"


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


class DoubaoProvider(LLMProvider):
    """OpenAI-compatible provider for Ark Coding Plan."""

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

        print(f"[DoubaoProvider] BaseURL: {self.base_url}")
        print(f"[DoubaoProvider] Model candidates: {', '.join(self.models)}")

    def _call_json(self, system_prompt: str, user_prompt: str, schema: Type[T], max_retries: int) -> T:
        last_err = None
        for model in self.models:
            retry_err = None
            for _ in range(max_retries + 1):
                prompt = user_prompt
                if retry_err:
                    prompt += f"\n\n[Previous attempt failed validation: {retry_err}]"
                try:
                    resp = self.client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": prompt},
                        ],
                        response_format={"type": "json_object"},
                    )
                    self.model = model
                    return schema.model_validate_json(resp.choices[0].message.content)
                except Exception as err:
                    last_err = err
                    if _is_unavailable_model_error(err):
                        print(f"[DoubaoProvider] model unavailable: {model}")
                        break
                    retry_err = err
                    if _ == max_retries:
                        raise RuntimeError(
                            f"Doubao generation failed on model {model} "
                            f"after {max_retries + 1} attempts: {err}"
                        ) from err

        raise RuntimeError(f"Doubao generation failed: no compatible Coding Plan model: {last_err}")

    def _call_text(self, system_prompt: str, user_prompt: str, max_retries: int) -> str:
        last_err = None
        for model in self.models:
            for _ in range(max_retries + 1):
                try:
                    resp = self.client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                    )
                    self.model = model
                    return resp.choices[0].message.content
                except Exception as err:
                    last_err = err
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
