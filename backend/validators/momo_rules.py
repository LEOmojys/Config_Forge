import re
from typing import Final

from ..schemas.momo import (
    MomoArchetype,
    MomoAttackCategory,
    MomoEncounterWave,
    MomoEncounterBundle,
    MomoEnemyBundle,
    MomoRole,
)
from ..stores.momo_seed_store import MomoSeedStore
from .rule_engine import RuleViolation, ValidationResult


_ID_PATTERN: Final = re.compile(r"[a-z][a-z0-9_]{2,63}")
_ROLE_ARCHETYPES: Final = {
    MomoRole.NORMAL_MELEE: MomoArchetype.CRAWLER,
    MomoRole.NORMAL_RANGED: MomoArchetype.SHOOTER,
    MomoRole.ELITE: MomoArchetype.ELITE,
    MomoRole.BOSS: MomoArchetype.BOSS,
}


class MomoRuleEngine:
    def __init__(self, seed_store: MomoSeedStore) -> None:
        self.seed = seed_store

    def validate_enemy_bundle(self, bundle: MomoEnemyBundle) -> ValidationResult:
        self.seed.load()
        result = ValidationResult()
        enemy = bundle.enemy
        self._require_id(result, enemy.enemy_id, "enemies", "enemy_id")
        region = self.seed.get_region(enemy.region_id)
        if region is None:
            result.violations.append(self._violation("MOMO_R002", "enemies", "region_id", "region_id is not present in the MoMo seed snapshot"))
        expected_archetype = _ROLE_ARCHETYPES[enemy.role]
        if enemy.archetype != expected_archetype:
            result.violations.append(self._violation("MOMO_R003", "enemies", "archetype", "role and archetype must use the supported MoMo pairing"))
        if not self.seed.has_asset(enemy.asset_id):
            result.violations.append(self._violation("MOMO_R005", "enemies", "asset_id", "asset_id is not present in the MoMo asset manifest"))
        if enemy.archetype in self.seed.archetypes:
            profile = self.seed.get_archetype(enemy.archetype)
            if enemy.tuning_profile_id != profile.tuning_profile_id:
                result.violations.append(self._violation("MOMO_R005", "enemies", "tuning_profile_id", "tuning_profile_id must match the selected archetype profile"))
        self._validate_enemy_numbers(result, bundle)
        attack_ids: set[str] = set()
        for attack in bundle.attacks:
            self._require_id(result, attack.attack_id, "enemy_attacks", "attack_id")
            if attack.attack_id in attack_ids:
                result.violations.append(self._violation("MOMO_R004", "enemy_attacks", "attack_id", "attack_id values must be unique inside a bundle"))
            attack_ids.add(attack.attack_id)
            if attack.enemy_id != enemy.enemy_id:
                result.violations.append(self._violation("MOMO_R004", "enemy_attacks", "enemy_id", "attack enemy_id must equal the owning enemy_id"))
            self._validate_attack(result, attack.attack_category, attack.projectile_type, attack.warning_asset_id, attack.summon_enemy_id, attack.telegraph_time, attack.active_time, attack.recovery_time, attack.cooldown, "enemy_attacks")
        self._validate_boss_contract(result, bundle)
        return result

    def validate_encounter_bundle(self, bundle: MomoEncounterBundle) -> ValidationResult:
        self.seed.load()
        result = ValidationResult()
        encounter = bundle.encounter
        self._require_id(result, encounter.encounter_id, "encounters", "encounter_id")
        region = self.seed.get_region(encounter.region_id)
        if region is None:
            result.violations.append(self._violation("MOMO_R002", "encounters", "region_id", "region_id is not present in the MoMo seed snapshot"))
            return result
        if encounter.room_id not in region.room_ids:
            result.violations.append(self._violation("MOMO_R009", "encounters", "room_id", "room_id is not available in the selected region"))
        if self.seed.balance is not None and encounter.combat_seed_policy not in self.seed.balance.allowed_seed_policies:
            result.violations.append(self._violation("MOMO_R009", "encounters", "combat_seed_policy", "combat_seed_policy is not allowed by the MoMo balance rules"))
        wave_indexes: set[int] = set()
        for wave in bundle.waves:
            if wave.encounter_id != encounter.encounter_id:
                result.violations.append(self._violation("MOMO_R010", "encounter_waves", "encounter_id", "wave encounter_id must equal the owning encounter_id"))
            if wave.wave_index in wave_indexes:
                result.violations.append(self._violation("MOMO_R010", "encounter_waves", "wave_index", "wave_index values must be unique inside an encounter"))
            wave_indexes.add(wave.wave_index)
            self._validate_wave(result, encounter.max_alive_enemies, region.allowed_enemy_ids, region.bounds.min_x, region.bounds.max_x, region.bounds.min_y, region.bounds.max_y, wave)
        return result

    def _validate_enemy_numbers(self, result: ValidationResult, bundle: MomoEnemyBundle) -> None:
        enemy = bundle.enemy
        if self.seed.balance is None:
            return
        minimum = self.seed.balance.min_telegraph_time
        if enemy.telegraph_time < minimum or enemy.active_time < self.seed.balance.min_active_time:
            result.violations.append(self._violation("MOMO_R006", "enemies", "telegraph_time", "enemy attack timing is below the readable timing floor"))

    def _validate_attack(self, result: ValidationResult, category: MomoAttackCategory, projectile_type: str | None, warning_asset_id: str, summon_enemy_id: str | None, telegraph_time: float, active_time: float, recovery_time: float, cooldown: float, table: str) -> None:
        if self.seed.balance is not None and (telegraph_time < self.seed.balance.min_telegraph_time or active_time < self.seed.balance.min_active_time or recovery_time <= 0 or cooldown <= 0):
            result.violations.append(self._violation("MOMO_R006", table, "telegraph_time", "attack timing must meet the MoMo readability minimums"))
        if not self.seed.has_asset(warning_asset_id):
            result.violations.append(self._violation("MOMO_R005", table, "warning_asset_id", "warning_asset_id is not present in the MoMo asset manifest"))
        match category:
            case MomoAttackCategory.PROJECTILE:
                if projectile_type is None or not self.seed.has_asset(projectile_type):
                    result.violations.append(self._violation("MOMO_R005", table, "projectile_type", "projectile attacks require a manifest projectile asset"))
            case MomoAttackCategory.SUMMON:
                if summon_enemy_id is None or not self._has_seed_enemy(summon_enemy_id):
                    result.violations.append(self._violation("MOMO_R009", table, "summon_enemy_id", "summon attacks must reference an allowed MoMo seed enemy"))
            case MomoAttackCategory.DIRECT | MomoAttackCategory.AREA:
                return

    def _validate_boss_contract(self, result: ValidationResult, bundle: MomoEnemyBundle) -> None:
        if bundle.enemy.role != MomoRole.BOSS:
            return
        categories = {attack.attack_category for attack in bundle.attacks}
        ranged_count = len(categories & {MomoAttackCategory.PROJECTILE, MomoAttackCategory.AREA})
        if MomoAttackCategory.DIRECT not in categories or MomoAttackCategory.SUMMON not in categories or ranged_count != 1 or len(categories) != 3:
            result.violations.append(self._violation("MOMO_R008", "enemy_attacks", "attack_category", "bosses require direct, one projectile-or-area, and summon attacks only"))

    def _validate_wave(self, result: ValidationResult, max_alive_enemies: int, allowed_enemy_ids: list[str], min_x: float, max_x: float, min_y: float, max_y: float, wave: MomoEncounterWave) -> None:
        spawns = wave.spawns
        total = sum(spawn.count for spawn in spawns)
        ceiling = self.seed.balance.max_alive_enemies if self.seed.balance is not None else 8
        if total > max_alive_enemies or total > ceiling:
            result.violations.append(self._violation("MOMO_R010", "encounter_waves", "count", "wave enemy count exceeds the encounter or global alive-enemy limit"))
        coordinates: set[tuple[float, float]] = set()
        for spawn in spawns:
            if spawn.enemy_id not in allowed_enemy_ids:
                result.violations.append(self._violation("MOMO_R009", "encounter_waves", "enemy_id", "spawn enemy_id is not allowed in the selected region"))
            coordinate = (spawn.spawn_x, spawn.spawn_y)
            if coordinate in coordinates:
                result.violations.append(self._violation("MOMO_R010", "encounter_waves", "spawn_x", "spawn coordinates must be unique inside each wave"))
            coordinates.add(coordinate)
            if not min_x <= spawn.spawn_x <= max_x or not min_y <= spawn.spawn_y <= max_y:
                result.violations.append(self._violation("MOMO_R010", "encounter_waves", "spawn_x", "spawn coordinates must remain inside the selected room bounds"))

    def _has_seed_enemy(self, enemy_id: str) -> bool:
        return any(enemy_id in region.allowed_enemy_ids for region in self.seed.regions.values())

    def _require_id(self, result: ValidationResult, value: str, table: str, field: str) -> None:
        if _ID_PATTERN.fullmatch(value) is None:
            result.violations.append(self._violation("MOMO_R001", table, field, "ID must be lowercase snake_case with 3-64 characters"))

    @staticmethod
    def _violation(rule_id: str, table: str, field: str, message: str) -> RuleViolation:
        return RuleViolation(rule_id, "error", table, field, message)
