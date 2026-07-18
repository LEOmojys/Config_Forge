"""Seed data store: loads and manages reference data from /data/seed."""
import json
from pathlib import Path
from typing import Optional
from ..schemas.catalog import ElementConfig, ItemConfig
from ..schemas.skill import SkillConfig
from ..schemas.monster import MonsterTemplateConfig


class SeedStore:
    """In-memory store for seed data. All lookups are O(1)."""

    def __init__(self, seed_dir: str = "data/seed"):
        self._seed_dir = Path(seed_dir)
        self.elements: dict[str, ElementConfig] = {}
        self.items: dict[str, ItemConfig] = {}
        self.skills: dict[str, SkillConfig] = {}
        self.templates: dict[str, MonsterTemplateConfig] = {}
        self._loaded = False

    def load(self):
        if self._loaded:
            return
        self._load_elements()
        self._load_items()
        self._load_skills()
        self._load_templates()
        self._loaded = True

    def _load_elements(self):
        raw = json.loads((self._seed_dir / "elements.json").read_text(encoding="utf-8"))
        for item in raw:
            elem = ElementConfig(**item)
            self.elements[elem.element_id.value] = elem

    def _load_items(self):
        raw = json.loads((self._seed_dir / "items.json").read_text(encoding="utf-8"))
        for item in raw:
            it = ItemConfig(**item)
            self.items[it.item_id] = it

    def _load_skills(self):
        raw = json.loads((self._seed_dir / "base_skills.json").read_text(encoding="utf-8"))
        for item in raw:
            sk = SkillConfig(**item)
            self.skills[sk.skill_id] = sk

    def _load_templates(self):
        raw = json.loads((self._seed_dir / "monster_templates.json").read_text(encoding="utf-8"))
        for item in raw:
            tpl = MonsterTemplateConfig(**item)
            self.templates[tpl.template_id] = tpl

    def get_element_ids(self) -> list[str]:
        return list(self.elements.keys())

    def get_item_ids(self) -> list[str]:
        return list(self.items.keys())

    def get_skill_ids(self) -> list[str]:
        return list(self.skills.keys())

    def get_template_ids(self) -> list[str]:
        return list(self.templates.keys())

    def resolve_element(self, element_id: str) -> Optional[ElementConfig]:
        return self.elements.get(element_id)

    def resolve_item(self, item_id: str) -> Optional[ItemConfig]:
        return self.items.get(item_id)

    def resolve_skill(self, skill_id: str) -> Optional[SkillConfig]:
        return self.skills.get(skill_id)

    def resolve_template(self, template_id: str) -> Optional[MonsterTemplateConfig]:
        return self.templates.get(template_id)

    def add_skill(self, skill: SkillConfig):
        self.skills[skill.skill_id] = skill

    def add_template(self, tpl: MonsterTemplateConfig):
        self.templates[tpl.template_id] = tpl

    def register_bundle(self, bundle):
        """Register bundle-internal skills and templates for subsequent validations."""
        if hasattr(bundle, 'skills'):
            for s in bundle.skills:
                self.skills[s.skill_id] = s
        if hasattr(bundle, 'monster_template'):
            self.templates[bundle.monster_template.template_id] = bundle.monster_template

    def to_context(self) -> dict:
        """Build context dict for prompt injection."""
        return {
            "available_elements": self.get_element_ids(),
            "available_items": self.get_item_ids(),
            "available_skills": self.get_skill_ids(),
            "available_templates": self.get_template_ids(),
        }
