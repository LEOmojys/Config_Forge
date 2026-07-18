"""Provider 抽象层：生成侧与审查侧可分别注入不同后端"""
from abc import ABC, abstractmethod
from typing import TypeVar, Type
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMProvider(ABC):
    """所有 LLM 后端的统一接口"""

    @abstractmethod
    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: Type[T],
        max_retries: int = 2,
    ) -> T:
        """生成符合 schema 的结构化对象"""
        ...

    @abstractmethod
    def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        """自由文本生成（用于 Critic 审查意见）"""
        ...
