"""Quest configuration schemas."""
from typing import Optional
from pydantic import BaseModel, Field
from .common import QuestType, ObjectiveType


class QuestTemplateConfig(BaseModel):
    quest_id: str = Field(min_length=3, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    quest_type: QuestType
    required_level: int = Field(ge=1, le=100)
    pre_quest_id: Optional[str] = Field(default=None, min_length=3, max_length=64)
    reward_group_id: str = Field(min_length=3, max_length=64)
    description: str = Field(default="", max_length=256)


class QuestObjectiveConfig(BaseModel):
    objective_id: str = Field(min_length=3, max_length=64)
    quest_id: str = Field(min_length=3, max_length=64)
    objective_type: ObjectiveType
    target_id: str = Field(min_length=1, max_length=64)
    target_count: int = Field(ge=1, le=999)
    description: str = Field(default="", max_length=256)
