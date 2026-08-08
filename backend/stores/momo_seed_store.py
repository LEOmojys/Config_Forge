import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from ..schemas.momo import MomoArchetype, MomoRole


class MomoBounds(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    min_x: float
    max_x: float
    min_y: float
    max_y: float


class MomoRegionSeed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    region_id: str
    room_ids: list[str]
    allowed_enemy_ids: list[str]
    bounds: MomoBounds


class MomoEnemyArchetypeSeed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enemy_id: str
    archetype: MomoArchetype
    role: MomoRole
    asset_id: str
    tuning_profile_id: str
    max_health: int
    move_speed: float
    radius: float
    touch_range: float
    preferred_range: float
    damage: int


class MomoAssetSeed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    asset_id: str
    path: str
    kind: str


class MomoAssetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    assets: list[MomoAssetSeed]


class MomoBalanceRules(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    design_version: str
    config_version: str
    min_telegraph_time: float = Field(gt=0)
    min_active_time: float = Field(gt=0)
    max_alive_enemies: int = Field(ge=1)
    allowed_seed_policies: list[str]


class MomoSeedStore:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self.regions: dict[str, MomoRegionSeed] = {}
        self.archetypes: dict[MomoArchetype, MomoEnemyArchetypeSeed] = {}
        self.assets: dict[str, MomoAssetSeed] = {}
        self.balance: MomoBalanceRules | None = None

    def load(self) -> None:
        regions = TypeAdapter(list[MomoRegionSeed]).validate_json(
            self._read("regions.json")
        )
        archetypes = TypeAdapter(list[MomoEnemyArchetypeSeed]).validate_json(
            self._read("enemy-archetypes.json")
        )
        manifest = MomoAssetManifest.model_validate_json(self._read("asset-manifest.json"))
        balance = MomoBalanceRules.model_validate_json(self._read("balance-rules.json"))
        self.regions = {region.region_id: region for region in regions}
        self.archetypes = {entry.archetype: entry for entry in archetypes}
        self.assets = {asset.asset_id: asset for asset in manifest.assets}
        self.balance = balance

    def get_region(self, region_id: str) -> MomoRegionSeed | None:
        return self.regions.get(region_id)

    def get_archetype(self, archetype: MomoArchetype) -> MomoEnemyArchetypeSeed:
        return self.archetypes[archetype]

    def has_asset(self, asset_id: str) -> bool:
        return asset_id in self.assets

    def to_context(self) -> str:
        if self.balance is None:
            self.load()
        return json.dumps(
            {
                "regions": [item.model_dump(mode="json") for item in self.regions.values()],
                "archetypes": [item.model_dump(mode="json") for item in self.archetypes.values()],
                "assets": [item.model_dump(mode="json") for item in self.assets.values()],
                "balance": self.balance.model_dump(mode="json") if self.balance else {},
            },
            ensure_ascii=False,
            indent=2,
        )

    def _read(self, filename: str) -> str:
        return (self.root_dir / filename).read_text(encoding="utf-8")
