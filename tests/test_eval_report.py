"""Tests for ablation report persistence (output/eval/)."""
import json
from pathlib import Path

from backend.evaluation.runner import EvalRunner, EvalSample
from backend.pipeline.mock_provider import MockLLMProvider
from backend.pipeline.orchestrator import Orchestrator
from backend.stores.result_store import ResultStore
from backend.stores.seed_store import SeedStore
from backend.stores.trace_store import TraceStore
from backend.validators.rule_engine import RuleEngine

ROOT = Path(__file__).resolve().parents[1]


def _make_orchestrator(tmp_path: Path) -> Orchestrator:
    seed = SeedStore(str(ROOT / "data" / "seed"))
    seed.load()
    provider = MockLLMProvider(seed)

    class _MockGen:
        def generate_skill(self, r, fb=""):
            return provider.generate_skill_bundle(r, fb)

        def generate_monster(self, r, fb=""):
            return provider.generate_monster_bundle(r, fb)

        def generate_quest(self, r, fb=""):
            return provider.generate_quest_bundle(r, fb)

    class _MockCritic:
        def review(self, d):
            return {"approved": True, "issues": []}

    return Orchestrator(
        _MockGen(),
        _MockCritic(),
        seed,
        RuleEngine(seed),
        TraceStore(str(tmp_path / "traces")),
        ResultStore(str(tmp_path / "results")),
        event_bus=None,
    )


def _samples() -> list[EvalSample]:
    return [
        EvalSample(id=1, type="skill",
                   requirement="Generate a fire-type normal attack skill with medium damage and short cooldown."),
        EvalSample(id=2, type="monster",
                   requirement="Generate a level 30 fire-element elite monster with high HP and melee AI."),
    ]


def test_run_ablation_writes_json_and_markdown(tmp_path):
    runner = EvalRunner(_make_orchestrator(tmp_path), output_dir=tmp_path / "eval")

    # Feed a real eval_set.json so sample source tracking is exercised.
    eval_set = tmp_path / "eval_set.json"
    eval_set.write_text(json.dumps([
        {"id": 1, "type": "skill",
         "requirement": "Generate a fire-type normal attack skill with medium damage and short cooldown."},
        {"id": 2, "type": "monster",
         "requirement": "Generate a level 30 fire-element elite monster with high HP and melee AI."},
    ]), encoding="utf-8")
    samples = runner.load_samples(str(eval_set))
    results = runner.run_ablation(samples)

    assert set(results) == {"G0_pure_llm", "G1_pydantic", "G2_rules", "G3_full"}

    report = runner.last_report
    json_path = Path(report["json"])
    md_path = Path(report["markdown"])
    assert json_path.exists() and md_path.exists()
    assert json_path.parent == tmp_path / "eval"

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert set(payload["groups"]) == set(results)
    assert payload["sample_total"] == 2
    assert payload["sample_source"] == str(eval_set)
    assert payload["groups"]["G0_pure_llm"]["disabled"] is True
    assert payload["groups"]["G1_pydantic"]["total"] == 2

    md = md_path.read_text(encoding="utf-8")
    assert "消融实验报告" in md
    assert "G3: + Critic" in md


def test_run_ablation_save_report_false_writes_nothing(tmp_path):
    runner = EvalRunner(_make_orchestrator(tmp_path), output_dir=tmp_path / "eval")
    runner.run_ablation(_samples(), save_report=False)

    assert not (tmp_path / "eval").exists()
    assert runner.last_report == {}


def test_save_report_returns_paths_and_updates_last_report(tmp_path):
    runner = EvalRunner(_make_orchestrator(tmp_path), output_dir=tmp_path / "eval")
    synthetic = {
        "G0_pure_llm": {"passed": 0, "total": 1, "pass_rate": 0, "avg_rounds": 0,
                        "details": [], "disabled": True, "note": "n/a"},
        "G1_pydantic": {"passed": 1, "total": 1, "pass_rate": 1.0, "avg_rounds": 1.0,
                        "details": [{"id": 1, "passed": True, "rounds": 1, "type": "skill"}]},
        "G2_rules": {"passed": 1, "total": 1, "pass_rate": 1.0, "avg_rounds": 1.0,
                     "details": [{"id": 1, "passed": True, "rounds": 1, "type": "skill"}]},
        "G3_full": {"passed": 1, "total": 1, "pass_rate": 1.0, "avg_rounds": 1.0,
                    "details": [{"id": 1, "passed": True, "rounds": 1, "type": "skill"}]},
    }
    paths = runner.save_report(synthetic, sample_total=1)
    assert paths == runner.last_report
    assert Path(paths["json"]).exists() and Path(paths["markdown"]).exists()
