"""DeepSeek API Provider：json_object + Instructor 校验重试

要点：
- DeepSeek 兼容 OpenAI SDK，base_url=https://api.deepseek.com
- response_format 仅支持 json_object，配合 Instructor 实现校验失败重试
- 官方要求 prompt 中必须出现 "json" 字样并给出示例结构
- 使用 deepseek-v4-flash（复杂场景可换 v4-pro），旧 ID deepseek-chat 已下线
- Token 计量：instructor 的 create 不暴露 usage，因此在裸客户端上拦截
  create 调用，把最后一次真实响应的 usage 记录到 self.last_usage
"""
import os
import instructor
from openai import OpenAI
from typing import Type, TypeVar
from pydantic import BaseModel
from .base import LLMProvider

T = TypeVar("T", bound=BaseModel)


def _usage_dict(usage) -> dict:
    """Normalize an OpenAI usage object into a plain dict (None-safe)."""
    if usage is None:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
        "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
        "total_tokens": getattr(usage, "total_tokens", 0) or 0,
    }


class DeepSeekProvider(LLMProvider):
    """DeepSeek API：审查侧的异构 Provider"""

    def __init__(self, model: str = "deepseek-v4-flash"):
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY environment variable not set")
        raw = OpenAI(
            base_url="https://api.deepseek.com",
            api_key=api_key,
        )
        self._raw = raw
        self._last_usage: dict | None = None
        original_create = raw.chat.completions.create

        def _tracking_create(*args, **kwargs):
            resp = original_create(*args, **kwargs)
            self._last_usage = _usage_dict(getattr(resp, "usage", None))
            return resp

        # Wrap BEFORE instructor.patch so instructor's internal calls
        # (including its validation retries) go through the tracking wrapper.
        raw.chat.completions.create = _tracking_create
        self.client = instructor.patch(raw, mode=instructor.Mode.JSON)
        self.model = model

    @property
    def last_usage(self):
        """Token usage of the last underlying completion (None if no call yet)."""
        return self._last_usage

    def generate_structured(self, system_prompt, user_prompt, schema: Type[T], max_retries: int = 2) -> T:
        self._last_usage = None
        return self.client.chat.completions.create(
            model=self.model,
            response_model=schema,
            max_retries=max_retries,
            max_tokens=4096,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

    def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        self._last_usage = None
        resp = self._raw.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return resp.choices[0].message.content
