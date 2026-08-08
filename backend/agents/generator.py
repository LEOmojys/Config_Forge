"""Generator Agent：根据需求 + Schema + 种子上下文生成配置 Bundle"""
import json
from pydantic import BaseModel
from ..providers.base import LLMProvider
from ..prompts.generator import (
    GENERATOR_SYSTEM_PROMPT,
    build_generator_user_prompt,
    build_seed_context,
)
from ..schemas.bundle import SkillBundle, MonsterBundle, QuestBundle
from ..schemas.momo import MomoEncounterBundle, MomoEnemyBundle
from ..prompts.momo import build_momo_prompt


class GeneratorAgent:
    """职责单一：接收需求 + 反馈 → 产出结构化 Bundle"""

    def __init__(self, provider: LLMProvider, seed_store, momo_seed_store=None):
        self.provider = provider
        self.seed = seed_store
        self.momo_seed = momo_seed_store

    def generate_skill(self, requirement: str, feedback: str = "") -> SkillBundle:
        return self._generate(
            requirement=requirement,
            job_type="skill",
            schema=SkillBundle,
            feedback=feedback,
        )

    def generate_monster(self, requirement: str, feedback: str = "") -> MonsterBundle:
        return self._generate(
            requirement=requirement,
            job_type="monster",
            schema=MonsterBundle,
            feedback=feedback,
        )

    def generate_quest(self, requirement: str, feedback: str = "") -> QuestBundle:
        return self._generate(
            requirement=requirement,
            job_type="quest",
            schema=QuestBundle,
            feedback=feedback,
        )

    def generate_momo_enemy(self, requirement: str, feedback: str = "") -> MomoEnemyBundle:
        return self._generate_momo(requirement, "momo_enemy", MomoEnemyBundle, feedback)

    def generate_momo_encounter(self, requirement: str, feedback: str = "") -> MomoEncounterBundle:
        return self._generate_momo(requirement, "momo_encounter", MomoEncounterBundle, feedback)

    def _generate(self, requirement: str, job_type: str, schema: type[BaseModel], feedback: str) -> BaseModel:
        self.seed.load()
        seed_context = build_seed_context(self.seed)
        system_prompt = GENERATOR_SYSTEM_PROMPT.replace("{seed_context}", seed_context)
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False, indent=2)
        user_prompt = build_generator_user_prompt(requirement, job_type, schema_json, feedback)
        return self.provider.generate_structured(system_prompt, user_prompt, schema, max_retries=2)

    def _generate_momo(self, requirement: str, job_type: str, schema: type[BaseModel], feedback: str) -> BaseModel:
        if self.momo_seed is None:
            raise RuntimeError("MoMo seed store is required for MoMo generation")
        system_prompt, user_prompt = build_momo_prompt(requirement, job_type, schema, self.momo_seed, feedback)
        return self.provider.generate_structured(system_prompt, user_prompt, schema, max_retries=2)
