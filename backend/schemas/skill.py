"""Skill configuration schema."""
from pydantic import BaseModel, Field, model_validator
from .common import SkillType, ElementId


class SkillConfig(BaseModel):
    skill_id: str = Field(min_length=3, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    skill_type: SkillType
    element_id: ElementId
    cooldown: float = Field(ge=0.0, le=120.0)
    damage_multiplier: float = Field(ge=0.0, le=50.0)
    stance_damage: float = Field(ge=0.0, le=100.0)
    range: float = Field(ge=0.0, le=100.0)
    is_aoe: bool = False
    energy_cost: int = Field(default=0, ge=0, le=200)
    description: str = Field(default="", max_length=256)

    @model_validator(mode="after")
    def check_dps_ceiling(self):
        dps = self.damage_multiplier / max(self.cooldown, 0.1)
        if dps > 5.0:
            raise ValueError(f"DPS {dps:.2f} exceeds ceiling 5.0, adjust cooldown or multiplier")
        return self
