"""API-level tests for the async /api/eval/run + SSE progress flow.

The eval_runner used by the app module is swapped for a Mock-provider based
runner so the test runs offline in ~seconds. The endpoint itself (background
executor, event bus, SSE endpoint) is the real production code path.
"""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.evaluation.runner import EvalRunner
from backend.pipeline.mock_provider import MockLLMProvider
from backend.pipeline.orchestrator import Orchestrator
from backend.stores.result_store import ResultStore
from backend.stores.seed_store import SeedStore
from backend.stores.trace_store import TraceStore
from backend.validators.rule_engine import RuleEngine

ROOT = Path(__file__).resolve().parents[1]


def _mock_runner(output_dir: Path = None) -> EvalRunner:
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

    orch = Orchestrator(
        _MockGen(),
        _MockCritic(),
        seed,
        RuleEngine(seed),
        TraceStore(str(ROOT / "output" / "traces")),
        ResultStore(str(ROOT / "output")),
        event_bus=None,
    )
    # Default to a throwaway dir so tests never pollute output/eval/.
    return EvalRunner(orch, output_dir=output_dir or (ROOT / "output" / "eval" / "_test_tmp"))


def test_eval_run_streams_progress_and_results(monkeypatch, tmp_path):
    # Swap the app-level runner for a fast Mock-based one (importing app loads
    # .env and may configure live providers, but eval then uses our mock).
    # importlib is required because `backend.api.app` the attribute is shadowed
    # by the FastAPI instance re-exported in backend.api.__init__.
    import importlib
    app_module = importlib.import_module("backend.api.app")

    app_module.eval_runner = _mock_runner(tmp_path / "eval")
    app_module._eval_state["running"] = False

    client = TestClient(app_module.app)

    resp = client.post("/api/eval/run")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "started"
    assert body["job_id"].startswith("eval_")
    job_id = body["job_id"]

    # Second run while first is in flight must be rejected (guard).
    # (Mock eval is fast; may already be done. Either 409 or a fresh job is
    # acceptable here — only assert it does not 500.)
    resp2 = client.post("/api/eval/run")
    assert resp2.status_code in (200, 409)

    # SSE stream: blocks until the job finishes (mock eval completes quickly).
    sse = client.get(f"/api/jobs/{job_id}/events", timeout=60)
    assert sse.status_code == 200
    payloads = []
    for line in sse.text.splitlines():
        if line.startswith("data: "):
            payloads.append(json.loads(line[6:]))
    types = [p["type"] for p in payloads]
    assert "start" in types
    assert "group_start" in types and "sample_done" in types and "group_done" in types
    assert types[-1] == "close"

    done = next(p for p in payloads if p["type"] == "done")
    results = done["data"]
    assert set(results) == {"G0_pure_llm", "G1_pydantic", "G2_rules", "G3_full", "_report"}
    assert results["G1_pydantic"]["total"] == 20
    assert results["G0_pure_llm"]["disabled"] is True
    assert results["G1_pydantic"]["contract_pass_rate"] == 1.0
    assert results["_report"]["json"] and results["_report"]["markdown"]

    # Guard must have been released after completion.
    assert app_module._eval_state["running"] is False
