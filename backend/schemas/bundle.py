"""Bundle schemas: aggregated objects that LLM generates, then Exporter splits into tables."""
from typing import Optional
from pydantic import BaseModel, Field
from .skill import SkillConfig
from .monster import MonsterTemplateConfig, MonsterConfig, MonsterSkillLink, MonsterLootEntry
from .quest import QuestTemplateConfig, QuestObjectiveConfig


class SkillBundle(BaseModel):
    skills: list[SkillConfig] = Field(min_length=1, max_length=8)


class MonsterBundle(BaseModel):
    monster_template: MonsterTemplateConfig
    monster_config: MonsterConfig
    skills: list[SkillConfig] = Field(default_factory=list, max_length=8, description="Bundle 内联技能定义")
    monster_skills: list[MonsterSkillLink] = Field(min_length=0, max_length=8)
    monster_loot: list[MonsterLootEntry] = Field(min_length=0, max_length=20)
    summon_template: Optional[MonsterTemplateConfig] = None
    summon_config: Optional[MonsterConfig] = None
    summon_skills: list[MonsterSkillLink] = Field(default_factory=list, max_length=8)
    summon_loot: list[MonsterLootEntry] = Field(default_factory=list, max_length=20)


class QuestBundle(BaseModel):
    quest_template: QuestTemplateConfig
    quest_objectives: list[QuestObjectiveConfig] = Field(min_length=1, max_length=20)
