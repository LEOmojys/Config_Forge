"""Monster configuration schemas."""
from typing import Optional
from pydantic import BaseModel, Field, model_validator
from .common import MonsterType, AIBehavior, ElementId


class MonsterTemplateConfig(BaseModel):
    template_id: str = Field(min_length=3, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    monster_type: MonsterType
    base_hp: int = Field(ge=1)
    base_attack: int = Field(ge=0)
    base_defense: int = Field(ge=0)
    base_speed: int = Field(ge=1)
    base_stance: int = Field(ge=0)
    default_ai: AIBehavior


class MonsterConfig(BaseModel):
    monster_id: str = Field(min_length=3, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    template_id: str = Field(min_length=3, max_length=64)
    level: int = Field(ge=1, le=100)
    element_id: ElementId
    hp_modify_ratio: float = Field(ge=0.1, le=10.0)
    attack_modify_ratio: float = Field(ge=0.1, le=10.0)
    defense_modify_ratio: float = Field(ge=0.1, le=10.0)
    stance_modify_ratio: float = Field(ge=0.1, le=10.0)
    loot_group_id: str = Field(min_length=3, max_length=64)
    summon_group_id: Optional[str] = Field(default=None, min_length=3, max_length=64)
    description: str = Field(default="", max_length=256)


class MonsterSkillLink(BaseModel):
    monster_id: str = Field(min_length=3, max_length=64)
    slot: int = Field(ge=1, le=8)
    skill_id: str = Field(min_length=3, max_length=64)
    trigger_key: str = Field(default="auto", min_length=1, max_length=32)
    weight: int = Field(default=10, ge=1, le=100)


class MonsterLootEntry(BaseModel):
    loot_group_id: str = Field(min_length=3, max_length=64)
    item_id: str = Field(min_length=3, max_length=64)
    chance: float = Field(ge=0.0, le=1.0)
    min_count: int = Field(default=1, ge=1, le=999)
    max_count: int = Field(default=1, ge=1, le=999)

    @model_validator(mode="after")
    def check_count_order(self):
        if self.min_count > self.max_count:
            raise ValueError(f"min_count({self.min_count}) must be <= max_count({self.max_count})")
        return self
