"""Self-tests proving that the acceptance framework detects real drift."""
from pathlib import Path
import json

import pytest

from backend.stores.seed_store import SeedStore
from .auditor import OutputAuditor
from .models import AuditReport, load_cases
from .runner import AcceptanceRunner, load_project_env


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = Path(__file__).with_name("cases.json")


def mock_cases():
    return [case for case in load_cases(CASES_PATH) if "mock" in case.modes]


def test_case_catalog_is_valid_and_comprehensive():
    cases = load_cases(CASES_PATH)
    assert len(cases) >= 12
    assert {case.job_type for case in cases} == {"skill", "monster", "quest"}
    assert any(case.batch_count == 10 for case in cases)
    assert any(case.enable_critic for case in cases)
    assert any("live" in case.modes for case in cases)
    assert any("critical" in case.tags for case in cases)


@pytest.mark.parametrize("case", mock_cases(), ids=lambda case: case.id)
def test_mock_acceptance_cases_pass_in_isolation(case, tmp_path):
    runner = AcceptanceRunner(PROJECT_ROOT, tmp_path / "acceptance", "mock")
    report = runner.run_case(case)
    assert report.passed, [item.__dict__ for item in report.findings]
    assert Path(report.artifacts["root"]).is_relative_to(tmp_path)


def test_auditor_detects_csv_tampering(tmp_path):
    case = next(item for item in mock_cases() if item.id == "skill_fire_aoe")
    runner = AcceptanceRunner(PROJECT_ROOT, tmp_path / "acceptance", "mock")
    first_report = runner.run_case(case)
    assert first_report.passed

    run_root = Path(first_report.artifacts["root"])
    csv_path = run_root / "csv" / "skills.csv"
    with csv_path.open("a", encoding="utf-8") as handle:
        handle.write("duplicate,row,that,must,be,detected\n")

    bundles = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((run_root / "json").glob("*.json"))
    ]
    seed = SeedStore(str(PROJECT_ROOT / "data" / "seed"))
    report = AuditReport(case.id, "mock", 2)
    OutputAuditor(seed).audit(case, bundles, ["passed"], run_root, report)
    assert not report.passed
    assert "CSV_ROW_MISMATCH" in {item.code for item in report.findings}


def test_auditor_detects_json_tampering(tmp_path):
    case = next(item for item in mock_cases() if item.id == "monster_fire_elite_level30")
    runner = AcceptanceRunner(PROJECT_ROOT, tmp_path / "acceptance", "mock")
    first_report = runner.run_case(case)
    assert first_report.passed

    run_root = Path(first_report.artifacts["root"])
    json_path = next((run_root / "json").glob("*.json"))
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["monster_config"]["name"] = "tampered_name"
    json_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    bundles = [data]
    trace_path = next((run_root / "traces").glob("trace_*.json"))
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    original_bundle = trace["rounds"][-1]["bundle"]
    seed = SeedStore(str(PROJECT_ROOT / "data" / "seed"))
    report = AuditReport(case.id, "mock", 2)
    OutputAuditor(seed).audit(case, [original_bundle], ["passed"], run_root, report)
    assert "JSON_BUNDLE_MISMATCH" in {item.code for item in report.findings}


def test_auditor_detects_non_terminal_trace(tmp_path):
    case = next(item for item in mock_cases() if item.id == "quest_daily_collect")
    runner = AcceptanceRunner(PROJECT_ROOT, tmp_path / "acceptance", "mock")
    first_report = runner.run_case(case)
    assert first_report.passed

    run_root = Path(first_report.artifacts["root"])
    trace_path = next((run_root / "traces").glob("trace_*.json"))
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    trace["status"] = "running"
    trace["completed_at"] = None
    trace_path.write_text(json.dumps(trace, ensure_ascii=False), encoding="utf-8")
    bundles = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (run_root / "json").glob("*.json")
    ]
    seed = SeedStore(str(PROJECT_ROOT / "data" / "seed"))
    report = AuditReport(case.id, "mock", 2)
    OutputAuditor(seed).audit(case, bundles, ["passed"], run_root, report)
    assert "TRACE_NOT_TERMINAL" in {item.code for item in report.findings}


def test_project_env_loader_fills_missing_values_without_overriding(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "ARK_CODING_API_KEY=from_file\n"
        "DEEPSEEK_API_KEY='critic_from_file'\n"
        "EMPTY_VALUE=\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("ARK_CODING_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "from_process")
    monkeypatch.delenv("EMPTY_VALUE", raising=False)

    assert load_project_env(tmp_path) == env_path
    assert __import__("os").environ["ARK_CODING_API_KEY"] == "from_file"
    assert __import__("os").environ["DEEPSEEK_API_KEY"] == "from_process"
    assert "EMPTY_VALUE" not in __import__("os").environ
