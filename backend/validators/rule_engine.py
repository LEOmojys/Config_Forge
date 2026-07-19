"""Rule engine: deterministic validation with structured, LLM-actionable violations."""
import re
from dataclasses import dataclass, field
from typing import Optional
from ..schemas.bundle import MonsterBundle, QuestBundle, SkillBundle
from ..schemas.monster import MonsterTemplateConfig, MonsterConfig, MonsterSkillLink, MonsterLootEntry
from ..schemas.quest import QuestTemplateConfig, QuestObjectiveConfig
from ..schemas.skill import SkillConfig


@dataclass
class RuleViolation:
    rule_id: str
    severity: str  # "error" | "warning"
    table: str
    field: str
    message: str


@dataclass
class ValidationResult:
    violations: list[RuleViolation] = field(default_factory=list)

    @property
    def errors(self) -> list[RuleViolation]:
        return [v for v in self.violations if v.severity == "error"]

    @property
    def warnings(self) -> list[RuleViolation]:
        return [v for v in self.violations if v.severity == "warning"]

    @property
    def passed(self) -> bool:
        return len(self.errors) == 0

    def to_feedback(self) -> str:
        if not self.violations:
            return ""
        lines = ["[Rule Violations Found - 请逐条修复]"]
        for v in self.violations:
            tag = "ERROR" if v.severity == "error" else "WARN"
            lines.append(f"  [{tag}] {v.rule_id} @ {v.table}.{v.field}: {v.message}")
        return "\n".join(lines)


