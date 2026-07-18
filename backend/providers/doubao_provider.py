"""豆包 API Provider（火山方舟）：服务端 json_schema 严格结构化输出

要点：
- 火山方舟提供 OpenAI 兼容端点 https://ark.cn-beijing.volces.com/api/v3
- response_format 支持 json_schema + strict: true，服务端保证 Schema 合法
- strict 模式要求所有字段列入 required、additionalProperties 为 false
- 异常时降级到 json_object + Pydantic 校验重试
"""
import os
from openai import OpenAI
from typing import Type, TypeVar
from pydantic import BaseModel
from .base import LLMProvider

T = TypeVar("T", bound=BaseModel)


def _to_strict_schema(model: Type[BaseModel]) -> dict:
    """Pydantic schema → 豆包 strict 模式：逐层追加 required + additionalProperties"""
    schema = model.model_json_schema()

    def enforce(node: dict):
        if node.get("type") == "object":
            props = node.get("properties", {})
            node["required"] = list(props.keys())
            node["additionalProperties"] = False
            for p in props.values():
                enforce(p)
        for key in ("items",):
            if key in node:
                enforce(node[key])
        for key in ("$defs", "definitions"):
            for sub in node.get(key, {}).values():
                enforce(sub)

    enforce(schema)
    return schema


class DoubaoProvider(LLMProvider):
    """豆包 API：结构化生成的主力 Provider"""

    def __init__(self, model: str = "doubao-seed-1-6-251015"):
        api_key = os.environ.get("ARK_API_KEY", "")
        if not api_key:
            raise ValueError("ARK_API_KEY environment variable not set (火山方舟 API Key)")
        self.client = OpenAI(
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            api_key=api_key,
        )
        self.model = model

    def generate_structured(self, system_prompt, user_prompt, schema: Type[T], max_retries: int = 2) -> T:
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema.__name__,
                        "schema": _to_strict_schema(schema),
                        "strict": True,
                    },
                },
                extra_body={"thinking": {"type": "disabled"}},
            )
        except Exception:
            return self._fallback_json_object(system_prompt, user_prompt, schema, max_retries)
        return schema.model_validate_json(resp.choices[0].message.content)

    def _fallback_json_object(self, system_prompt, user_prompt, schema, max_retries) -> T:
        last_err = None
        for _ in range(max_retries + 1):
            prompt = user_prompt + (f"\n\n【上次校验失败】{last_err}" if last_err else "")
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                extra_body={"thinking": {"type": "disabled"}},
            )
            try:
                return schema.model_validate_json(resp.choices[0].message.content)
            except Exception as e:
                last_err = e
        raise RuntimeError(f"豆包结构化生成多次失败: {last_err}")

    def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return resp.choices[0].message.content
