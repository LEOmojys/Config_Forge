"""Regression tests found by real-provider acceptance runs."""
import csv

import pytest

from backend.pipeline.exporter import CsvExporter
from backend.providers.doubao_provider import DoubaoProvider, _is_unavailable_model_error
from backend.schemas.bundle import MonsterBundle, SkillBundle


def test_summon_loot_is_exported(tmp_path):
    bundle = MonsterBundle.model_validate({
        "monster_template": {
            "template_id": "tpl_summoner",
            "name": "Summoner",
            "monster_type": "elite",
            "base_hp": 1000,
            "base_attack": 100,
            "base_defense": 50,
            "base_speed": 80,
            "base_stance": 50,
            "default_ai": "summoner"
        },
        "monster_config": {
            "monster_id": "mon_summoner",
            "name": "Summoner",
            "template_id": "tpl_summoner",
            "level": 30,
            "element_id": "thunder",
            "hp_modify_ratio": 1.5,
            "attack_modify_ratio": 1.2,
            "defense_modify_ratio": 1.0,
            "stance_modify_ratio": 1.0,
            "loot_group_id": "loot_summoner"
        },
        "monster_skills": [],
        "monster_loot": [{
            "loot_group_id": "loot_summoner",
            "item_id": "it_gold_pouch",
            "chance": 0.5,
            "min_count": 1,
            "max_count": 1
        }],
        "summon_template": {
            "template_id": "tpl_summon_minion",
            "name": "Minion",
            "monster_type": "summon",
            "base_hp": 200,
            "base_attack": 30,
            "base_defense": 10,
            "base_speed": 70,
            "base_stance": 10,
            "default_ai": "melee"
        },
        "summon_config": {
            "monster_id": "mon_summon_minion",
            "name": "Minion",
            "template_id": "tpl_summon_minion",
            "level": 30,
            "element_id": "thunder",
            "hp_modify_ratio": 1.0,
            "attack_modify_ratio": 1.0,
            "defense_modify_ratio": 1.0,
            "stance_modify_ratio": 1.0,
            "loot_group_id": "loot_summon_minion"
        },
        "summon_loot": [{
            "loot_group_id": "loot_summon_minion",
            "item_id": "it_iron_ore",
            "chance": 0.25,
            "min_count": 1,
            "max_count": 2
        }]
    })
    CsvExporter(str(tmp_path)).export_monster(bundle)
    with (tmp_path / "monster_loot.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["loot_group_id"] for row in rows} == {"loot_summoner", "loot_summon_minion"}


def test_provider_does_not_switch_model_after_validation_failures(monkeypatch):
    monkeypatch.setenv("ARK_CODING_API_KEY", "test-key")
    monkeypatch.setenv("ARK_CODING_MODEL", "ark-code-latest")
    monkeypatch.setenv("ARK_CODING_MODEL_FALLBACKS", "explicit-fallback")
    provider = DoubaoProvider()
    calls = []

    class _Completions:
        @staticmethod
        def create(**kwargs):
            calls.append(kwargs["model"])
            return type("Response", (), {
                "choices": [type("Choice", (), {
                    "message": type("Message", (), {"content": "{}"})()
                })()]
            })()

    provider.client = type("Client", (), {
        "chat": type("Chat", (), {"completions": _Completions()})()
    })()
    with pytest.raises(RuntimeError, match="ark-code-latest"):
        provider.generate_structured("system", "user", SkillBundle, max_retries=2)
    assert calls == ["ark-code-latest"] * 3


def test_unsupported_model_is_classified_as_unavailable():
    assert _is_unavailable_model_error(Exception("UnsupportedModel: does not support the Coding Plan feature"))
