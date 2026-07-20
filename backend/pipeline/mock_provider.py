"""Mock LLM Provider: generates plausible config bundles without real API calls.

In MVP mode, this provider returns template-based bundles with randomized
variations. For production, replace with real API calls to Doubao/DeepSeek.
"""
import random
import copy
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


T = TypeVar("T")


class MockLLMProvider:
    """Deterministic-ish mock that generates plausible bundles for MVP demo."""

    def __init__(self, seed_store):
        self.seed = seed_store
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

    def _pick(self, items: list):
        return self._rng.choice(items)

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