class RuleEngine:
    def __init__(self, seed_store):
        self.seed = seed_store

    def validate_skill_bundle(self, bundle: SkillBundle) -> ValidationResult:
        result = ValidationResult()
        for skill in bundle.skills:
            result.violations.extend(self._R001_skill(skill))
            result.violations.extend(self._R002_element(skill.skill_id, "skills", "element_id", skill.element_id.value))
        return result

    def validate_monster_bundle(self, bundle: MonsterBundle) -> ValidationResult:
        result = ValidationResult()
        tpl = bundle.monster_template
        result.violations.extend(self._R001_template(tpl))

        cfg = bundle.monster_config
        result.violations.extend(self._R001_monster_config(cfg))
        result.violations.extend(self._R002_element(cfg.monster_id, "monster_configs", "element_id", cfg.element_id.value))
        result.violations.extend(self._R003_template_ref(cfg, bundle))
        result.violations.extend(self._R007_ratio(cfg))
        result.violations.extend(self._R008_boss_skills(bundle))
        result.violations.extend(self._R009_summoner_check(bundle))

        # Bundle-internal skill IDs (from skills field) plus seed skills are valid
        bundle_skill_ids = {s.skill_id for s in bundle.skills}
        for link in bundle.monster_skills:
            result.violations.extend(self._R003_monster_skill_owner(link, cfg.monster_id, "monster_skills"))
            result.violations.extend(self._R004_skill_ref(link, bundle_skill_ids))

        # Loot items: check seed + provide available alternatives
        result.violations.extend(self._R003_loot_group_ref(bundle.monster_loot, cfg.loot_group_id, "monster_loot"))
        result.violations.extend(self._R005_loot_item_ref(bundle.monster_loot))
        result.violations.extend(self._R006_loot_chance_sum(bundle.monster_loot))

        if bundle.summon_template:
            result.violations.extend(self._R001_template(bundle.summon_template))
        if bundle.summon_config:
            result.violations.extend(self._R001_monster_config(bundle.summon_config))
            result.violations.extend(self._R002_element(
                bundle.summon_config.monster_id,
                "monster_configs",
                "element_id",
                bundle.summon_config.element_id.value,
            ))
            result.violations.extend(self._R003_template_ref(bundle.summon_config, bundle))
            result.violations.extend(self._R007_ratio(bundle.summon_config))
            for link in bundle.summon_skills:
                result.violations.extend(self._R003_monster_skill_owner(
                    link, bundle.summon_config.monster_id, "monster_skills"
                ))
                result.violations.extend(self._R004_skill_ref(link, bundle_skill_ids))
            result.violations.extend(self._R003_loot_group_ref(
                bundle.summon_loot, bundle.summon_config.loot_group_id, "monster_loot"
            ))
            result.violations.extend(self._R005_loot_item_ref(bundle.summon_loot))
            result.violations.extend(self._R006_loot_chance_sum(bundle.summon_loot))
        elif bundle.summon_skills or bundle.summon_loot:
            result.violations.append(RuleViolation(
                "R003", "error", "monster_configs", "summon_config",
                "summon_skills/summon_loot require summon_config"
            ))
        return result

    def validate_quest_bundle(self, bundle: QuestBundle) -> ValidationResult:
        result = ValidationResult()
        qt = bundle.quest_template
        result.violations.extend(self._R001_quest_template(qt))
        for obj in bundle.quest_objectives:
            result.violations.extend(self._R001_quest_objective(obj))
            result.violations.extend(self._R003_quest_objective_owner(obj, qt.quest_id))
            result.violations.extend(self._R010_objective_target(obj))
        return result

    # ── R001: snake_case ID + prefix convention ──────
    # Per-type expected prefixes (seed convention):
    _PREFIXES = {
        "skill_id": "sk_",
        "template_id": "tpl_",
        "monster_id": "mon_",
        "loot_group_id": "loot_",
        "quest_id": "qst_",
        "objective_id": "obj_",
        "reward_group_id": "rew_",
    }

    def _check_id(self, id_val: str, table: str, field: str) -> list[RuleViolation]:
        violations = []
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,63}", id_val):
            violations.append(RuleViolation("R001", "error", table, field,
                f"ID '{id_val}' must be snake_case (lowercase, digits, underscores, 3-64 chars)"))
            return violations
        # Check prefix convention (only for generated IDs, not seed IDs)
        expected = self._PREFIXES.get(field)
        if expected and not id_val.startswith(expected):
            violations.append(RuleViolation("R001", "error", table, field,
                f"ID '{id_val}' must use '{expected}' prefix (e.g. {expected}fireball), not '{id_val[:3]}_'"))
        return violations

    def _R001_skill(self, s: SkillConfig) -> list[RuleViolation]:
        return self._check_id(s.skill_id, "skills", "skill_id")

    def _R001_template(self, t: MonsterTemplateConfig) -> list[RuleViolation]:
        return self._check_id(t.template_id, "monster_templates", "template_id")

    def _R001_monster_config(self, c: MonsterConfig) -> list[RuleViolation]:
        v = self._check_id(c.monster_id, "monster_configs", "monster_id")
        v += self._check_id(c.template_id, "monster_configs", "template_id")
        return v

    def _R001_quest_template(self, q: QuestTemplateConfig) -> list[RuleViolation]:
        v = self._check_id(q.quest_id, "quest_templates", "quest_id")
        v += self._check_id(q.reward_group_id, "quest_templates", "reward_group_id")
        if q.pre_quest_id:
            v += self._check_id(q.pre_quest_id, "quest_templates", "quest_id")
        return v

    def _R001_quest_objective(self, o: QuestObjectiveConfig) -> list[RuleViolation]:
        return self._check_id(o.objective_id, "quest_objectives", "objective_id")

    # ── R002: element_id exists ──────────────────────
    def _R002_element(self, entity_id: str, table: str, field: str, element_id: str) -> list[RuleViolation]:
        if element_id not in self.seed.elements:
            available = ", ".join(self.seed.get_element_ids())
            return [RuleViolation("R002", "error", table, field,
                f"element_id={element_id} 不存在。可用: [{available}]")]
        return []

    # ── R003: template_id exists (seed OR bundle-internal) ──
    def _R003_template_ref(self, cfg: MonsterConfig, bundle: MonsterBundle = None) -> list[RuleViolation]:
        # Accept if in seed store OR is the bundle's own template
        if cfg.template_id in self.seed.templates:
            return []
        if bundle and cfg.template_id == bundle.monster_template.template_id:
            return []
        if bundle and bundle.summon_template and cfg.template_id == bundle.summon_template.template_id:
            return []
        available = ", ".join(self.seed.get_template_ids())
        return [RuleViolation("R003", "error", "monster_configs", "template_id",
            f"template_id={cfg.template_id} 不存在。可用种子模板: [{available}]，或使用 Bundle 内自定义模板 ID")]

    # ── R004: skill_id exists (seed OR bundle-internal skills) ──
    def _R003_monster_skill_owner(
        self, link: MonsterSkillLink, expected_monster_id: str, table: str
    ) -> list[RuleViolation]:
        if link.monster_id == expected_monster_id:
            return []
        return [RuleViolation("R003", "error", table, "monster_id",
            f"monster_id={link.monster_id} must match owning monster_id={expected_monster_id}")]

    def _R003_loot_group_ref(
        self, loots: list[MonsterLootEntry], expected_loot_group_id: str, table: str
    ) -> list[RuleViolation]:
        violations = []
        for loot in loots:
            if loot.loot_group_id != expected_loot_group_id:
                violations.append(RuleViolation("R003", "error", table, "loot_group_id",
                    f"loot_group_id={loot.loot_group_id} must match owning loot_group_id={expected_loot_group_id}"))
        return violations

    def _R003_quest_objective_owner(self, obj: QuestObjectiveConfig, expected_quest_id: str) -> list[RuleViolation]:
        if obj.quest_id == expected_quest_id:
            return []
        return [RuleViolation("R003", "error", "quest_objectives", "quest_id",
            f"quest_id={obj.quest_id} must match quest_template.quest_id={expected_quest_id}")]

    def _R004_skill_ref(self, link: MonsterSkillLink, bundle_skill_ids: set[str]) -> list[RuleViolation]:
        if link.skill_id in self.seed.skills or link.skill_id in bundle_skill_ids:
            return []
        available = ", ".join(self.seed.get_skill_ids())
        hint = f"可用种子技能: [{available}]。如需自定义技能请在 bundle.skills 中定义。" if bundle_skill_ids else f"可用种子技能: [{available}]。或在 bundle.skills 中定义新技能。"
        return [RuleViolation("R004", "error", "monster_skills", "skill_id",
            f"skill_id={link.skill_id} 不存在。{hint}")]

    # ── R005: loot item_id exists ────────────────────
    def _R005_loot_item_ref(self, loots: list[MonsterLootEntry]) -> list[RuleViolation]:
        violations = []
        for loot in loots:
            if loot.item_id not in self.seed.items:
                available = ", ".join(self.seed.get_item_ids())
                violations.append(RuleViolation("R005", "error", "monster_loot", "item_id",
                    f"item_id={loot.item_id} 不存在。可用道具: [{available}]"))
        return violations

    # ── R006: loot chance sum ────────────────────────
    def _R006_loot_chance_sum(self, loots: list[MonsterLootEntry]) -> list[RuleViolation]:
        groups: dict[str, float] = {}
        for loot in loots:
            groups[loot.loot_group_id] = groups.get(loot.loot_group_id, 0) + loot.chance
        violations = []
        for gid, total in groups.items():
            if total > 1.0001:
                violations.append(RuleViolation("R006", "error", "monster_loot", "chance",
                    f"loot_group_id={gid} total chance {total:.3f} exceeds 1.0"))
        return violations

    # ── R007: ratio bounds ───────────────────────────
    def _R007_ratio(self, cfg: MonsterConfig) -> list[RuleViolation]:
        violations = []
        for field_name, val in [
            ("hp_modify_ratio", cfg.hp_modify_ratio),
            ("attack_modify_ratio", cfg.attack_modify_ratio),
            ("defense_modify_ratio", cfg.defense_modify_ratio),
            ("stance_modify_ratio", cfg.stance_modify_ratio),
        ]:
            if val < 0.1 or val > 10.0:
                violations.append(RuleViolation("R007", "error", "monster_configs", field_name,
                    f"{field_name}={val} out of allowed range [0.1, 10.0]"))
        return violations

    # ── R008: boss has >= 2 skills ───────────────────
    def _R008_boss_skills(self, bundle: MonsterBundle) -> list[RuleViolation]:
        tpl = bundle.monster_template
        if tpl.monster_type.value == "boss" and len(bundle.monster_skills) < 2:
            return [RuleViolation("R008", "error", "monster_skills", "skill_id",
                f"boss monster '{tpl.name}' 至少需要 2 个技能, 当前仅 {len(bundle.monster_skills)} 个")]
        return []

    # ── R009: summoner check ─────────────────────────
    def _R009_summoner_check(self, bundle: MonsterBundle) -> list[RuleViolation]:
        tpl = bundle.monster_template
        if tpl.default_ai.value == "summoner":
            has_summon = bundle.summon_config is not None
            has_summon_skill = any("summon" in s.skill_id.lower() for s in bundle.skills)
            if not has_summon and not has_summon_skill:
                return [RuleViolation("R009", "warning", "monster_configs", "summon_group_id",
                    f"summoner monster '{tpl.name}' has no summon_config or summon skill")]
        return []

    # ── R010: objective target_id type match ─────────
    def _R010_objective_target(self, obj: QuestObjectiveConfig) -> list[RuleViolation]:
        otype = obj.objective_type.value
        tid = obj.target_id
        if otype == "kill":
            valid = tid in self.seed.templates
            if not valid:
                available = ", ".join(self.seed.get_template_ids())
                return [RuleViolation("R010", "error", "quest_objectives", "target_id",
                    f"kill target_id={tid} 不存在。可用怪物模板: [{available}]")]
        elif otype == "collect":
            valid = tid in self.seed.items
            if not valid:
                available = ", ".join(self.seed.get_item_ids())
                return [RuleViolation("R010", "error", "quest_objectives", "target_id",
                    f"collect target_id={tid} 不存在。可用道具: [{available}]")]
        return []
