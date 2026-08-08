"""Mock LLM Provider: generates plausible config bundles without real API calls.

In MVP mode, this provider returns template-based bundles with randomized
variations. For production, replace with real API calls to Doubao/DeepSeek.
"""
import copy
import hashlib
import random
import uuid
import re
from typing import TypeVar, Type
from ..schemas.bundle import SkillBundle, MonsterBundle, QuestBundle
from ..schemas.skill import SkillConfig
from ..schemas.monster import (
    MonsterTemplateConfig, MonsterConfig, MonsterSkillLink, MonsterLootEntry,
)
from ..schemas.quest import QuestTemplateConfig, QuestObjectiveConfig
from ..schemas.common import (
    ElementId, MonsterType, AIBehavior, SkillType, QuestType, ObjectiveType,
)
from ..schemas.momo import (
    MomoArchetype,
    MomoAttackCategory,
    MomoAttackDefinition,
    MomoEncounterBundle,
    MomoEncounterDefinition,
    MomoEncounterType,
    MomoEncounterWave,
    MomoEnemyBundle,
    MomoEnemyDefinition,
    MomoRole,
    MomoSpawn,
)


T = TypeVar("T")


class MockLLMProvider:
    """Deterministic-ish mock that generates plausible bundles for MVP demo."""

    def __init__(self, seed_store, momo_seed_store=None):
        self.seed = seed_store
        self.momo_seed = momo_seed_store
        self._rng = random.Random()

    def generate_skill_bundle(self, requirement: str, feedback: str = "") -> SkillBundle:
        self._rng.seed(hash(requirement) % (2**31))
        elements = self.seed.get_element_ids()
        elem = self._element_from_requirement(requirement) or self._pick(elements)
        is_ulti = "ultimate" in requirement.lower() or "大招" in requirement.lower()
        is_aoe = "aoe" in requirement.lower() or "范围" in requirement.lower() or "群" in requirement.lower()
        skill_id = f"sk_{uuid.uuid4().hex[:8]}"
        return SkillBundle(skills=[SkillConfig(
            skill_id=skill_id,
            name=f"Generated Skill {skill_id[-4:]}",
            skill_type=SkillType.ULTIMATE if is_ulti else SkillType.NORMAL,
            element_id=ElementId(elem),
            cooldown=round(self._rng.uniform(2.0, 18.0), 1),
            damage_multiplier=round(self._rng.uniform(0.5, 4.0), 2),
            stance_damage=round(self._rng.uniform(0.0, 5.0), 1),
            range=round(self._rng.uniform(3.0, 30.0), 1),
            is_aoe=is_aoe,
            energy_cost=self._rng.choice([0, 20, 30, 40, 60]),
            description=f"Auto-generated skill: {requirement[:80]}",
        )])

    def generate_monster_bundle(self, requirement: str, feedback: str = "") -> MonsterBundle:
        self._rng.seed(hash(requirement) % (2**31))
        templates = list(self.seed.templates.values())
        lower = requirement.lower()
        requested_type = None
        if "boss" in lower or "首领" in requirement:
            requested_type = MonsterType.BOSS
        elif "elite" in lower or "精英" in requirement:
            requested_type = MonsterType.ELITE
        elif "normal" in lower or "普通" in requirement:
            requested_type = MonsterType.NORMAL
        matching_templates = [item for item in templates if requested_type is None or item.monster_type == requested_type]
        tpl = copy.deepcopy(self._pick(matching_templates or templates))
        if requested_type is not None:
            tpl.monster_type = requested_type
        elements = self.seed.get_element_ids()
        elem = self._element_from_requirement(requirement) or self._pick(elements)
        is_summoner = "summon" in requirement.lower() or "召唤" in requirement.lower()
        if is_summoner:
            tpl.default_ai = AIBehavior.SUMMONER
        m_id = f"mon_{uuid.uuid4().hex[:8]}"
        lg_id = f"loot_{uuid.uuid4().hex[:6]}"
        cfg = MonsterConfig(
            monster_id=m_id,
            name=f"Generated {tpl.name} {m_id[-4:]}",
            template_id=tpl.template_id,
            level=self._level_from_requirement(requirement) or self._rng.randint(10, 80),
            element_id=ElementId(elem),
            hp_modify_ratio=round(self._rng.uniform(0.8, 2.5), 2),
            attack_modify_ratio=round(self._rng.uniform(0.8, 2.0), 2),
            defense_modify_ratio=round(self._rng.uniform(0.8, 2.0), 2),
            stance_modify_ratio=round(self._rng.uniform(0.8, 1.5), 2),
            loot_group_id=lg_id,
            description=f"Auto-generated monster: {requirement[:80]}",
        )
        skill_ids = self.seed.get_skill_ids()
        ms = []
        minimum_skills = 2 if tpl.monster_type == MonsterType.BOSS else 1
        skill_count = min(self._rng.randint(minimum_skills, 3), len(skill_ids))
        for i, sid in enumerate(self._rng.sample(skill_ids, skill_count), start=1):
            ms.append(MonsterSkillLink(monster_id=m_id, slot=i, skill_id=sid, trigger_key="auto", weight=10))
        item_ids = self.seed.get_item_ids()
        loot = []
        used_items = self._rng.sample(item_ids, min(self._rng.randint(1, 3), len(item_ids)))
        remaining = 1.0
        for i, iid in enumerate(used_items):
            chance = remaining if i == len(used_items) - 1 else round(self._rng.uniform(0.1, remaining * 0.6), 2)
            remaining -= chance
            loot.append(MonsterLootEntry(loot_group_id=lg_id, item_id=iid, chance=chance, min_count=1, max_count=self._rng.randint(1, 3)))
        return MonsterBundle(monster_template=tpl, monster_config=cfg, skills=[], monster_skills=ms, monster_loot=loot)

    def generate_quest_bundle(self, requirement: str, feedback: str = "") -> QuestBundle:
        self._rng.seed(hash(requirement) % (2**31))
        q_id = f"qst_{uuid.uuid4().hex[:8]}"
        lower = requirement.lower()
        is_main = "main" in lower or "主线" in requirement
        if "daily" in lower or "日常" in requirement:
            quest_type = QuestType.DAILY
        elif "challenge" in lower or "挑战" in requirement:
            quest_type = QuestType.CHALLENGE
        else:
            quest_type = QuestType.MAIN if is_main else QuestType.SIDE
        qt = QuestTemplateConfig(
            quest_id=q_id,
            name=f"Generated Quest {q_id[-4:]}",
            quest_type=quest_type,
            required_level=self._level_from_requirement(requirement) or self._rng.randint(1, 50),
            reward_group_id=f"rew_{uuid.uuid4().hex[:6]}",
            description=f"Auto-generated quest: {requirement[:80]}",
        )
        objectives = []
        o_types = [ObjectiveType.KILL, ObjectiveType.COLLECT, ObjectiveType.TALK, ObjectiveType.EXPLORE]
        required_types = []
        if "kill" in lower or "击杀" in requirement or "消灭" in requirement:
            required_types.append(ObjectiveType.KILL)
        if "collect" in lower or "收集" in requirement:
            required_types.append(ObjectiveType.COLLECT)
        remaining_types = [item for item in o_types if item not in required_types]
        target_count = max(2, len(required_types))
        selected_types = required_types + self._rng.sample(
            remaining_types,
            min(target_count - len(required_types), len(remaining_types)),
        )
        for i, otype in enumerate(selected_types, start=1):
            if otype == ObjectiveType.KILL:
                tid = self._pick(self.seed.get_template_ids())
            elif otype == ObjectiveType.COLLECT:
                tid = self._pick(self.seed.get_item_ids())
            else:
                tid = f"target_{uuid.uuid4().hex[:4]}"
            objectives.append(QuestObjectiveConfig(
                objective_id=f"obj_{q_id[4:]}_{i}",
                quest_id=q_id,
                objective_type=otype,
                target_id=tid,
                target_count=self._rng.randint(1, 10),
                description=f"Objective {i}: {otype.value} {tid}",
            ))
        return QuestBundle(quest_template=qt, quest_objectives=objectives)

    def generate_momo_enemy_bundle(self, requirement: str, feedback: str = "") -> MomoEnemyBundle:
        seed = self._momo_seed()
        rng, token = self._momo_rng(requirement)
        archetype = self._momo_archetype(requirement)
        profile = seed.get_archetype(archetype)
        enemy_id = f"momo_enemy_{archetype.value}_{token}"
        role_name = archetype.value.replace("_", " ").title()
        enemy = MomoEnemyDefinition(
            enemy_id=enemy_id,
            region_id="region_1_foundry",
            role=profile.role,
            archetype=archetype,
            name=f"Foundry {role_name} {token[:5]}",
            description=f"A generated MoMo {archetype.value} designed for the foundry region.",
            max_health=profile.max_health + rng.randint(0, max(2, profile.max_health // 5)),
            move_speed=round(profile.move_speed * rng.uniform(0.96, 1.04), 2),
            radius=profile.radius,
            touch_range=profile.touch_range,
            preferred_range=profile.preferred_range,
            damage=profile.damage + rng.randint(0, 1),
            telegraph_time=0.72 if archetype == MomoArchetype.BOSS else 0.4,
            active_time=0.2,
            recovery_time=1.05 if archetype == MomoArchetype.BOSS else 0.72,
            cooldown=1.8 if archetype == MomoArchetype.BOSS else 1.3,
            tuning_profile_id=profile.tuning_profile_id,
            asset_id=profile.asset_id,
        )
        attacks = self._momo_attacks(enemy, token)
        return MomoEnemyBundle(enemy=enemy, attacks=attacks)

    def generate_momo_encounter_bundle(self, requirement: str, feedback: str = "") -> MomoEncounterBundle:
        self._momo_seed()
        _, token = self._momo_rng(requirement)
        archetype = self._momo_archetype(requirement)
        encounter_type = self._momo_encounter_type(archetype)
        is_boss = encounter_type == MomoEncounterType.BOSS
        encounter_id = f"momo_encounter_foundry_{token}"
        encounter = MomoEncounterDefinition(
            encounter_id=encounter_id,
            region_id="region_1_foundry",
            encounter_type=encounter_type,
            room_id="foundry_boss" if is_boss else "open_court",
            name=f"Foundry {encounter_type.value.title()} Encounter {token[:5]}",
            reward_gold=40 if is_boss else 30 if encounter_type == MomoEncounterType.ELITE else 14,
            combat_seed_policy="derived",
            max_alive_enemies=1 if is_boss else 5 if encounter_type == MomoEncounterType.NORMAL else 3,
            description="A generated MoMo encounter with room-safe spawn assignments.",
        )
        spawns = self._momo_spawns(encounter_type)
        wave = MomoEncounterWave(encounter_id=encounter_id, wave_index=1, spawns=spawns)
        return MomoEncounterBundle(encounter=encounter, waves=[wave])

    def _pick(self, items: list):
        return self._rng.choice(items)

    def _momo_seed(self):
        if self.momo_seed is None:
            raise RuntimeError("MoMo seed store is required for MoMo generation")
        self.momo_seed.load()
        return self.momo_seed

    @staticmethod
    def _momo_rng(requirement: str) -> tuple[random.Random, str]:
        digest = hashlib.sha256(requirement.encode("utf-8")).hexdigest()
        return random.Random(int(digest[:16], 16)), digest[:8]

    @staticmethod
    def _momo_archetype(requirement: str) -> MomoArchetype:
        lowered = requirement.casefold()
        choices = (
            (MomoArchetype.BOSS, ("boss", "overseer", "leader", "首领", "监工")),
            (MomoArchetype.ELITE, ("elite", "精英", "guard")),
            (MomoArchetype.SHOOTER, ("shooter", "ranged", "远程", "射手")),
        )
        for archetype, tokens in choices:
            if any(token in lowered for token in tokens):
                return archetype
        return MomoArchetype.CRAWLER

    @staticmethod
    def _momo_encounter_type(archetype: MomoArchetype) -> MomoEncounterType:
        match archetype:
            case MomoArchetype.BOSS:
                return MomoEncounterType.BOSS
            case MomoArchetype.ELITE:
                return MomoEncounterType.ELITE
            case MomoArchetype.CRAWLER | MomoArchetype.SHOOTER:
                return MomoEncounterType.NORMAL

    @staticmethod
    def _momo_attacks(enemy: MomoEnemyDefinition, token: str) -> list[MomoAttackDefinition]:
        direct = MomoAttackDefinition(
            attack_id=f"momo_attack_{token}_direct",
            enemy_id=enemy.enemy_id,
            attack_category=MomoAttackCategory.DIRECT,
            damage=enemy.damage,
            telegraph_time=enemy.telegraph_time,
            active_time=enemy.active_time,
            recovery_time=enemy.recovery_time,
            cooldown=enemy.cooldown,
            max_hits_per_target=1,
            projectile_type=None,
            warning_asset_id="enemy_warning_ring",
            summon_enemy_id=None,
            phase=1,
            description="A readable direct-contact attack.",
        )
        match enemy.archetype:
            case MomoArchetype.CRAWLER:
                return [direct]
            case MomoArchetype.SHOOTER:
                return [MockLLMProvider._momo_projectile_attack(enemy, token)]
            case MomoArchetype.ELITE:
                return [direct, MockLLMProvider._momo_area_attack(enemy, token)]
            case MomoArchetype.BOSS:
                return [direct, MockLLMProvider._momo_projectile_attack(enemy, token), MockLLMProvider._momo_summon_attack(enemy, token)]

    @staticmethod
    def _momo_projectile_attack(enemy: MomoEnemyDefinition, token: str) -> MomoAttackDefinition:
        projectile = "enemy_boss_fireball" if enemy.archetype == MomoArchetype.BOSS else "enemy_rivet"
        return MomoAttackDefinition(
            attack_id=f"momo_attack_{token}_projectile",
            enemy_id=enemy.enemy_id,
            attack_category=MomoAttackCategory.PROJECTILE,
            damage=enemy.damage,
            telegraph_time=max(enemy.telegraph_time, 0.5),
            active_time=enemy.active_time,
            recovery_time=enemy.recovery_time,
            cooldown=max(enemy.cooldown, 1.6),
            max_hits_per_target=1,
            projectile_type=projectile,
            warning_asset_id="enemy_warning_ring",
            summon_enemy_id=None,
            phase=1,
            description="A telegraphed projectile attack.",
        )

    @staticmethod
    def _momo_area_attack(enemy: MomoEnemyDefinition, token: str) -> MomoAttackDefinition:
        return MomoAttackDefinition(
            attack_id=f"momo_attack_{token}_area",
            enemy_id=enemy.enemy_id,
            attack_category=MomoAttackCategory.AREA,
            damage=enemy.damage,
            telegraph_time=max(enemy.telegraph_time, 0.5),
            active_time=enemy.active_time,
            recovery_time=enemy.recovery_time,
            cooldown=max(enemy.cooldown, 1.8),
            max_hits_per_target=1,
            projectile_type=None,
            warning_asset_id="enemy_warning_ring",
            summon_enemy_id=None,
            phase=1,
            description="A marked area-pressure attack.",
        )

    @staticmethod
    def _momo_summon_attack(enemy: MomoEnemyDefinition, token: str) -> MomoAttackDefinition:
        return MomoAttackDefinition(
            attack_id=f"momo_attack_{token}_summon",
            enemy_id=enemy.enemy_id,
            attack_category=MomoAttackCategory.SUMMON,
            damage=0,
            telegraph_time=max(enemy.telegraph_time, 0.6),
            active_time=enemy.active_time,
            recovery_time=enemy.recovery_time,
            cooldown=7.0,
            max_hits_per_target=0,
            projectile_type=None,
            warning_asset_id="enemy_warning_ring",
            summon_enemy_id="enemy_crawler",
            phase=2,
            description="A second-phase crawler reinforcement call.",
        )

    @staticmethod
    def _momo_spawns(encounter_type: MomoEncounterType) -> list[MomoSpawn]:
        match encounter_type:
            case MomoEncounterType.BOSS:
                return [MomoSpawn(enemy_id="enemy_boss", count=1, spawn_group="core", spawn_x=0.0, spawn_y=2.8)]
            case MomoEncounterType.ELITE:
                return [
                    MomoSpawn(enemy_id="enemy_elite", count=1, spawn_group="center_guard", spawn_x=0.0, spawn_y=2.6),
                    MomoSpawn(enemy_id="enemy_crawler", count=2, spawn_group="flankers", spawn_x=-5.0, spawn_y=-2.2),
                ]
            case MomoEncounterType.NORMAL:
                return [
                    MomoSpawn(enemy_id="enemy_crawler", count=3, spawn_group="north_scrap", spawn_x=-5.2, spawn_y=2.4),
                    MomoSpawn(enemy_id="enemy_shooter", count=2, spawn_group="south_rivets", spawn_x=5.2, spawn_y=-2.4),
                ]

    @staticmethod
    def _level_from_requirement(requirement: str):
        patterns = [r"\blevel\s*(\d{1,3})\b", r"等级\s*(\d{1,3})", r"(\d{1,3})\s*级"]
        for pattern in patterns:
            match = re.search(pattern, requirement, flags=re.IGNORECASE)
            if match:
                return max(1, min(int(match.group(1)), 100))
        return None

    @staticmethod
    def _element_from_requirement(requirement: str):
        lower = requirement.lower()
        aliases = [
            (ElementId.IMAGINARY.value, ["imaginary", "虚数"]),
            (ElementId.QUANTUM.value, ["quantum", "量子"]),
            (ElementId.PHYSICAL.value, ["physical", "物理"]),
            (ElementId.THUNDER.value, ["thunder", "lightning", "雷"]),
            (ElementId.WIND.value, ["wind", "风"]),
            (ElementId.WATER.value, ["water", "水"]),
            (ElementId.FIRE.value, ["fire", "火"]),
            (ElementId.ICE.value, ["ice", "冰", "雪山", "snow"]),
        ]
        for element, terms in aliases:
            if any(term in lower or term in requirement for term in terms):
                return element
        return None

    def review(self, bundle, job_type: str) -> dict:
        """Mock Critic: always returns approved with a note."""
        return {"approved": True, "issues": [], "note": "Mock critic: design review passed (MVP mode)."}
