"""Batch generation behavior tests without calling external LLM APIs."""
from pathlib import Path
import importlib

api = importlib.import_module("backend.api.app")


class _FakeTraceStore:
    def __init__(self):
        self.created = []
        self.items = []
        self.completed = []

    def create(self, job_type, requirement, metadata=None):
        trace_id = f"trace_child_{len(self.created) + 1:02d}"
        self.created.append((trace_id, job_type, requirement, metadata or {}))
        return trace_id

    def add_batch_item(self, trace_id, item):
        self.items.append((trace_id, item))

    def complete(self, trace_id, status, result=None, error=None):
        self.completed.append((trace_id, status, result, error))


class _FakeEventBus:
    def __init__(self):
        self.events = []

    def push(self, job_id, event_type, data):
        self.events.append((job_id, event_type, data))


def test_batch_count_detection():
    assert api._resolve_batch_count(api.GenerateRequest(
        job_type="monster",
        requirement="生成10种不同的怪物，处于雪山地形，存在掉落物",
    )) == 10
    assert api._resolve_batch_count(api.GenerateRequest(
        job_type="monster",
        requirement="生成十二种雪山怪物",
    )) == 12
    assert api._resolve_batch_count(api.GenerateRequest(
        job_type="monster",
        requirement="生成10种怪物",
        batch_count=3,
    )) == 10
    assert api._resolve_batch_count(api.GenerateRequest(
        job_type="monster",
        requirement="生成一批雪山怪物",
        batch_count=3,
    )) == 3


def test_batch_generation_aggregates_ten_items(monkeypatch):
    fake_traces = _FakeTraceStore()
    fake_events = _FakeEventBus()

    def fake_generate(job_type, requirement, enable_critic, job_id, trace_id, emit_events=True):
        index = len(fake_traces.created)
        monster_id = f"mon_batch_{index:02d}"
        return {
            "job_id": job_id,
            "trace_id": trace_id,
            "status": "passed",
            "rounds": 1,
            "type": job_type,
            "bundle": {
                "monster_config": {"monster_id": monster_id, "name": f"Snow Monster {index}"},
            },
        }

    monkeypatch.setattr(api, "trace_store", fake_traces)
    monkeypatch.setattr(api, "event_bus", fake_events)
    monkeypatch.setattr(api, "_generate_one", fake_generate)
    monkeypatch.setattr(api, "_export", lambda bundle, job_type: [Path("output/csv/monster_configs.csv")])

    request = api.GenerateRequest(
        job_type="monster",
        requirement="生成10种不同的怪物，处于雪山地形，存在掉落物",
        enable_critic=True,
    )
    result = api._run_batch_generation(request, 10, "j_parent", "trace_parent")

    assert result["status"] == "passed"
    assert result["is_batch"] is True
    assert result["batch_count"] == 10
    assert result["succeeded"] == 10
    assert result["failed"] == 0
    assert len(result["items"]) == 10
    assert len({item["id"] for item in result["items"]}) == 10
    assert len(fake_traces.created) == 10
    assert len(fake_traces.items) == 10
    assert [event[1] for event in fake_events.events].count("batch_item_done") == 10
    assert all("至少 1 条 monster_loot" in created[2] for created in fake_traces.created)
