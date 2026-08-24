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
    # Golden yardstick: mock bundles satisfy the full contract.
    for key in ("G1_pydantic", "G2_rules", "G3_full"):
        assert payload["groups"][key]["contract_pass_rate"] == 1.0
        assert payload["groups"][key]["contract_passed"] == 2

    md = md_path.read_text(encoding="utf-8")
    assert "消融实验报告" in md
    assert "G3: + Critic" in md
    assert "合同符合率" in md


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


def test_run_ablation_emits_progress_events(tmp_path):
    runner = EvalRunner(_make_orchestrator(tmp_path), output_dir=tmp_path / "eval")
    events = []
    runner.run_ablation(_samples(), progress_cb=lambda etype, data: events.append((etype, data)))

    types = [etype for etype, _ in events]
    assert types[0] == "eval_start"

    group_starts = [d for t, d in events if t == "group_start"]
    assert [d["group"] for d in group_starts] == ["G0_pure_llm", "G1_pydantic", "G2_rules", "G3_full"]

    group_dones = [d for t, d in events if t == "group_done"]
    assert [d["group"] for d in group_dones] == ["G0_pure_llm", "G1_pydantic", "G2_rules", "G3_full"]
    assert group_dones[0]["result"]["disabled"] is True

    # G0 disabled emits no samples; G1+G2+G3 × 2 samples = 6 sample_done events
    sample_dones = [d for t, d in events if t == "sample_done"]
    assert len(sample_dones) == 6
    assert all("group" in d and d["total"] == 2 for d in sample_dones)
    assert {d["group"] for d in sample_dones} == {"G1_pydantic", "G2_rules", "G3_full"}


def test_orchestrator_dry_run_includes_round_logs(tmp_path):
    orch = _make_orchestrator(tmp_path)
    res = orch._run(
        "monster", "Generate a level 30 fire elite monster with melee AI",
        enable_critic=True, skip_validation=False, dry_run=True,
    )
    assert res["status"] == "passed"
    assert "round_logs" in res
    assert len(res["round_logs"]) == 1
    assert res["round_logs"][0]["passed"] is True
    assert res["round_logs"][0]["violations"] == []
    # Tokens slot must exist even when providers record nothing (mock mode).
    assert "tokens" in res["round_logs"][0]
    assert res["round_logs"][0]["tokens"]["generation"] is None
    assert res["round_logs"][0]["tokens"]["critic"] is None


class _UsageFakeOrch:
    """Fake orchestrator returning round_logs with provider token usage."""

    def _run(self, job_type, requirement, enable_critic, skip_validation, dry_run):
        return {
            "status": "passed", "rounds": 2, "bundle": None, "type": job_type,
            "round_logs": [
                {"round": 1, "violations": [], "critic": None, "passed": False,
                 "tokens": {"generation": {"prompt_tokens": 3000, "completion_tokens": 800,
                                           "total_tokens": 3800},
                            "critic": None}},
                {"round": 2, "violations": [], "critic": {"approved": True, "issues": []},
                 "passed": True,
                 "tokens": {"generation": {"prompt_tokens": 3100, "completion_tokens": 700,
                                           "total_tokens": 3800},
                            "critic": {"prompt_tokens": 600, "completion_tokens": 100,
                                       "total_tokens": 700}}},
            ],
        }


def test_token_aggregation_in_eval_details(tmp_path):
    runner = EvalRunner(_UsageFakeOrch(), output_dir=tmp_path / "eval")
    samples = [EvalSample(id=1, type="monster", requirement="any requirement")]
    results = runner.run_ablation(samples, save_report=False)

    for key in ("G1_pydantic", "G2_rules", "G3_full"):
        g = results[key]
        d = g["details"][0]
        assert d["tokens"] == {"prompt": 6700, "completion": 1600, "total": 8300}
        assert g["avg_tokens_per_sample"] == 8300.0


def test_checkpoint_written_during_run_and_removed_on_success(tmp_path):
    runner = EvalRunner(_make_orchestrator(tmp_path), output_dir=tmp_path / "eval")
    cp = tmp_path / "running.json"
    observed = {}

    def cb(etype, data):
        if etype == "group_start" and data["group"] in ("G2_rules", "G3_full"):
            payload = json.loads(cp.read_text(encoding="utf-8"))
            observed[data["group"]] = {
                "current_group": payload["current_group"],
                "groups": set(payload["groups"].keys()),
            }

    runner.run_ablation(_samples(), progress_cb=cb, checkpoint_path=cp)

    # At group_start of G2, the checkpoint reflects completed G0+G1 and says
    # G2 is next; at group_start of G3 it reflects G0+G1+G2.
    assert observed["G2_rules"]["current_group"] == "G2_rules"
    assert observed["G2_rules"]["groups"] == {"G0_pure_llm", "G1_pydantic"}
    assert observed["G3_full"]["current_group"] == "G3_full"
    assert observed["G3_full"]["groups"] == {"G0_pure_llm", "G1_pydantic", "G2_rules"}
    # Success removes the checkpoint.
    assert not cp.exists()


