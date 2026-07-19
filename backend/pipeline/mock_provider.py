"""Mock LLM Provider: generates plausible config bundles without real API calls.

In MVP mode, this provider returns template-based bundles with randomized
variations. For production, replace with real API calls to Doubao/DeepSeek.
"""
import random
import copy
import uuid
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
        elem = self._pick(elements)
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
        tpl = copy.deepcopy(self._pick(templates))
        elements = self.seed.get_element_ids()
        elem = self._pick(elements)
        is_summoner = "summon" in requirement.lower() or "召唤" in requirement.lower()
        if is_summoner:
            tpl.default_ai = AIBehavior.SUMMONER
        m_id = f"mon_{uuid.uuid4().hex[:8]}"
        lg_id = f"loot_{uuid.uuid4().hex[:6]}"
        cfg = MonsterConfig(
            monster_id=m_id,
            name=f"Generated {tpl.name} {m_id[-4:]}",
            template_id=tpl.template_id,
            level=self._rng.randint(10, 80),
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
        for i, sid in enumerate(self._rng.sample(skill_ids, min(self._rng.randint(1, 3), len(skill_ids))), start=1):
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
        is_main = "main" in requirement.lower() or "主线" in requirement.lower()
        qt = QuestTemplateConfig(
            quest_id=q_id,
            name=f"Generated Quest {q_id[-4:]}",
            quest_type=QuestType.MAIN if is_main else QuestType.SIDE,
            required_level=self._rng.randint(1, 50),
            reward_group_id=f"rew_{uuid.uuid4().hex[:6]}",
            description=f"Auto-generated quest: {requirement[:80]}",
        )
        objectives = []
        o_types = [ObjectiveType.KILL, ObjectiveType.COLLECT, ObjectiveType.TALK, ObjectiveType.EXPLORE]
        for i, otype in enumerate(self._rng.sample(o_types, self._rng.randint(2, 4)), start=1):
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

    def review(self, bundle, job_type: str) -> dict:
        """Mock Critic: always returns approved with a note."""
        return {"approved": True, "issues": [], "note": "Mock critic: design review passed (MVP mode)."}
