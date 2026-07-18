"""Common enumerations and base class shared across all config types."""
from enum import Enum
from pydantic import BaseModel, Field, field_validator
import re


class ElementId(str, Enum):
    FIRE = "fire"
    ICE = "ice"
    THUNDER = "thunder"
    WIND = "wind"
    QUANTUM = "quantum"
    IMAGINARY = "imaginary"
    PHYSICAL = "physical"
    WATER = "water"


class MonsterType(str, Enum):
    NORMAL = "normal"
    ELITE = "elite"
    BOSS = "boss"
    SUMMON = "summon"


class AIBehavior(str, Enum):
    MELEE = "melee"
    RANGED = "ranged"
    SUMMONER = "summoner"
    SUPPORT = "support"
    BOSS_PHASE = "boss_phase"


class SkillType(str, Enum):
    NORMAL = "normal"
    ULTIMATE = "ultimate"
    PASSIVE = "passive"
    MONSTER = "monster"


class ItemType(str, Enum):
    MATERIAL = "material"
    CURRENCY = "currency"
    QUEST_ITEM = "quest_item"


class QuestType(str, Enum):
    MAIN = "main"
    SIDE = "side"
    DAILY = "daily"
    CHALLENGE = "challenge"


class ObjectiveType(str, Enum):
    KILL = "kill"
    COLLECT = "collect"
    TALK = "talk"
    EXPLORE = "explore"


class ConfigBase(BaseModel):
    @field_validator("id", check_fields=False)
    @classmethod
    def check_snake_case(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,63}", v):
            raise ValueError(f"ID '{v}' must be snake_case (lowercase, digits, underscores, 3-64 chars)")
        return v