def test_finalize_checkpoint_marks_interrupted(tmp_path):
    cp = tmp_path / "running.json"
    cp.write_text(json.dumps(
        {"status": "running", "current_group": "G2_rules", "groups": {}}), encoding="utf-8")
    EvalRunner.finalize_checkpoint(cp, "interrupted")
    payload = json.loads(cp.read_text(encoding="utf-8"))
    assert payload["status"] == "interrupted"
    assert payload["current_group"] == "G2_rules"


def test_audit_uses_full_contract_even_when_gates_skipped(tmp_path):
    """Golden yardstick: G1 skips validation (status=passed), but the offline
    audit still scores the final bundle against the full rule contract."""
    seed = SeedStore(str(ROOT / "data" / "seed"))
    seed.load()
    provider = MockLLMProvider(seed)
    bundle = provider.generate_monster_bundle("Generate a level 30 fire elite monster with melee AI")

    # Tamper the bundle so it violates R003 (template_id is schema-valid as a
    # string, but does not exist in the seed) — a rule-level, not schema-level,
    # violation. This is exactly what G1's skipped gates would miss.
    tampered = bundle.model_dump(mode="json", exclude_none=True)
    tampered["monster_config"]["template_id"] = "tpl_nonexistent"

    class _FakeOrch:
        def _run(self, *args, **kwargs):
            return {"status": "passed", "rounds": 1, "bundle": tampered,
                    "type": "monster", "round_logs": []}

    runner = EvalRunner(_FakeOrch(), rule_engine=RuleEngine(seed), output_dir=tmp_path / "eval")
    samples = [EvalSample(id=1, type="monster", requirement="any")]
    results = runner.run_ablation(samples, save_report=False)

    g1 = results["G1_pydantic"]
    assert g1["passed"] == 1                 # gates skipped → pipeline says passed
    assert g1["pass_rate"] == 1.0
    assert g1["contract_passed"] == 0        # golden audit catches the violation
    assert g1["contract_pass_rate"] == 0.0
    entry = g1["details"][0]
    assert entry["audit_passed"] is False
    assert entry["audit_errors"] >= 1
    assert "R003" in entry["audit_error_rule_ids"]

    # G2/G3 (rules enabled) would have caught it in-pipeline, but the audit
    # metric stays the same yardstick across groups.
    for key in ("G2_rules", "G3_full"):
        assert results[key]["contract_pass_rate"] == 0.0


class _FakeFailingOrch:
    """Sample 1 raises (generation error), sample 2 exhausts 3 rounds (need_human)."""

    def _run(self, job_type, requirement, enable_critic, skip_validation, dry_run):
        sample_id = int(requirement.split("sample")[1].split()[0])
        if sample_id == 1:
            raise RuntimeError("Doubao generation failed: Invalid JSON: EOF while parsing")
        return {
            "status": "need_human",
            "rounds": 3,
            "bundle": None,
            "type": job_type,
            "round_logs": [
                {"round": 1, "violations": [{"rule_id": "R006", "severity": "error",
                                             "table": "monster_loot", "field": "chance",
                                             "message": "total chance 1.800 exceeds 1.0"}],
                 "critic": None, "passed": False},
                {"round": 2, "violations": [{"rule_id": "R006", "severity": "error",
                                             "table": "monster_loot", "field": "chance",
                                             "message": "total chance 1.200 exceeds 1.0"}],
                 "critic": None, "passed": False},
                {"round": 3, "violations": [{"rule_id": "R006", "severity": "error",
                                             "table": "monster_loot", "field": "chance",
                                             "message": "total chance 1.100 exceeds 1.0"}],
                 "critic": None, "passed": False},
            ],
        }


def test_failure_classification_generation_error_vs_need_human(tmp_path):
    runner = EvalRunner(_FakeFailingOrch(), output_dir=tmp_path / "eval")
    samples = [
        EvalSample(id=1, type="monster", requirement="sample 1 needs a boss"),
        EvalSample(id=2, type="monster", requirement="sample 2 needs a summoner"),
    ]
    results = runner.run_ablation(samples, save_report=False)

    for key in ("G1_pydantic", "G2_rules", "G3_full"):
        g = results[key]
        assert g["passed"] == 0
        assert g["failures_by_kind"] == {"generation_error": 1, "need_human": 1}
        assert g["contract_pass_rate"] == 0.0
        gen_err = next(d for d in g["details"] if d["id"] == 1)
        assert gen_err["error_kind"] == "generation_error"
        assert "EOF while parsing" in gen_err["error"]
        nh = next(d for d in g["details"] if d["id"] == 2)
        assert nh["error_kind"] == "need_human"
        assert "3 revision rounds" in nh["error"]
        assert nh["last_violations"][-1]["rule_id"] == "R006"
