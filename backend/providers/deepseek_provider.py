"""DeepSeek API Provider：json_object + Instructor 校验重试

要点：
- DeepSeek 兼容 OpenAI SDK，base_url=https://api.deepseek.com
- response_format 仅支持 json_object，配合 Instructor 实现校验失败重试
- 官方要求 prompt 中必须出现 "json" 字样并给出示例结构
- 使用 deepseek-v4-flash（复杂场景可换 v4-pro），旧 ID deepseek-chat 已下线
"""
import os
import instructor
from openai import OpenAI
from typing import Type, TypeVar
from pydantic import BaseModel
from .base import LLMProvider

T = TypeVar("T", bound=BaseModel)


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
        self.client = instructor.patch(raw, mode=instructor.Mode.JSON)
        self.model = model

    def generate_structured(self, system_prompt, user_prompt, schema: Type[T], max_retries: int = 2) -> T:
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
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return resp.choices[0].message.content
