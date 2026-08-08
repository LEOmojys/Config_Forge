from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class MomoRole(str, Enum):
    NORMAL_MELEE = "normal_melee"
    NORMAL_RANGED = "normal_ranged"
    ELITE = "elite"
    BOSS = "boss"


class MomoArchetype(str, Enum):
    CRAWLER = "crawler"
    SHOOTER = "shooter"
    ELITE = "elite"
    BOSS = "boss"


class MomoAttackCategory(str, Enum):
    DIRECT = "direct"
    PROJECTILE = "projectile"
    AREA = "area"
    SUMMON = "summon"


class MomoEncounterType(str, Enum):
    NORMAL = "normal"
    ELITE = "elite"
    BOSS = "boss"


class MomoEnemyDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enemy_id: str = Field(min_length=3, max_length=64)
    region_id: str = Field(min_length=3, max_length=64)
    role: MomoRole
    archetype: MomoArchetype
    name: str = Field(min_length=3, max_length=80)
    description: str = Field(min_length=8, max_length=500)
    max_health: int = Field(ge=1, le=5000)
    move_speed: float = Field(gt=0, le=20)
    radius: float = Field(gt=0, le=5)
    touch_range: float = Field(ge=0, le=20)
    preferred_range: float = Field(ge=0, le=30)
    damage: int = Field(ge=0, le=500)
    telegraph_time: float = Field(ge=0, le=10)
    active_time: float = Field(ge=0, le=10)
    recovery_time: float = Field(ge=0, le=10)
    cooldown: float = Field(gt=0, le=30)
    tuning_profile_id: str = Field(min_length=3, max_length=64)
    asset_id: str = Field(min_length=3, max_length=64)


class MomoAttackDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attack_id: str = Field(min_length=3, max_length=64)
    enemy_id: str = Field(min_length=3, max_length=64)
    attack_category: MomoAttackCategory
    damage: int = Field(ge=0, le=500)
    telegraph_time: float = Field(ge=0, le=10)
    active_time: float = Field(ge=0, le=10)
    recovery_time: float = Field(ge=0, le=10)
    cooldown: float = Field(gt=0, le=30)
    max_hits_per_target: int = Field(ge=0, le=20)
    projectile_type: str | None = Field(default=None, max_length=64)
    warning_asset_id: str = Field(min_length=3, max_length=64)
    summon_enemy_id: str | None = Field(default=None, max_length=64)
    phase: int = Field(default=1, ge=1, le=2)
    description: str = Field(min_length=8, max_length=500)


class MomoEnemyBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enemy: MomoEnemyDefinition
    attacks: list[MomoAttackDefinition] = Field(min_length=1, max_length=8)


class MomoEncounterDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    encounter_id: str = Field(min_length=3, max_length=64)
    region_id: str = Field(min_length=3, max_length=64)
    encounter_type: MomoEncounterType
    room_id: str = Field(min_length=3, max_length=64)
    name: str = Field(min_length=3, max_length=80)
    reward_gold: int = Field(ge=0, le=1000)
    combat_seed_policy: str = Field(min_length=3, max_length=32)
    max_alive_enemies: int = Field(ge=1, le=8)
    description: str = Field(min_length=8, max_length=500)


class MomoSpawn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enemy_id: str = Field(min_length=3, max_length=64)
    count: int = Field(ge=1, le=8)
    spawn_group: str = Field(min_length=3, max_length=64)
    spawn_x: float = Field(ge=-20, le=20)
    spawn_y: float = Field(ge=-20, le=20)


class MomoEncounterWave(BaseModel):
    model_config = ConfigDict(extra="forbid")

    encounter_id: str = Field(min_length=3, max_length=64)
    wave_index: int = Field(ge=1, le=20)
    spawns: list[MomoSpawn] = Field(min_length=1, max_length=8)


class MomoEncounterBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    encounter: MomoEncounterDefinition
    waves: list[MomoEncounterWave] = Field(min_length=1, max_length=20)
