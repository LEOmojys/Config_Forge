"""Independent audits for generated bundles and persisted artifacts."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any
import csv
import json

from pydantic import BaseModel, ValidationError

from backend.schemas.bundle import MonsterBundle, QuestBundle, SkillBundle
from backend.validators.rule_engine import RuleEngine
from .models import AcceptanceCase, AuditReport


BUNDLE_MODELS = {
    "skill": SkillBundle,
    "monster": MonsterBundle,
    "quest": QuestBundle,
}

TABLE_HEADERS = {
    "skills": ["skill_id", "name", "skill_type", "element_id", "cooldown", "damage_multiplier", "stance_damage", "range", "is_aoe", "energy_cost", "description"],
    "monster_templates": ["template_id", "name", "monster_type", "base_hp", "base_attack", "base_defense", "base_speed", "base_stance", "default_ai"],
    "monster_configs": ["monster_id", "name", "template_id", "level", "element_id", "hp_modify_ratio", "attack_modify_ratio", "defense_modify_ratio", "stance_modify_ratio", "loot_group_id", "summon_group_id", "description"],
    "monster_skills": ["monster_id", "slot", "skill_id", "trigger_key", "weight"],
    "monster_loot": ["loot_group_id", "item_id", "chance", "min_count", "max_count"],
    "quest_templates": ["quest_id", "name", "quest_type", "required_level", "pre_quest_id", "reward_group_id", "description"],
    "quest_objectives": ["objective_id", "quest_id", "objective_type", "target_id", "target_count", "description"],
}


def _canonical(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _row(data: dict[str, Any], headers: list[str]) -> tuple[str, ...]:
    return tuple(_csv_value(data.get(header)) for header in headers)


class OutputAuditor:
    def __init__(self, seed_store):
        self.seed = seed_store
        self.seed.load()
        self.rules = RuleEngine(seed_store)

    def audit(self, case: AcceptanceCase, raw_bundles: list[dict[str, Any]],
              statuses: list[str], artifact_root: Path, report: AuditReport) -> AuditReport:
        models = self._validate_bundles(case, raw_bundles, report)
        self._audit_statuses(case, statuses, report)
        self._audit_semantics(case, models, report)
        self._audit_json(case, models, artifact_root / "json", report)
        self._audit_csv(case, models, artifact_root / "csv", report)
        self._audit_traces(case, models, artifact_root / "traces", report)
        report.metrics.update({
            "requested_count": case.batch_count,
            "bundle_count": len(raw_bundles),
            "terminal_statuses": Counter(statuses),
            "error_count": sum(item.severity == "error" for item in report.findings),
            "warning_count": sum(item.severity == "warning" for item in report.findings),
        })
        return report

    def _validate_bundles(self, case: AcceptanceCase, raw_bundles: list[dict[str, Any]],
                          report: AuditReport) -> list[BaseModel]:
        model_type = BUNDLE_MODELS[case.job_type]
        models = []
        expected_count = int(case.expected.get("count", case.batch_count))
        if len(raw_bundles) != expected_count:
            report.add("COUNT_MISMATCH", f"Expected {expected_count} bundles, got {len(raw_bundles)}", "bundles")
        for index, raw in enumerate(raw_bundles, start=1):
            try:
                bundle = model_type.model_validate(raw)
            except ValidationError as exc:
                report.add("SCHEMA_INVALID", str(exc), f"bundles[{index - 1}]")
                continue
            models.append(bundle)
            if case.job_type == "skill":
                validation = self.rules.validate_skill_bundle(bundle)
            elif case.job_type == "monster":
                validation = self.rules.validate_monster_bundle(bundle)
            else:
                validation = self.rules.validate_quest_bundle(bundle)
            for violation in validation.violations:
                report.add(
                    f"RULE_{violation.rule_id}",
                    violation.message,
                    f"bundles[{index - 1}].{violation.table}.{violation.field}",
                    violation.severity,
                )
        return models

    @staticmethod
    def _audit_statuses(case: AcceptanceCase, statuses: list[str], report: AuditReport):
        allowed = set(case.expected.get("allowed_statuses", ["passed"]))
        for index, status in enumerate(statuses):
            if status not in allowed:
                report.add("STATUS_UNEXPECTED", f"Status {status!r} not in {sorted(allowed)}", f"statuses[{index}]")
        if len(statuses) != case.batch_count:
            report.add("STATUS_COUNT_MISMATCH", f"Expected {case.batch_count} statuses, got {len(statuses)}", "statuses")

    def _audit_semantics(self, case: AcceptanceCase, models: list[BaseModel], report: AuditReport):
        identities = [self._identity(case.job_type, item) for item in models]
        if case.expected.get("unique_ids", case.batch_count > 1):
            ids = [item["id"] for item in identities if item.get("id")]
            if len(ids) != len(set(ids)):
                report.add("DUPLICATE_ID", f"Duplicate primary IDs found: {ids}", "bundles")
        if case.expected.get("unique_names", False):
            names = [item["name"] for item in identities if item.get("name")]
            if len(names) != len(set(names)):
                report.add("DUPLICATE_NAME", f"Duplicate names found: {names}", "bundles")

        required_text = case.expected.get("required_text_any", [])
        for index, model in enumerate(models):
            if required_text:
                haystack = _canonical(model.model_dump(mode="json", exclude_none=True)).lower()
                if not any(str(term).lower() in haystack for term in required_text):
                    report.add("REQUIRED_TEXT_MISSING", f"None of {required_text} appears in output", f"bundles[{index}]")

            if case.job_type == "monster":
                self._audit_monster(model, case.expected.get("monster", {}), index, report)
            elif case.job_type == "skill":
                self._audit_skill(model, case.expected.get("skill", {}), index, report)
            else:
                self._audit_quest(model, case.expected.get("quest", {}), index, report)

    @staticmethod
    def _identity(job_type: str, bundle: BaseModel) -> dict[str, Any]:
        if job_type == "monster":
            return {"id": bundle.monster_config.monster_id, "name": bundle.monster_config.name}
        if job_type == "quest":
            return {"id": bundle.quest_template.quest_id, "name": bundle.quest_template.name}
        first = bundle.skills[0]
        return {"id": first.skill_id, "name": first.name}

    def _audit_monster(self, bundle: MonsterBundle, expected: dict[str, Any], index: int, report: AuditReport):
        base = f"bundles[{index}]"
        config = bundle.monster_config
        template = bundle.monster_template
        if expected.get("types") and template.monster_type.value not in expected["types"]:
            report.add("MONSTER_TYPE_MISMATCH", f"Expected type in {expected['types']}, got {template.monster_type.value}", f"{base}.monster_template.monster_type")
        if expected.get("elements") and config.element_id.value not in expected["elements"]:
            report.add("ELEMENT_MISMATCH", f"Expected element in {expected['elements']}, got {config.element_id.value}", f"{base}.monster_config.element_id")
        self._audit_range(config.level, expected.get("level"), "LEVEL_OUT_OF_RANGE", f"{base}.monster_config.level", report)
        if len(bundle.monster_skills) < int(expected.get("min_skills", 0)):
            report.add("TOO_FEW_SKILLS", f"Expected at least {expected['min_skills']} monster skills, got {len(bundle.monster_skills)}", f"{base}.monster_skills")
        if len(bundle.monster_loot) < int(expected.get("min_loot", 0)):
            report.add("TOO_FEW_LOOT", f"Expected at least {expected['min_loot']} loot rows, got {len(bundle.monster_loot)}", f"{base}.monster_loot")
        if expected.get("require_summon") and bundle.summon_config is None:
            report.add("SUMMON_MISSING", "Expected summon_config", f"{base}.summon_config")
        for loot_index, loot in enumerate(bundle.monster_loot):
            if loot.loot_group_id != config.loot_group_id:
                report.add("LOOT_OWNER_MISMATCH", f"{loot.loot_group_id} != {config.loot_group_id}", f"{base}.monster_loot[{loot_index}].loot_group_id")
            if loot.item_id not in self.seed.items:
                report.add("LOOT_ITEM_UNKNOWN", f"Unknown item_id {loot.item_id}", f"{base}.monster_loot[{loot_index}].item_id")

    @staticmethod
    def _audit_skill(bundle: SkillBundle, expected: dict[str, Any], index: int, report: AuditReport):
        base = f"bundles[{index}].skills"
        if len(bundle.skills) < int(expected.get("min_skills", 1)):
            report.add("TOO_FEW_SKILLS", f"Expected at least {expected['min_skills']} skills, got {len(bundle.skills)}", base)
        for skill_index, skill in enumerate(bundle.skills):
            path = f"{base}[{skill_index}]"
            if expected.get("types") and skill.skill_type.value not in expected["types"]:
                report.add("SKILL_TYPE_MISMATCH", f"Expected type in {expected['types']}, got {skill.skill_type.value}", f"{path}.skill_type")
            if expected.get("elements") and skill.element_id.value not in expected["elements"]:
                report.add("ELEMENT_MISMATCH", f"Expected element in {expected['elements']}, got {skill.element_id.value}", f"{path}.element_id")
            if "is_aoe" in expected and skill.is_aoe != bool(expected["is_aoe"]):
                report.add("AOE_MISMATCH", f"Expected is_aoe={expected['is_aoe']}, got {skill.is_aoe}", f"{path}.is_aoe")
            OutputAuditor._audit_range(skill.cooldown, expected.get("cooldown"), "COOLDOWN_OUT_OF_RANGE", f"{path}.cooldown", report)

    @staticmethod
    def _audit_quest(bundle: QuestBundle, expected: dict[str, Any], index: int, report: AuditReport):
        base = f"bundles[{index}]"
        template = bundle.quest_template
        if expected.get("types") and template.quest_type.value not in expected["types"]:
            report.add("QUEST_TYPE_MISMATCH", f"Expected type in {expected['types']}, got {template.quest_type.value}", f"{base}.quest_template.quest_type")
        OutputAuditor._audit_range(template.required_level, expected.get("required_level"), "LEVEL_OUT_OF_RANGE", f"{base}.quest_template.required_level", report)
        if len(bundle.quest_objectives) < int(expected.get("min_objectives", 1)):
            report.add("TOO_FEW_OBJECTIVES", f"Expected at least {expected['min_objectives']} objectives, got {len(bundle.quest_objectives)}", f"{base}.quest_objectives")
        actual_types = {item.objective_type.value for item in bundle.quest_objectives}
        missing = set(expected.get("required_objective_types", [])) - actual_types
        if missing:
            report.add("OBJECTIVE_TYPE_MISSING", f"Missing objective types: {sorted(missing)}", f"{base}.quest_objectives")

    @staticmethod
    def _audit_range(value: float, bounds: Any, code: str, path: str, report: AuditReport):
        if not bounds:
            return
        minimum = bounds.get("min")
        maximum = bounds.get("max")
        if minimum is not None and value < minimum or maximum is not None and value > maximum:
            report.add(code, f"Value {value} outside range [{minimum}, {maximum}]", path)

    def _audit_json(self, case: AcceptanceCase, models: list[BaseModel], json_dir: Path, report: AuditReport):
        files = sorted(json_dir.glob("*.json")) if json_dir.exists() else []
        if len(files) != len(models):
            report.add("JSON_FILE_COUNT", f"Expected {len(models)} JSON files, got {len(files)}", str(json_dir))
        actual = Counter()
        for path in files:
            try:
                actual[_canonical(json.loads(path.read_text(encoding="utf-8")))] += 1
            except Exception as exc:
                report.add("JSON_PARSE_ERROR", str(exc), str(path))
        expected = Counter(_canonical(item.model_dump(mode="json", exclude_none=True)) for item in models)
        if actual != expected:
            report.add("JSON_BUNDLE_MISMATCH", f"Persisted JSON bundles differ from generated bundles (missing={sum((expected - actual).values())}, extra={sum((actual - expected).values())})", str(json_dir))

    def _audit_csv(self, case: AcceptanceCase, models: list[BaseModel], csv_dir: Path, report: AuditReport):
        expected_rows = self._expected_csv_rows(case.job_type, models)
        actual_tables = {path.stem for path in csv_dir.glob("*.csv")} if csv_dir.exists() else set()
        expected_tables = {name for name, rows in expected_rows.items() if rows}
        if actual_tables != expected_tables:
            report.add("CSV_TABLE_SET_MISMATCH", f"Expected tables {sorted(expected_tables)}, got {sorted(actual_tables)}", str(csv_dir))
        for table_name in sorted(expected_tables | actual_tables):
            path = csv_dir / f"{table_name}.csv"
            if not path.exists():
                continue
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.reader(handle)
                headers = next(reader, [])
                rows = Counter(tuple(row) for row in reader)
            expected_headers = TABLE_HEADERS.get(table_name, [])
            if headers != expected_headers:
                report.add("CSV_HEADER_MISMATCH", f"Expected {expected_headers}, got {headers}", str(path))
                continue
            expected_counter = Counter(expected_rows.get(table_name, []))
            if rows != expected_counter:
                report.add("CSV_ROW_MISMATCH", f"Rows differ (missing={sum((expected_counter - rows).values())}, extra={sum((rows - expected_counter).values())})", str(path))

    def _audit_traces(self, case: AcceptanceCase, models: list[BaseModel], trace_dir: Path, report: AuditReport):
        traces = []
        for path in sorted(trace_dir.glob("trace_*.json")) if trace_dir.exists() else []:
            try:
                traces.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception as exc:
                report.add("TRACE_PARSE_ERROR", str(exc), str(path))
        parents = [item for item in traces if item.get("is_batch")]
        children = [item for item in traces if not item.get("is_batch")]
        expected_trace_count = case.batch_count + (1 if case.batch_count > 1 else 0)
        if len(traces) != expected_trace_count:
            report.add("TRACE_COUNT_MISMATCH", f"Expected {expected_trace_count} traces, got {len(traces)}", str(trace_dir))
        terminal = {"passed", "partial", "need_human", "failed", "error"}
        for item in traces:
            if item.get("status") not in terminal:
                report.add("TRACE_NOT_TERMINAL", f"Trace status is {item.get('status')!r}", item.get("trace_id", "trace"))
        if case.batch_count > 1:
            if len(parents) != 1:
                report.add("BATCH_PARENT_COUNT", f"Expected one parent trace, got {len(parents)}", str(trace_dir))
            elif len(parents[0].get("batch_items", [])) != case.batch_count:
                report.add("BATCH_PARENT_ITEMS", f"Expected {case.batch_count} parent items, got {len(parents[0].get('batch_items', []))}", parents[0].get("trace_id", "parent"))
        persisted_bundles = Counter()
        for child in children:
            passed_round = next((item for item in reversed(child.get("rounds", [])) if item.get("passed")), None)
            if passed_round and passed_round.get("bundle"):
                persisted_bundles[_canonical(passed_round["bundle"])] += 1
        expected_bundles = Counter(_canonical(item.model_dump(mode="json", exclude_none=True)) for item in models)
        if persisted_bundles != expected_bundles:
            report.add("TRACE_BUNDLE_MISMATCH", f"Trace bundles differ from generated bundles (missing={sum((expected_bundles - persisted_bundles).values())}, extra={sum((persisted_bundles - expected_bundles).values())})", str(trace_dir))

    @staticmethod
    def _expected_csv_rows(job_type: str, models: list[BaseModel]) -> dict[str, list[tuple[str, ...]]]:
        output = {name: [] for name in TABLE_HEADERS}
        for model in models:
            data = model.model_dump(mode="json", exclude_none=False)
            if job_type == "skill":
                for skill in data["skills"]:
                    output["skills"].append(_row(skill, TABLE_HEADERS["skills"]))
            elif job_type == "quest":
                output["quest_templates"].append(_row(data["quest_template"], TABLE_HEADERS["quest_templates"]))
                for objective in data["quest_objectives"]:
                    output["quest_objectives"].append(_row(objective, TABLE_HEADERS["quest_objectives"]))
            else:
                for skill in data.get("skills", []):
                    output["skills"].append(_row(skill, TABLE_HEADERS["skills"]))
                for key in ("monster_template", "summon_template"):
                    if data.get(key):
                        output["monster_templates"].append(_row(data[key], TABLE_HEADERS["monster_templates"]))
                for key in ("monster_config", "summon_config"):
                    if data.get(key):
                        output["monster_configs"].append(_row(data[key], TABLE_HEADERS["monster_configs"]))
                for key in ("monster_skills", "summon_skills"):
                    for link in data.get(key, []):
                        output["monster_skills"].append(_row(link, TABLE_HEADERS["monster_skills"]))
                for key in ("monster_loot", "summon_loot"):
                    for loot in data.get(key, []):
                        output["monster_loot"].append(_row(loot, TABLE_HEADERS["monster_loot"]))
        return output
