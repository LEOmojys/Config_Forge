"""Critic Agent：持审查清单从游戏设计视角把关，输出结构化审查结论"""
from pydantic import BaseModel, Field
from ..providers.base import LLMProvider
from ..prompts.critic import CRITIC_SYSTEM_PROMPT, build_critic_user_prompt


class ReviewResult(BaseModel):
    """Critic 的结构化审查结论"""
    approved: bool = Field(description="是否通过设计审查")
    issues: list[str] = Field(default_factory=list, description="具体问题列表")


class CriticAgent:
    """职责单一：审查配置设计质量，不负责格式/引用校验"""

    def __init__(self, provider: LLMProvider):
        self.provider = provider

    def review(self, config_dict: dict) -> dict:
        """返回 {"approved": bool, "issues": [str]}"""
        user_prompt = build_critic_user_prompt(config_dict)
        result: ReviewResult = self.provider.generate_structured(
            CRITIC_SYSTEM_PROMPT, user_prompt, ReviewResult, max_retries=2
        )
        return result.model_dump()
